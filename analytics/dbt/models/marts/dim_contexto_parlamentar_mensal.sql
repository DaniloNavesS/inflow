-- Contexto oficial nos dias de exercício da competência, nunca cadastro atual.
select senador_id::text || ':' || ano::text || ':' || mes::text as contexto_id,
       senador_id, ano, mes, dias_exercicio,
       nullif(trim(partido_competencia), '') as partido_competencia,
       nullif(trim(uf_competencia), '') as uf_competencia,
       status_partido, status_uf, source_url, fonte_sha256, coletado_em
from {{ ref('contexto_parlamentar') }}
