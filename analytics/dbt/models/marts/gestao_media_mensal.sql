with mensal as (
    select senador_id, ano, mes, sum(valor_total) as total
    from {{ ref('agg_despesas_mensais') }} group by senador_id, ano, mes
)
select senador_id, ano, sum(total) as valor_total, count(*) as meses_com_despesas,
       sum(total) / count(*) as media_mensal
from mensal group by senador_id, ano
