import logging
import sys
import time

import psycopg2

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger("inflow_ingestor")


def wait_for_database(max_attempts: int = 30, delay_seconds: int = 2) -> psycopg2.extensions.connection:

    logger.info("Aguardando disponibilidade do banco de dados PostgreSQL...")

    for attempt in range(1, max_attempts + 1):

        try:

            conn = psycopg2.connect(

                host=DB_HOST,

                port=DB_PORT,

                dbname=DB_NAME,

                user=DB_USER,

                password=DB_PASSWORD,

                connect_timeout=5

            )

            conn.autocommit = False

            logger.info("Conexão com PostgreSQL estabelecida com sucesso!")

            return conn

        except psycopg2.OperationalError as e:

            logger.warning("PostgreSQL indisponível na tentativa %d/%d: %s", attempt, max_attempts, e)

            time.sleep(delay_seconds)

    logger.error("Falha crítica: impossível conectar ao PostgreSQL após múltiplas tentativas.")

    sys.exit(1)
