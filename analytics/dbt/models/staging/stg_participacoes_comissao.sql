select id as participacao_id, senador_id, comissao_id, cargo,
       data_inicio, data_fim, timestamp_ingestao
from {{ source('oltp', 'participacoes_comissao') }}
