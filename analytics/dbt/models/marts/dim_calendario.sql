with limites as (
    select min(dia) as inicio, max(dia) as fim from (
        select competencia as dia from {{ ref('int_despesas') }}
        union all
        select data_calendario from {{ ref('int_despesas') }}
    ) datas
)
select dia::date as data_id, extract(year from dia)::int as ano,
       extract(month from dia)::int as mes, extract(day from dia)::int as dia,
       extract(quarter from dia)::int as trimestre
from limites cross join lateral generate_series(inicio, fim, interval '1 day') as calendario(dia)
