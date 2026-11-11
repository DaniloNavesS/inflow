-- Pergunta central, recorte 2024. Uma linha por senador e competência.
SELECT s.nome AS senador, c.ano, c.mes, c.valor_total,
       c.partido_competencia, c.uf_competencia, c.dias_exercicio,
       c.status_comparacao_partido, c.quantidade_pares_partido,
       c.media_pares_partido, c.diferenca_media_partido, c.desvio_percentual_partido,
       c.status_comparacao_uf, c.quantidade_pares_uf,
       c.media_pares_uf, c.diferenca_media_uf, c.desvio_percentual_uf
FROM analytics_marts.gestao_comparacao_despesas_mensais c
JOIN analytics_marts.dim_senador s USING (senador_id)
WHERE c.ano=2024 AND c.em_exercicio_no_mes
ORDER BY c.mes, c.valor_total DESC, c.senador_id;

-- Detalhamento independente. Não somar novamente os totais mensais da consulta anterior.
SELECT s.nome AS senador, d.ano, d.mes, t.tipo_despesa,
       f.fornecedor_id, f.razao_social AS fornecedor, d.valor_total, d.quantidade_despesas
FROM analytics_marts.agg_despesas_mensais_fornecedor_categoria d
JOIN analytics_marts.dim_senador s USING (senador_id)
JOIN analytics_marts.dim_fornecedor f USING (fornecedor_id)
JOIN analytics_marts.dim_categoria_despesa t USING (categoria_id)
JOIN analytics_marts.fct_despesas_mensais m
  ON m.senador_id=d.senador_id AND m.ano=d.ano AND m.mes=d.mes
WHERE d.ano=2024 AND m.em_exercicio_no_mes
ORDER BY d.mes, s.nome, t.tipo_despesa, d.valor_total DESC, d.fornecedor_id;

-- Auditoria das competências que a comparação não resolve, sem descartar seus valores.
SELECT status_contexto_partido, status_contexto_uf, count(*) AS competencias,
       sum(valor_total) AS valor_total
FROM analytics_marts.gestao_comparacao_despesas_mensais
WHERE ano=2024
GROUP BY status_contexto_partido, status_contexto_uf
ORDER BY status_contexto_partido, status_contexto_uf;
