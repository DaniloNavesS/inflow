import logging
import time

import psycopg2

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


logger = logging.getLogger("inflow_ingestion")


def wait_for_database(
    max_attempts: int = 30,
    delay_seconds: int = 2,
) -> psycopg2.extensions.connection:
    logger.info("Aguardando disponibilidade do banco de dados PostgreSQL...")
    for attempt in range(1, max_attempts + 1):
        try:
            connection = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=5,
            )
            connection.autocommit = False
            logger.info("Conexão com PostgreSQL estabelecida com sucesso.")
            return connection
        except psycopg2.OperationalError as error:
            logger.warning(
                "PostgreSQL indisponível na tentativa %d/%d: %s",
                attempt,
                max_attempts,
                error,
            )
            time.sleep(delay_seconds)
    raise RuntimeError("PostgreSQL indisponível após múltiplas tentativas")

