DO $$ BEGIN
  IF (SELECT count(*) FROM analytics_marts.fct_despesas) <> 5 THEN
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
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_comissoes_senador WHERE senador_id=1 AND data_referencia='2024-12-31' AND comissoes_com_vigencia_confirmada=1 AND vinculos_sem_inicio_conhecido=1) THEN
    RAISE EXCEPTION 'Cargos duplicaram comissão, limite final excluído ou vigência desconhecida inferida'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.gestao_comissoes_senador WHERE senador_id=2 AND comissoes_com_vigencia_confirmada=0) THEN
    RAISE EXCEPTION 'Senador sem participação desapareceu'; END IF;
  IF NOT EXISTS (SELECT 1 FROM analytics_marts.fct_estrutura_gabinete WHERE senador_id=1 AND ano=2024 AND qtd_total_servidores=5)
     OR (SELECT count(*) FROM analytics_marts.fct_estrutura_gabinete WHERE senador_id=1) <> 2 THEN
    RAISE EXCEPTION 'Gabinete perdeu granularidade anual ou quantitativo'; END IF;
END $$;
