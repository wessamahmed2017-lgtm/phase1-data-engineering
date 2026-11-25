# Phase 3 Cleaning, Relational Modeling, and QA Notes

## Scope and source

Phase 3 builds on the Phase 2 pinned Our World in Data Energy snapshot (`2026-09-10`). Phase 2 continues to preserve every source row in both the CSV and `raw.energy_observations`. The new pipeline validates and transforms that input without updating or deleting anything in the raw schema.

## Cleaning decisions and row-count reconciliation

The Phase 2 profiling notes report 19,494 raw CSV rows, 130 columns, and zero exact full-row duplicates for the pinned snapshot. Phase 3 keeps missing indicator values as `NULL` (no imputation), retains records whose ISO code is missing by assigning a deterministic synthetic entity key, and removes only exact duplicate records. A conflicting duplicate entity/year key, invalid number, invalid share, missing identity, schema mismatch, or row-count mismatch stops the run.

The pinned CSV was re-read and validated before writing the Phase 3 pipeline. It contains 19,494 data rows and 130 columns; the transform produced 19,494 clean rows, found zero exact duplicate rows, and passed all 85% measure-null thresholds. The final dimensions contain 260 entities, including 40 entities without an ISO code (retained using stable synthetic keys). The Phase 2 profile also reported 2,014 rows with a missing ISO code.

For the profiled snapshot the reconciliation is:

| Layer | Rows | Meaning |
|---|---:|---|
| Phase 2 CSV / `raw.energy_observations` | 19,494 | Immutable source rows for a successful ingestion run. |
| Exact full-row duplicates removed | 0 | Baseline reported by the Phase 2 profiler. |
| Phase 3 `analytics.fact_energy_metrics` | 19,494 | One clean entity/year observation per raw row after the duplicate rule. The runtime log and SQL count check record the observed result. |

The loader compares the CSV count, ingestion-run count, and raw JSONB count before loading. After loading, SQL checks confirm `clean rows = raw rows - exact duplicate rows`. `analytics.fact_energy_metrics.source_run_id` and `source_row_number` link every fact back to its raw JSONB observation.

## Relational model

- `analytics.dim_country`: one row per dataset entity. `entity_code` is the primary key; `iso_code` is unique when present. Entity type distinguishes ISO-coded countries, `OWID_` aggregates, and other/code-less entities.
- `analytics.fact_energy_metrics`: one row per entity/year, with a composite primary key `(entity_code, year)`, a foreign key to the dimension, a foreign key to the source raw row, and a foreign key to the cleaning run.
- `analytics.cleaning_runs`: source ingestion run, timestamps, status, raw/duplicate/clean counts, and error details.
- `analytics.data_quality_log`: one PASS/FAIL result and explanatory details per check and cleaning run.

The dimension join lets country-only views exclude aggregates while the normalized fact table retains all dataset entities. The raw-row reference supports traceability and the fact grain supports the year-by-year project questions.

## Analytical questions and SQL views

The CSV uses the field names finalized in Phase 2: `renewables_energy_twh`, `renewables_energy_share_pct`, `fossil_fuels_energy_share_pct`, `low_carbon_energy_share_pct`, `total_energy_twh`, and `total_energy_per_capita_kwh`. It does not have total national `co2_per_capita`; the energy/CO2 view therefore computes electricity-generation CO2-equivalent tonnes per person from `electricity_emissions_mtco2eq` and `population`. This narrower proxy is called out in the view and quality notes.

1. Renewable use and fastest growth: `analytics.v_renewables_by_country_year` provides annual renewable energy (`renewables_energy_twh`), share, and year-over-year change. `analytics.v_fastest_renewables_growth` ranks each country's latest available complete ten-year sequence.
2. Energy use versus CO2 emissions: `analytics.v_energy_co2_by_country_year` exposes paired country/year values; `analytics.v_energy_co2_correlation_by_year` summarizes their correlation and sample size by year. Because this CSV does not contain total country CO2 per capita, it compares `total_energy_per_capita_kwh` with derived electricity-generation CO2-equivalent tonnes per capita. See `DATA_QUALITY.md` for the derivation and limitation.
3. Fossil versus low-carbon energy mix: `analytics.v_fossil_vs_low_carbon_mix` exposes total primary energy (`total_energy_twh`) and the fossil (`fossil_fuels_energy_share_pct`), low-carbon, and renewable shares by country/year.

Example live queries in pgAdmin:

```sql
SELECT * FROM analytics.v_fastest_renewables_growth LIMIT 10;
SELECT * FROM analytics.v_energy_co2_correlation_by_year ORDER BY year;
SELECT * FROM analytics.v_fossil_vs_low_carbon_mix
WHERE country_code = 'EGY' ORDER BY year;
```

## Live run sequence

From the repository root, keep the existing `.env` and raw Phase 2 flow:

```powershell
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" up -d
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" --profile ingestion up --build ingestion
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" -f "Phase 2/docker-compose.phase3.yml" --profile cleaning run --build --rm cleaning
```

In pgAdmin, show the `analytics` tables and foreign keys, then run:

```sql
SELECT * FROM analytics.cleaning_runs ORDER BY started_at DESC LIMIT 5;
SELECT * FROM analytics.data_quality_log ORDER BY checked_at DESC LIMIT 20;
SELECT * FROM analytics.fact_energy_metrics ORDER BY entity_code, year LIMIT 10;
```

The clean pipeline prints all SQL check statuses and returns non-zero when a check fails. The `--demo-bad-data` command described in `DATA_QUALITY.md` confirms the negative-value SQL check and rolls back the injected value. Full rules and thresholds are in that file.
