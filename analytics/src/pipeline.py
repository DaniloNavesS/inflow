"""Orquestração monitorada da materialização e comparação da camada analítica."""
import logging
import time
from contextlib import closing

import psycopg2

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, LAKE_DIR
from consumption import compare
from delta_export import export_despesas
from duck import connect
from monitoring.metrics import start_pipeline, finish_pipeline, fail_pipeline, start_job, finish_job, fail_job
from parquet_export import export_despesas_enriquecidas

logger = logging.getLogger("inflow_analytics")


def run_lake():
    with closing(psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
    )) as db, closing(connect()) as con:
        run_id = start_pipeline(db, "analytics_lake")
        started = time.perf_counter()
        try:
            # Uma origem estável para as duas materializações. A comparação posterior
            # detecta também mudanças concorrentes no OLTP em vez de aprovar dados distintos.
            con.execute("BEGIN TRANSACTION")
            for name, function in (
                ("lake_parquet", lambda: export_despesas_enriquecidas(con, LAKE_DIR)),
                ("lake_delta", lambda: export_despesas(con, LAKE_DIR)),
                ("lake_consumption", lambda: compare(con, db, LAKE_DIR)),
            ):
                job_id = start_job(db, run_id, name)
                job_started = time.perf_counter()
                try:
                    result = function()
                    rows = (sum(value["linhas"] for value in result.values())
                            if name == "lake_consumption" else result["linhas"])
                    written = (sum(result.get(key, 0) for key in (
                        "num_target_rows_inserted", "num_target_rows_updated", "num_target_rows_deleted",
                    )) if name == "lake_delta" else rows if name == "lake_parquet" else 0)
                    finish_job(db, job_id, time.perf_counter() - job_started,
                               records_read=rows, records_written=written)
                    logger.info("%s: %s", name, result if name != "lake_consumption" else {
                        key: {k: v for k, v in value.items() if k != "resultado"}
                        for key, value in result.items()
                    })
                except Exception as exc:
                    db.rollback()
                    fail_job(db, job_id, time.perf_counter() - job_started, str(exc))
                    raise
            con.execute("COMMIT")
            finish_pipeline(db, run_id, time.perf_counter() - started)
        except Exception as exc:
            db.rollback()
            fail_pipeline(db, run_id, time.perf_counter() - started, str(exc))
            raise
