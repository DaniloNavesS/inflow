with esperado as (
    select senador_id, ano, mes, categoria_id, sum(valor) as valor_total, count(*) as quantidade_despesas
    from {{ ref('fct_despesas') }} group by senador_id, ano, mes, categoria_id
), obtido as (
    select senador_id, ano, mes, categoria_id, valor_total, quantidade_despesas
    from {{ ref('agg_despesas_mensais') }}
)
(select * from esperado except all select * from obtido)
union all
(select * from obtido except all select * from esperado)
