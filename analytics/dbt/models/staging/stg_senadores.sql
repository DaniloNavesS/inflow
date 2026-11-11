select id as senador_id, nome, partido as partido_atual, uf as uf_atual
from {{ source('oltp', 'senadores') }}
