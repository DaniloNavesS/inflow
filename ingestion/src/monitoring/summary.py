import logging

import psycopg2

logger = logging.getLogger("inflow_ingestor")


def log_database_summary(conn: psycopg2.extensions.connection):

    tabelas = [
        "oltp.senadores",
        "oltp.comissoes",
        "oltp.participacoes_comissao",
        "oltp.sessoes_presenca",
        "oltp.sessao_plenaria",
        "oltp.documento_dsf",
        "oltp.registro_presenca",
        "oltp.fornecedores",
        "oltp.despesas",
        "oltp.estrutura_gabinete",
        "oltp.empresas",
        "oltp.socios",
    ]

    logger.info("==================================================")

    logger.info("       RELATÓRIO DE INGESTÃO E AUDITORIA OLTP     ")

    logger.info("==================================================")

    with conn.cursor() as cur:

        for t in tabelas:

            cur.execute(f"SELECT COUNT(*) FROM {t};")
            count = cur.fetchone()[0]
            logger.info("Tabela '%-25s': %8d registros", t, count)
        cur.execute("SELECT COALESCE(SUM(valor), 0.0) FROM oltp.despesas;")

        total_despesas = cur.fetchone()[0]

        logger.info("Total Financeiro Reembolsado (CEAPS): R$ %14.2f", total_despesas)

    logger.info("==================================================")
