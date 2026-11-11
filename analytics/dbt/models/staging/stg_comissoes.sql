select id as comissao_id, sigla, nome, casa
from {{ source('oltp', 'comissoes') }}
