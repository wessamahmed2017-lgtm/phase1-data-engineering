CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.ingestion_runs (
    run_id UUID PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_http_status INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    rows_fetched BIGINT NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS raw.energy_observations (
    run_id UUID NOT NULL REFERENCES raw.ingestion_runs(run_id),
    row_number BIGINT NOT NULL,
    source_row JSONB NOT NULL,
    PRIMARY KEY (run_id, row_number)
);
