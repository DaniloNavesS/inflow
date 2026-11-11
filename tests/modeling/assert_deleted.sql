DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM analytics_marts.fct_despesas) OR
     EXISTS (SELECT 1 FROM analytics_marts.agg_despesas_mensais) OR
     EXISTS (SELECT 1 FROM analytics_marts.dim_calendario) THEN
    RAISE EXCEPTION 'Origem vazia deixou dados antigos nos marts'; END IF;
  IF (SELECT count(*) FROM analytics_marts.dim_fornecedor_historico) <> 2 OR
     EXISTS (SELECT 1 FROM analytics_marts.dim_fornecedor_historico WHERE versao_atual) THEN
    RAISE EXCEPTION 'Exclusão deve encerrar a versão atual e preservar o histórico'; END IF;
END $$;
