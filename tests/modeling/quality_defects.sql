-- Defeitos injetados diretamente nos marts para provar que cada teste de qualidade
-- detecta o problema que promete detectar. Cada defeito atinge um par (modelo, teste)
-- distinto, então podem ser aplicados juntos; run.sh exige falha de cada seletor e
-- depois reconstrói os marts com `dbt build`.

-- distribuição: buraco em fevereiro entre janeiro e março
INSERT INTO analytics_marts.fct_despesas (despesa_id, senador_id, fornecedor_id, data_despesa, ano, mes,
    tipo_despesa, valor, atualizado_em, competencia, data_documento_valida, categoria_id,
    data_calendario, materializado_em)
SELECT despesa_id + 100, senador_id, fornecedor_id, data_despesa, ano, 3, tipo_despesa, valor,
       atualizado_em, make_date(ano, 3, 1), data_documento_valida, categoria_id, data_calendario,
       materializado_em
FROM analytics_marts.fct_despesas WHERE despesa_id = 1;
DELETE FROM analytics_marts.fct_despesas WHERE mes = 2;

-- esquema: valor monetário vira ponto flutuante; coluna consumida pelo painel some
ALTER TABLE analytics_marts.fct_despesas ALTER COLUMN valor TYPE double precision;
ALTER TABLE analytics_marts.dim_senador DROP COLUMN uf_atual;

-- distribuição: lançamento fora da faixa plausível; datas inválidas acima do limite
UPDATE analytics_marts.fct_despesas SET valor = 5000000 WHERE despesa_id = 1;
UPDATE analytics_marts.fct_despesas SET data_documento_valida = false, data_calendario = NULL;

-- integridade: fato órfão; presença contada sem identidade exata
UPDATE analytics_marts.fct_despesas SET senador_id = 999 WHERE despesa_id = 1;
UPDATE analytics_marts.fct_registros_presenca SET apto_contagem = true WHERE resolucao <> 'EXATA';

-- volume: camada de gestão perde um senador
DELETE FROM analytics_marts.gestao_comissoes_senador WHERE senador_id = 1;

-- unicidade: grão senador x competência duplicado
INSERT INTO analytics_marts.fct_despesas_mensais
SELECT * FROM analytics_marts.fct_despesas_mensais WHERE senador_id = 1 AND mes = 1;

-- histórico: versão redundante (sem mudança real) e duas versões abertas
UPDATE analytics_marts.dim_fornecedor_historico SET razao_social = 'Nome corrigido' WHERE NOT versao_atual;
INSERT INTO analytics_marts.dim_fornecedor_historico (fornecedor_versao_id, fornecedor_id, documento,
    razao_social, observado_desde, observado_ate, versao_atual)
SELECT fornecedor_versao_id || '-dup', fornecedor_id, documento, razao_social,
       observado_desde - interval '1 day', NULL, true
FROM analytics_marts.dim_fornecedor_historico WHERE versao_atual;
UPDATE analytics_marts.dim_contexto_parlamentar_mensal SET dias_exercicio = 0 WHERE status_partido = 'UNICO';
