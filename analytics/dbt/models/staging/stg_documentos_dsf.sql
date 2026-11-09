select id as documento_dsf_id, sessao_id, codigo_diario, numero_diario,
       data_publicacao, url_documento, pagina_inicial, pagina_final,
       sha256, status_parser, mensagem_parser, atualizado_em
from {{ source('oltp', 'documento_dsf') }}
