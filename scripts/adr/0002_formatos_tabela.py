"""Medição da ADR 0002: Parquet puro (opção nula) x Delta (delta-rs) x Iceberg (PyIceberg).

Lê oltp.despesas do PostgreSQL, grava nos três formatos em um diretório temporário, aplica
um lote de CDC simulado (1 despesa corrigida + 1 nova) e consulta tudo pelo DuckDB.

    pip install -r scripts/adr/requirements.txt
    python scripts/adr/0002_formatos_tabela.py --ano 2024

Conexão pelas mesmas variáveis dos testes: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.
"""
import argparse
import os
import statistics
import tempfile
import time
from decimal import Decimal
from pathlib import Path

import duckdb
import psycopg2
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from deltalake import DeltaTable, WriterProperties, write_deltalake
from pyiceberg.catalog.sql import SqlCatalog

SCHEMA = pa.schema([
    ("id", pa.int64()), ("senador_id", pa.int32()), ("fornecedor_id", pa.int64()),
    ("data_despesa", pa.date32()), ("ano", pa.int32()), ("mes", pa.int32()),
    ("tipo_despesa", pa.string()), ("tipo_documento", pa.string()),
    ("num_documento", pa.string()), ("detalhamento", pa.string()),
    ("valor", pa.decimal128(14, 2)),
])
CONSULTA = "SELECT senador_id, tipo_despesa, sum(valor) FROM {} GROUP BY 1, 2 ORDER BY 3 DESC"


def ler_despesas(ano):
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("DB_NAME", "inflow_db"), user=os.getenv("DB_USER", "inflow_user"),
        password=os.getenv("DB_PASSWORD", "inflow_pass"),
    )
    with conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(SCHEMA.names)} FROM oltp.despesas"
            " WHERE %(ano)s IS NULL OR ano = %(ano)s ORDER BY id",
            {"ano": ano},
        )
        registros = cur.fetchall()
    conn.close()
    return pa.Table.from_pylist([dict(zip(SCHEMA.names, row)) for row in registros], schema=SCHEMA)


def cronometrar(funcao, repeticoes=1):
    tempos = []
    for _ in range(repeticoes):
        inicio = time.perf_counter()
        resultado = funcao()
        tempos.append((time.perf_counter() - inicio) * 1000)
    return statistics.median(tempos), resultado


def tamanho(pasta):
    arquivos = [p for p in Path(pasta).rglob("*") if p.is_file()]
    dados = [p for p in arquivos if p.suffix == ".parquet"]
    return len(arquivos), len(dados), sum(p.stat().st_size for p in arquivos) / 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, help="Pasta onde preservar os arquivos do experimento")
    args = parser.parse_args()
    ano = args.ano
    despesas = ler_despesas(ano)
    if not despesas.num_rows:
        parser.error(f"Nenhuma despesa encontrada para ano={ano}; carregue o OLTP antes da medição.")
    primeira = despesas.slice(0, 1).to_pylist()[0]
    valor_antigo = primeira["valor"]
    corrigida = {**primeira, "valor": valor_antigo + Decimal("1.23")}
    nova = {**primeira, "id": max(despesas["id"].to_pylist()) + 1}
    lote_cdc = pa.Table.from_pylist([corrigida, nova], schema=SCHEMA)
    print(f"despesas: {despesas.num_rows} linhas (ano={ano}); lote de CDC: 1 correção + 1 inserção")

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    raiz = Path(tempfile.mkdtemp(prefix="adr0002_", dir=args.output_dir)).resolve()
    resultados = {}

    # Opção nula: um arquivo Parquet; aplicar o lote é reescrever o arquivo inteiro.
    parquet = raiz / "parquet" / "despesas.parquet"
    parquet.parent.mkdir()
    escrita, _ = cronometrar(lambda: pq.write_table(despesas, parquet, compression="zstd"))

    def reescrever_parquet():
        atual = pq.read_table(parquet)
        mantidas = atual.filter(pc.invert(pc.is_in(atual["id"], lote_cdc["id"])))
        pq.write_table(pa.concat_tables([mantidas, lote_cdc]), parquet, compression="zstd")

    apos_escrita = tamanho(parquet.parent)
    lote, _ = cronometrar(reescrever_parquet)
    resultados["Parquet (nula)"] = (escrita, apos_escrita, lote, tamanho(parquet.parent),
                                    f"read_parquet('{parquet.as_posix()}')", "não")

    # Delta via delta-rs: a tabela é o diretório; o log fica em _delta_log.
    delta = (raiz / "delta").as_posix()
    zstd = WriterProperties(compression="ZSTD")
    escrita, _ = cronometrar(lambda: write_deltalake(delta, despesas, writer_properties=zstd))
    apos_escrita = tamanho(delta)
    lote, _ = cronometrar(lambda: (
        DeltaTable(delta)
        .merge(lote_cdc, predicate="t.id = s.id", source_alias="s", target_alias="t",
               writer_properties=zstd)
        .when_matched_update_all().when_not_matched_insert_all().execute()
    ))
    antigo = DeltaTable(delta, version=0).to_pyarrow_table(
        filters=[("id", "=", primeira["id"])])["valor"][0].as_py()
    resultados["Delta (delta-rs)"] = (escrita, apos_escrita, lote, tamanho(delta),
                                      f"delta_scan('{delta}')", f"sim ({antigo == valor_antigo})")

    # Iceberg via PyIceberg: exige catálogo; aqui, SQLite local.
    # Warehouse relativo ao diretório corrente: o PyIceberg não resolve file:///C:/ no Windows.
    os.chdir(raiz)
    iceberg = Path("iceberg")
    iceberg.mkdir()
    catalogo = SqlCatalog("local", uri="sqlite:///iceberg/catalogo.db", warehouse="iceberg")
    catalogo.create_namespace("analytics")
    tabela = catalogo.create_table("analytics.despesas", schema=SCHEMA)
    escrita, _ = cronometrar(lambda: tabela.append(despesas))
    apos_escrita = tamanho(iceberg)
    primeiro_snapshot = tabela.current_snapshot().snapshot_id
    lote, _ = cronometrar(lambda: tabela.upsert(lote_cdc, join_cols=["id"]))
    antigo = tabela.scan(row_filter=f"id == {primeira['id']}", snapshot_id=primeiro_snapshot
                         ).to_arrow()["valor"][0].as_py()
    resultados["Iceberg (PyIceberg)"] = (
        escrita, apos_escrita, lote, tamanho(iceberg),
        f"iceberg_scan('{tabela.metadata_location}')", f"sim ({antigo == valor_antigo})")

    con = duckdb.connect()
    con.execute("INSTALL delta; LOAD delta; INSTALL iceberg; LOAD iceberg;")
    print("\n| Formato | Escrita inicial (ms) | Arquivos / de dados / kB | Lote de CDC (ms) |"
          " Arquivos / de dados / kB após o lote | Consulta DuckDB (ms) | Linhas | Versão anterior legível |")
    print("|---|---:|---:|---:|---:|---:|---:|---|")
    expected_table = pa.concat_tables([
        despesas.filter(pc.invert(pc.is_in(despesas["id"], lote_cdc["id"]))), lote_cdc,
    ])
    con.register("esperado", expected_table)
    esperado = con.execute(CONSULTA.format("esperado")).fetchall()
    for nome, (escrita, antes, lote, depois, fonte, historico) in resultados.items():
        consulta, resultado = cronometrar(lambda: con.execute(CONSULTA.format(fonte)).fetchall(), 5)
        linhas = con.execute(f"SELECT count(*) FROM {fonte}").fetchone()[0]
        # Agregações empatadas podem vir em ordens diferentes.
        if sorted(resultado) != sorted(esperado) or linhas != despesas.num_rows + 1:
            raise RuntimeError(f"Resultado divergente em {nome} após o lote simulado.")
        print(f"| {nome} | {escrita:.0f} | {antes[0]} / {antes[1]} / {antes[2]:.0f} | {lote:.0f} |"
              f" {depois[0]} / {depois[1]} / {depois[2]:.0f} | {consulta:.1f} | {linhas} | {historico} |")
    print(f"\narquivos em {raiz}")


if __name__ == "__main__":
    main()
