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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("inflow_ingestor")

def main():
    logger.info("Iniciando pipeline de carga automatizada InFlow (E1)...")
    start_time = time.time()

    conn = wait_for_database()
    session = get_resilient_session()

    try:
        senador_ids = ingest_senadores(session, conn)
        ingest_comissoes_e_participacoes(session, conn, senador_ids)
        ingest_sessoes_presenca(session, conn, senador_ids)
        ingest_ceaps_despesas(session, conn, INGESTION_YEAR)
        ingest_estrutura_gabinete(session, conn, senador_ids, INGESTION_YEAR)

        log_database_summary(conn)

        elapsed = time.time() - start_time
        logger.info(
            "Pipeline de ingestão finalizado com sucesso em %.2f segundos!",
            elapsed,
        )
    except Exception as e:
        logger.exception(
            "Erro crítico durante a execução do pipeline de ingestão: %s",
            e,
        )
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
