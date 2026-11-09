-- Uma linha por lançamento CEAPS. Preserva datas originais e precisão monetária.
--
-- Índice da consulta de gestão "gasto mensal por categoria de um senador num ano"
-- (ver documentation/docs/otimizacao-consultas.mdx). senador_id e ano são os filtros
-- de igualdade; mes e categoria_id entregam as linhas já na ordem do GROUP BY; valor
-- fecha a cobertura e permite Index Only Scan. O dbt recria a tabela a cada build,
-- por isso o índice é declarado aqui e não criado à mão.
--
-- A tabela recriada nasce sem estatísticas e o planejador estimava 3 linhas onde há
-- centenas. O ANALYZE no post_hook as coleta antes do consumo. VACUUM não é possível
-- aqui (o dbt executa o hook dentro de transação); o mapa de visibilidade que permite
-- Index Only Scan sem consultar a tabela fica a cargo do autovacuum.
{{ config(
    indexes=[
        {'columns': ['senador_id', 'ano', 'mes', 'categoria_id', 'valor']}
    ],
    post_hook="analyze {{ this }}"
) }}

select d.*, current_timestamp as materializado_em
from {{ ref('int_despesas') }} d
