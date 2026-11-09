{#
  Volume mínimo absoluto. `minimo` é número ou nome de limite (vars.limites_qualidade).
  Pega carga vazia ou truncada antes que o painel mostre zeros como se fossem dados.
#}
{% test volume_minimo(model, minimo) %}
{%- set limite = qualidade_valor(minimo) %}
select count(*) as linhas, {{ limite }} as minimo_esperado
from {{ model }}
having count(*) < {{ limite }}
{% endtest %}


{#
  Volume entre camadas: a contagem do modelo deve ser igual à de outra relação.
  `expressao_contagem` é avaliada sobre `comparar_com` (ex.: count(distinct senador_id))
  e `filtro`, quando informado, restringe `comparar_com`.
#}
{% test volume_igual(model, comparar_com, expressao_contagem='count(*)', filtro=none) %}
with obtido as (
    select count(*) as linhas from {{ model }}
), esperado as (
    select {{ expressao_contagem }} as linhas from {{ comparar_com }}
    {% if filtro %}where {{ filtro }}{% endif %}
)
select o.linhas as linhas_modelo, e.linhas as linhas_esperadas
from obtido o cross join esperado e
where o.linhas <> e.linhas
{% endtest %}


{#
  Volume por partição: aponta grupos (ex.: competência) cuja contagem fica abaixo de uma
  fração da mediana dos grupos. Detecta mês carregado pela metade, sem exigir número fixo.
#}
{% test volume_por_grupo(model, grupo, fracao_minima_mediana) %}
{%- set fracao = qualidade_valor(fracao_minima_mediana) %}
with contagens as (
    select {{ grupo }} as grupo, count(*) as linhas
    from {{ model }}
    group by {{ grupo }}
), referencia as (
    select percentile_cont(0.5) within group (order by linhas) as mediana
    from contagens
)
select c.grupo, c.linhas, r.mediana, {{ fracao }} as fracao_minima
from contagens c cross join referencia r
where c.linhas < {{ fracao }} * r.mediana
{% endtest %}
