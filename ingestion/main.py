#!/usr/bin/env python3
import logging
import sys
import time

from clients.senate import get_resilient_session
from config import INGESTION_YEAR
from database.postgres import wait_for_database
from jobs.committees import ingest_comissoes_e_participacoes
from jobs.expenses import ingest_ceaps_despesas
from jobs.senators import ingest_historico_parlamentar, ingest_senadores
from jobs.sessions import ingest_sessoes_presenca
from jobs.staff import ingest_estrutura_gabinete
from monitoring.metrics import execute_monitored_job, finish_pipeline, start_pipeline
from monitoring.summary import log_database_summary


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("inflow_ingestion")


def main():
    logger.info("Iniciando pipeline de carga automatizada InFlow (E1)...")
    started_at = time.perf_counter()
    connection = wait_for_database()
    session = get_resilient_session()
    run_id = start_pipeline(connection, INGESTION_YEAR)

    try:
        senator_ids = execute_monitored_job(
            connection,
            run_id,
            "senators",
            ("senadores",),
            ingest_senadores,
            session,
            connection,
            run_id,
        )
        execute_monitored_job(
            connection,
            run_id,
            "committees",
            ("comissoes", "participacoes_comissao"),
            ingest_comissoes_e_participacoes,
            session,
            connection,
            senator_ids,
            run_id,
        )
        execute_monitored_job(
            connection,
            run_id,
            "parliamentary_history",
            ("mandatos", "exercicios_mandato", "filiacoes_partidarias"),
            ingest_historico_parlamentar,
            session,
            connection,
            senator_ids,
            run_id,
        )
        execute_monitored_job(
            connection,
            run_id,
            "dsf_attendance",
            ("sessao_plenaria", "documento_dsf", "registro_presenca"),
            ingest_sessoes_presenca,
            session,
            connection,
            senator_ids,
            run_id,
        )
        execute_monitored_job(
            connection,
            run_id,
            "ceaps_expenses",
            ("fornecedores", "despesas"),
            ingest_ceaps_despesas,
            session,
            connection,
            INGESTION_YEAR,
            run_id,
        )
        execute_monitored_job(
            connection,
            run_id,
            "staff",
            ("estrutura_gabinete",),
            ingest_estrutura_gabinete,
            session,
            connection,
            senator_ids,
            INGESTION_YEAR,
            run_id,
        )
        log_database_summary(connection)
        finish_pipeline(connection, run_id, time.perf_counter() - started_at)
        logger.info(
            "Pipeline finalizado com sucesso em %.2f segundos.",
            time.perf_counter() - started_at,
        )
    except Exception as error:
        connection.rollback()
        finish_pipeline(connection, run_id, time.perf_counter() - started_at, error)
        logger.exception("Erro crítico durante a ingestão: %s", error)
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
