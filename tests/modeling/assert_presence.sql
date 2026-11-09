DO $$ BEGIN
  IF (SELECT count(*) FROM analytics_marts.fct_registros_presenca) <> 8 THEN
    RAISE EXCEPTION 'Modelagem perdeu ou duplicou linhas documentais'; END IF;
  IF (SELECT count(*) FROM analytics_marts.fct_registros_presenca WHERE senador_id IS NULL) <> 2 THEN
    RAISE EXCEPTION 'Identidades não resolvidas devem permanecer nulas'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.fct_registros_presenca WHERE registro_presenca_id=1 AND apto_contagem AND NOT voto_registrado AND partido_documento='ANTIGO') THEN
    RAISE EXCEPTION 'Presença sem voto ou partido documental não foi preservado'; END IF;
  IF EXISTS (SELECT 1 FROM analytics_marts.fct_registros_presenca WHERE registro_presenca_id IN (3,4,5,6,7,8) AND apto_contagem) THEN
    RAISE EXCEPTION 'Registro parcial, falho, desconhecido, inconsistente ou sem identidade entrou na contagem'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_presencas_documentadas WHERE senador_id=1 AND ano=2023 AND sessoes_com_presenca_documentada=1 AND registros_documentais=4 AND registros_fora_contagem=2) THEN
    RAISE EXCEPTION 'Sessão duplicada ou registros excluídos da contagem foram calculados incorretamente'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_presencas_documentadas WHERE senador_id=2 AND sessoes_com_presenca_documentada=0 AND registros_fora_contagem=2) THEN
    RAISE EXCEPTION 'Zero presenças confirmadas não pode virar ausência inferida'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.dim_documento_dsf WHERE documento_dsf_id=5 AND status_parser='FALHA') THEN
    RAISE EXCEPTION 'Documento sem linhas extraídas desapareceu'; END IF;
END $$;
