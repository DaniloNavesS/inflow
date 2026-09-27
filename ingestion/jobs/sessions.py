import logging

import psycopg2
import requests

from jobs.attendance import ingest_dsf_attendance

logger = logging.getLogger("inflow_ingestion")

def ingest_sessoes_presenca(session: requests.Session, conn: psycopg2.extensions.connection, senador_ids: list):
    """Compatibilidade do fluxo principal: presença vem exclusivamente do DSF."""
    logger.info("Iniciando ingestão documental de presença no DSF.")
    metrics = ingest_dsf_attendance(session, conn)
    for metric in metrics:
        logger.info(
            "DSF %d, sessão %d: %d/%d linhas; %d não resolvidas; %s.",
            metric["diary_code"], metric["session_number"], metric["extracted"],
            metric["expected_count"], metric["unresolved"], metric["status"],
        )
    return metrics


# -----------------------------------------------------------------------------
# Etapa 4: Ingestão de Fornecedores e Despesas (CEAPS)
# -----------------------------------------------------------------------------

