-- Inclui documentos parciais e falhos, mesmo quando não há registros extraídos.
select * from {{ ref('stg_documentos_dsf') }}
