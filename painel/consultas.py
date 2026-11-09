"""Consultas do painel: somente leitura, SQL parametrizado, apenas analytics_marts e monitoring."""
import os
from decimal import Decimal

import pandas as pd
import psycopg2

# Nome de coluna não pode ser parâmetro SQL: lista fechada (coluna do grupo, coluna de status).
GRUPOS_VALIDOS = {
    "partido": ("partido_competencia", "status_partido"),
    "uf": ("uf_competencia", "status_uf"),
}

CHAVES_FILTRO = ("anos", "partidos", "ufs", "senadores", "categorias")


def conectar():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "inflow_db"),
        user=os.getenv("DB_USER", "inflow_user"),
        password=os.getenv("DB_PASSWORD", "inflow_pass"),
        connect_timeout=5,
        options="-c statement_timeout=10000 -c default_transaction_read_only=on",
    )


def _consultar(sql, params=None):
    conn = conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            colunas = [c.name for c in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=colunas)
    finally:
        conn.close()
    # NUMERIC chega como Decimal; os gráficos precisam de float.
    for coluna in df.columns:
        if df[coluna].map(lambda v: isinstance(v, Decimal)).any():
            df[coluna] = pd.to_numeric(df[coluna], errors="coerce").astype(float)
    return df


def _filtros(filtros):
    """Normaliza os filtros; lista vazia significa 'todos'."""
    filtros = filtros or {}
    return {k: list(filtros.get(k) or []) for k in CHAVES_FILTRO}


def _clausula(coluna, chave, valores, tipo):
    """Fragmento parametrizado: (cardinality(%(chave)s) = 0 OR coluna = ANY(%(chave)s))."""
    return f"(cardinality(%({chave})s::{tipo}[]) = 0 OR {coluna} = ANY(%({chave})s::{tipo}[]))"


def ultima_atualizacao():
    return _consultar(
        """
        SELECT
            (SELECT max(finished_at) FROM monitoring.pipeline_runs
              WHERE pipeline_name = 'senate_ingestion' AND status = 'success') AS coleta,
            (SELECT max(materializado_em) FROM analytics_marts.fct_despesas) AS modelos
        """
    )


def opcoes_filtros():
    anos = _consultar("SELECT DISTINCT ano FROM analytics_marts.gestao_media_mensal ORDER BY ano")
    # Atuais (perguntas 1, 11 e gasto mensal) e da competência (perguntas 4 e 10).
    partidos = _consultar(
        "SELECT partido_atual AS partido FROM analytics_marts.dim_senador WHERE partido_atual IS NOT NULL "
        "UNION SELECT partido_competencia FROM analytics_marts.fct_despesas_mensais "
        "WHERE partido_competencia IS NOT NULL ORDER BY 1"
    )
    ufs = _consultar(
        "SELECT uf_atual AS uf FROM analytics_marts.dim_senador WHERE uf_atual IS NOT NULL "
        "UNION SELECT uf_competencia FROM analytics_marts.fct_despesas_mensais "
        "WHERE uf_competencia IS NOT NULL ORDER BY 1"
    )
    senadores = _consultar(
        "SELECT senador_id, nome FROM analytics_marts.dim_senador ORDER BY nome"
    )
    categorias = _consultar(
        "SELECT categoria_id, tipo_despesa FROM analytics_marts.dim_categoria_despesa ORDER BY tipo_despesa"
    )
    return {
        "anos": anos,
        "partidos": partidos,
        "ufs": ufs,
        "senadores": senadores,
        "categorias": categorias,
    }


def media_mensal_senador(filtros=None):
    """Pergunta 1: média mensal de gasto de cada senador (meses com despesas)."""
    f = _filtros(filtros)
    return _consultar(
        f"""
        SELECT s.senador_id, s.nome, s.partido_atual, s.uf_atual, g.ano,
               g.valor_total, g.meses_com_despesas, g.media_mensal
        FROM analytics_marts.gestao_media_mensal g
        JOIN analytics_marts.dim_senador s USING (senador_id)
        WHERE {_clausula('g.ano', 'anos', f['anos'], 'int')}
          AND {_clausula('s.partido_atual', 'partidos', f['partidos'], 'text')}
          AND {_clausula('s.uf_atual', 'ufs', f['ufs'], 'text')}
          AND {_clausula('s.senador_id', 'senadores', f['senadores'], 'int')}
        ORDER BY g.media_mensal DESC, s.nome
        """,
        f,
    )


def _filtros_competencia(f):
    """Filtros sobre fct_despesas_mensais: partido e UF da competência, não os atuais."""
    return f"""
          {_clausula('m.ano', 'anos', f['anos'], 'int')}
          AND {_clausula('m.partido_competencia', 'partidos', f['partidos'], 'text')}
          AND {_clausula('m.uf_competencia', 'ufs', f['ufs'], 'text')}
          AND {_clausula('m.senador_id', 'senadores', f['senadores'], 'int')}"""


def media_mensal_por_grupo(grupo, filtros=None):
    """Perguntas 4 e 10: gasto médio por senador-mês, por partido ou UF da competência.

    Usa o contexto histórico mensal (fct_despesas_mensais). Entram só competências com
    lançamentos, senador em exercício e classificação única; as demais aparecem em
    competencias_fora_do_grupo, sem descartar valores.
    """
    if grupo not in GRUPOS_VALIDOS:
        raise ValueError(f"grupo inválido: {grupo!r}; use um de {tuple(GRUPOS_VALIDOS)}")
    coluna, status = GRUPOS_VALIDOS[grupo]
    f = _filtros(filtros)
    return _consultar(
        f"""
        SELECT m.{coluna} AS grupo, m.ano,
               count(DISTINCT m.senador_id) AS senadores,
               count(*) AS competencias,
               sum(m.valor_total) AS valor_total,
               sum(m.valor_total) / count(*) AS media_mensal
        FROM analytics_marts.fct_despesas_mensais m
        WHERE m.em_exercicio_no_mes
          AND m.{status} = 'UNICO'
          AND m.{coluna} IS NOT NULL
          AND {_filtros_competencia(f)}
        GROUP BY m.{coluna}, m.ano
        ORDER BY m.ano, media_mensal DESC
        """,
        f,
    )


def competencias_fora_do_grupo(grupo, filtros=None):
    """Competências que não entram nas perguntas 4/10, por estado do contexto."""
    if grupo not in GRUPOS_VALIDOS:
        raise ValueError(f"grupo inválido: {grupo!r}; use um de {tuple(GRUPOS_VALIDOS)}")
    coluna, status = GRUPOS_VALIDOS[grupo]
    f = _filtros(filtros)
    return _consultar(
        f"""
        SELECT m.ano,
               CASE WHEN NOT m.em_exercicio_no_mes AND m.{status} = 'UNICO'
                    THEN 'SEM_EXERCICIO' ELSE m.{status} END AS estado,
               count(*) AS competencias,
               sum(m.valor_total) AS valor_total
        FROM analytics_marts.fct_despesas_mensais m
        WHERE NOT (m.em_exercicio_no_mes AND m.{status} = 'UNICO' AND m.{coluna} IS NOT NULL)
          AND {_clausula('m.ano', 'anos', f['anos'], 'int')}
          AND {_clausula('m.senador_id', 'senadores', f['senadores'], 'int')}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        f,
    )


def maior_categoria(filtros=None):
    """Pergunta 11: categoria de maior gasto de cada senador (pode haver empates)."""
    f = _filtros(filtros)
    return _consultar(
        f"""
        SELECT s.senador_id, s.nome, s.partido_atual, s.uf_atual, m.ano, m.tipo_despesa,
               m.valor_total, m.valor_total_ano, m.percentual_total_ano
        FROM analytics_marts.gestao_maior_categoria m
        JOIN analytics_marts.dim_senador s USING (senador_id)
        WHERE {_clausula('m.ano', 'anos', f['anos'], 'int')}
          AND {_clausula('s.partido_atual', 'partidos', f['partidos'], 'text')}
          AND {_clausula('s.uf_atual', 'ufs', f['ufs'], 'text')}
          AND {_clausula('s.senador_id', 'senadores', f['senadores'], 'int')}
          AND (cardinality(%(categorias)s::text[]) = 0 OR m.tipo_despesa IN (
                SELECT tipo_despesa FROM analytics_marts.dim_categoria_despesa
                WHERE categoria_id = ANY(%(categorias)s::text[])))
        ORDER BY m.ano, s.nome
        """,
        f,
    )


def gasto_mensal(filtros=None):
    """Série mensal de gasto (agg_despesas_mensais), com filtro de categoria."""
    f = _filtros(filtros)
    return _consultar(
        f"""
        SELECT a.ano, a.mes, a.competencia,
               sum(a.valor_total) AS valor_total,
               sum(a.quantidade_despesas) AS quantidade_despesas
        FROM analytics_marts.agg_despesas_mensais a
        JOIN analytics_marts.dim_senador s USING (senador_id)
        WHERE {_clausula('a.ano', 'anos', f['anos'], 'int')}
          AND {_clausula('s.partido_atual', 'partidos', f['partidos'], 'text')}
          AND {_clausula('s.uf_atual', 'ufs', f['ufs'], 'text')}
          AND {_clausula('s.senador_id', 'senadores', f['senadores'], 'int')}
          AND {_clausula('a.categoria_id', 'categorias', f['categorias'], 'text')}
        GROUP BY a.ano, a.mes, a.competencia
        ORDER BY a.ano, a.mes
        """,
        f,
    )


def _filtros_comparacao(f):
    return f"""
          {_clausula('c.ano', 'anos', f['anos'], 'int')}
          AND {_clausula('c.partido_competencia', 'partidos', f['partidos'], 'text')}
          AND {_clausula('c.uf_competencia', 'ufs', f['ufs'], 'text')}
          AND {_clausula('c.senador_id', 'senadores', f['senadores'], 'int')}"""


def comparacao_resumo(filtros=None):
    """Pergunta central: por senador e ano, quanto gastou acima/abaixo da média dos pares.

    Soma só diferenças em reais de competências COMPARAVEL; percentuais não são somados.
    """
    f = _filtros(filtros)
    return _consultar(
        f"""
        SELECT s.senador_id, s.nome, c.ano,
               string_agg(DISTINCT c.partido_competencia, ', ') AS partidos_no_ano,
               string_agg(DISTINCT c.uf_competencia, ', ') AS ufs_no_ano,
               count(*) AS competencias,
               sum(c.valor_total) AS valor_total,
               count(*) FILTER (WHERE c.status_comparacao_partido = 'COMPARAVEL') AS meses_comparaveis_partido,
               count(*) FILTER (WHERE c.status_comparacao_partido = 'COMPARAVEL' AND c.acima_media_partido)
                   AS meses_acima_partido,
               sum(c.diferenca_media_partido) FILTER (WHERE c.status_comparacao_partido = 'COMPARAVEL')
                   AS diferenca_acumulada_partido,
               count(*) FILTER (WHERE c.status_comparacao_uf = 'COMPARAVEL') AS meses_comparaveis_uf,
               count(*) FILTER (WHERE c.status_comparacao_uf = 'COMPARAVEL' AND c.acima_media_uf)
                   AS meses_acima_uf,
               sum(c.diferenca_media_uf) FILTER (WHERE c.status_comparacao_uf = 'COMPARAVEL')
                   AS diferenca_acumulada_uf
        FROM analytics_marts.gestao_comparacao_despesas_mensais c
        JOIN analytics_marts.dim_senador s USING (senador_id)
        WHERE c.em_exercicio_no_mes
          AND {_filtros_comparacao(f)}
        GROUP BY s.senador_id, s.nome, c.ano
        ORDER BY c.ano, diferenca_acumulada_partido DESC NULLS LAST, s.nome
        """,
        f,
    )


def comparacao_mensal(filtros=None):
    """Pergunta central: uma linha por senador e competência, com estados e pares visíveis."""
    f = _filtros(filtros)
    return _consultar(
        f"""
        SELECT s.senador_id, s.nome, c.ano, c.mes, c.competencia, c.valor_total, c.dias_exercicio,
               c.partido_competencia, c.status_comparacao_partido, c.quantidade_pares_partido,
               c.media_pares_partido, c.diferenca_media_partido, c.desvio_percentual_partido,
               c.uf_competencia, c.status_comparacao_uf, c.quantidade_pares_uf,
               c.media_pares_uf, c.diferenca_media_uf, c.desvio_percentual_uf
        FROM analytics_marts.gestao_comparacao_despesas_mensais c
        JOIN analytics_marts.dim_senador s USING (senador_id)
        WHERE c.em_exercicio_no_mes
          AND {_filtros_comparacao(f)}
        ORDER BY c.ano, c.mes, c.valor_total DESC, s.senador_id
        """,
        f,
    )
