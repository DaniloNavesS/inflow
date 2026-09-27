from __future__ import annotations

import hashlib
import json
import logging
import uuid

from psycopg2.extras import Json


logger = logging.getLogger("inflow_ingestion")


def canonical_json_bytes(payload) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def save_raw_payload(
    connection,
    *,
    entity_type: str,
    source_name: str,
    source_url: str,
    run_id: uuid.UUID,
    payload_json=None,
    payload_bytes: bytes | None = None,
    media_type: str,
    http_status: int | None = None,
    ingestion_year: int | None = None,
) -> str:
    """Preserva uma versão única do conteúdo original antes da transformação."""
    if (payload_json is None) == (payload_bytes is None):
        raise ValueError("Informe exatamente um entre payload_json e payload_bytes")

    raw_content = canonical_json_bytes(payload_json) if payload_json is not None else payload_bytes
    content_hash = hashlib.sha256(raw_content).hexdigest()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO bronze.payloads_brutos (
                tipo_entidade, nome_fonte, url_fonte, tipo_midia,
                payload_json, payload_binario, sha256, status_http,
                ano_ingestao, primeira_execucao_id, ultima_execucao_id
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (url_fonte, sha256) DO UPDATE SET
                ultima_execucao_id = EXCLUDED.ultima_execucao_id,
                status_http = EXCLUDED.status_http,
                visto_por_ultimo_em = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                entity_type,
                source_name,
                source_url,
                media_type,
                Json(payload_json) if payload_json is not None else None,
                payload_bytes,
                content_hash,
                http_status,
                ingestion_year,
                str(run_id),
                str(run_id),
            ),
        )
        raw_id = cursor.fetchone()[0]
    connection.commit()
    logger.debug("Payload bruto preservado: tipo=%s id=%s sha256=%s", entity_type, raw_id, content_hash[:12])
    return content_hash
