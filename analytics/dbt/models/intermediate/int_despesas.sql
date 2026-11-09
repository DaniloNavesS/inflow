select *, md5(tipo_despesa) as categoria_id,
       case when data_documento_valida then data_despesa end as data_calendario
from {{ ref('stg_despesas') }}
