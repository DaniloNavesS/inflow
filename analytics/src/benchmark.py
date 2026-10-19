"""Experimento de escala; dados sintéticos, PostgreSQL exclusivo e consultas verificadas.

Não existe um número universal de linhas que justifique Parquet. Este experimento
mede motores + formatos + transporte neste ambiente, incluindo custo da exportação.
"""
import argparse
import csv
import datetime
import json
import hashlib
import math
import os
import platform
import random
import statistics
import tempfile
import time
from contextlib import closing
from pathlib import Path

import duckdb
import psycopg2
import pyarrow
import deltalake
from deltalake import write_deltalake, WriterProperties
import pyiceberg
from pyiceberg.catalog.sql import SqlCatalog

from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
from duck import connect

QUERIES = {
    "agregacao_completa": """SELECT senador_id, tipo_despesa, sum(valor)
        FROM {source} GROUP BY senador_id, tipo_despesa ORDER BY 1, 2""",
    "filtro_mensal": """SELECT senador_id, sum(valor) FROM {source}
        WHERE ano = 2024 AND mes = 6 GROUP BY senador_id ORDER BY 1""",
    "busca_por_id": "SELECT id, valor, detalhamento FROM {source} WHERE id = {id}",
}
COLUMNS = "id, senador_id, fornecedor_id, data_despesa, ano, mes, tipo_despesa, tipo_documento, num_documento, detalhamento, valor"
LAYOUTS = ("sem_particao", "ano_mes")
FORMATS = ("parquet", "delta", "iceberg")


def timed(function):
    started = time.perf_counter()
    result = function()
    return (time.perf_counter() - started) * 1000, result


def break_even(export_ms, postgres_ms, file_ms):
    """Consultas iguais até amortizar uma exportação, sem custo de manutenção."""
    saving = postgres_ms - file_ms
    return max(1, math.ceil(export_ms / saving)) if saving > 0 else None


def generate(db, rows):
    # A proteção em main exige banco dedicado antes de qualquer DDL/TRUNCATE.
    with db.cursor() as cursor:
        cursor.execute("""
            CREATE SCHEMA IF NOT EXISTS benchmark;
            CREATE TABLE IF NOT EXISTS benchmark.despesas (
                id BIGINT PRIMARY KEY, senador_id INTEGER NOT NULL,
                fornecedor_id BIGINT NOT NULL, data_despesa DATE NOT NULL,
                ano SMALLINT NOT NULL, mes SMALLINT NOT NULL,
                tipo_despesa TEXT NOT NULL, tipo_documento TEXT,
                num_documento TEXT, detalhamento TEXT, valor NUMERIC(14,2) NOT NULL
            );
            CREATE INDEX IF NOT EXISTS benchmark_despesas_mes ON benchmark.despesas(ano, mes);
            CREATE INDEX IF NOT EXISTS benchmark_despesas_senador ON benchmark.despesas(senador_id, data_despesa);
            CREATE INDEX IF NOT EXISTS benchmark_despesas_fornecedor ON benchmark.despesas(fornecedor_id);
            CREATE INDEX IF NOT EXISTS benchmark_despesas_tipo ON benchmark.despesas(tipo_despesa);
            TRUNCATE benchmark.despesas;
        """)
        cursor.execute("""
            INSERT INTO benchmark.despesas
            SELECT i, 1 + (i * 37 %% 100), 1 + (i * 17 %% 10000),
                   make_date(2020 + (i %% 6)::int, 1 + ((i / 6) %% 12)::int, 1 + (i %% 28)::int),
                   2020 + (i %% 6), 1 + ((i / 6) %% 12),
                   'Categoria ' || (i * 7 %% 10), 'Nota fiscal', 'DOC-' || i,
                   'Despesa sintética ' || md5(i::text) || md5((i * 31)::text),
                   ((i * 7919 %% 1000000)::numeric / 100)::numeric(14,2)
            FROM generate_series(1, %s::bigint) AS i
        """, (rows,))
    db.commit()
    # Evita medir com estatísticas desatualizadas. VACUUM não pode rodar na transação.
    db.autocommit = True
    with db.cursor() as cursor:
        cursor.execute("VACUUM (ANALYZE) benchmark.despesas")
    db.autocommit = False


def measure_queries(db, con, sources, repetitions, rows, export_times,
                    postgres_source, lookup_id):
    results = []
    randomizer = random.Random(42)
    for name, template in QUERIES.items():
        def run(engine):
            if engine == "postgres":
                with db.cursor() as cursor:
                    cursor.execute(template.format(source=postgres_source, id=lookup_id))
                    return cursor.fetchall()
            return con.execute(template.format(source=sources[engine], id=lookup_id)).fetchall()

        expected = run("postgres")
        engines = ["postgres", *sources]
        # Aquecimento explícito de cada consulta/motor; não alegamos leitura fria.
        for engine in engines:
            if run(engine) != expected:
                raise RuntimeError(f"Resultado divergente: {name}/{engine}")
        samples = {engine: [] for engine in engines}
        for _ in range(repetitions):
            order = engines.copy()
            randomizer.shuffle(order)
            for engine in order:
                elapsed, actual = timed(lambda: run(engine))
                if actual != expected:
                    raise RuntimeError(f"Resultado divergente: {name}/{engine}")
                samples[engine].append(elapsed)
        pg_ms = statistics.median(samples["postgres"])
        with db.cursor() as cursor:
            cursor.execute("EXPLAIN (FORMAT JSON) " + template.format(source=postgres_source, id=lookup_id))
            pg_plan = cursor.fetchone()[0]
        for engine in sources:
            file_format, layout = engine.split("/")
            median = statistics.median(samples[engine])
            results.append({
                "linhas": rows, "consulta": name, "formato": file_format, "layout": layout,
                "postgres_ms": pg_ms, "consulta_ms": median,
                "aceleracao": pg_ms / median, "exportacao_ms": export_times[engine],
                "consultas_para_amortizar": break_even(export_times[engine], pg_ms, median),
                "amostras_postgres_ms": samples["postgres"], "amostras_formato_ms": samples[engine],
                "linhas_resultado": len(expected), "id_consultado": lookup_id if name == "busca_por_id" else None,
                "plano_postgres": pg_plan,
                "plano_duckdb": con.execute("EXPLAIN " + template.format(source=sources[engine], id=lookup_id)).fetchall(),
            })
    return results


def run_size(db, con, rows, repetitions, root, source="synthetic"):
    postgres_source = "benchmark.despesas" if source == "synthetic" else "oltp.despesas"
    if source == "synthetic":
        print(f"\nGerando {rows:,} despesas sintéticas e índices PostgreSQL...", flush=True)
        generation_ms, _ = timed(lambda: generate(db, rows))
    else:
        print("\nLendo despesas REAIS do OLTP, com sessão somente leitura...", flush=True)
        generation_ms = None
    read_ms, data = timed(lambda: con.execute(f"SELECT {COLUMNS} FROM pg.{postgres_source} ORDER BY id").to_arrow_table())
    rows = data.num_rows
    if not rows:
        raise ValueError("A origem não contém despesas para medir.")
    folder = root / str(rows)
    folder.mkdir()
    con.register("origem_benchmark", data)
    expected_partitions = con.execute("SELECT count(*) FROM (SELECT DISTINCT ano, mes FROM origem_benchmark)").fetchone()[0]
    sources, times, storage, writes = {}, {}, {}, []
    # Todos os seis caminhos são consultados na mesma rodada aleatorizada, com uma
    # única referência PostgreSQL. Não medimos cada layout em uma sessão separada.
    combinations = [(fmt, layout) for layout in LAYOUTS for fmt in FORMATS]
    random.Random(42).shuffle(combinations)
    for fmt, layout in combinations:
        key = f"{fmt}/{layout}"
        path = folder / layout / fmt
        path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path = path.parent / "catalogo.db"

        def write():
            if fmt == "parquet":
                if layout == "ano_mes":
                    path.mkdir()
                    con.execute(f"""COPY origem_benchmark TO '{path}'
                        (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY(ano, mes), WRITE_PARTITION_COLUMNS true)""")
                else:
                    path.mkdir()
                    con.execute(f"COPY origem_benchmark TO '{path}/dados.parquet' (FORMAT PARQUET, COMPRESSION ZSTD)")
                return f"read_parquet('{path}/**/*.parquet', hive_partitioning={'true' if layout == 'ano_mes' else 'false'})"
            if fmt == "delta":
                write_deltalake(path, data, partition_by=["ano", "mes"] if layout == "ano_mes" else None,
                               writer_properties=WriterProperties(compression="ZSTD"))
                if deltalake.DeltaTable(path).metadata().partition_columns != (["ano", "mes"] if layout == "ano_mes" else []):
                    raise RuntimeError("Particionamento Delta divergente do solicitado.")
                return f"delta_scan('{path}')"
            # Inclui inicialização do catálogo no custo de primeira escrita Iceberg.
            with closing(SqlCatalog("local", uri=f"sqlite:///{catalog_path}", warehouse=path.as_uri())) as catalog:
                catalog.create_namespace("analytics")
                with catalog.create_table_transaction("analytics.despesas", schema=data.schema,
                        properties={"write.parquet.compression-codec": "zstd"}) as transaction:
                    if layout == "ano_mes":
                        with transaction.update_spec() as spec:
                            spec.add_identity("ano")
                            spec.add_identity("mes")
                table = catalog.load_table("analytics.despesas")
                table.append(data)
                names = [table.schema().find_field(field.source_id).name for field in table.spec().fields]
                if names != (["ano", "mes"] if layout == "ano_mes" else []):
                    raise RuntimeError("Particionamento Iceberg divergente do solicitado.")
                return f"iceberg_scan('{table.metadata_location}')"

        write_ms, sql_source = timed(write)
        sources[key] = sql_source
        times[key] = read_ms + write_ms
        files = list(path.rglob("*.parquet"))
        if layout == "ano_mes" and len(files) < expected_partitions:
            raise RuntimeError(f"{key}: menos arquivos que partições esperadas.")
        storage[key] = {
            "formato_bytes": sum(p.stat().st_size for p in path.rglob("*") if p.is_file()),
            "catalogo_bytes": catalog_path.stat().st_size if fmt == "iceberg" else 0,
            "arquivos_parquet": len(files),
            "particoes_esperadas": expected_partitions if layout == "ano_mes" else 0,
        }
        writes.append({"formato": fmt, "layout": layout, "escrita_ms": write_ms, **storage[key]})
        print(f"Escrita {key}: {write_ms:.1f} ms, {len(files)} arquivos Parquet", flush=True)
    lookup_id = data["id"][rows // 2].as_py()
    results = measure_queries(db, con, sources, repetitions, rows, times, postgres_source, lookup_id)
    with db.cursor() as cursor:
        cursor.execute("SELECT pg_total_relation_size(%s)", (postgres_source,))
        postgres_bytes = cursor.fetchone()[0]
    for result in results:
        result.update(postgres_bytes=postgres_bytes, **storage[f"{result['formato']}/{result['layout']}"])
        payback = result["consultas_para_amortizar"]
        print(f"{rows:>10,} | {result['consulta']:20} | {result['formato']:7}/{result['layout']:12} | "
              f"PG {result['postgres_ms']:9.3f} ms | arquivo {result['consulta_ms']:9.3f} ms | "
              f"{result['aceleracao']:7.2f}x | amortiza: {payback if payback else 'não'}", flush=True)
    con.unregister("origem_benchmark")
    return results, {"linhas": rows, "geracao_e_indices_ms": generation_ms, "leitura_origem_ms": read_ms,
                     "escritas": writes}


def save_report(output, records, setup, repetitions, db, source="synthetic"):
    with db.cursor() as cursor:
        cursor.execute("SELECT version()")
        postgres_version = cursor.fetchone()[0]
    metadata = {
        "versao_experimento": 2,
        "dados": ("sintéticos determinísticos; não são medições da base real do Senado" if source == "synthetic"
                  else "reais: todas as linhas de oltp.despesas, sem alterar a origem"),
        "origem": source,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sistema": platform.platform(), "cpus_visiveis": os.cpu_count(),
        "postgres": postgres_version, "duckdb": duckdb.__version__,
        "pyarrow": pyarrow.__version__, "deltalake": deltalake.__version__, "pyiceberg": pyiceberg.__version__,
        "repeticoes": repetitions, "cache": "aquecido, ordem alternada com semente 42",
        "comparacao": "PostgreSQL via rede Docker x DuckDB local com arquivos; inclui fetch e índices PG",
        "layouts": list(LAYOUTS),
        "layout": "Todos sem partição e todos por identidade em ano/mes; ZSTD nos seis caminhos",
        "referencia_postgres": "Uma amostra PostgreSQL por consulta/repetição, compartilhada pelos dois layouts",
        "iceberg_exportacao": "Inclui inicialização do catálogo, namespace, tabela, partições e append",
        "amortizacao": "ceil((leitura do PostgreSQL + escrita do formato) / economia por consulta); sem manutenção",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "resultado.json").write_text(json.dumps({"metadados": metadata, "preparacao": setup,
                                                       "resultados": records}, indent=2, ensure_ascii=False))
    fields = [key for key in records[0] if not key.startswith(("amostras_", "plano_"))]
    with (output / "resultado.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    lines = ["# Benchmark de escala do lake", "", metadata["dados"], "",
             "Medianas com cache aquecido. Aceleração > 1 significa menor tempo que PostgreSQL.", "",
             "| Linhas | Consulta | Formato | Layout | PostgreSQL ms | Arquivo ms | Aceleração | Consultas para amortizar |",
             "|---:|---|---|---|---:|---:|---:|---:|"]
    for r in records:
        lines.append(f"| {r['linhas']} | {r['consulta']} | {r['formato']} | {r['layout']} | {r['postgres_ms']:.3f} | "
                     f"{r['consulta_ms']:.3f} | {r['aceleracao']:.2f}x | {r['consultas_para_amortizar'] or 'não'} |")
    lines.extend(["", "## Primeiro volume observado com vantagem de consulta", ""])
    for layout in LAYOUTS:
        for query in QUERIES:
            winners = [r for r in records if r["consulta"] == query and r["layout"] == layout
                       and r["formato"] == "parquet" and r["aceleracao"] > 1]
            conclusion = f"{min(r['linhas'] for r in winners):,} linhas" if winners else "não encontrado nos volumes testados"
            message = f"{query}/{layout}: {conclusion}."
            lines.append(f"- {message}")
            print(message, flush=True)
    lines.extend(["", "Esses pontos são observações, não limiares universais nem garantia de vantagem estável.",
                  "Amortização considera consultas idênticas entre exportações. Atualizações frequentes podem eliminar a vantagem.",
                  "O experimento não mede concorrência, cache frio, CDC ou custo operacional; não extrapole para outras distribuições.",
                  "O tamanho PostgreSQL inclui índices; Iceberg usa catálogo SQLite cujo tamanho não está no tamanho do warehouse.",
                  "Parquet é formato de arquivo; Delta e Iceberg gerenciam tabelas sobre arquivos. DuckDB executa as consultas."])
    (output / "relatorio.md").write_text("\n".join(lines) + "\n")
    print(f"\nRelatórios preservados em {output}: relatorio.md, resultado.csv e resultado.json", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, nargs="+", default=[10000, 100000, 1000000])
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=Path("/resultados"))
    parser.add_argument("--source", choices=["synthetic", "oltp"], default="synthetic",
                        help="oltp mede a base real somente em leitura e ignora --rows")
    args = parser.parse_args()
    if any(rows < 1 for rows in args.rows) or args.repetitions < 3:
        parser.error("Use volumes positivos e pelo menos três repetições.")
    if args.source == "synthetic" and (os.getenv("ANALYTICS_BENCHMARK_DATABASE") != "1" or DB_NAME != "inflow_benchmark"):
        parser.error("Execute com make benchmark-lake; requer banco exclusivo inflow_benchmark.")
    print("BENCHMARK: PostgreSQL x DuckDB com Parquet, Delta e Iceberg", flush=True)
    print(f"Origem: {args.source}; cache aquecido; exportação incluída no cálculo de amortização.", flush=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = args.output_dir / stamp
    with closing(psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                                user=DB_USER, password=DB_PASSWORD)) as db, closing(connect()) as con:
        if args.source == "oltp":
            db.set_session(readonly=True)
        con.load_extension("delta")
        con.load_extension("iceberg")
        records, setup = [], []
        with tempfile.TemporaryDirectory(prefix="inflow_scale_") as temporary:
            for rows in sorted(set(args.rows)) if args.source == "synthetic" else [None]:
                result, preparation = run_size(db, con, rows, args.repetitions, Path(temporary), args.source)
                records.extend(result)
                setup.append(preparation)
                # Preserva resultados parciais se uma escala maior falhar.
                save_report(output, records, setup, args.repetitions, db, args.source)


if __name__ == "__main__":
    main()
