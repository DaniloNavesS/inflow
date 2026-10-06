"""Sócios e dados cadastrais (RFB) das empresas fornecedoras da CEAPS.

Fonte: dados abertos do CNPJ da Receita Federal, publicados por mês em
{RFB_CNPJ_BASE_URL}/AAAA-MM/. Layout dos campos:
https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf

Os arquivos somam alguns GB; o job baixa uma vez por mês para o cache, lê cada
ZIP em fluxo e mantém só as linhas dos CNPJs que aparecem em oltp.fornecedores.
"""
import csv
import datetime
import io
import logging
import re
import shutil
import time
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from bronze.raw import save_raw_payload
from clients.rfb import download_file, get_rfb_session, list_folder, list_months
from config import (
    CNPJ_CACHE_DIR,
    CNPJ_OWNER_MAX_DEPTH,
    RFB_CNPJ_BASE_URL,
    RFB_CNPJ_MONTH,
    RFB_CNPJ_TOKEN,
)

logger = logging.getLogger("inflow_ingestor")

PARTS = range(10)
GROUPS = ("Empresas", "Socios")
LOOKUPS = ("Qualificacoes.zip", "Naturezas.zip")
EMPRESA_COLUMNS = 7
SOCIO_COLUMNS = 11
NO_REPRESENTATIVE = "***000000**"
UNDOCUMENTED_CODE = "CÓDIGO AUSENTE NA TABELA DE DOMÍNIO DA RFB"


# ------------------------------------------------------------------------------
# Conversões de campo (layout RFB)
# ------------------------------------------------------------------------------

def parse_date(value: str) -> datetime.date | None:
    value = (value or "").strip()
    if not value or set(value) == {"0"}:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def parse_capital(value: str) -> Decimal | None:
    value = (value or "").strip()
    if not value:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        capital = Decimal(value)
    except InvalidOperation:
        return None
    return capital if capital >= 0 else None


def parse_text(value: str, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] or None


def parse_document(value: str) -> str | None:
    value = (value or "").strip()
    return None if not value or value == NO_REPRESENTATIVE else value[:14]


def cnpj_basico(document: str | None) -> str | None:
    """8 primeiros dígitos de um CNPJ completo; CPF, documento mascarado ou ausente não têm QSA."""
    document = (document or "").strip()
    digits = re.sub(r"\D", "", document)
    if "*" in document or len(digits) != 14:
        return None
    return digits[:8]


def parse_empresa(row: list[str], reference: datetime.date) -> tuple | None:
    if len(row) != EMPRESA_COLUMNS or not re.fullmatch(r"\d{8}", row[0]):
        return None
    porte = (row[5] or "").strip() or None
    return (
        row[0],
        reference,
        parse_text(row[1], 255) or "NÃO INFORMADO",
        parse_int(row[2]),
        parse_int(row[3]),
        parse_capital(row[4]),
        porte if porte in {"00", "01", "03", "05"} else None,
        parse_text(row[6], 150),
    )


def parse_socio(row: list[str], reference: datetime.date) -> tuple | None:
    if len(row) != SOCIO_COLUMNS or not re.fullmatch(r"\d{8}", row[0]):
        return None
    tipo = parse_int(row[1])
    qualificacao = parse_int(row[4])
    nome = parse_text(row[2], 255)
    if tipo not in (1, 2, 3) or qualificacao is None or not nome:
        return None
    faixa = parse_int(row[10])
    return (
        row[0],
        reference,
        tipo,
        nome,
        parse_document(row[3]),
        qualificacao,
        parse_date(row[5]),
        parse_int(row[6]),
        parse_document(row[7]),
        parse_text(row[8], 255),
        parse_int(row[9]),
        faixa if faixa is not None and 0 <= faixa <= 9 else None,
    )


def iter_zip_rows(path: Path):
    """Lê o único CSV do ZIP em fluxo: separador ';', aspas, sem cabeçalho, Latin-1."""
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as raw:
            yield from csv.reader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";")


def scan_file(path: Path, keys: set[str]) -> tuple[list[list[str]], int]:
    """Linhas do ZIP cuja raiz de CNPJ está em keys, e o total de linhas varridas.

    Toda linha começa com "NNNNNNNN" (a raiz entre aspas). Comparar esse trecho antes do
    parse CSV evita interpretar dezenas de milhões de linhas que serão descartadas.
    """
    rows, lines = [], 0
    if not keys:
        return rows, lines
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as raw:
            for line in io.TextIOWrapper(raw, encoding="latin-1", newline=""):
                lines += 1
                if line[1:9] in keys:
                    rows.append(next(csv.reader([line], delimiter=";")))
    return rows, lines


def partner_companies(socio_records) -> set[str]:
    """Raízes de CNPJ das empresas que são sócias (tipo 1) nos registros dados.

    A RFB publica o documento do sócio PJ apenas com os 8 dígitos da raiz.
    """
    return {
        record[4] for record in socio_records
        if record[2] == 1 and record[4] and re.fullmatch(r"\d{8}", record[4])
    }


# ------------------------------------------------------------------------------
# Fonte
# ------------------------------------------------------------------------------

def required_files() -> list[str]:
    return [f"{group}{part}.zip" for group in GROUPS for part in PARTS] + list(LOOKUPS)


def choose_month(session, base_url: str, override: str = "") -> tuple[str, dict]:
    """Mês mais recente com todos os arquivos publicados (a RFB sobe um mês ao longo de dias)."""
    candidates = [override] if override else list(reversed(list_months(session, base_url)))
    for month in candidates:
        files = list_folder(session, f"{base_url}/{month}")
        missing = [name for name in required_files() if name not in files]
        if not missing:
            return month, files
        logger.warning("RFB: mês %s incompleto, faltam %s.", month, ", ".join(missing))
    raise RuntimeError("Nenhum mês completo de dados abertos do CNPJ encontrado na RFB.")


def load_targets(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT cnpj_cpf FROM oltp.fornecedores;")
        return {basico for (document,) in cur.fetchall() if (basico := cnpj_basico(document))}


# ------------------------------------------------------------------------------
# Carga
# ------------------------------------------------------------------------------

def upsert_lookup(conn, table: str, rows: list[tuple[int, str]]) -> None:
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO oltp.{table} (codigo, descricao) VALUES %s
            ON CONFLICT (codigo) DO UPDATE SET descricao = EXCLUDED.descricao
            WHERE oltp.{table}.descricao IS DISTINCT FROM EXCLUDED.descricao;
            """,
            rows,
        )


def read_lookup(path: Path) -> list[tuple[int, str]]:
    rows = {}
    for row in iter_zip_rows(path):
        code = parse_int(row[0]) if row else None
        if code is not None and len(row) >= 2:
            rows[code] = parse_text(row[1], 255) or UNDOCUMENTED_CODE
    return sorted(rows.items())


def ensure_codes(conn, table: str, known: set[int], used: set[int]) -> None:
    """Códigos usados nos dados que a tabela de domínio da RFB não traz entram com rótulo explícito."""
    missing = sorted(used - known)
    if missing:
        logger.warning("RFB: %d código(s) sem descrição em %s: %s", len(missing), table, missing)
        upsert_lookup(conn, table, [(code, UNDOCUMENTED_CODE) for code in missing])


def ingest_cnpj_owners(conn: psycopg2.extensions.connection, run_id) -> dict:
    started = time.perf_counter()
    session = get_rfb_session(RFB_CNPJ_TOKEN)
    base_url = RFB_CNPJ_BASE_URL.rstrip("/")

    targets = load_targets(conn)
    logger.info("RFB: %d raízes de CNPJ entre os fornecedores da CEAPS.", len(targets))
    if not targets:
        logger.warning("RFB: nenhum fornecedor com CNPJ completo; execute antes o job de despesas.")
        return {"records_read": 0, "records_written": 0}

    month, files = choose_month(session, base_url, RFB_CNPJ_MONTH)
    reference = datetime.date(int(month[:4]), int(month[5:7]), 1)
    cache = Path(CNPJ_CACHE_DIR) / month
    logger.info("RFB: usando o retrato %s.", month)

    def fetch(name: str) -> Path:
        return download_file(session, f"{base_url}/{month}/{name}", cache / name, files.get(name))

    # Tabelas de domínio
    qualificacoes = read_lookup(fetch("Qualificacoes.zip"))
    naturezas = read_lookup(fetch("Naturezas.zip"))
    upsert_lookup(conn, "qualificacoes_socio", qualificacoes)
    upsert_lookup(conn, "naturezas_juridicas", naturezas)

    read = rejected = 0
    raw_rows = {group: [] for group in GROUPS}

    # Sócios, subindo a cadeia societária: o nível 0 são os fornecedores; cada nível
    # seguinte são as empresas que aparecem como sócias (PJ) no nível anterior.
    socios = {}
    known = set(targets)
    frontier = set(targets)
    socio_files = [fetch(f"Socios{part}.zip") for part in PARTS]
    for level in range(CNPJ_OWNER_MAX_DEPTH + 1):
        level_records = []
        for path in socio_files:
            rows, lines = scan_file(path, frontier)
            read += lines
            for row in rows:
                raw_rows["Socios"].append(row)
                record = parse_socio(row, reference)
                if record is None:
                    rejected += 1
                    continue
                socios[(record[0], record[2], record[3], record[4], record[5])] = record
                level_records.append(record)
        frontier = partner_companies(level_records) - known
        logger.info(
            "RFB: nível %d da cadeia societária: %d sócios lidos; %d empresas sócias novas.",
            level, len(level_records), len(frontier),
        )
        if not frontier:
            break
        if level == CNPJ_OWNER_MAX_DEPTH:
            # Sem o quadro de sócios, essas empresas aparecem como cadeia interrompida.
            logger.warning(
                "RFB: profundidade máxima (%d) atingida; %d empresas sócias não foram expandidas.",
                CNPJ_OWNER_MAX_DEPTH, len(frontier),
            )
            break
        known |= frontier

    # Dados cadastrais de todas as empresas da cadeia, em uma única varredura.
    empresas = {}
    for part in PARTS:
        path = fetch(f"Empresas{part}.zip")
        rows, lines = scan_file(path, known)
        read += lines
        for row in rows:
            raw_rows["Empresas"].append(row)
            record = parse_empresa(row, reference)
            if record is None:
                rejected += 1
                continue
            empresas[record[0]] = record
        logger.info("RFB: %s lido (%d linhas varridas até aqui).", path.name, read)

    for group, rows in raw_rows.items():
        save_raw_payload(
            conn,
            entity_type=f"rfb_{group.lower()}",
            source_name="rfb_dados_abertos_cnpj",
            source_url=f"{base_url}/{month}/{group}*.zip",
            payload_json={"mes_referencia": month, "linhas": rows},
            media_type="application/json",
            run_id=run_id,
        )

    # Sócio só entra se a empresa do mesmo retrato existe (FK composta).
    orphan = [key for key, record in socios.items() if record[0] not in empresas]
    for key in orphan:
        del socios[key]

    ensure_codes(
        conn, "naturezas_juridicas", {code for code, _ in naturezas},
        {r[3] for r in empresas.values() if r[3] is not None},
    )
    ensure_codes(
        conn, "qualificacoes_socio", {code for code, _ in qualificacoes},
        {r[4] for r in empresas.values() if r[4] is not None}
        | {r[5] for r in socios.values()}
        | {r[10] for r in socios.values() if r[10] is not None},
    )

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO oltp.empresas (
                cnpj_basico, data_referencia, razao_social, natureza_juridica,
                qualificacao_responsavel, capital_social, porte, ente_federativo
            ) VALUES %s
            ON CONFLICT (cnpj_basico, data_referencia) DO UPDATE SET
                razao_social = EXCLUDED.razao_social,
                natureza_juridica = EXCLUDED.natureza_juridica,
                qualificacao_responsavel = EXCLUDED.qualificacao_responsavel,
                capital_social = EXCLUDED.capital_social,
                porte = EXCLUDED.porte,
                ente_federativo = EXCLUDED.ente_federativo
            WHERE (oltp.empresas.razao_social, oltp.empresas.natureza_juridica,
                   oltp.empresas.qualificacao_responsavel, oltp.empresas.capital_social,
                   oltp.empresas.porte, oltp.empresas.ente_federativo)
                IS DISTINCT FROM
                  (EXCLUDED.razao_social, EXCLUDED.natureza_juridica,
                   EXCLUDED.qualificacao_responsavel, EXCLUDED.capital_social,
                   EXCLUDED.porte, EXCLUDED.ente_federativo);
            """,
            list(empresas.values()),
            page_size=1000,
        )
        execute_values(
            cur,
            """
            INSERT INTO oltp.socios (
                cnpj_basico, data_referencia, tipo_socio, nome_socio, documento_socio,
                qualificacao, data_entrada, pais, documento_representante,
                nome_representante, qualificacao_representante, faixa_etaria
            ) VALUES %s
            ON CONFLICT ON CONSTRAINT unq_socios_retrato DO NOTHING;
            """,
            list(socios.values()),
            page_size=1000,
        )
    conn.commit()

    # Só o mês atual fica em cache.
    for old in Path(CNPJ_CACHE_DIR).glob("*"):
        if old.is_dir() and old.name != month:
            shutil.rmtree(old, ignore_errors=True)

    not_found = len(targets - set(empresas))
    logger.info(
        "RFB: %d empresas (%d fornecedores e %d sócias na cadeia) e %d sócios carregados para %s em %.0f s; "
        "%d raízes de CNPJ não encontradas na base; %d linhas rejeitadas no layout; %d sócios sem empresa.",
        len(empresas), len(targets & set(empresas)), len(set(empresas) - targets), len(socios),
        month, time.perf_counter() - started, not_found, rejected, len(orphan),
    )
    return {
        "records_read": read,
        "records_written": len(empresas) + len(socios),
        "records_skipped": not_found + len(orphan),
        "records_failed": rejected,
    }
