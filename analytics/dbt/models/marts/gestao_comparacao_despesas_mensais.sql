select mensal_id, senador_id, ano, mes, competencia, valor_total, quantidade_despesas,
       dias_exercicio, em_exercicio_no_mes, partido_competencia, uf_competencia,
       status_partido as status_contexto_partido, status_uf as status_contexto_uf,
       case when not apto_partido then status_partido
            when quantidade_pares_partido=0 then 'SEM_PARES' else 'COMPARAVEL' end as status_comparacao_partido,
       case when not apto_uf then status_uf
            when quantidade_pares_uf=0 then 'SEM_PARES' else 'COMPARAVEL' end as status_comparacao_uf,
       quantidade_pares_partido, media_pares_partido,
       valor_total-media_pares_partido as diferenca_media_partido,
       100*(valor_total-media_pares_partido)/nullif(media_pares_partido,0) as desvio_percentual_partido,
       valor_total>media_pares_partido as acima_media_partido,
       quantidade_pares_uf, media_pares_uf,
       valor_total-media_pares_uf as diferenca_media_uf,
       100*(valor_total-media_pares_uf)/nullif(media_pares_uf,0) as desvio_percentual_uf,
       valor_total>media_pares_uf as acima_media_uf,
       contexto_source_url, contexto_sha256, contexto_coletado_em, materializado_em
from {{ ref('int_comparacao_despesas_mensais') }}
