"""Cenário determinístico permitido apenas no banco de teste descartável."""
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def analytics_sample():
    if os.getenv("ANALYTICS_TEST_DATABASE") != "1":
        return
    import psycopg2
    from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    from contextlib import closing
    with closing(psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                                user=DB_USER, password=DB_PASSWORD)) as db:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO oltp.senadores (id, nome, partido, uf)
                VALUES (99001, 'Cenário de teste A', 'TESTE', 'DF'),
                       (99002, 'Cenário de teste B', 'TESTE', 'SP') ON CONFLICT DO NOTHING;
                INSERT INTO oltp.fornecedores (id, cnpj_cpf, razao_social)
                VALUES (99001, '12345678000100', 'Fornecedor de teste') ON CONFLICT DO NOTHING;
                INSERT INTO oltp.empresas (cnpj_basico, data_referencia, razao_social)
                VALUES ('12345678', '2024-01-01', 'Empresa antiga'),
                       ('12345678', '2024-02-01', 'Empresa recente') ON CONFLICT DO NOTHING;
                INSERT INTO oltp.despesas
                    (id, senador_id, fornecedor_id, ano, mes, data_despesa, tipo_despesa, valor)
                VALUES (99001, 99001, 99001, 2024, 1, '2024-01-10', 'Passagens', 100.00),
                       (99002, 99001, 99001, 2024, 2, '2024-02-10', 'Passagens', 101.23),
                       (99003, 99001, 99001, 2024, 2, '2024-02-10', 'Escritório', 50.00),
                       (99004, 99002, 99001, 2024, 1, '2024-01-11', 'Escritório', 80.00)
                ON CONFLICT DO NOTHING;
            """)
        db.commit()
