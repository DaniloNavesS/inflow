import logging
import sys
import time
from clients.senate import get_resilient_session
from config import INGESTION_YEAR
from database.postgres import wait_for_database
from jobs.committees import ingest_comissoes_e_participacoes
from jobs.expenses import ingest_ceaps_despesas
from jobs.senators import ingest_senadores
from jobs.sessions import ingest_sessoes_presenca
from jobs.staff import ingest_estrutura_gabinete
from monitoring.summary import log_database_summary

from monitoring.metrics import (
    start_pipeline,
    finish_pipeline,
    fail_pipeline,
    start_job,
    finish_job,
    fail_job,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("inflow_ingestor")

def execute_monitored_job(
    conn,
    run_id,
    job_name,
    function,
    *args,
    **kwargs,
):
    """
    Executa um job registrando início, fim, duração e falhas.
    """

    job_id = start_job(
        conn=conn,
        run_id=run_id,
        job_name=job_name,
    )

    start_time = time.perf_counter()

    try:
        result = function(*args, **kwargs)
        duration = time.perf_counter() - start_time
        finish_job(
            conn=conn,
            job_id=job_id,
            duration_seconds=duration,
        )
        return result

    except Exception as exc:
        duration = time.perf_counter() - start_time
        conn.rollback()

        fail_job(
            conn=conn,
            job_id=job_id,
            duration_seconds=duration,
            error_message=str(exc),
        )
        raise

def main():
    logger.info(
        "Iniciando pipeline de carga automatizada InFlow (E1)..."
    )

    pipeline_start = time.perf_counter()

    conn = wait_for_database()
    session = get_resilient_session()

    run_id = start_pipeline(
        conn=conn,
        pipeline_name="senate_ingestion",
        ingestion_year=INGESTION_YEAR,
    )

    try:
        # 1. Senadores
        senador_ids = execute_monitored_job(
            conn,
            run_id,
            "senators",
            ingest_senadores,
            session,
            conn,
        )

        # 2. Comissões
        execute_monitored_job(
            conn,
            run_id,
            "committees",
            ingest_comissoes_e_participacoes,
            session,
            conn,
            senador_ids,
        )

        # 3. Sessões
        execute_monitored_job(
            conn,
            run_id,
            "sessions",
            ingest_sessoes_presenca,
            session,
            conn,
            senador_ids,
        )

        # 4. CEAPS
        execute_monitored_job(
            conn,
            run_id,
            "expenses",
            ingest_ceaps_despesas,
            session,
            conn,
            INGESTION_YEAR,
        )

        # 5. Estrutura de Gabinete
        execute_monitored_job(
            conn,
            run_id,
            "staff",
            ingest_estrutura_gabinete,
            session,
            conn,
            senador_ids,
            INGESTION_YEAR,
        )

        # Auditoria
        log_database_summary(conn)

        pipeline_duration = (
            time.perf_counter() - pipeline_start
        )

        finish_pipeline(
            conn=conn,
            run_id=run_id,
            duration_seconds=pipeline_duration,
        )

        logger.info(
            "Pipeline de ingestão finalizado "
            "com sucesso em %.2f segundos!",
            pipeline_duration,
        )

    except Exception as exc:

        pipeline_duration = (
            time.perf_counter() - pipeline_start
        )

        conn.rollback()

        fail_pipeline(
            conn=conn,
            run_id=run_id,
            duration_seconds=pipeline_duration,
            error_message=str(exc),
        )

        logger.exception(
            "Erro crítico durante a execução do pipeline: %s",
            exc,
        )

        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
