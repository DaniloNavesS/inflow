{#
  Distribuição: faixa válida de uma coluna numérica ou de data. Limites são números,
  nomes de limite (vars.limites_qualidade) ou, para datas, literais SQL entre aspas.
  Nulos são ignorados; use not_null para exigi-los.
#}
{% test intervalo_valores(model, column_name, minimo=none, maximo=none) %}
{%- set minimo = qualidade_valor(minimo) %}
{%- set maximo = qualidade_valor(maximo) %}
select {{ column_name }} as valor
from {{ model }}
where {{ column_name }} is not null
  and (
    false
    {% if minimo is not none %} or {{ column_name }} < {{ minimo }}{% endif %}
    {% if maximo is not none %} or {{ column_name }} > {{ maximo }}{% endif %}
  )
{% endtest %}


{#
  Distribuição: fração de linhas que satisfazem `condicao` deve ficar em [minimo, maximo].
  Tabela vazia não é avaliada (volume é responsabilidade dos testes de volume).
#}
{% test proporcao(model, condicao, minimo=none, maximo=none) %}
{%- set minimo = qualidade_valor(minimo) %}
{%- set maximo = qualidade_valor(maximo) %}
with medida as (
    select count(*) as linhas,
           count(*) filter (where coalesce(({{ condicao }}), false)) as atendem
    from {{ model }}
)
select linhas, atendem, atendem::numeric / linhas as proporcao,
       {{ minimo if minimo is not none else 'null' }} as minimo,
       {{ maximo if maximo is not none else 'null' }} as maximo
from medida
where linhas > 0
  and (
    false
    {% if minimo is not none %} or atendem::numeric / linhas < {{ minimo }}{% endif %}
    {% if maximo is not none %} or atendem::numeric / linhas > {{ maximo }}{% endif %}
  )
{% endtest %}


{#
  Distribuição: nenhum grupo concentra mais que `maximo` (fração) do total de `medida`.
  Ex.: um único fornecedor com 90% do gasto indica carga parcial ou chave colapsada.
#}
{% test concentracao_maxima(model, grupo, medida, maximo) %}
{%- set maximo = qualidade_valor(maximo) %}
with por_grupo as (
    select {{ grupo }} as grupo, sum({{ medida }}) as total_grupo
    from {{ model }}
    group by {{ grupo }}
), total as (
    select sum(total_grupo) as total_geral from por_grupo
)
select p.grupo, p.total_grupo, t.total_geral,
       p.total_grupo / t.total_geral as participacao, {{ maximo }} as maximo
from por_grupo p cross join total t
where t.total_geral > 0
  and p.total_grupo / t.total_geral > {{ maximo }}
{% endtest %}
