import datetime
import zipfile
from decimal import Decimal

import pytest

from clients.rfb import parse_propfind
from jobs.cnpj_owners import (
    cnpj_basico,
    iter_zip_rows,
    parse_capital,
    parse_date,
    parse_empresa,
    parse_socio,
)

REFERENCE = datetime.date(2026, 9, 1)

# Formato real de Socios*.zip (nome trocado); layout em cnpj-metadados.pdf.
SOCIO_LINE = '"07396865";"2";"FULANO DE TAL";"***240659**";"49";"20050518";"";"***000000**";"";"00";"6"'
EMPRESA_LINE = '"07396865";"EMPRESA EXEMPLO LTDA";"2062";"49";"10000,00";"01";""'


def test_cnpj_basico_only_for_complete_cnpj():
    assert cnpj_basico("12.345.678/0001-90") == "12345678"
    assert cnpj_basico("12345678000190") == "12345678"
    assert cnpj_basico("123.456.789-01") is None
    assert cnpj_basico("***.456.789-**") is None
    assert cnpj_basico("SEM_DOCUMENTO") is None
    assert cnpj_basico(None) is None


def test_dates_and_capital_follow_rfb_layout():
    assert parse_date("20050518") == datetime.date(2005, 5, 18)
    assert parse_date("00000000") is None
    assert parse_date("") is None
    assert parse_date("20051399") is None
    assert parse_capital("10000,00") == Decimal("10000.00")
    assert parse_capital("1.500,50") == Decimal("1500.50")
    assert parse_capital("") is None
    assert parse_capital("-1,00") is None


def test_parse_socio_keeps_masked_cpf_and_drops_empty_representative():
    row = [field.strip('"') for field in SOCIO_LINE.split(";")]
    record = parse_socio(row, REFERENCE)
    assert record == (
        "07396865", REFERENCE, 2, "FULANO DE TAL", "***240659**", 49,
        datetime.date(2005, 5, 18), None, None, None, 0, 6,
    )


def test_parse_empresa():
    row = [field.strip('"') for field in EMPRESA_LINE.split(";")]
    assert parse_empresa(row, REFERENCE) == (
        "07396865", REFERENCE, "EMPRESA EXEMPLO LTDA", 2062, 49, Decimal("10000.00"), "01", None,
    )


def test_rows_outside_layout_are_rejected():
    assert parse_socio(["07396865", "2"], REFERENCE) is None
    assert parse_socio(["0739686X"] + ["x"] * 10, REFERENCE) is None
    assert parse_empresa(["07396865", "SEM COLUNAS"], REFERENCE) is None


def test_zip_is_read_as_latin1_csv(tmp_path):
    path = tmp_path / "Socios0.zip"
    content = (SOCIO_LINE.replace("FULANO DE TAL", "JOÃO DA CONCEIÇÃO") + "\n").encode("latin-1")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("K3241.K03200Y0.D60912.SOCIOCSV", content)
    rows = list(iter_zip_rows(path))
    assert len(rows) == 1
    assert rows[0][2] == "JOÃO DA CONCEIÇÃO"
    assert len(rows[0]) == 11


def test_propfind_lists_months_files_and_sizes():
    xml = """<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:">
      <d:response><d:href>/public.php/webdav/Dados/Cadastros/CNPJ/2026-09/</d:href>
        <d:propstat><d:prop/></d:propstat></d:response>
      <d:response><d:href>/public.php/webdav/Dados/Cadastros/CNPJ/2026-09/Socios0.zip</d:href>
        <d:propstat><d:prop><d:getcontentlength>247683729</d:getcontentlength></d:prop></d:propstat></d:response>
      <d:response><d:href>/public.php/webdav/Dados/Cadastros/CNPJ/2026-09/Qualifica%c3%a7%c3%b5es/</d:href>
        <d:propstat><d:prop/></d:propstat></d:response>
    </d:multistatus>"""
    entries = parse_propfind(xml)
    assert entries["Socios0.zip"] == 247683729
    assert entries["2026-09/"] is None
    assert "Qualificações/" in entries


# ------------------------------------------------------------------------------
# Integração: só roda depois que o job carregou dados
# ------------------------------------------------------------------------------

def scalar(db, sql):
    with db.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0]


@pytest.fixture
def loaded(db):
    if not scalar(db, "SELECT to_regclass('oltp.empresas') IS NOT NULL"):
        pytest.skip("Esquema sem oltp.empresas: recrie o volume (make clean).")
    if not scalar(db, "SELECT count(*) FROM empresas"):
        pytest.skip("Enriquecimento RFB ainda não executado (make cnpj).")
    return db


def test_every_company_is_a_supplier_or_a_partner_in_its_chain(loaded):
    assert scalar(loaded, """
        SELECT count(*) FROM empresas e
        WHERE NOT EXISTS (
            SELECT 1 FROM fornecedores f
            WHERE f.cnpj_cpf NOT LIKE '%*%'
              AND left(regexp_replace(f.cnpj_cpf, '[^0-9]', '', 'g'), 8) = e.cnpj_basico
        )
        AND NOT EXISTS (
            SELECT 1 FROM socios s
            WHERE s.tipo_socio = 1 AND s.documento_socio = e.cnpj_basico
        )
    """) == 0


def test_most_suppliers_with_cnpj_are_found_in_rfb(loaded):
    coverage = scalar(loaded, """
        WITH alvo AS (
            SELECT DISTINCT left(regexp_replace(cnpj_cpf, '[^0-9]', '', 'g'), 8) AS basico
            FROM fornecedores
            WHERE cnpj_cpf NOT LIKE '%*%'
              AND length(regexp_replace(cnpj_cpf, '[^0-9]', '', 'g')) = 14
        )
        SELECT avg((EXISTS (SELECT 1 FROM empresas e WHERE e.cnpj_basico = alvo.basico))::int)
        FROM alvo
    """)
    assert coverage >= 0.95


def test_partner_documents_stay_masked_as_published(loaded):
    assert scalar(loaded, """
        SELECT count(*) FROM socios
        WHERE tipo_socio = 2 AND documento_socio IS NOT NULL AND documento_socio !~ '^\\*\\*\\*[0-9]{6}\\*\\*$'
    """) == 0


def test_supplier_partners_view_resolves(loaded):
    assert scalar(loaded, "SELECT count(*) FROM vw_socios_fornecedores") > 0
