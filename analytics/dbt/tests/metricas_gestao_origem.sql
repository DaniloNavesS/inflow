-- Recalcula as perguntas 1 e 11 diretamente no OLTP, sem usar a agregação mensal.
with mensal as (
    select senador_id, ano, mes, sum(valor) as total
    from {{ source('oltp', 'despesas') }} group by senador_id, ano, mes
), media_esperada as (
    select senador_id, ano, sum(total) as valor_total, count(*) as meses_com_despesas,
           sum(total) / count(*) as media_mensal
    from mensal group by senador_id, ano
), categorias as (
    select senador_id, ano, tipo_despesa, sum(valor) as valor_total
    from {{ source('oltp', 'despesas') }} group by senador_id, ano, tipo_despesa
), ranking as (
    select *, dense_rank() over (partition by senador_id, ano order by valor_total desc) as posicao,
           sum(valor_total) over (partition by senador_id, ano) as valor_total_ano
    from categorias
), categorias_esperadas as (
    select senador_id, ano, tipo_despesa, valor_total, valor_total_ano,
           100 * valor_total / nullif(valor_total_ano, 0) as percentual_total_ano
    from ranking where posicao = 1
), diferencas_media as (
    (select * from media_esperada except all select * from {{ ref('gestao_media_mensal') }})
    union all
    (select * from {{ ref('gestao_media_mensal') }} except all select * from media_esperada)
), diferencas_categoria as (
    (select * from categorias_esperadas except all select * from {{ ref('gestao_maior_categoria') }})
    union all
    (select * from {{ ref('gestao_maior_categoria') }} except all select * from categorias_esperadas)
)
select 'media_mensal' as metrica from diferencas_media
union all
select 'maior_categoria' from diferencas_categoria
