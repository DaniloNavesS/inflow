import os
import sys
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "ingestion" / "src"))
if Path("/app/src").is_dir():
    sys.path.insert(0, "/app/src")


@pytest.fixture
def db():
    try:
        connection = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5433")),
            dbname=os.getenv("DB_NAME", "inflow_db"),
            user=os.getenv("DB_USER", "inflow_user"),
            password=os.getenv("DB_PASSWORD", "inflow_pass"),
            connect_timeout=3,
        )
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL de integração indisponível: {exc}")
    with connection.cursor() as cursor:
        cursor.execute("SET search_path TO oltp, public")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def populated_db(db):
    if os.getenv("CNPJ_TEST_DATABASE") == "1":
        pytest.skip("Requer a ingestão completa; o banco CNPJ temporário não contém esses dados.")
    return db
