-- Unicidade da identidade no histórico: um mesmo CNPJ/CPF não pode estar aberto em dois
-- fornecedor_id ao mesmo tempo. A origem garante isso por constraint; aqui verificamos que
-- o snapshot não reintroduziu a colisão (por exemplo, após recarga com novos IDs).
select documento, count(distinct fornecedor_id) as fornecedores
from {{ ref('dim_fornecedor_historico') }}
where versao_atual
group by documento
having count(distinct fornecedor_id) > 1
