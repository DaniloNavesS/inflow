"""Janela mensal de despesas da CEAPS com regra de dado atrasado.

Cada execução é um lote. As despesas novas ou corrigidas desde o lote anterior viram
lançamentos (deltas) na janela do seu tempo de evento. O watermark usado para classificar
um lote é o que os lotes anteriores deixaram; ele só avança no fim do lote.
"""
import logging

from psycopg2 import sql

from config import LATE_DATA_ALLOWED_MONTHS

logger = logging.getLogger("inflow_ingestor")

FLUXO_DESPESAS = "despesas"
FONTE_DESPESAS = "oltp.despesas"
# Abaixo disso a data do documento é erro de digitação da origem (ex. 0202-07-04).
DATA_MINIMA_VALIDA = "2000-01-01"

QUERY_LANCAMENTOS = """
    WITH atual AS (
        SELECT
            d.id AS despesa_id,
            d.senador_id,
            d.valor,
            CASE
                WHEN d.data_despesa >= %(data_minima)s::date
                    THEN date_trunc('month', d.data_despesa)::date
                ELSE make_date(d.ano, d.mes, 1)
            END AS janela_inicio,
            CASE
                WHEN d.data_despesa >= %(data_minima)s::date THEN 'DATA_DESPESA'
                ELSE 'COMPETENCIA'
            END AS origem_tempo_evento
        FROM {fonte} d
    ),
    mudancas AS (
        SELECT
            a.*,
            e.despesa_id IS NOT NULL AS correcao,
            e.senador_id AS senador_anterior,
            e.janela_inicio AS janela_anterior,
            e.valor AS valor_anterior
        FROM atual a
        LEFT JOIN analytics.janela_despesas_estado e
            ON e.fluxo = %(fluxo)s AND e.despesa_id = a.despesa_id
        WHERE e.despesa_id IS NULL
            OR ROW(e.senador_id, e.janela_inicio, e.valor)
                IS DISTINCT FROM ROW(a.senador_id, a.janela_inicio, a.valor)
    ),
    deltas AS (
        -- Correção: estorna o que a despesa contribuía antes...
        SELECT despesa_id, senador_anterior AS senador_id, janela_anterior AS janela_inicio,
               -valor_anterior AS delta_valor, -1 AS delta_quantidade,
               'CORRECAO' AS motivo, origem_tempo_evento
        FROM mudancas
        WHERE correcao
        UNION ALL
        -- ...e lança a contribuição atual (única linha quando a despesa é nova).
        SELECT despesa_id, senador_id, janela_inicio, valor, 1,
               CASE WHEN correcao THEN 'CORRECAO' ELSE 'INSERCAO' END, origem_tempo_evento
        FROM mudancas
    ),
    lancados AS (
        INSERT INTO analytics.janela_despesas_lancamentos (
            fluxo, lote, despesa_id, senador_id, janela_inicio, delta_valor,
            delta_quantidade, classificacao, motivo, origem_tempo_evento, watermark_no_lote
        )
        SELECT
            %(fluxo)s, %(lote)s, despesa_id, senador_id, janela_inicio, delta_valor,
            delta_quantidade,
            CASE
                WHEN (janela_inicio + INTERVAL '1 month')::date <= %(watermark)s::date
                    THEN 'ATRASADO'
                ELSE 'NO_PRAZO'
            END,
            motivo, origem_tempo_evento, %(watermark)s::date
        FROM deltas
        RETURNING classificacao
    ),
    estado AS (
        INSERT INTO analytics.janela_despesas_estado (
            fluxo, despesa_id, senador_id, janela_inicio, valor
        )
        SELECT %(fluxo)s, despesa_id, senador_id, janela_inicio, valor
        FROM mudancas
        ON CONFLICT (fluxo, despesa_id) DO UPDATE SET
            senador_id = EXCLUDED.senador_id,
            janela_inicio = EXCLUDED.janela_inicio,
            valor = EXCLUDED.valor
        RETURNING 1
    )
    SELECT
        (SELECT count(*) FROM estado),
        (SELECT count(*) FROM lancados WHERE classificacao = 'NO_PRAZO'),
        (SELECT count(*) FROM lancados WHERE classificacao = 'ATRASADO');
"""

# O relógio é a competência (ano, mes), não data_despesa: a competência é validada pela
# origem e pelo esquema, enquanto uma data digitada errada fecharia janelas indevidamente.
QUERY_AVANCA_WATERMARK = """
    UPDATE analytics.janela_controle c
    SET watermark = GREATEST(c.watermark, m.candidato),
        ultimo_lote = %(lote)s,
        atraso_permitido_meses = %(atraso)s,
        atualizado_em = CURRENT_TIMESTAMP
    FROM (
        SELECT (
            LEAST(max(make_date(ano, mes, 1)), date_trunc('month', CURRENT_DATE)::date)
            - make_interval(months => %(atraso)s)
        )::date AS candidato
        FROM {fonte}
    ) m
    WHERE c.fluxo = %(fluxo)s
    RETURNING c.watermark;
"""


def processar_lote(
    conn,
    fluxo: str = FLUXO_DESPESAS,
    fonte: str = FONTE_DESPESAS,
    atraso_meses: int = LATE_DATA_ALLOWED_MONTHS,
) -> dict:
    """Processa um lote dentro da transação corrente; quem chama decide o commit."""
    fonte_sql = sql.Identifier(*fonte.split("."))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analytics.janela_controle (fluxo, atraso_permitido_meses)
            VALUES (%s, %s)
            ON CONFLICT (fluxo) DO NOTHING
            """,
            (fluxo, atraso_meses),
        )
        # O bloqueio da linha de controle serializa execuções concorrentes do mesmo fluxo.
        cur.execute(
            "SELECT watermark, ultimo_lote FROM analytics.janela_controle"
            " WHERE fluxo = %s FOR UPDATE",
            (fluxo,),
        )
        watermark, ultimo_lote = cur.fetchone()
        params = {
            "fluxo": fluxo,
            "lote": ultimo_lote + 1,
            "watermark": watermark,
            "atraso": atraso_meses,
            "data_minima": DATA_MINIMA_VALIDA,
        }
        cur.execute(sql.SQL(QUERY_LANCAMENTOS).format(fonte=fonte_sql), params)
        despesas, no_prazo, atrasados = cur.fetchone()
        cur.execute(sql.SQL(QUERY_AVANCA_WATERMARK).format(fonte=fonte_sql), params)
        novo_watermark = cur.fetchone()[0]

    return {
        "lote": params["lote"],
        "despesas": despesas,
        "no_prazo": no_prazo,
        "atrasados": atrasados,
        "watermark_anterior": watermark,
        "watermark": novo_watermark,
    }


def reiniciar_fluxo(conn, fluxo: str = FLUXO_DESPESAS) -> None:
    """Apaga watermark, estado e lançamentos do fluxo; o próximo lote recomeça do zero."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM analytics.janela_controle WHERE fluxo = %s", (fluxo,))


def process_expense_windows(conn) -> dict:
    resultado = processar_lote(conn)
    conn.commit()
    logger.info(
        "Janela de despesas, lote %d: %d despesas novas ou corrigidas, %d lançamentos no "
        "prazo, %d atrasados; watermark %s -> %s.",
        resultado["lote"],
        resultado["despesas"],
        resultado["no_prazo"],
        resultado["atrasados"],
        resultado["watermark_anterior"],
        resultado["watermark"],
    )
    return {
        "records_read": resultado["despesas"],
        "records_written": resultado["no_prazo"] + resultado["atrasados"],
    }
