select dbt_scd_id as fornecedor_versao_id, fornecedor_id, documento, razao_social,
       dbt_valid_from as observado_desde, dbt_valid_to as observado_ate,
       dbt_valid_to is null as versao_atual
from {{ ref('fornecedores_historico') }}
