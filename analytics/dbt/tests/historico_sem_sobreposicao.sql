with periodos as (
    select *, lead(observado_desde) over (
        partition by fornecedor_id order by observado_desde
    ) as proximo_inicio
    from {{ ref('dim_fornecedor_historico') }}
)
select * from periodos
where observado_ate < observado_desde
   or (proximo_inicio is not null and (observado_ate is null or observado_ate > proximo_inicio))
