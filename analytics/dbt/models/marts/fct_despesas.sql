-- Uma linha por lançamento CEAPS. Preserva datas originais e precisão monetária.
--
-- Índice da consulta de gestão "gasto mensal por categoria de um senador num ano"
-- (ver documentation/docs/otimizacao-consultas.mdx). senador_id e ano são os filtros
-- de igualdade; mes e categoria_id entregam as linhas já na ordem do GROUP BY; valor
-- fecha a cobertura e permite Index Only Scan. O dbt recria a tabela a cada build,
-- por isso o índice é declarado aqui e não criado à mão.
{{ config(
    indexes=[
        {'columns': ['senador_id', 'ano', 'mes', 'categoria_id', 'valor']}
    ]
) }}

select d.*, current_timestamp as materializado_em
from {{ ref('int_despesas') }} d
