with origem as (
    select senador_id, ano, mes, sum(valor) as valor_total, count(*) as quantidade_despesas
    from {{ source('oltp','despesas') }} group by senador_id,ano,mes
), destino as (
    select senador_id,ano,mes,valor_total,quantidade_despesas from {{ ref('gestao_comparacao_despesas_mensais') }}
), detalhamento as (
    select senador_id,ano,mes,sum(valor_total) as valor_total,
           sum(quantidade_despesas)::bigint as quantidade_despesas
    from {{ ref('agg_despesas_mensais_fornecedor_categoria') }} group by senador_id,ano,mes
)
(select * from origem except all select * from destino)
union all
(select * from destino except all select * from origem)
union all
(select * from origem except all select * from detalhamento)
union all
(select * from detalhamento except all select * from origem)
