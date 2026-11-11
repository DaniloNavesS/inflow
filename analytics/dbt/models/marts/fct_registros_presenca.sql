-- Uma linha documental da origem, inclusive sem senador identificado.
select p.*, s.data_sessao, d.status_parser,
       coalesce(p.sessao_id = d.sessao_id, false) as sessao_documento_consistente,
       coalesce(p.senador_id is not null and p.resolucao = 'EXATA'
           and p.situacao = 'PRESENTE' and d.status_parser = 'SUCESSO'
           and p.sessao_id = d.sessao_id, false) as apto_contagem,
       current_timestamp as materializado_em
from {{ ref('stg_registros_presenca') }} p
left join {{ ref('dim_sessao_plenaria') }} s on s.sessao_id = p.sessao_id
left join {{ ref('dim_documento_dsf') }} d on d.documento_dsf_id = p.documento_dsf_id
