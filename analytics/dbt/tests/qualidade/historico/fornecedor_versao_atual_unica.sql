-- Histórico (SCD2): no máximo uma versão aberta por fornecedor.
-- Duas versões atuais fazem o painel contar o mesmo fornecedor duas vezes.
select fornecedor_id, count(*) as versoes_atuais
from {{ ref('dim_fornecedor_historico') }}
where observado_ate is null
group by fornecedor_id
having count(*) > 1
