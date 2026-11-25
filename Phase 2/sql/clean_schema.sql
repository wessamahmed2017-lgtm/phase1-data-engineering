CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.cleaning_runs (
    cleaning_run_id UUID PRIMARY KEY,
    source_ingestion_run_id UUID NOT NULL REFERENCES raw.ingestion_runs(run_id),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    raw_rows BIGINT CHECK (raw_rows IS NULL OR raw_rows >= 0),
    duplicate_rows BIGINT CHECK (duplicate_rows IS NULL OR duplicate_rows >= 0),
    cleaned_rows BIGINT CHECK (cleaned_rows IS NULL OR cleaned_rows >= 0),
    error TEXT
);

CREATE TABLE IF NOT EXISTS analytics.dim_country (
    entity_code TEXT PRIMARY KEY,
    iso_code TEXT UNIQUE,
    country_name TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('country', 'aggregate', 'other'))
);

CREATE TABLE IF NOT EXISTS analytics.fact_energy_metrics (
    entity_code TEXT NOT NULL REFERENCES analytics.dim_country(entity_code),
    year SMALLINT NOT NULL,
    renewables_energy_twh NUMERIC,
    renewables_energy_share_pct NUMERIC,
    fossil_fuels_energy_share_pct NUMERIC,
    low_carbon_energy_share_pct NUMERIC,
    total_energy_twh NUMERIC,
    total_energy_per_capita_kwh NUMERIC,
    electricity_co2e_per_capita_tonnes NUMERIC,
    source_run_id UUID NOT NULL,
    source_row_number BIGINT NOT NULL,
    cleaning_run_id UUID NOT NULL REFERENCES analytics.cleaning_runs(cleaning_run_id),
    PRIMARY KEY (entity_code, year),
    FOREIGN KEY (source_run_id, source_row_number)
        REFERENCES raw.energy_observations(run_id, row_number)
);

CREATE INDEX IF NOT EXISTS ix_fact_energy_metrics_year
    ON analytics.fact_energy_metrics(year);
CREATE INDEX IF NOT EXISTS ix_fact_energy_metrics_cleaning_run
    ON analytics.fact_energy_metrics(cleaning_run_id);

CREATE TABLE IF NOT EXISTS analytics.data_quality_log (
    cleaning_run_id UUID NOT NULL REFERENCES analytics.cleaning_runs(cleaning_run_id),
    check_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
    details TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (cleaning_run_id, check_name)
);
