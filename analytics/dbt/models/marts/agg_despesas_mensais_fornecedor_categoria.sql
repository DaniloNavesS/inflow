-- Detalhamento mensal para a pergunta central, sem juntar fatos institucionais.
select senador_id, ano, mes, competencia, fornecedor_id, categoria_id,
       sum(valor) as valor_total, count(*) as quantidade_despesas,
       max(materializado_em) as materializado_em
from {{ ref('fct_despesas') }}
group by senador_id, ano, mes, competencia, fornecedor_id, categoria_id
