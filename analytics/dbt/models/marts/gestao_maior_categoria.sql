with totais as (
    select senador_id, ano, categoria_id, sum(valor_total) as valor_total
    from {{ ref('agg_despesas_mensais') }} group by senador_id, ano, categoria_id
), ranking as (
    select *, dense_rank() over (partition by senador_id, ano order by valor_total desc) as posicao,
           sum(valor_total) over (partition by senador_id, ano) as valor_total_ano
    from totais
)
select r.senador_id, r.ano, c.tipo_despesa, r.valor_total, r.valor_total_ano,
       100 * r.valor_total / nullif(r.valor_total_ano, 0) as percentual_total_ano
from ranking r join {{ ref('dim_categoria_despesa') }} c using (categoria_id)
where posicao = 1
