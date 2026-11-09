{#
  Esquema: compara as colunas publicadas com o contrato declarado no YAML.

  `colunas` mapeia nome -> tipo. O tipo pode ser uma família semântica (inteiro, decimal,
  flutuante, texto, data, instante, booleano) ou o nome exato do information_schema
  (ex.: 'numeric', 'timestamp with time zone'). Família evita falso alarme quando só a
  largura muda (integer -> bigint) e ainda pega o que quebra consumidores: valor monetário
  virando float ou texto, data virando texto, coluna removida ou renomeada.

  Com permitir_extras=false, coluna nova sem atualizar o contrato também falha.
  Uma linha retornada por problema; tabela ausente devolve todas as colunas como ausentes.
#}
{% test esquema_esperado(model, colunas, permitir_extras=false) %}
with esperado as (
    {%- for nome, tipo in colunas.items() %}
    select '{{ nome }}'::text as coluna, '{{ tipo }}'::text as tipo_esperado
    {%- if not loop.last %} union all{% endif %}
    {%- endfor %}
), atual as (
    select column_name::text as coluna, data_type::text as tipo_real,
           {{ qualidade_familia_tipo('data_type') }} as familia
    from information_schema.columns
    where table_schema = '{{ model.schema }}'
      and table_name = '{{ model.identifier }}'
)
select coalesce(e.coluna, a.coluna) as coluna, e.tipo_esperado, a.tipo_real,
       case when a.coluna is null then 'coluna ausente'
            when e.coluna is null then 'coluna fora do contrato'
            else 'tipo divergente' end as problema
from esperado e
full join atual a on a.coluna = e.coluna
where a.coluna is null
   or (e.coluna is null and not {{ 'true' if permitir_extras else 'false' }})
   or (e.coluna is not null and a.coluna is not null
       and e.tipo_esperado not in (a.familia, a.tipo_real))
{% endtest %}
