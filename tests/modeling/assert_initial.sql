DO $$ BEGIN
  IF (SELECT count(*) FROM analytics_marts.fct_despesas) <> 3 THEN
    RAISE EXCEPTION 'Granularidade alterada'; END IF;
  IF (SELECT count(*) FROM analytics_marts.dim_fornecedor_historico) <> 1 THEN
    RAISE EXCEPTION 'Reexecução criou versão sem mudança'; END IF;
  IF (SELECT media_mensal FROM analytics_marts.gestao_media_mensal) <> 100.10 THEN
    RAISE EXCEPTION 'Média deve considerar somente meses com despesas'; END IF;
  IF (SELECT count(*) FROM analytics_marts.gestao_maior_categoria) <> 2 THEN
    RAISE EXCEPTION 'Empates foram perdidos'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.fct_despesas WHERE despesa_id=3 AND data_calendario IS NULL AND NOT data_documento_valida) THEN
    RAISE EXCEPTION 'Data inválida não foi sinalizada'; END IF;
END $$;
