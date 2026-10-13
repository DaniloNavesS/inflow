"""Etapa 2 da camada analítica: despesas_enriquecidas em Parquet particionado.

A exportação roda numa pasta temporária (não toca no ./lake real) e o resultado é
comparado com o Postgres, que continua sendo a fonte da verdade.
"""
import json
from decimal import Decimal

import pytest

duckdb = pytest.importorskip("duckdb")

from duck import connect  # noqa: E402
from parquet_export import TABLE, export_despesas_enriquecidas  # noqa: E402


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    lake = tmp_path_factory.mktemp("lake")
    try:
        con = connect()
    except duckdb.Error as exc:
        pytest.skip(f"Postgres indisponível para o DuckDB: {exc}")
    result = export_despesas_enriquecidas(con, lake)
    yield lake / "parquet" / TABLE, result, con
    con.close()


def parquet(path, hive=True):
    return f"read_parquet('{path.as_posix()}/**/*.parquet', hive_partitioning={str(hive).lower()})"


def scalar(db, sql):
    with db.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()


def test_totals_match_postgres(exported, db):
    path, result, con = exported
    expected = scalar(db, "SELECT count(*), coalesce(sum(valor), 0) FROM despesas")
    assert con.execute(f"SELECT count(*), sum(valor) FROM {parquet(path)}").fetchone() == expected
    assert (result["linhas"], Decimal(result["soma_valor"])) == expected


def test_each_expense_appears_once(exported):
    path, _, con = exported
    rows, distinct = con.execute(
        f"SELECT count(*), count(DISTINCT despesa_id) FROM {parquet(path)}"
    ).fetchone()
    assert rows == distinct


def test_one_partition_per_month_with_matching_totals(exported, db):
    path, _, con = exported
    with db.cursor() as cursor:
        cursor.execute("SELECT ano, mes, count(*), sum(valor) FROM despesas GROUP BY 1, 2 ORDER BY 1, 2")
        expected = cursor.fetchall()
    actual = con.execute(
        f"SELECT ano, mes, count(*), sum(valor) FROM {parquet(path)} GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    assert actual == expected
    folders = sorted((int(p.parent.name[4:]), int(p.name[4:])) for p in path.glob("ano=*/mes=*"))
    assert folders == [(ano, mes) for ano, mes, *_ in expected]


def test_types_are_preserved_inside_the_files(exported):
    path, _, con = exported
    types = dict(con.execute(
        f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM {parquet(path, hive=False)})"
    ).fetchall())
    assert types["valor"] == "DECIMAL(14,2)"
    assert types["ano"] == "SMALLINT"
    assert types["data_despesa"] == "DATE"
    assert types["timestamp_ingestao"] == "TIMESTAMP WITH TIME ZONE"


def test_rfb_enrichment_matches_postgres_join(exported, db):
    path, _, con = exported
    (expected,) = scalar(db, """
        SELECT count(*) FROM despesas d
        JOIN fornecedores f ON f.id = d.fornecedor_id
        WHERE f.cnpj_cpf NOT LIKE '%*%'
          AND length(regexp_replace(f.cnpj_cpf, '[^0-9]', '', 'g')) = 14
          AND EXISTS (SELECT 1 FROM empresas e
                      WHERE e.cnpj_basico = left(regexp_replace(f.cnpj_cpf, '[^0-9]', '', 'g'), 8))
    """)
    (actual,) = con.execute(
        f"SELECT count(*) FROM {parquet(path)} WHERE empresa_razao_social IS NOT NULL"
    ).fetchone()
    assert actual == expected


def test_manifest_describes_the_snapshot(exported):
    path, result, _ = exported
    manifest = json.loads((path / "_manifest.json").read_text())
    assert manifest["linhas"] == result["linhas"]
    assert manifest["particionamento"] == ["ano", "mes"]


def test_rerun_replaces_the_table_without_leftovers(exported):
    path, first, con = exported
    second = export_despesas_enriquecidas(con, path.parent.parent)
    assert second["linhas"] == first["linhas"]
    assert second["arquivos"] == first["arquivos"]
    assert not list(path.parent.glob(".*staging")) and not list(path.parent.glob(".*previous"))
    assert con.execute(f"SELECT count(*) FROM {parquet(path)}").fetchone()[0] == first["linhas"]
