import csv
import datetime
import io
import os
import zipfile
from decimal import Decimal
from pathlib import Path

import psycopg2
import pytest

from main import execute_monitored_job
from monitoring.metrics import start_pipeline
from jobs import cnpj_owners
from bronze.raw import save_raw_payload

COMPANY_A = "90000001"
COMPANY_B = "90000002"
COMPANY_OUTSIDE = "90000003"
CNPJ_A = f"{COMPANY_A}000100"
CNPJ_A_BRANCH = f"{COMPANY_A}000200"
CNPJ_B = f"{COMPANY_B}000100"
CNPJ_SHORT = f"{COMPANY_A}00010"


def connect_test_db():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "postgres"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "inflow_cnpj_test"),
        user=os.environ.get("DB_USER", "inflow_test"),
        password=os.environ.get("DB_PASSWORD", "inflow_test"),
        connect_timeout=3,
    )


def reset_test_data(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER IF EXISTS trg_test_fail_cnpj_socio ON oltp.socios")
        cur.execute("DROP FUNCTION IF EXISTS oltp.test_fail_cnpj_socio()")
        cur.execute("""
            TRUNCATE TABLE
                bronze.raw_payloads,
                oltp.socios,
                oltp.empresas,
                oltp.qualificacoes_socio,
                oltp.naturezas_juridicas,
                oltp.fornecedores,
                monitoring.job_runs,
                monitoring.pipeline_runs
            RESTART IDENTITY CASCADE
        """)
    conn.commit()


@pytest.fixture
def cnpj_db():
    if os.environ.get("CNPJ_TEST_DATABASE") != "1" or os.environ.get("DB_NAME") != "inflow_cnpj_test":
        pytest.fail("CNPJ integration tests require tests/docker-compose.cnpj.yml and its disposable database.")
    try:
        conn = connect_test_db()
    except psycopg2.OperationalError as exc:
        pytest.fail(f"Dedicated PostgreSQL integration database is unavailable: {exc}")
    with conn.cursor() as cur:
        cur.execute("SHOW server_version_num")
        version = int(cur.fetchone()[0])
    if not 150000 <= version < 160000:
        conn.close()
        pytest.fail(f"CNPJ integration tests require PostgreSQL 15; connected to {version}.")
    conn.commit()
    reset_test_data(conn)
    try:
        yield conn
    finally:
        conn.rollback()
        reset_test_data(conn)
        conn.close()


def company_row(basic, name="EMPRESA TESTE", capital="1500,50"):
    return [basic, name, "2062", "49", capital, "01", ""]


def partner_row(basic, name="JOÃO EXEMPLO", document="***123456**", joined="20190102"):
    return [basic, "2", name, document, "49", joined, "", "***000000**", "", "00", "5"]


def files_for(companies, partners):
    files = {name: [] for name in cnpj_owners.required_files()}
    files["Qualificacoes.zip"] = [["49", "Sócio-Administrador"]]
    files["Naturezas.zip"] = [["2062", "Sociedade Empresária Limitada"]]
    files["Empresas0.zip"] = companies
    files["Socios0.zip"] = partners
    return files


def install_source(monkeypatch, tmp_path, name, month, company_rows, partner_rows, missing_file=None):
    base_url = f"https://rfb.test/{name}"
    source_files = files_for(company_rows, partner_rows)
    monkeypatch.setattr(cnpj_owners, "RFB_CNPJ_BASE_URL", base_url)
    monkeypatch.setattr(cnpj_owners, "RFB_CNPJ_MONTH", month)
    monkeypatch.setattr(cnpj_owners, "CNPJ_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(cnpj_owners, "get_rfb_session", lambda _token: object())
    monkeypatch.setattr(cnpj_owners, "list_months", lambda _session, _url: [month])
    monkeypatch.setattr(
        cnpj_owners,
        "list_folder",
        lambda _session, _url: {
            filename: 1 for filename in cnpj_owners.required_files() if filename != missing_file
        },
    )

    def download(_session, url, destination, _expected_size=None):
        filename = url.rsplit("/", 1)[-1]
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        text = io.StringIO(newline="")
        writer = csv.writer(text, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerows(source_files[filename])
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("synthetic.csv", text.getvalue().encode("latin-1"))
        return output

    monkeypatch.setattr(cnpj_owners, "download_file", download)


def add_suppliers(conn, documents):
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO oltp.fornecedores (cnpj_cpf, razao_social) VALUES (%s, %s)",
            [(document, f"Fornecedor {index}") for index, document in enumerate(documents)],
        )
    conn.commit()


def run_job(conn, name):
    run_id = start_pipeline(conn, f"cnpj_test_{name}")
    return cnpj_owners.ingest_cnpj_owners(conn, run_id), run_id


def snapshot(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT cnpj_basico, data_referencia, razao_social, natureza_juridica,
                   qualificacao_responsavel, capital_social, porte, ente_federativo,
                   timestamp_ingestao, atualizado_em
            FROM oltp.empresas
            ORDER BY cnpj_basico, data_referencia
        """)
        companies = cur.fetchall()
        cur.execute("""
            SELECT id, cnpj_basico, data_referencia, tipo_socio, nome_socio,
                   documento_socio, qualificacao, data_entrada, pais,
                   documento_representante, nome_representante,
                   qualificacao_representante, faixa_etaria, timestamp_ingestao
            FROM oltp.socios
            ORDER BY cnpj_basico, data_referencia, nome_socio
        """)
        partners = cur.fetchall()
        cur.execute("""
            SELECT entity_type, source_url, media_type, payload::text, content_sha256
            FROM bronze.raw_payloads
            ORDER BY entity_type, source_url, content_sha256
        """)
        evidence = cur.fetchall()
    return companies, partners, evidence


def test_first_load_links_only_complete_supplier_cnpjs_and_preserves_rfb_fields(cnpj_db, monkeypatch, tmp_path):
    add_suppliers(cnpj_db, [
        CNPJ_A,
        CNPJ_A_BRANCH,
        CNPJ_B,
        "12345678901",
        CNPJ_SHORT,
        "***123456**",
    ])
    install_source(
        monkeypatch,
        tmp_path,
        "first_load",
        "2026-09",
        [company_row(COMPANY_A, "EMPRESA ÁRVORE"), company_row(COMPANY_OUTSIDE, "FORA DO ALVO")],
        [partner_row(COMPANY_A)],
    )

    result, _run_id = run_job(cnpj_db, "first_load")

    assert result["records_written"] == 2
    with cnpj_db.cursor() as cur:
        cur.execute("""
            SELECT e.razao_social, e.data_referencia, e.capital_social,
                   e.natureza_juridica, n.descricao,
                   e.qualificacao_responsavel, q.descricao
            FROM oltp.empresas e
            JOIN oltp.naturezas_juridicas n ON n.codigo = e.natureza_juridica
            JOIN oltp.qualificacoes_socio q ON q.codigo = e.qualificacao_responsavel
        """)
        assert cur.fetchone() == (
            "EMPRESA ÁRVORE",
            datetime.date(2026, 9, 1),
            Decimal("1500.50"),
            2062,
            "Sociedade Empresária Limitada",
            49,
            "Sócio-Administrador",
        )
        cur.execute("""
            SELECT tipo_socio, nome_socio, documento_socio, data_entrada
            FROM oltp.socios
        """)
        assert cur.fetchone() == (2, "JOÃO EXEMPLO", "***123456**", datetime.date(2019, 1, 2))
        cur.execute("SELECT count(*) FROM oltp.empresas")
        assert cur.fetchone()[0] == 1
        cur.execute("""
            SELECT cnpj_cpf, razao_social_rfb, data_referencia
            FROM oltp.vw_socios_fornecedores ORDER BY cnpj_cpf
        """)
        assert cur.fetchall() == [
            (CNPJ_A, "EMPRESA ÁRVORE", datetime.date(2026, 9, 1)),
            (CNPJ_A_BRANCH, "EMPRESA ÁRVORE", datetime.date(2026, 9, 1)),
        ]
        cur.execute("SELECT count(*) FROM bronze.raw_payloads")
        assert cur.fetchone()[0] == 2


def test_same_input_twice_preserves_business_and_evidence_content(cnpj_db, monkeypatch, tmp_path):
    add_suppliers(cnpj_db, [CNPJ_A])
    install_source(
        monkeypatch,
        tmp_path,
        "repeat",
        "2026-09",
        [company_row(COMPANY_A)],
        [partner_row(COMPANY_A)],
    )

    _first, run_id = run_job(cnpj_db, "repeat")
    before = snapshot(cnpj_db)
    cnpj_owners.ingest_cnpj_owners(cnpj_db, run_id)

    assert snapshot(cnpj_db) == before
    assert len(before[0]) == 1
    assert len(before[1]) == 1
    assert len(before[2]) == 2


def test_newest_month_remains_current_when_older_month_is_loaded_later(cnpj_db, monkeypatch, tmp_path):
    add_suppliers(cnpj_db, [CNPJ_A, CNPJ_A_BRANCH])
    install_source(
        monkeypatch,
        tmp_path,
        "months",
        "2026-09",
        [company_row(COMPANY_A, "EMPRESA SETEMBRO")],
        [partner_row(COMPANY_A, "SÓCIO SETEMBRO")],
    )
    _new_result, new_run = run_job(cnpj_db, "months")
    install_source(
        monkeypatch,
        tmp_path,
        "months",
        "2026-08",
        [company_row(COMPANY_A, "EMPRESA AGOSTO")],
        [partner_row(COMPANY_A, "SÓCIO AGOSTO")],
    )
    cnpj_owners.ingest_cnpj_owners(cnpj_db, new_run)

    with cnpj_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM oltp.empresas WHERE cnpj_basico = %s", (COMPANY_A,))
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT DISTINCT data_referencia FROM oltp.vw_socios_fornecedores")
        assert cur.fetchall() == [(datetime.date(2026, 9, 1),)]
        cur.execute("SELECT count(*) FROM oltp.socios")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM bronze.raw_payloads")
        assert cur.fetchone()[0] == 4


def test_save_raw_payload_keeps_default_commit_and_allows_caller_transaction(cnpj_db):
    run_id = start_pipeline(cnpj_db, "raw_commit_compatibility")
    observer = connect_test_db()
    try:
        save_raw_payload(
            cnpj_db,
            entity_type="compatibility_test",
            source_name="test",
            source_url=f"https://rfb.test/commit/{run_id}",
            payload_json={"value": 1},
            media_type="application/json",
            run_id=run_id,
        )
        with observer.cursor() as cur:
            cur.execute("SELECT count(*) FROM bronze.raw_payloads WHERE entity_type='compatibility_test'")
            assert cur.fetchone()[0] == 1

        save_raw_payload(
            cnpj_db,
            entity_type="transaction_test",
            source_name="test",
            source_url=f"https://rfb.test/uncommitted/{run_id}",
            payload_json={"value": 2},
            media_type="application/json",
            run_id=run_id,
            commit=False,
        )
        with observer.cursor() as cur:
            cur.execute("SELECT count(*) FROM bronze.raw_payloads WHERE entity_type='transaction_test'")
            assert cur.fetchone()[0] == 0
        cnpj_db.commit()
        with observer.cursor() as cur:
            cur.execute("SELECT count(*) FROM bronze.raw_payloads WHERE entity_type='transaction_test'")
            assert cur.fetchone()[0] == 1
    finally:
        observer.close()


def test_failed_monitored_persistence_rolls_back_bronze_and_business_then_can_retry(
    cnpj_db, monkeypatch, tmp_path
):
    add_suppliers(cnpj_db, [CNPJ_A])
    install_source(
        monkeypatch,
        tmp_path,
        "atomicity",
        "2026-09",
        [company_row(COMPANY_A)],
        [partner_row(COMPANY_A)],
    )
    with cnpj_db.cursor() as cur:
        cur.execute("""
            CREATE FUNCTION oltp.test_fail_cnpj_socio() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'synthetic persistence failure';
            END;
            $$ LANGUAGE plpgsql
        """)
        cur.execute("""
            CREATE TRIGGER trg_test_fail_cnpj_socio
            BEFORE INSERT ON oltp.socios
            FOR EACH ROW EXECUTE FUNCTION oltp.test_fail_cnpj_socio()
        """)
    cnpj_db.commit()

    failed_run = start_pipeline(cnpj_db, "cnpj_atomicity_failure")
    with pytest.raises(psycopg2.Error, match="synthetic persistence failure"):
        execute_monitored_job(
            cnpj_db, failed_run, "cnpj_owners",
            cnpj_owners.ingest_cnpj_owners, cnpj_db, failed_run,
        )

    with cnpj_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM oltp.empresas")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM oltp.socios")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM oltp.qualificacoes_socio")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM oltp.naturezas_juridicas")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM bronze.raw_payloads")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT status FROM monitoring.job_runs WHERE run_id=%s", (str(failed_run),))
        assert cur.fetchone()[0] == "failed"

    with cnpj_db.cursor() as cur:
        cur.execute("DROP TRIGGER trg_test_fail_cnpj_socio ON oltp.socios")
        cur.execute("DROP FUNCTION oltp.test_fail_cnpj_socio()")
    cnpj_db.commit()

    successful_run = start_pipeline(cnpj_db, "cnpj_atomicity_retry")
    result = execute_monitored_job(
        cnpj_db, successful_run, "cnpj_owners",
        cnpj_owners.ingest_cnpj_owners, cnpj_db, successful_run,
    )
    assert result["records_written"] == 2
    with cnpj_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM oltp.empresas")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM oltp.socios")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM bronze.raw_payloads")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT status FROM monitoring.job_runs WHERE run_id=%s", (str(successful_run),))
        assert cur.fetchone()[0] == "success"
