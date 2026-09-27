import logging

import psycopg2

logger = logging.getLogger("inflow_ingestion")

def log_database_summary(conn: psycopg2.extensions.connection):
    tabelas = [
        "senadores",
        "mandatos",
        "exercicios_mandato",
        "filiacoes_partidarias",
        "comissoes",
        "participacoes_comissao",
        "sessao_plenaria",
        "documento_dsf",
        "registro_presenca",
        "licenca_justificativa",
        "fornecedores",
        "despesas",
        "estrutura_gabinete"
    ]
    
    logger.info("==================================================")
    logger.info("       RELATÓRIO DE INGESTÃO E AUDITORIA OLTP     ")
    logger.info("==================================================")
    with conn.cursor() as cur:
        for t in tabelas:
            cur.execute(f"SELECT COUNT(*) FROM {t};")
            count = cur.fetchone()[0]
            logger.info("Tabela '%-25s': %8d registros", t, count)
            
        cur.execute("SELECT COALESCE(SUM(valor), 0.0) FROM despesas;")
        total_despesas = cur.fetchone()[0]
        logger.info("Total Financeiro Reembolsado (CEAPS): R$ %14.2f", total_despesas)
    logger.info("==================================================")

