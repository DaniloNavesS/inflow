select distinct md5(tipo_despesa) as categoria_id, tipo_despesa
from {{ ref('stg_despesas') }}
