"""Etapa 2: despesas da CEAPS enriquecidas, materializadas em Parquet particionado.

Uma linha por lançamento da CEAPS, já com senador, fornecedor e o retrato mais
recente da empresa na RFB, para que as consultas de gestão não precisem de JOIN.
Layout: <lake>/parquet/despesas_enriquecidas/ano=AAAA/mes=M/*.parquet
"""
import datetime
import json
import logging
import shutil
import time
from pathlib import Path

import duckdb

from duck import PG

logger = logging.getLogger("inflow_analytics")

TABLE = "despesas_enriquecidas"

QUERY = f"""
WITH empresa AS (
    -- Retrato mais recente de cada empresa na RFB.
    SELECT e.cnpj_basico, e.data_referencia, e.razao_social, e.natureza_juridica,
           n.descricao AS natureza_juridica_descricao, e.porte, e.capital_social
    FROM {PG}.oltp.empresas e
    LEFT JOIN {PG}.oltp.naturezas_juridicas n ON n.codigo = e.natureza_juridica
    QUALIFY row_number() OVER (PARTITION BY e.cnpj_basico ORDER BY e.data_referencia DESC) = 1
),
fornecedor AS (
    SELECT f.id, f.cnpj_cpf, f.razao_social,
           regexp_replace(f.cnpj_cpf, '[^0-9]', '', 'g') AS digitos
    FROM {PG}.oltp.fornecedores f
)
SELECT
    d.id                          AS despesa_id,
    d.ano,
    d.mes,
    d.data_despesa,
    d.tipo_despesa,
    d.tipo_documento,
    d.num_documento,
    d.detalhamento,
    d.valor,
    s.id                          AS senador_id,
    s.nome                        AS senador_nome,
    s.partido                     AS senador_partido,
    s.uf                          AS senador_uf,
    f.id                          AS fornecedor_id,
    f.cnpj_cpf                    AS fornecedor_documento,
    CASE
        WHEN f.cnpj_cpf LIKE '%*%' THEN 'CPF_MASCARADO'
        WHEN length(f.digitos) = 14 THEN 'CNPJ'
        WHEN length(f.digitos) = 11 THEN 'CPF'
        WHEN f.cnpj_cpf = 'SEM_DOCUMENTO' THEN 'SEM_DOCUMENTO'
        ELSE 'OUTRO'
    END                           AS fornecedor_tipo_documento,
    f.razao_social                AS fornecedor_nome,
    em.cnpj_basico                AS empresa_cnpj_basico,
    em.razao_social               AS empresa_razao_social,
    em.natureza_juridica          AS empresa_natureza_juridica,
    em.natureza_juridica_descricao AS empresa_natureza_juridica_descricao,
    em.porte                      AS empresa_porte,
    em.capital_social             AS empresa_capital_social,
    em.data_referencia            AS empresa_data_referencia_rfb,
    d.timestamp_ingestao,
    d.atualizado_em,
    CAST(? AS TIMESTAMPTZ)        AS materializado_em
FROM {PG}.oltp.despesas d
JOIN {PG}.oltp.senadores s ON s.id = d.senador_id
JOIN fornecedor f ON f.id = d.fornecedor_id
LEFT JOIN empresa em
    ON f.cnpj_cpf NOT LIKE '%*%'
   AND length(f.digitos) = 14
   AND em.cnpj_basico = left(f.digitos, 8)
"""


def export_despesas_enriquecidas(con: duckdb.DuckDBPyConnection, lake_dir: Path) -> dict:
    """Reescreve a tabela inteira; a pasta final só é trocada quando a nova está completa."""
    started = time.perf_counter()
    materialized_at = datetime.datetime.now(datetime.timezone.utc)

    root = lake_dir / "parquet"
    target = root / TABLE
    staging = root / f".{TABLE}.staging"
    previous = root / f".{TABLE}.previous"
    root.mkdir(parents=True, exist_ok=True)
    for leftover in (staging, previous):
        shutil.rmtree(leftover, ignore_errors=True)

    con.execute("CREATE OR REPLACE TEMP TABLE despesas_enriquecidas AS " + QUERY, [materialized_at])
    rows, total = con.execute(
        "SELECT count(*), coalesce(sum(valor), 0) FROM despesas_enriquecidas"
    ).fetchone()

    con.execute(f"""
        COPY despesas_enriquecidas TO '{staging.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (ano, mes), WRITE_PARTITION_COLUMNS true)
    """)

    manifest = {
        "tabela": TABLE,
        "formato": "parquet",
        "particionamento": ["ano", "mes"],
        "linhas": rows,
        "soma_valor": str(total),
        "materializado_em": materialized_at.isoformat(),
        "origem": "postgres oltp.despesas + senadores + fornecedores + empresas (retrato mais recente)",
    }
    (staging / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    # Troca: a versão anterior só sai depois que a nova está no lugar.
    if target.exists():
        target.rename(previous)
    staging.rename(target)
    shutil.rmtree(previous, ignore_errors=True)

    partitions = len(list(target.glob("ano=*/mes=*")))
    files = len(list(target.rglob("*.parquet")))
    size_mb = sum(p.stat().st_size for p in target.rglob("*.parquet")) / 1e6
    logger.info(
        "Parquet %s: %d linhas, R$ %s, %d partições, %d arquivos, %.1f MB em %.1f s",
        TABLE, rows, total, partitions, files, size_mb, time.perf_counter() - started,
    )
    return {**manifest, "particoes": partitions, "arquivos": files, "tamanho_mb": round(size_mb, 2)}
