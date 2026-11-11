with base as (
    select *, em_exercicio_no_mes and status_partido='UNICO'
                  and partido_competencia is not null as apto_partido,
              em_exercicio_no_mes and status_uf='UNICO'
                  and uf_competencia is not null as apto_uf
    from {{ ref('fct_despesas_mensais') }}
), grupos as (
    select *,
        count(*) filter (where apto_partido) over (partition by ano, mes, partido_competencia) as tamanho_grupo_partido,
        sum(valor_total) filter (where apto_partido) over (partition by ano, mes, partido_competencia) as total_grupo_partido,
        count(*) filter (where apto_uf) over (partition by ano, mes, uf_competencia) as tamanho_grupo_uf,
        sum(valor_total) filter (where apto_uf) over (partition by ano, mes, uf_competencia) as total_grupo_uf
    from base
)
select *,
    case when apto_partido then tamanho_grupo_partido-1 end as quantidade_pares_partido,
    case when apto_uf then tamanho_grupo_uf-1 end as quantidade_pares_uf,
    case when apto_partido and tamanho_grupo_partido>1
         then (total_grupo_partido-valor_total)/(tamanho_grupo_partido-1) end as media_pares_partido,
    case when apto_uf and tamanho_grupo_uf>1
         then (total_grupo_uf-valor_total)/(tamanho_grupo_uf-1) end as media_pares_uf
from grupos
