select id as fornecedor_id, cnpj_cpf as documento, razao_social
from {{ source('oltp', 'fornecedores') }}
