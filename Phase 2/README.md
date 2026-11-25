# Phase 2 - Data Ingestion, Raw Storage & Containerization

Phase 2 extends the approved Phase 1 project and uses the same pinned OWID Energy CSV snapshot. Phase 1 proposal files and its original Compose file remain separate and unchanged by this phase.

## Files

- `scripts/ingest.py`: downloads the source CSV, preserves it as a raw file, and inserts each original row as JSONB in PostgreSQL.
- `scripts/profile_raw.py`: checks missing values, full-row duplicates, and numeric values without changing the raw data.
- `sql/raw_schema.sql`: DDL for `raw.ingestion_runs` and `raw.energy_observations`.
- `Dockerfile`, `requirements.txt`, `docker-compose.phase2.yml`: containerized one-shot ingestion service that joins the existing PostgreSQL network.
- `docs/phase2_notes.md` and `docs/Phase_2_Ingestion_Profiling.pdf`: technical and profiling summary.
- `data/raw/owid_energy.csv`: downloaded locally at runtime; ignored by Git to keep the repository lean.

## Run the complete stack and ingestion

Run these commands from the repository root in PowerShell. Keep the repository-root `.env` created for Phase 1.

```powershell
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" up -d
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" --profile ingestion up --build ingestion
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" logs ingestion
```

The first command starts PostgreSQL and pgAdmin. The second builds and runs the one-shot ingestion service after PostgreSQL is healthy. It leaves the exited container available for log inspection. The original CSV is persisted under `Phase 2/data/raw/`; PostgreSQL stores run metadata and raw JSONB rows in schema `raw`.

## Verify in pgAdmin

Open the existing `energy_db` database, then use Query Tool:

```sql
SELECT status, rows_fetched, started_at, finished_at
FROM raw.ingestion_runs
ORDER BY started_at DESC
LIMIT 5;

SELECT row_number, source_row ->> 'country' AS country, source_row ->> 'year' AS year
FROM raw.energy_observations
ORDER BY row_number
LIMIT 5;
```

The Phase 2 lab asks for an in-person live defense. There is no Phase 2 video submission; bring the repository and run the pipeline live.

## Phase 3 cleaning, relational model, and data quality

Phase 3 keeps the Phase 2 raw CSV and JSONB rows unchanged. It validates the pinned CSV against the latest successful ingestion run, removes exact duplicate CSV rows, loads normalized country/entity and country-year fact tables, builds analytical views, and halts with a non-zero exit if any quality check fails.

From the repository root, start PostgreSQL and run Phase 2 ingestion as above. Then build and run the clean pipeline:

```powershell
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" -f "Phase 2/docker-compose.phase3.yml" --profile cleaning run --build --rm cleaning
```

The Phase 3 service waits for the existing PostgreSQL health check. It reads `Phase 2/data/raw/owid_energy.csv` and references the matching Phase 2 run in `raw.ingestion_runs`. The pipeline creates `analytics.dim_country`, `analytics.fact_energy_metrics`, `analytics.cleaning_runs`, and `analytics.data_quality_log`, and then creates the five SQL views in `Phase 2/sql/analytics_views.sql`.

Run the database-free pass/fail checks:

```powershell
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" -f "Phase 2/docker-compose.phase3.yml" --profile cleaning run --build --rm --no-deps cleaning python -m unittest discover -s tests -v
```

After one successful clean run, demonstrate the post-load SQL failure path. The injected negative value exists only inside a database transaction; the demo runs the same SQL checks as the pipeline and rolls the transaction back:

```powershell
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" -f "Phase 2/docker-compose.phase3.yml" --profile cleaning run --rm cleaning python clean_transform.py --demo-bad-data
```

See `Phase 2/docs/phase3_notes.md` for the three project questions, before/after row counts, run sequence, and live-demo queries. See `Phase 2/docs/DATA_QUALITY.md` for each rule, threshold, failure behavior, and expected pass/fail output.
