-- Histórico (SCD2): versões consecutivas e contíguas precisam diferir em algum atributo
-- rastreado. Versão idêntica à anterior indica snapshot reprocessado sem mudança real,
-- o que infla contagens de "alterações cadastrais". Versões separadas por lacuna
-- (exclusão seguida de reinclusão) podem repetir os atributos.
with ordenado as (
    select *,
        lag(observado_ate) over w as fim_anterior,
        lag(documento) over w as documento_anterior,
        lag(razao_social) over w as razao_social_anterior
    from {{ ref('dim_fornecedor_historico') }}
    window w as (partition by fornecedor_id order by observado_desde)
)
select fornecedor_id, fornecedor_versao_id, observado_desde, documento, razao_social
from ordenado
where fim_anterior = observado_desde
  and documento is not distinct from documento_anterior
  and razao_social is not distinct from razao_social_anterior
