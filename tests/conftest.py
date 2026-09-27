import os
import sys
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "ingestion"))
if Path("/app").is_dir():
    sys.path.insert(0, "/app")


@pytest.fixture(scope="session")
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
    yield connection
    connection.close()
