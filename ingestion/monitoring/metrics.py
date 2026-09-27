from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any


def _count_rows(connection, tables: Sequence[str]) -> int:
    total = 0
    with connection.cursor() as cursor:
        for table in tables:
            if not table.replace("_", "").isalnum():
                raise ValueError(f"Nome de tabela inválido para monitoramento: {table}")
            cursor.execute(f"SELECT count(*) FROM {table}")
            total += cursor.fetchone()[0]
    return total


def start_pipeline(connection, ingestion_year: int) -> uuid.UUID:
    run_id = uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO monitoring.pipeline_runs
                (run_id, pipeline_name, ingestion_year)
            VALUES (%s, 'senate_ingestion', %s)
            """,
            (str(run_id), ingestion_year),
        )
    connection.commit()
    return run_id


def finish_pipeline(
    connection,
    run_id: uuid.UUID,
    duration_seconds: float,
    error: Exception | None = None,
) -> None:
    status = "failed" if error else "success"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE monitoring.pipeline_runs
               SET finished_at = CURRENT_TIMESTAMP,
                   duration_seconds = %s,
                   status = %s,
                   error_message = %s
             WHERE run_id = %s
            """,
            (duration_seconds, status, str(error) if error else None, str(run_id)),
        )
    connection.commit()


def execute_monitored_job(
    connection,
    run_id: uuid.UUID,
    job_name: str,
    tables: Sequence[str],
    function: Callable[..., Any],
    *args,
    **kwargs,
):
    before = _count_rows(connection, tables)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO monitoring.job_runs
                (run_id, job_name, records_before)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (str(run_id), job_name, before),
        )
        job_id = cursor.fetchone()[0]
    connection.commit()
    started_at = time.perf_counter()

    try:
        result = function(*args, **kwargs)
        after = _count_rows(connection, tables)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE monitoring.job_runs
                   SET finished_at = CURRENT_TIMESTAMP,
                       duration_seconds = %s,
                       status = 'success',
                       records_after = %s,
                       records_delta = %s
                 WHERE id = %s
                """,
                (time.perf_counter() - started_at, after, after - before, job_id),
            )
        connection.commit()
        return result
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE monitoring.job_runs
                   SET finished_at = CURRENT_TIMESTAMP,
                       duration_seconds = %s,
                       status = 'failed',
                       records_after = %s,
                       error_message = %s
                 WHERE id = %s
                """,
                (time.perf_counter() - started_at, before, str(error), job_id),
            )
        connection.commit()
        raise
