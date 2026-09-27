EXPECTED_TABLES = {
    "senadores", "mandatos", "exercicios_mandato", "filiacoes_partidarias",
    "comissoes", "participacoes_comissao", "sessao_plenaria", "documento_dsf",
    "registro_presenca", "licenca_justificativa", "fornecedores", "despesas",
    "estrutura_gabinete",
}


def scalar(db, sql):
    with db.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0]


def test_schema(db):
    with db.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        actual = {row[0] for row in cursor.fetchall()}
    assert EXPECTED_TABLES <= actual
    assert "sessoes_presenca" not in actual


def test_minimum_volume(db):
    assert scalar(db, "SELECT count(*) FROM senadores") >= 81
    assert scalar(db, "SELECT count(*) FROM despesas") >= 1000
    assert scalar(db, "SELECT count(*) FROM sessao_plenaria") >= 3
    assert scalar(db, "SELECT count(*) FROM registro_presenca") >= 200


def test_attendance_distribution_and_quality(db):
    with db.cursor() as cursor:
        cursor.execute("""
            SELECT s.data_sessao, count(r.id), d.status_parser
            FROM sessao_plenaria s
            JOIN documento_dsf d ON d.sessao_id = s.id
            LEFT JOIN registro_presenca r ON r.documento_dsf_id = d.id
            GROUP BY s.data_sessao, d.status_parser
            ORDER BY s.data_sessao
        """)
        rows = cursor.fetchall()
    assert [row[1] for row in rows] == [75, 70, 75]
    assert all(row[2] == "SUCESSO" for row in rows)
    assert scalar(db, "SELECT count(*) FROM registro_presenca WHERE situacao <> 'PRESENTE'") == 0


def test_supplier_quality(db):
    assert scalar(db, "SELECT count(*) FROM fornecedores WHERE chave_deduplicacao = 'SEM_DOCUMENTO'") == 0
    assert scalar(db, "SELECT count(*) FROM fornecedores WHERE chave_deduplicacao IS NULL") == 0
    assert scalar(db, "SELECT count(DISTINCT fornecedor_id) FROM despesas") > 100


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
        SELECT count(*) FROM exercicios_mandato e
        LEFT JOIN mandatos m
          ON m.codigo_mandato = e.codigo_mandato AND m.senador_id = e.senador_id
        WHERE m.id IS NULL
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
            SELECT chave_deduplicacao FROM fornecedores GROUP BY 1 HAVING count(*) > 1
        ) duplicates
    """) == 0
    assert scalar(db, """
        SELECT count(*) FROM (
            SELECT codigo_mandato, senador_id
            FROM mandatos GROUP BY 1,2 HAVING count(*) > 1
        ) duplicates
    """) == 0


def test_pipeline_monitoring(db):
    assert scalar(db, "SELECT to_regclass('monitoring.pipeline_runs') IS NOT NULL")
    assert scalar(db, "SELECT to_regclass('monitoring.job_runs') IS NOT NULL")
    assert scalar(db, """
        SELECT count(*)
        FROM monitoring.pipeline_runs
        WHERE status = 'success' AND finished_at IS NOT NULL
    """) >= 1
    assert scalar(db, """
        SELECT count(*)
        FROM monitoring.job_runs
        WHERE status = 'success'
          AND finished_at IS NOT NULL
          AND records_after >= records_before
    """) >= 6


def test_bronze_preserves_json_and_pdf_without_duplicates(db):
    assert scalar(db, "SELECT to_regclass('bronze.payloads_brutos') IS NOT NULL")
    assert scalar(db, "SELECT count(*) FROM bronze.payloads_brutos WHERE payload_json IS NOT NULL") > 0
    assert scalar(db, "SELECT count(*) FROM bronze.payloads_brutos WHERE payload_binario IS NOT NULL") >= 3
    assert scalar(db, """
        SELECT count(*) FROM (
            SELECT url_fonte, sha256
            FROM bronze.payloads_brutos
            GROUP BY 1, 2 HAVING count(*) > 1
        ) duplicados
    """) == 0
