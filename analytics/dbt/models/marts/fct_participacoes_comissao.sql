-- Uma linha por registro da origem, não por comissão distinta.
select *, data_inicio is not null as inicio_conhecido,
       current_timestamp as materializado_em
from {{ ref('stg_participacoes_comissao') }}
