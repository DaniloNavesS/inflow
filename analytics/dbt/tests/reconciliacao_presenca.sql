with origem as (
    select id, sessao_id, documento_dsf_id, senador_id, nome_documento,
           partido_documento, uf_documento, situacao, voto_registrado, pagina, resolucao
    from {{ source('oltp', 'registro_presenca') }}
), destino as (
    select registro_presenca_id as id, sessao_id, documento_dsf_id, senador_id, nome_documento,
           partido_documento, uf_documento, situacao, voto_registrado, pagina, resolucao
    from {{ ref('fct_registros_presenca') }}
)
(select * from origem except all select * from destino)
union all
(select * from destino except all select * from origem)
