"""Etapa 1 da camada analítica: o contêiner analytics lê o Postgres e grava no lake.

Rodam só no contêiner analytics (make test-lake); no contêiner de ingestão,
sem duckdb instalado, são ignorados.
"""
import pytest

duckdb = pytest.importorskip("duckdb")

from config import LAKE_DIR  # noqa: E402
from duck import PG, connect  # noqa: E402


@pytest.fixture(scope="module")
def con():
    try:
        connection = connect()
    except duckdb.Error as exc:
        pytest.skip(f"Postgres indisponível para o DuckDB: {exc}")
    yield connection
    connection.close()


def test_duckdb_reads_the_same_rows_as_postgres(con, db):
    with db.cursor() as cursor:
        cursor.execute("SELECT count(*), coalesce(sum(valor), 0) FROM despesas")
        expected = cursor.fetchone()
    actual = con.execute(f"SELECT count(*), coalesce(sum(valor), 0) FROM {PG}.oltp.despesas").fetchone()
    assert actual == expected


def test_postgres_is_attached_read_only(con):
    with pytest.raises(duckdb.Error):
        con.execute(f"CREATE TABLE {PG}.oltp.nao_deve_existir (id INT)")


def test_delta_extension_loads_without_internet(con):
    con.load_extension("delta")


def test_lake_dir_is_writable():
    LAKE_DIR.mkdir(parents=True, exist_ok=True)
    probe = LAKE_DIR / ".test_probe"
    probe.write_text("ok")
    assert probe.read_text() == "ok"
    probe.unlink()
