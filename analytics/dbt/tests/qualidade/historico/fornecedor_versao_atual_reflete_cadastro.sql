-- Histórico (SCD2): a versão aberta é exatamente o cadastro atual.
-- Pega fornecedor sem versão atual, versão atual com atributos desatualizados e
-- fornecedor excluído da origem que continua com versão aberta (hard delete não encerrado).
with atual as (
    select fornecedor_id, documento, razao_social from {{ ref('dim_fornecedor') }}
), historico_aberto as (
    select fornecedor_id, documento, razao_social
    from {{ ref('dim_fornecedor_historico') }}
    where versao_atual
)
(select 'sem versão aberta equivalente' as problema, * from atual
 except all
 select 'sem versão aberta equivalente', * from historico_aberto)
union all
(select 'versão aberta sem cadastro equivalente', * from historico_aberto
 except all
 select 'versão aberta sem cadastro equivalente', * from atual)
