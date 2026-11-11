with mensal as (
    select senador_id, ano, mes, competencia, sum(valor_total) as valor_total,
           sum(quantidade_despesas)::bigint as quantidade_despesas,
           max(materializado_em) as materializado_em
    from {{ ref('agg_despesas_mensais') }} group by senador_id, ano, mes, competencia
)
select m.*, m.senador_id::text || ':' || m.ano::text || ':' || m.mes::text as mensal_id,
       c.dias_exercicio, c.partido_competencia, c.uf_competencia,
       coalesce(c.status_partido, 'NAO_COLETADO') as status_partido,
       coalesce(c.status_uf, 'NAO_COLETADO') as status_uf,
       coalesce(c.dias_exercicio > 0, false) as em_exercicio_no_mes,
       c.source_url as contexto_source_url, c.fonte_sha256 as contexto_sha256,
       c.coletado_em as contexto_coletado_em
from mensal m
left join {{ ref('dim_contexto_parlamentar_mensal') }} c
    on c.senador_id=m.senador_id and c.ano=m.ano and c.mes=m.mes
