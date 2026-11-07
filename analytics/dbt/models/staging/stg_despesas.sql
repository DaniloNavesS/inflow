select id as despesa_id, senador_id, fornecedor_id, data_despesa,
       ano, mes, tipo_despesa, valor, atualizado_em,
       make_date(ano, mes, 1) as competencia,
       data_despesa between date '2000-01-01' and date '2100-12-31' as data_documento_valida
from {{ source('oltp', 'despesas') }}
