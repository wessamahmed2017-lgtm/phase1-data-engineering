# Phase 2 Ingestion & Raw Profiling Notes

## Source and failure handling

The pipeline fetches the Phase 1 approved Our World in Data Energy CSV, pinned to the `2026-09-10` snapshot for reproducibility: [OWID CSV](https://catalog.ourworldindata.org/garden/energy/2026-09-10/owid_energy/owid_energy.csv). Python's standard-library HTTP client applies a 60-second timeout and checks for HTTP 200. The download is streamed to a temporary file and atomically renamed only after it completes, so an interrupted request does not replace a previously intact raw file. Exceptions and non-success status are logged and produce a non-zero process exit. Logs include UTC execution timestamps, source HTTP status, elapsed time, bytes, SHA-256, run ID, fetched row count, and outcome.

## Raw storage and containerization

`docker-compose.phase2.yml` is an additive Compose file. Used with the Phase 1 `docker-compose.yml`, it adds the one-shot Python service to the same default Compose network. The service waits for the existing PostgreSQL health check, then uses the Compose service hostname `postgres` to connect to `energy_db` as `energy_user`. The root `.env` supplies credentials; no password or API key is stored in this folder or committed.

The downloaded CSV is preserved byte-for-byte at `Phase 2/data/raw/owid_energy.csv`; this local data file is ignored by Git. Each CSV row is also stored without type coercion as a JSONB object in `raw.energy_observations`, with its run ID and row number. `raw.ingestion_runs` records source URL/status, SHA-256, start/end timestamps, status, row count, and any error. No cleaning or transformation is performed in Phase 2.

## Raw profiling findings

The pinned source snapshot was profiled locally before transformation. It contains **19,494 data rows and 130 columns** (14,524,837 downloaded bytes). The full-row duplicate check found **0 duplicate rows**. All checked numeric columns (including `year`, `population`, `gdp`, energy indicators, and CO2-related indicators) parsed without invalid numeric values.

The principal data-quality item for Phase 3 is missingness: **128 of 130 columns** contain blank values. Missingness is especially high in energy annual-change and disaggregated indicators. Examples:

- `biofuels_energy_annual_change_pct`: 17,603 missing values.
- `solar_energy_annual_change_pct`: 17,185 missing values.
- `nuclear_energy_annual_change_pct`: 16,979 missing values.
- `wind_energy_annual_change_pct`: 16,917 missing values.
- `biofuels_energy_per_capita_kwh`: 16,820 missing values.
- `gdp`: 7,660 missing values; `population`: 1,175 missing values.
- `iso_code`: 2,014 missing values. These rows include aggregate/geographic entities, so Phase 3 should classify them before deciding whether they are invalid.

Blank values can represent unreported observations or indicators that do not apply to a country/year. Phase 3 should distinguish expected gaps from records that need correction and should document any imputation or exclusion rule. Phase 2 retains every source field as-is.

## Reproduce the live demo

From the repository root, follow the commands in `Phase 2/README.md`. In the live defense, show the ingestion container logs and use pgAdmin to query `raw.ingestion_runs` and sample rows from `raw.energy_observations`. The assignment specifies an in-person Phase 2 lab defense; it does not require a video submission.
