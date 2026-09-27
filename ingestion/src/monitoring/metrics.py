from __future__ import annotations
import logging
import time
import uuid
import psycopg2

logger = logging.getLogger("inflow_ingestor")

# ============================================================
# PIPELINE
# ============================================================

def start_pipeline(
    conn: psycopg2.extensions.connection,
    pipeline_name: str,
    ingestion_year: int | None = None,
) -> uuid.UUID:
    """
    Registra o início de uma execução completa do pipeline.
    """
    run_id = uuid.uuid4()

    query = """
        INSERT INTO monitoring.pipeline_runs (
            run_id,
            pipeline_name,
            ingestion_year,
            started_at,
            status
        )
        VALUES (
            %s,
            %s,
            %s,
            CURRENT_TIMESTAMP,
            'running'
        );
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                str(run_id),
                pipeline_name,
                ingestion_year,
            ),
        )

    conn.commit()

    logger.info(
        "Monitoramento: pipeline iniciado. run_id=%s",
        run_id,
    )

    return run_id


def finish_pipeline(
    conn: psycopg2.extensions.connection,
    run_id: uuid.UUID,
    duration_seconds: float,
) -> None:
    """
    Marca o pipeline como concluído com sucesso.
    """

    query = """
        UPDATE monitoring.pipeline_runs
        SET
            finished_at = CURRENT_TIMESTAMP,
            duration_seconds = %s,
            status = 'success'
        WHERE run_id = %s;
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                duration_seconds,
                str(run_id),
            ),
        )

    conn.commit()

    logger.info(
        "Monitoramento: pipeline %s finalizado em %.3f segundos.",
        run_id,
        duration_seconds,
    )


def fail_pipeline(
    conn: psycopg2.extensions.connection,
    run_id: uuid.UUID,
    duration_seconds: float,
    error_message: str,
) -> None:
    """
    Marca o pipeline como falho.
    """

    query = """
        UPDATE monitoring.pipeline_runs
        SET
            finished_at = CURRENT_TIMESTAMP,
            duration_seconds = %s,
            status = 'failed',
            error_message = %s
        WHERE run_id = %s;
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                duration_seconds,
                error_message,
                str(run_id),
            ),
        )

    conn.commit()

    logger.error(
        "Monitoramento: pipeline %s marcado como failed.",
        run_id,
    )


# ============================================================
# JOBS
# ============================================================

def start_job(
    conn: psycopg2.extensions.connection,
    run_id: uuid.UUID,
    job_name: str,
) -> int:
    """
    Registra o início de um job do pipeline.
    """

    query = """
        INSERT INTO monitoring.job_runs (
            run_id,
            job_name,
            started_at,
            status
        )
        VALUES (
            %s,
            %s,
            CURRENT_TIMESTAMP,
            'running'
        )
        RETURNING id;
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                str(run_id),
                job_name,
            ),
        )

        job_id = cur.fetchone()[0]

    conn.commit()

    logger.info(
        "Monitoramento: job '%s' iniciado. job_id=%s",
        job_name,
        job_id,
    )

    return job_id


def finish_job(
    conn: psycopg2.extensions.connection,
    job_id: int,
    duration_seconds: float,
    records_read: int = 0,
    records_written: int = 0,
    records_skipped: int = 0,
    records_failed: int = 0,
) -> None:
    """
    Finaliza um job com sucesso e persiste suas métricas.
    """

    query = """
        UPDATE monitoring.job_runs
        SET
            finished_at = CURRENT_TIMESTAMP,
            duration_seconds = %s,
            status = 'success',
            records_read = %s,
            records_written = %s,
            records_skipped = %s,
            records_failed = %s
        WHERE id = %s;
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                duration_seconds,
                records_read,
                records_written,
                records_skipped,
                records_failed,
                job_id,
            ),
        )

    conn.commit()

    logger.info(
        "Monitoramento: job %s finalizado em %.3f segundos.",
        job_id,
        duration_seconds,
    )


def fail_job(
    conn: psycopg2.extensions.connection,
    job_id: int,
    duration_seconds: float,
    error_message: str,
) -> None:
    """
    Marca um job como falho.
    """

    query = """
        UPDATE monitoring.job_runs
        SET
            finished_at = CURRENT_TIMESTAMP,
            duration_seconds = %s,
            status = 'failed',
            error_message = %s
        WHERE id = %s;
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            (
                duration_seconds,
                error_message,
                job_id,
            ),
        )

    conn.commit()

    logger.error(
        "Monitoramento: job %s marcado como failed.",
        job_id,
    )