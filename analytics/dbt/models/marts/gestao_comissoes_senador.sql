{% set data_referencia = var('data_referencia_comissoes', run_started_at.strftime('%Y-%m-%d')) %}
with referencia as (
    select '{{ data_referencia }}'::date as data_referencia
)
select s.senador_id, r.data_referencia,
       count(distinct p.comissao_id) filter (
           where p.data_inicio <= r.data_referencia
             and (p.data_fim is null or p.data_fim >= r.data_referencia)
       ) as comissoes_com_vigencia_confirmada,
       count(p.participacao_id) filter (
           where p.data_inicio is null
             and (p.data_fim is null or p.data_fim >= r.data_referencia)
       ) as vinculos_sem_inicio_conhecido
from {{ ref('dim_senador') }} s cross join referencia r
left join {{ ref('fct_participacoes_comissao') }} p on p.senador_id = s.senador_id
group by s.senador_id, r.data_referencia
