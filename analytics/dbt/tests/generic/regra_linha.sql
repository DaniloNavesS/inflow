{#
  Integridade de regra de negócio por linha: retorna as linhas em que `expressao` não é
  verdadeira. Nulo conta como violação; quem aceita nulo deve dizer isso na expressão.
#}
{% test regra_linha(model, expressao) %}
select *
from {{ model }}
where not coalesce(({{ expressao }}), false)
{% endtest %}
