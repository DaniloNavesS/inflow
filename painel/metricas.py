"""Definições SQL das métricas que o painel calcula por conta própria.

Fica num módulo só para que a troca pela camada semântica da E4 mexa em um lugar. Hoje cobre o que
não vem pronto de um mart: a média por grupo (perguntas 4 e 10) e a regra de elegibilidade da
competência. Ver "Onde cada métrica é calculada" em documentation/docs/painel.mdx.
"""

# Nome de coluna não pode ser parâmetro SQL: lista fechada (coluna do grupo, coluna de status).
GRUPOS_VALIDOS = {
    "partido": ("partido_competencia", "status_partido"),
    "uf": ("uf_competencia", "status_uf"),
}


def media_senador_mes(alias):
    """Gasto médio por senador-mês: soma dos valores sobre as competências elegíveis.

    Inclui o próprio senador no grupo, ao contrário da média dos pares da pergunta central
    (int_comparacao_despesas_mensais), que o exclui.
    """
    return f"sum({alias}.valor_total) / count(*)"


def competencia_elegivel(alias, grupo):
    """Competência que entra na média do grupo: em exercício, classificação única e grupo conhecido.

    Mesma regra de apto_partido/apto_uf no dbt (int_comparacao_despesas_mensais). Negar o resultado
    dá as competências fora do cálculo.
    """
    if grupo not in GRUPOS_VALIDOS:
        raise ValueError(f"grupo inválido: {grupo!r}; use um de {tuple(GRUPOS_VALIDOS)}")
    coluna, status = GRUPOS_VALIDOS[grupo]
    return (
        f"{alias}.em_exercicio_no_mes AND {alias}.{status} = 'UNICO' "
        f"AND {alias}.{coluna} IS NOT NULL"
    )
