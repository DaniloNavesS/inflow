-- Histórico (SCD2): intervalos [observado_desde, observado_ate) não vazios e nunca no futuro.
-- O snapshot grava timestamp sem fuso no horário da sessão; localtimestamp usa a mesma base.
select fornecedor_id, fornecedor_versao_id, observado_desde, observado_ate
from {{ ref('dim_fornecedor_historico') }}
where observado_desde > localtimestamp
   or observado_ate > localtimestamp
   or observado_ate <= observado_desde
