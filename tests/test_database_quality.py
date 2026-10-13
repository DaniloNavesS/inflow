"""Qualidade do esquema atual e, após a ingestão completa, dos dados carregados."""

EXPECTED_TABLES = {
    "senadores", "comissoes", "participacoes_comissao", "sessoes_presenca",
    "fornecedores", "despesas", "estrutura_gabinete", "sessao_plenaria",
    "documento_dsf", "registro_presenca", "qualificacoes_socio",
    "naturezas_juridicas", "empresas", "socios",
}


def scalar(db, sql):
    with db.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0]


def test_schema(db):
    with db.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'oltp'")
        actual = {row[0] for row in cursor.fetchall()}
    assert EXPECTED_TABLES <= actual
    assert scalar(db, "SELECT to_regclass('oltp.vw_donos_finais') IS NOT NULL")


def test_minimum_volume(populated_db):
    assert scalar(populated_db, "SELECT count(*) FROM senadores") >= 81
    assert scalar(populated_db, "SELECT count(*) FROM despesas") >= 1000
    assert scalar(populated_db, "SELECT count(*) FROM sessao_plenaria") >= 3
    assert scalar(populated_db, "SELECT count(*) FROM registro_presenca") >= 200


def test_attendance_distribution_and_quality(populated_db):
    with populated_db.cursor() as cursor:
        cursor.execute("""
            SELECT s.data_sessao, count(r.id), d.status_parser
            FROM sessao_plenaria s
            JOIN documento_dsf d ON d.sessao_id = s.id
            LEFT JOIN registro_presenca r ON r.documento_dsf_id = d.id
            GROUP BY s.data_sessao, d.status_parser
            ORDER BY s.data_sessao
        """)
        rows = cursor.fetchall()
    successful = [row for row in rows if row[2] == "SUCESSO"]
    assert len({row[0] for row in successful}) >= 3
    assert all(row[1] > 0 for row in successful)


def test_supplier_quality(populated_db):
    assert scalar(populated_db, "SELECT count(*) FROM fornecedores WHERE btrim(cnpj_cpf) = ''") == 0
    assert scalar(populated_db, "SELECT count(DISTINCT fornecedor_id) FROM despesas") > 100


def test_referential_integrity(db):
    assert scalar(db, """
        SELECT count(*) FROM despesas d
        LEFT JOIN fornecedores f ON f.id = d.fornecedor_id
        WHERE f.id IS NULL
    """) == 0
    assert scalar(db, """
        SELECT count(*) FROM registro_presenca r
        LEFT JOIN documento_dsf d ON d.id = r.documento_dsf_id
        WHERE d.id IS NULL
    """) == 0
    assert scalar(db, """
        SELECT count(*) FROM socios s
        LEFT JOIN empresas e
          ON e.cnpj_basico = s.cnpj_basico AND e.data_referencia = s.data_referencia
        WHERE e.cnpj_basico IS NULL
    """) == 0


def test_natural_keys_support_idempotent_reprocessing(db):
    assert scalar(db, """
        SELECT count(*) FROM (
            SELECT codigo_diario, pagina_inicial, pagina_final
            FROM documento_dsf GROUP BY 1,2,3 HAVING count(*) > 1
        ) duplicates
    """) == 0
    assert scalar(db, """
        SELECT count(*) FROM (
            SELECT cnpj_cpf FROM fornecedores GROUP BY 1 HAVING count(*) > 1
        ) duplicates
    """) == 0
    assert scalar(db, """
        SELECT count(*) FROM (
            SELECT cnpj_basico, data_referencia
            FROM empresas GROUP BY 1,2 HAVING count(*) > 1
        ) duplicates
    """) == 0


def test_pipeline_monitoring_schema(db):
    assert scalar(db, "SELECT to_regclass('monitoring.pipeline_runs') IS NOT NULL")
    assert scalar(db, "SELECT to_regclass('monitoring.job_runs') IS NOT NULL")


def test_pipeline_monitoring_data(populated_db):
    assert scalar(populated_db, """
        SELECT count(*) FROM monitoring.pipeline_runs
        WHERE status = 'success' AND finished_at IS NOT NULL
    """) >= 1
    assert scalar(populated_db, """
        SELECT count(*) FROM monitoring.job_runs
        WHERE status = 'success' AND finished_at IS NOT NULL
          AND records_read >= 0 AND records_written >= 0
    """) >= 6


def test_bronze_schema_and_no_duplicates(db):
    assert scalar(db, "SELECT to_regclass('bronze.raw_payloads') IS NOT NULL")
    assert scalar(db, """
        SELECT count(*) FROM (
            SELECT source_url, content_sha256
            FROM bronze.raw_payloads
            WHERE content_sha256 IS NOT NULL
            GROUP BY 1, 2 HAVING count(*) > 1
        ) duplicates
    """) == 0


def test_bronze_payloads_after_ingestion(populated_db):
    assert scalar(populated_db, "SELECT count(*) FROM bronze.raw_payloads WHERE payload IS NOT NULL") > 0
    assert scalar(populated_db, "SELECT count(*) FROM bronze.raw_payloads WHERE payload_binary IS NOT NULL") >= 3
