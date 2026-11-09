-- EXCEPT ALL detecta perdas, duplicações e alteração de valores por chave.
with origem as (select id, valor from {{ source('oltp', 'despesas') }}),
destino as (select despesa_id as id, valor from {{ ref('fct_despesas') }})
(select * from origem except all select * from destino)
union all
(select * from destino except all select * from origem)
