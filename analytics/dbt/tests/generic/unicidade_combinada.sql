{#
  Unicidade da chave natural composta (grão do modelo). Nulos contam como valor:
  duas linhas (1, NULL) e (1, NULL) são duplicata do mesmo grão.
#}
{% test unicidade_combinada(model, colunas) %}
select {{ colunas | join(', ') }}, count(*) as ocorrencias
from {{ model }}
group by {{ colunas | join(', ') }}
having count(*) > 1
{% endtest %}
