"""Dono final de um fornecedor da CEAPS a partir do QSA da RFB (oltp.vw_donos_finais).

Os testes de banco montam um cenário sintético dentro de uma transação própria e
desfazem tudo no final: não dependem dos dados reais nem os alteram.

Cenário (raízes de CNPJ 9999990x, que não existem na base real):

    despesa ──► fornecedor A ──┬─ Sócio PF "PESSOA DIRETA"             -> dono, nível 1
                               ├─ Administrador PF "SO ADMINISTRA"     -> não é dono
                               └─ Sócio PJ B ──┬─ Sócio PJ X (sem dados) -> cadeia interrompida
                                               └─ Sócio PJ C ──┬─ Sócio PF "DONA FINAL" -> dono, nível 3
                                                               └─ Sócio PJ A      -> ciclo
    fornecedor G: empresário individual, sem QSA
    fornecedor H: S.A. com apenas Diretor no QSA
    fornecedor I: CNPJ que não está na base da RFB
"""
import datetime
import os
import zipfile

import psycopg2
import pytest

from jobs.cnpj_owners import partner_companies, scan_file

REF = datetime.date(2026, 9, 1)
SOCIO = 22
SOCIO_ADMINISTRADOR = 49
ADMINISTRADOR = 5
DIRETOR = 10
EMPRESARIO_INDIVIDUAL = 2135


# ------------------------------------------------------------------------------
# Unidade: expansão da cadeia no job
# ------------------------------------------------------------------------------

def socio(cnpj, tipo, nome, documento, qualificacao):
    return (cnpj, REF, tipo, nome, documento, qualificacao, None, None, None, None, None, None)


def test_partner_companies_returns_only_pj_partner_roots():
    records = [
        socio("11111111", 1, "HOLDING LTDA", "22222222", SOCIO),
        socio("11111111", 2, "PESSOA", "***123456**", SOCIO),
        socio("11111111", 1, "EXTERIOR INC", None, 37),
    ]
    assert partner_companies(records) == {"22222222"}


def test_scan_file_only_parses_lines_of_requested_roots(tmp_path):
    path = tmp_path / "Socios0.zip"
    content = (
        '"11111111";"1";"HOLDING LTDA";"22222222";"22";"20200101";"";"***000000**";"";"00";"0"\n'
        '"33333333";"2";"OUTRA PESSOA";"***654321**";"22";"20200101";"";"***000000**";"";"00";"5"\n'
    ).encode("latin-1")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SOCIOCSV", content)
    rows, lines = scan_file(path, {"11111111"})
    assert lines == 2
    assert [row[0] for row in rows] == ["11111111"]
    assert scan_file(path, set()) == ([], 0)


# ------------------------------------------------------------------------------
# Banco: lógica da view
# ------------------------------------------------------------------------------

@pytest.fixture
def cenario():
    """Conexão própria com o cenário inserido; rollback no final."""
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5433")),
            dbname=os.getenv("DB_NAME", "inflow_db"),
            user=os.getenv("DB_USER", "inflow_user"),
            password=os.getenv("DB_PASSWORD", "inflow_pass"),
            connect_timeout=3,
        )
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL de integração indisponível: {exc}")

    cur = conn.cursor()
    cur.execute("SELECT to_regclass('oltp.vw_donos_finais') IS NOT NULL")
    if not cur.fetchone()[0]:
        conn.close()
        pytest.skip("Esquema sem oltp.vw_donos_finais: aplique scripts/sql/oltp/013_donos_finais.sql.")

    cur.execute("SET search_path TO oltp, public")
    for codigo, descricao in ((SOCIO, "Sócio"), (SOCIO_ADMINISTRADOR, "Sócio-Administrador"),
                              (ADMINISTRADOR, "Administrador"), (DIRETOR, "Diretor")):
        cur.execute(
            "INSERT INTO qualificacoes_socio (codigo, descricao) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (codigo, descricao),
        )
    cur.execute(
        "INSERT INTO naturezas_juridicas (codigo, descricao) VALUES (%s, 'Empresário (Individual)') "
        "ON CONFLICT DO NOTHING",
        (EMPRESARIO_INDIVIDUAL,),
    )

    empresas = [
        ("99999901", "EMPRESA A LTDA", None),
        ("99999902", "HOLDING B LTDA", None),
        ("99999903", "HOLDING C LTDA", None),
        ("99999904", "FULANO EMPRESARIO 12345678901", EMPRESARIO_INDIVIDUAL),
        ("99999905", "COMPANHIA H S.A.", None),
    ]
    for cnpj, nome, natureza in empresas:
        cur.execute(
            "INSERT INTO empresas (cnpj_basico, data_referencia, razao_social, natureza_juridica) "
            "VALUES (%s, %s, %s, %s)",
            (cnpj, REF, nome, natureza),
        )

    socios = [
        ("99999901", 2, "PESSOA DIRETA", "***111111**", SOCIO_ADMINISTRADOR),
        ("99999901", 2, "SO ADMINISTRA", "***222222**", ADMINISTRADOR),
        ("99999901", 1, "HOLDING B LTDA", "99999902", SOCIO),
        ("99999902", 1, "HOLDING C LTDA", "99999903", SOCIO),
        ("99999902", 1, "EMPRESA X SEM DADOS", "99999909", SOCIO),
        ("99999903", 2, "DONA FINAL", "***333333**", SOCIO),
        ("99999903", 1, "EMPRESA A LTDA", "99999901", SOCIO),
        ("99999905", 2, "DIRETOR CONTRATADO", "***444444**", DIRETOR),
    ]
    for cnpj, tipo, nome, documento, qualificacao in socios:
        cur.execute(
            "INSERT INTO socios (cnpj_basico, data_referencia, tipo_socio, nome_socio, "
            "documento_socio, qualificacao) VALUES (%s, %s, %s, %s, %s, %s)",
            (cnpj, REF, tipo, nome, documento, qualificacao),
        )

    # O primeiro vem formatado, como a CEAPS publica parte dos documentos.
    fornecedores = {}
    for raiz, cnpj in (("99999901", "99.999.901/0001-00"), ("99999904", "99999904000100"),
                       ("99999905", "99999905000100"), ("99999906", "99999906000100")):
        cur.execute(
            "INSERT INTO fornecedores (cnpj_cpf, razao_social) VALUES (%s, 'TESTE') RETURNING id",
            (cnpj,),
        )
        fornecedores[raiz] = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO senadores (id, nome, partido, uf) VALUES (999999, 'SENADOR TESTE', 'TESTE', 'DF')"
    )
    cur.execute(
        "INSERT INTO despesas (id, senador_id, fornecedor_id, data_despesa, ano, mes, tipo_despesa, valor) "
        "VALUES (999999999, 999999, %s, %s, 2024, 1, 'TESTE', 100.00)",
        (fornecedores["99999901"], datetime.date(2024, 1, 15)),
    )

    try:
        yield cur, fornecedores
    finally:
        conn.rollback()
        conn.close()


def donos(cur, fornecedor_id):
    cur.execute(
        "SELECT tipo_dono, nome_dono, documento_dono, nivel, cadeia_cnpj, cadeia "
        "FROM vw_donos_finais WHERE fornecedor_id = %s ORDER BY nivel, tipo_dono, nome_dono",
        (fornecedor_id,),
    )
    return cur.fetchall()


def test_chain_reaches_individual_owners_through_holdings(cenario):
    cur, fornecedores = cenario
    rows = donos(cur, fornecedores["99999901"])
    pessoas = {(r[1], r[3]) for r in rows if r[0] == "PESSOA_FISICA"}
    assert pessoas == {("PESSOA DIRETA", 1), ("DONA FINAL", 3)}

    dona = next(r for r in rows if r[1] == "DONA FINAL")
    assert dona[4] == ["99999901", "99999902", "99999903"]
    assert dona[5] == "EMPRESA A LTDA > HOLDING B LTDA > HOLDING C LTDA"


def test_administrator_without_capital_is_not_an_owner(cenario):
    cur, fornecedores = cenario
    nomes = {r[1] for r in donos(cur, fornecedores["99999901"])}
    assert "SO ADMINISTRA" not in nomes


def test_chain_interruptions_are_labelled(cenario):
    cur, fornecedores = cenario
    rows = donos(cur, fornecedores["99999901"])
    tipos = {(r[0], r[2]) for r in rows if r[0] != "PESSOA_FISICA"}
    assert tipos == {("PESSOA_JURIDICA_SEM_DADOS", "99999909"), ("CICLO", "99999901")}


def test_companies_without_partners_with_capital(cenario):
    cur, fornecedores = cenario
    assert [r[:2] for r in donos(cur, fornecedores["99999904"])] == [
        ("EMPRESARIO_INDIVIDUAL", "FULANO EMPRESARIO 12345678901"),
    ]
    assert [r[0] for r in donos(cur, fornecedores["99999905"])] == ["QSA_SEM_SOCIO_COM_CAPITAL"]
    assert [r[:2] for r in donos(cur, fornecedores["99999906"])] == [("EMPRESA_NAO_ENCONTRADA", None)]


def test_owner_from_a_senator_expense(cenario):
    """O caminho pedido: de uma despesa paga pelo senador até o dono final do fornecedor."""
    cur, _ = cenario
    cur.execute("""
        SELECT s.nome, d.valor, v.nome_dono, v.nivel, v.cadeia
        FROM despesas d
        JOIN senadores s ON s.id = d.senador_id
        JOIN vw_donos_finais v ON v.fornecedor_id = d.fornecedor_id
        WHERE d.id = 999999999 AND v.tipo_dono = 'PESSOA_FISICA'
        ORDER BY v.nivel
    """)
    assert [(r[2], r[3]) for r in cur.fetchall()] == [("PESSOA DIRETA", 1), ("DONA FINAL", 3)]


def test_ownership_qualifications(cenario):
    cur, _ = cenario
    cur.execute(
        "SELECT codigo, qualificacao_indica_propriedade(codigo::smallint) "
        "FROM unnest(ARRAY[5, 10, 16, 22, 26, 49, 53, 63, 65]) AS codigo"
    )
    assert dict(cur.fetchall()) == {
        5: False, 10: False, 16: False, 22: True, 26: False, 49: True, 53: False, 63: False, 65: True,
    }
