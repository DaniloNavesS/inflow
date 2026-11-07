DO $$ BEGIN
  IF (SELECT count(*) FROM analytics_marts.dim_fornecedor_historico) <> 2 THEN
    RAISE EXCEPTION 'Mudança não preservou as duas versões'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.dim_fornecedor_historico WHERE razao_social='Nome original' AND observado_ate IS NOT NULL AND NOT versao_atual) THEN
    RAISE EXCEPTION 'Versão antiga não foi encerrada'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.dim_fornecedor_historico WHERE razao_social='Nome corrigido' AND versao_atual) THEN
    RAISE EXCEPTION 'Versão atual ausente'; END IF;
END $$;
