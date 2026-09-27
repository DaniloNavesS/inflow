from __future__ import annotations
import logging
import uuid
import psycopg2
from psycopg2.extras import Json

logger = logging.getLogger("inflow_ingestor")

def save_raw_payload(
    conn: psycopg2.extensions.connection,
    *,
    entity_type: str,
    source_name: str,
    source_url: str,
    payload,
    run_id: uuid.UUID,
    http_status: int | None = None,
    ingestion_year: int | None = None,
) -> uuid.UUID:
    """
    Persiste na camada Bronze a resposta original recebida da API.
    Nenhuma transformação de negócio deve ser realizada
    antes desta função.
    """
    
    batch_id = uuid.uuid4()

    query = """
        INSERT INTO bronze.raw_payloads (
            entity_type,
            source_name,
            source_url,
            payload,
            http_status,
            ingestion_year,
            run_id,
            batch_id,
            received_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            CURRENT_TIMESTAMP
        );
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                entity_type,
                source_name,
                source_url,
                Json(payload),
                http_status,
                ingestion_year,
                str(run_id),
                str(batch_id),
            ),
        )

    conn.commit()

    logger.info(
        "Payload Bronze salvo: entity=%s batch=%s",
        entity_type,
        batch_id,
    )

    return batch_id