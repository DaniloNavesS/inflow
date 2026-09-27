import hashlib
import io
import re
from dataclasses import dataclass

import pdfplumber

from bronze.raw import save_raw_payload
from domain import normalize_name


DSF_SAMPLES = (
    {
        "session_number": 149,
        "session_date": "2023-10-10",
        "session_type": "Deliberativa Ordinária Semipresencial",
        "diary_code": 113837,
        "diary_number": 178,
        "publication_date": "2023-10-11",
        "first_page": 76,
        "last_page": 77,
        "expected_count": 75,
    },
    {
        "session_number": 152,
        "session_date": "2023-10-17",
        "session_type": "Deliberativa Ordinária",
        "diary_code": 113894,
        "diary_number": 181,
        "publication_date": "2023-10-18",
        "first_page": 106,
        "last_page": 107,
        "expected_count": 70,
    },
    {
        "session_number": 159,
        "session_date": "2023-10-24",
        "session_type": "Deliberativa Ordinária",
        "diary_code": 113913,
        "diary_number": 186,
        "publication_date": "2023-10-25",
        "first_page": 90,
        "last_page": 91,
        "expected_count": 75,
    },
)

ROW_RE = re.compile(
    r"^\s*(?P<party>\S(?:.*?\S)?)\s+(?P<uf>[A-Z]{2})\s+"
    r"(?P<name>.+?)\s{2,}(?P<presence>X)(?:\s{2,}(?P<vote>X))?\s*$"
)


@dataclass(frozen=True)
class AttendanceRow:
    party: str
    uf: str
    name: str
    vote_recorded: bool
    page: int


def diary_url(sample: dict) -> str:
    return (
        "https://legis.senado.leg.br/diarios/BuscaPaginasDiario"
        f"?codDiario={sample['diary_code']}&paginaInicial={sample['first_page']}"
        f"&paginaFinal={sample['last_page']}"
    )


def extract_pdf_text_by_page(content: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(content)) as document:
        return [page.extract_text(layout=True) or "" for page in document.pages]


def parse_attendance_pages(pages: list[str], first_page: int) -> list[AttendanceRow]:
    rows = []
    for offset, text in enumerate(pages):
        compact_text = re.sub(r"\s+", " ", text.upper())
        if "REGISTRO DE COMPARECIMENTO" not in compact_text:
            continue
        for line in text.splitlines():
            match = ROW_RE.match(line)
            if not match:
                continue
            rows.append(
                AttendanceRow(
                    party=match.group("party").strip(),
                    uf=match.group("uf"),
                    name=match.group("name").strip(),
                    vote_recorded=bool(match.group("vote")),
                    page=first_page + offset,
                )
            )
    return rows


def resolve_senator(name: str, senators_by_name: dict[str, set[int]]) -> tuple[int | None, str]:
    matches = senators_by_name.get(normalize_name(name), set())
    if len(matches) == 1:
        return next(iter(matches)), "EXATA"
    if len(matches) > 1:
        return None, "AMBIGUA"
    return None, "NAO_RESOLVIDA"


def ingest_dsf_attendance(session, conn, run_id, samples=DSF_SAMPLES) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, nome, nome_completo FROM oltp.senadores")
        senators_by_name: dict[str, set[int]] = {}
        for senator_id, short_name, full_name in cur.fetchall():
            for value in (short_name, full_name):
                if value:
                    senators_by_name.setdefault(normalize_name(value), set()).add(senator_id)

    metrics = []
    for sample in samples:
        url = diary_url(sample)
        response = session.get(url, timeout=120)
        response.raise_for_status()
        content = response.content
        save_raw_payload(
            conn, entity_type="dsf_document", source_name="diario_senado_federal",
            source_url=url, run_id=run_id, payload_bytes=content,
            media_type="application/pdf", http_status=response.status_code,
        )

        try:
            rows = parse_attendance_pages(
                extract_pdf_text_by_page(content), sample["first_page"]
            )
            resolved = [resolve_senator(row.name, senators_by_name) for row in rows]
            unresolved = sum(1 for senator_id, _ in resolved if senator_id is None)
            status = "SUCESSO" if len(rows) == sample["expected_count"] and unresolved == 0 else "PARCIAL"
            message = (
                f"extraidos={len(rows)}; esperados={sample['expected_count']}; "
                f"nao_resolvidos={unresolved}"
            )
        except Exception as exc:
            rows, resolved, status = [], [], "FALHA"
            message = f"parser: {type(exc).__name__}: {exc}"

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oltp.sessao_plenaria
                    (numero, data_sessao, tipo, legislatura, sessao_legislativa)
                VALUES (%s, %s, %s, 57, 1)
                ON CONFLICT (numero, data_sessao) DO UPDATE SET tipo = EXCLUDED.tipo
                RETURNING id
                """,
                (sample["session_number"], sample["session_date"], sample["session_type"]),
            )
            session_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO oltp.documento_dsf
                    (sessao_id, codigo_diario, numero_diario, data_publicacao,
                     url_documento, pagina_inicial, pagina_final, sha256,
                     status_parser, mensagem_parser)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (codigo_diario, pagina_inicial, pagina_final) DO UPDATE SET
                    sha256 = EXCLUDED.sha256,
                    status_parser = EXCLUDED.status_parser,
                    mensagem_parser = EXCLUDED.mensagem_parser,
                    atualizado_em = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (
                    session_id, sample["diary_code"], sample["diary_number"],
                    sample["publication_date"], url, sample["first_page"],
                    sample["last_page"], hashlib.sha256(content).hexdigest(), status, message,
                ),
            )
            document_id = cur.fetchone()[0]
            for row, (senator_id, resolution) in zip(rows, resolved):
                cur.execute(
                    """
                    INSERT INTO oltp.registro_presenca
                        (sessao_id, documento_dsf_id, senador_id, nome_documento,
                         partido_documento, uf_documento, situacao, voto_registrado,
                         pagina, resolucao)
                    VALUES (%s,%s,%s,%s,%s,%s,'PRESENTE',%s,%s,%s)
                    ON CONFLICT (documento_dsf_id, nome_documento) DO UPDATE SET
                        senador_id = EXCLUDED.senador_id,
                        partido_documento = EXCLUDED.partido_documento,
                        uf_documento = EXCLUDED.uf_documento,
                        voto_registrado = EXCLUDED.voto_registrado,
                        pagina = EXCLUDED.pagina,
                        resolucao = EXCLUDED.resolucao,
                        atualizado_em = CURRENT_TIMESTAMP
                    """,
                    (
                        session_id, document_id, senator_id, row.name, row.party,
                        row.uf, row.vote_recorded, row.page, resolution,
                    ),
                )
        conn.commit()
        metrics.append({**sample, "extracted": len(rows), "unresolved": unresolved if rows else 0, "status": status})
    return metrics
