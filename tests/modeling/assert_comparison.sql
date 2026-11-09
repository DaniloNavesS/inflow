DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_comparacao_despesas_mensais
                 WHERE senador_id=1 AND mes=1 AND partido_competencia='A'
                   AND quantidade_pares_partido=1 AND media_pares_partido=0
                   AND diferenca_media_partido=100.10 AND desvio_percentual_partido IS NULL
                   AND quantidade_pares_uf=1 AND media_pares_uf=0 AND acima_media_partido) THEN
    RAISE EXCEPTION 'Grupo histórico, exclusão do próprio ou média zero incorretos'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_comparacao_despesas_mensais
                 WHERE senador_id=2 AND media_pares_partido=100.10
                   AND diferenca_media_partido=-100.10 AND desvio_percentual_partido=-100) THEN
    RAISE EXCEPTION 'Média dos pares ou desvio percentual incorreto'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_comparacao_despesas_mensais
                 WHERE senador_id=1 AND mes=2 AND status_comparacao_partido='MULTIPLOS'
                   AND media_pares_partido IS NULL AND status_comparacao_uf='SEM_PARES'
                   AND quantidade_pares_uf=0 AND media_pares_uf IS NULL) THEN
    RAISE EXCEPTION 'Mudança de partido ou grupo unitário tratado como comparação válida'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_comparacao_despesas_mensais
                 WHERE senador_id=3 AND status_comparacao_partido='NAO_COLETADO'
                   AND valor_total=900 AND media_pares_partido IS NULL AND media_pares_uf IS NULL) THEN
    RAISE EXCEPTION 'Contexto ausente inferido do cadastro atual ou despesa perdida'; END IF;
  IF (SELECT count(*) FROM analytics_marts.gestao_comparacao_despesas_mensais) <> 4 THEN
    RAISE EXCEPTION 'Meses sem lançamento foram inventados ou competências duplicadas'; END IF;
END $$;
