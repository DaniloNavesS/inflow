"""Mesmas perguntas de gestão no PostgreSQL, Parquet e Delta, sem arredondar valores."""
import json
import statistics
import time
from decimal import Decimal
from pathlib import Path


# Pergunta 1: média dos totais mensais nos meses COM despesas, por senador e ano.
# Pergunta 11: categoria de maior valor por senador e ano, incluindo empates.
QUERIES = {
    "media_mensal_por_senador": """
        WITH mensal AS (
            SELECT senador_id, ano, mes, sum(valor) AS total
            FROM {source} GROUP BY senador_id, ano, mes
        )
        SELECT senador_id, ano, sum(total) AS total, count(*) AS meses_com_despesas
        FROM mensal GROUP BY senador_id, ano ORDER BY senador_id, ano
    """,
    "maior_categoria_por_senador": """
        WITH categorias AS (
            SELECT senador_id, ano, tipo_despesa, sum(valor) AS total
            FROM {source} GROUP BY senador_id, ano, tipo_despesa
        ), ranking AS (
            SELECT *, dense_rank() OVER (
                PARTITION BY senador_id, ano ORDER BY total DESC
            ) AS posicao FROM categorias
        )
        SELECT senador_id, ano, tipo_despesa, total FROM ranking
        WHERE posicao = 1 ORDER BY senador_id, ano, tipo_despesa
    """,
}


def measured(query, repetitions=5):
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        rows = query()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples), rows


def compare(con, db, lake_dir: Path, repetitions=5) -> dict:
    """Falha se houver divergência; inclui fetch no tempo, sem tempo de conexão."""
    parquet = str(lake_dir / "parquet" / "despesas_enriquecidas" / "**" / "*.parquet").replace("'", "''")
    delta = str(lake_dir / "delta" / "despesas").replace("'", "''")
    con.load_extension("delta")
    sources = {
        "parquet": f"read_parquet('{parquet}', hive_partitioning=true)",
        "delta": f"delta_scan('{delta}')",
    }
    report = {}
    for name, template in QUERIES.items():
        def postgres_query():
            with db.cursor() as cursor:
                cursor.execute(template.format(source="oltp.despesas"))
                return cursor.fetchall()

        pg_ms, expected = measured(postgres_query, repetitions)
        entry = {"postgres_ms": pg_ms, "linhas": len(expected)}
        for label, source in sources.items():
            ms, rows = measured(lambda: con.execute(template.format(source=source)).fetchall(), repetitions)
            if rows != expected:
                raise ValueError(f"Resultado {label} diverge do PostgreSQL na consulta {name}.")
            entry[f"{label}_ms"] = ms
        # A razão é calculada em Python para evitar diferenças de precisão de AVG
        # entre os motores; os numeradores e denominadores são comparados exatamente.
        entry["resultado"] = [
            [*row, row[2] / Decimal(row[3])] if name == "media_mensal_por_senador" else list(row)
            for row in expected
        ]
        entry["colunas"] = (
            ["senador_id", "ano", "total", "meses_com_despesas", "media_mensal"]
            if name == "media_mensal_por_senador"
            else ["senador_id", "ano", "tipo_despesa", "total"]
        )
        report[name] = entry
    output = lake_dir / "consumo.json"
    output.write_text(json.dumps(report, default=str, ensure_ascii=False, indent=2))
    return report
