CREATE SCHEMA IF NOT EXISTS monitoring;

-- ============================================================
-- EXECUÇÕES DO PIPELINE
-- ============================================================

CREATE TABLE IF NOT EXISTS monitoring.pipeline_runs (
    run_id UUID PRIMARY KEY,
    pipeline_name VARCHAR(100) NOT NULL,
    ingestion_year INTEGER,
    started_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    duration_seconds NUMERIC(12, 3),
    status VARCHAR(20) NOT NULL
        DEFAULT 'running',
    error_message TEXT,
    CONSTRAINT chk_pipeline_status
        CHECK (
            status IN (
                'running',
                'success',
                'failed'
            )
        )
);


-- ============================================================
-- EXECUÇÕES DOS JOBS
-- ============================================================

CREATE TABLE IF NOT EXISTS monitoring.job_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL
        REFERENCES monitoring.pipeline_runs(run_id)
        ON DELETE CASCADE,
    job_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    duration_seconds NUMERIC(12, 3),
    status VARCHAR(20) NOT NULL
        DEFAULT 'running',
    records_read BIGINT DEFAULT 0,
    records_written BIGINT DEFAULT 0,
    records_skipped BIGINT DEFAULT 0,
    records_failed BIGINT DEFAULT 0,
    error_message TEXT,
    CONSTRAINT chk_job_status
        CHECK (
            status IN (
                'running',
                'success',
                'failed'
            )
        )
);

-- ============================================================
-- ÍNDICES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
    ON monitoring.pipeline_runs(started_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON monitoring.pipeline_runs(status);

CREATE INDEX IF NOT EXISTS idx_job_runs_run_id
    ON monitoring.job_runs(run_id);

CREATE INDEX IF NOT EXISTS idx_job_runs_job_name
    ON monitoring.job_runs(job_name);

CREATE INDEX IF NOT EXISTS idx_job_runs_started_at
    ON monitoring.job_runs(started_at);