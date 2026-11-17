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
