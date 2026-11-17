# Global Energy Trends: Phase 1 Project Proposal

## Team
| Full name | Student ID | Assigned role |
|---|---|---|
| Wessam Ahmed Shahat | 692300284 | Data source and analysis |
| Ahmed Mohamed Shaban | 69230029 | Ingestion and data quality |
| Stevo Waleed Gamal | 692300344 | Database and orchestration |

## Dataset
**Our World in Data Energy dataset** — https://catalog.ourworldindata.org/energy/owid_energy/

The current public CSV snapshot (2026-09-10) contains 19,494 rows × 130 columns, including country-year observations and energy supply, production, electricity mix, emissions, population, and GDP indicators. Fields include country names, ISO codes, years, and numeric measures; indicator values can be missing where a country/year is not reported. OWID documents the data and code in the linked catalog. Data produced by OWID is CC BY; third-party source terms may also apply.

## Analytical questions
1. How has renewable energy consumption changed by country and year, and which countries have grown fastest over the most recent decade with complete data?
2. How does energy use per person relate to CO2 emissions per person across countries and years?
3. What share of primary energy consumption comes from fossil fuels versus low-carbon sources in each country, and how has that mix changed over time?

## Proposed architecture
```text
[OWID Energy CSV]
        -> [Python extraction / validation]
        -> [PostgreSQL: raw + analytical tables]
        -> [Kestra orchestration]
        -> [Dashboard]
```

## Expected database tables
- `raw_energy_observations`: `entity`, `code`, `year`, selected original indicators, `source_snapshot_date`, `ingested_at`.
- `dim_country`: `country_code` (primary key), `country_name`.
- `fact_energy_metrics`: `country_code`, `year`, `renewables_share`, `renewables_consumption`, `fossil_fuel_share`, `energy_per_capita`, `co2_per_capita`.
- `data_quality_log`: `run_id`, `check_name`, `status`, `details`, `checked_at`.

We will finalize exact metric column names against the CSV header in Phase 2 and retain the original fields needed to reproduce results.

## Environment and configuration
Docker Compose starts PostgreSQL 16 and pgAdmin 4 (9.19.0) with named persistent volumes. Copy `.env.example` to `.env` and replace the example credentials locally; do not commit `.env`. PostgreSQL is reachable on localhost:5432 and pgAdmin on http://localhost:5050. From pgAdmin, register a server with host `postgres`, port `5432`, and the credentials in `.env`.

## Team roles and readiness
All members should be able to explain the CSV source, each analytical question, the Compose services, the persistent volume, and how pgAdmin reaches PostgreSQL over the Compose network. Confirm the listed names, IDs, and responsibilities before submission.
