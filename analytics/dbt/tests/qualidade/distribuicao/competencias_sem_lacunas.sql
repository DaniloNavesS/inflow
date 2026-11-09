-- Distribuição temporal: entre a primeira e a última competência carregada de cada ano,
-- todo mês tem ao menos um lançamento. Um mês inteiro sem despesas na CEAPS indica falha
-- de coleta, não ausência de gasto; o painel mostraria queda inexistente.
with meses as (
    select ano, mes from {{ ref('fct_despesas') }} group by ano, mes
), limites as (
    select ano, min(mes) as primeiro, max(mes) as ultimo from meses group by ano
)
select l.ano, esperado.mes as mes_sem_lancamentos
from limites l
cross join lateral generate_series(l.primeiro::int, l.ultimo::int) as esperado(mes)
left join meses m on m.ano = l.ano and m.mes = esperado.mes
where m.mes is null
