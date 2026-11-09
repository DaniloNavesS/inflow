-- Histórico mensal de partido/UF: o status descreve o valor publicado.
--   UNICO         <-> partido/UF preenchido
--   SEM_EXERCICIO <-> zero dias em exercício (para partido e UF ao mesmo tempo)
--   dias_exercicio entre 0 e o número de dias da competência
with contexto as (
    select *,
        extract(day from (make_date(ano, mes, 1) + interval '1 month' - interval '1 day'))::int as dias_no_mes
    from {{ ref('dim_contexto_parlamentar_mensal') }}
)
select contexto_id, dias_exercicio, dias_no_mes, partido_competencia, status_partido,
       uf_competencia, status_uf
from contexto
where (status_partido = 'UNICO') <> (partido_competencia is not null)
   or (status_uf = 'UNICO') <> (uf_competencia is not null)
   or (status_partido = 'SEM_EXERCICIO') <> (dias_exercicio = 0)
   or (status_uf = 'SEM_EXERCICIO') <> (dias_exercicio = 0)
   or dias_exercicio is null
   or dias_exercicio not between 0 and dias_no_mes
