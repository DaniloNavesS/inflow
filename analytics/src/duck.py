"""Conexão DuckDB com o Postgres do projeto anexado como fonte somente leitura."""
import duckdb
from psycopg2.extensions import make_dsn

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

PG = "pg"  # nome do catálogo: tabelas ficam em pg.oltp.<tabela>


def postgres_dsn() -> str:
    return make_dsn(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)


def connect() -> duckdb.DuckDBPyConnection:
    """DuckDB em memória com o Postgres anexado em modo READ_ONLY.

    A camada analítica nunca escreve na origem: o OLTP continua sendo a fonte
    da verdade e o lake é derivado dele.
    """
    con = duckdb.connect()
    con.load_extension("postgres")
    dsn = postgres_dsn().replace("'", "''")
    con.execute(f"ATTACH '{dsn}' AS {PG} (TYPE postgres, READ_ONLY)")
    return con
