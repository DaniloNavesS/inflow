{#
  Limites dos testes de qualidade, centralizados em dbt_project.yml (vars.limites_qualidade).
  `qualidade_limite('chave')` devolve o limite do perfil ativo e falha na compilação se a
  chave não existir, para que um erro de digitação nunca vire um teste que sempre passa.
#}
{% macro qualidade_limite(nome) %}
    {%- set perfil = var('perfil_qualidade', 'producao') -%}
    {%- set limites = var('limites_qualidade', {}) -%}
    {%- if perfil not in limites -%}
        {{ exceptions.raise_compiler_error("Perfil de qualidade desconhecido: " ~ perfil) }}
    {%- endif -%}
    {%- if nome not in limites[perfil] -%}
        {{ exceptions.raise_compiler_error("Limite '" ~ nome ~ "' ausente no perfil " ~ perfil) }}
    {%- endif -%}
    {{- return(limites[perfil][nome]) -}}
{% endmacro %}

{#
  Aceita um número literal ou o nome de um limite configurado. Nulo continua nulo
  (limite não aplicado).
#}
{% macro qualidade_valor(valor) %}
    {%- if valor is none -%}
        {{- return(none) -}}
    {%- elif valor is string -%}
        {{- return(qualidade_limite(valor)) -}}
    {%- else -%}
        {{- return(valor) -}}
    {%- endif -%}
{% endmacro %}

{# Família semântica de um tipo do information_schema do PostgreSQL. #}
{% macro qualidade_familia_tipo(coluna) %}
    case
        when {{ coluna }} in ('smallint', 'integer', 'bigint') then 'inteiro'
        when {{ coluna }} = 'numeric' then 'decimal'
        when {{ coluna }} in ('real', 'double precision') then 'flutuante'
        when {{ coluna }} in ('text', 'character varying', 'character') then 'texto'
        when {{ coluna }} = 'date' then 'data'
        when {{ coluna }} like 'timestamp%' then 'instante'
        when {{ coluna }} = 'boolean' then 'booleano'
        else {{ coluna }}
    end
{% endmacro %}
