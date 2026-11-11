-- Cadastro atual; não representa o cadastro na data do documento fiscal.
select * from {{ ref('stg_fornecedores') }}
