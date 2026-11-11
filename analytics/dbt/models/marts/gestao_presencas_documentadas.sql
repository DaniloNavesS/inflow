-- Contagem da amostra documental carregada, sem denominador de assiduidade.
select senador_id, extract(year from data_sessao)::int as ano,
       count(distinct sessao_id) filter (where apto_contagem) as sessoes_com_presenca_documentada,
       count(*) as registros_documentais,
       count(*) filter (where not apto_contagem) as registros_fora_contagem,
       max(materializado_em) as materializado_em
from {{ ref('fct_registros_presenca') }}
where senador_id is not null
group by senador_id, extract(year from data_sessao)::int
