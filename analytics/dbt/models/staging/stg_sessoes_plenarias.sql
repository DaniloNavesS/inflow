select id as sessao_id, numero, data_sessao, tipo, legislatura,
       sessao_legislativa, atualizado_em
from {{ source('oltp', 'sessao_plenaria') }}
