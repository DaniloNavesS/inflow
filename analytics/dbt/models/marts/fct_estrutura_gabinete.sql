-- Quantitativos anuais: não somar anos para contar pessoas distintas.
select *, current_timestamp as materializado_em
from {{ ref('stg_estrutura_gabinete') }}
