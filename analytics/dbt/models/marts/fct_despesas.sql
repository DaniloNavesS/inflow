-- Uma linha por lançamento CEAPS. Preserva datas originais e precisão monetária.
select d.*, current_timestamp as materializado_em
from {{ ref('int_despesas') }} d
