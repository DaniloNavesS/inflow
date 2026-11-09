-- Validação independente das janelas: peers por autojunção e média direta.
with base as (
    select d.senador_id,d.ano,d.mes,sum(d.valor) as valor_total,
           c.partido_competencia,c.uf_competencia,c.status_partido,c.status_uf,c.dias_exercicio
    from {{ source('oltp','despesas') }} d
    left join {{ ref('dim_contexto_parlamentar_mensal') }} c
      on c.senador_id=d.senador_id and c.ano=d.ano and c.mes=d.mes
    group by d.senador_id,d.ano,d.mes,c.partido_competencia,c.uf_competencia,
             c.status_partido,c.status_uf,c.dias_exercicio
), esperado as (
    select a.senador_id,a.ano,a.mes,
        (select avg(b.valor_total) from base b
         where b.ano=a.ano and b.mes=a.mes and b.senador_id<>a.senador_id
           and a.dias_exercicio>0 and b.dias_exercicio>0
           and a.status_partido='UNICO' and b.status_partido='UNICO'
           and b.partido_competencia=a.partido_competencia) as media_pares_partido,
        (select avg(b.valor_total) from base b
         where b.ano=a.ano and b.mes=a.mes and b.senador_id<>a.senador_id
           and a.dias_exercicio>0 and b.dias_exercicio>0
           and a.status_uf='UNICO' and b.status_uf='UNICO'
           and b.uf_competencia=a.uf_competencia) as media_pares_uf
    from base a
), obtido as (
    select senador_id,ano,mes,media_pares_partido,media_pares_uf
    from {{ ref('gestao_comparacao_despesas_mensais') }}
)
(select * from esperado except all select * from obtido)
union all
(select * from obtido except all select * from esperado)
