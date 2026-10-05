import logging
import sys
import time
from clients.senate import get_resilient_session
from config import ENABLE_CNPJ_OWNERS, INGESTION_YEAR
from database.postgres import wait_for_database
from jobs.attendance import ingest_dsf_attendance
from jobs.cnpj_owners import ingest_cnpj_owners
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
        # Jobs que devolvem contadores (records_read, records_written...) os registram em job_runs.
        counters = result if isinstance(result, dict) and all(
            key.startswith("records_") for key in result
        ) else {}
        finish_job(
            conn=conn,
            job_id=job_id,
            duration_seconds=duration,
            **counters,
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
            run_id,
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
            run_id,
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
            run_id,
        )

        # 4. Presença oficial extraída do Diário do Senado Federal
        execute_monitored_job(
            conn,
            run_id,
            "dsf_attendance",
            ingest_dsf_attendance,
            session,
            conn,
            run_id,
        )

        # 5. CEAPS
        execute_monitored_job(
            conn,
            run_id,
            "expenses",
            ingest_ceaps_despesas,
            session,
            conn,
            INGESTION_YEAR,
            run_id,
        )

        # 6. Estrutura de Gabinete
        execute_monitored_job(
            conn,
            run_id,
            "staff",
            ingest_estrutura_gabinete,
            session,
            conn,
            senador_ids,
            INGESTION_YEAR,
            run_id,
        )

        # 7. Sócios e dados cadastrais (RFB) dos fornecedores. Enriquecimento opcional:
        # depende de um servidor externo lento, então a falha fica registrada em
        # monitoring.job_runs sem invalidar a carga do Senado.
        if ENABLE_CNPJ_OWNERS:
            try:
                execute_monitored_job(
                    conn,
                    run_id,
                    "cnpj_owners",
                    ingest_cnpj_owners,
                    conn,
                    run_id,
                )
            except Exception as exc:
                logger.error(
                    "Job cnpj_owners falhou; carga do Senado mantida: %s",
                    exc,
                )
        else:
            logger.info("Job cnpj_owners desativado (ENABLE_CNPJ_OWNERS=0).")

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

def main_cnpj():
    """Executa só o enriquecimento RFB, sobre os fornecedores já carregados."""
    pipeline_start = time.perf_counter()
    conn = wait_for_database()
    run_id = start_pipeline(conn=conn, pipeline_name="rfb_cnpj_enrichment")
    try:
        execute_monitored_job(conn, run_id, "cnpj_owners", ingest_cnpj_owners, conn, run_id)
        log_database_summary(conn)
        finish_pipeline(
            conn=conn,
            run_id=run_id,
            duration_seconds=time.perf_counter() - pipeline_start,
        )
    except Exception as exc:
        conn.rollback()
        fail_pipeline(
            conn=conn,
            run_id=run_id,
            duration_seconds=time.perf_counter() - pipeline_start,
            error_message=str(exc),
        )
        logger.exception("Erro no enriquecimento RFB: %s", exc)
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    if sys.argv[1:] == ["cnpj"]:
        main_cnpj()
    else:
        main()
