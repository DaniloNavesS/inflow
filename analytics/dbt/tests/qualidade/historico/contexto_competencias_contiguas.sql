-- Histórico mensal de partido/UF: dentro de um ano, as competências de cada senador
-- formam uma sequência sem buracos. Um mês faltando no meio vira NAO_COLETADO na
-- comparação e some silenciosamente da média dos pares.
select senador_id, ano, min(mes) as primeiro_mes, max(mes) as ultimo_mes,
       count(*) as meses_presentes
from {{ ref('dim_contexto_parlamentar_mensal') }}
group by senador_id, ano
having count(*) <> max(mes) - min(mes) + 1
