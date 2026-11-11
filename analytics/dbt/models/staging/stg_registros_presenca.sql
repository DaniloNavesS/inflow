select id as registro_presenca_id, sessao_id, documento_dsf_id, senador_id,
       nome_documento, partido_documento, uf_documento, situacao,
       voto_registrado, pagina, resolucao, atualizado_em
from {{ source('oltp', 'registro_presenca') }}
