with diferencas_comissao as (
    (select id, senador_id, comissao_id, cargo, data_inicio, data_fim
     from {{ source('oltp', 'participacoes_comissao') }}
     except all
     select participacao_id, senador_id, comissao_id, cargo, data_inicio, data_fim
     from {{ ref('fct_participacoes_comissao') }})
    union all
    (select participacao_id, senador_id, comissao_id, cargo, data_inicio, data_fim
     from {{ ref('fct_participacoes_comissao') }}
     except all
     select id, senador_id, comissao_id, cargo, data_inicio, data_fim
     from {{ source('oltp', 'participacoes_comissao') }})
), diferencas_gabinete as (
    (select id, senador_id, ano, qtd_pessoal_gabinete, qtd_pessoal_escritorio,
            qtd_total_servidores, auxilio_moradia, imovel_funcional
     from {{ source('oltp', 'estrutura_gabinete') }}
     except all
     select estrutura_id, senador_id, ano, qtd_pessoal_gabinete, qtd_pessoal_escritorio,
            qtd_total_servidores, auxilio_moradia, imovel_funcional
     from {{ ref('fct_estrutura_gabinete') }})
    union all
    (select estrutura_id, senador_id, ano, qtd_pessoal_gabinete, qtd_pessoal_escritorio,
            qtd_total_servidores, auxilio_moradia, imovel_funcional
     from {{ ref('fct_estrutura_gabinete') }}
     except all
     select id, senador_id, ano, qtd_pessoal_gabinete, qtd_pessoal_escritorio,
            qtd_total_servidores, auxilio_moradia, imovel_funcional
     from {{ source('oltp', 'estrutura_gabinete') }})
)
select 'participacoes' as modelo from diferencas_comissao
union all
select 'gabinete' from diferencas_gabinete
