DO $$ BEGIN
  IF (SELECT count(*) FROM analytics_marts.fct_despesas) <> 4 THEN
    RAISE EXCEPTION 'Granularidade alterada'; END IF;
  IF (SELECT count(*) FROM analytics_marts.dim_fornecedor_historico) <> 1 THEN
    RAISE EXCEPTION 'Reexecução criou versão sem mudança'; END IF;
  IF (SELECT media_mensal FROM analytics_marts.gestao_media_mensal WHERE senador_id=1) <> 100.10 THEN
    RAISE EXCEPTION 'Média deve considerar somente meses com despesas'; END IF;
  IF (SELECT count(*) FROM analytics_marts.gestao_maior_categoria WHERE senador_id=1) <> 2 THEN
    RAISE EXCEPTION 'Empates foram perdidos'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.fct_despesas WHERE despesa_id=3 AND data_calendario IS NULL AND NOT data_documento_valida) THEN
    RAISE EXCEPTION 'Data inválida não foi sinalizada'; END IF;
  IF EXISTS (SELECT 1 FROM analytics_marts.gestao_maior_categoria WHERE senador_id=1 AND percentual_total_ano <> 50) THEN
    RAISE EXCEPTION 'Participação percentual incorreta'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_maior_categoria WHERE senador_id=2 AND percentual_total_ano IS NULL AND valor_total_ano=0) THEN
    RAISE EXCEPTION 'Total anual zero deve produzir percentual nulo'; END IF;
END $$;
