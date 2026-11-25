# Phase 3 Data Quality Rules

The raw CSV and `raw.energy_observations` JSONB layer remain unchanged. Cleaning reads the preserved `Phase 2/data/raw/owid_energy.csv`, reconciles it to the latest successful Phase 2 ingestion run, and writes to the separate `analytics` schema.

## Cleaning and pre-load rules

| Rule | Threshold or behavior | Failure action |
|---|---|---|
| Required headers | `country`, `iso_code`, `year`, `renewables_energy_twh`, `renewables_energy_share_pct`, `fossil_fuels_energy_share_pct`, `low_carbon_energy_share_pct`, `total_energy_twh`, `total_energy_per_capita_kwh`, `population`, and `electricity_emissions_mtco2eq` must exist once each in the pinned CSV. | Log the missing/duplicate header and exit non-zero before replacing clean tables. |
| File and raw row counts | CSV rows must equal `raw.ingestion_runs.rows_fetched`, and the matching JSONB row count must equal that same value. | Log all counts and halt. |
| Country and year keys | Neither can be blank. Year must be an integer from 1700 through 2100, covering the earliest year in the pinned source. | Log the source row and halt. |
| Exact duplicates | Remove only byte-value-equivalent CSV records after parsing; count every removed row. | Count duplicates in run metadata and reconcile `clean rows = raw rows - exact duplicates`. |
| Duplicate country/year key | A second record with the same entity and year that is not a full-row duplicate is ambiguous. | Log both source row numbers and halt rather than choosing one record. |
| Missing ISO code | Preserve the entity with a stable `NOISO_<hash>` key; classify the entity as `other`. Three-letter codes are `country`; `OWID_` codes are `aggregate`. | No row is dropped only because its ISO code is missing. |
| Numeric types | Parse source measures as finite `Decimal` values. Blank source values stay SQL `NULL`; no imputation is performed. Electricity CO2e per capita is derived as `electricity_emissions_mtco2eq * 1,000,000 / population` when both inputs exist and population is positive. | Invalid or non-finite numbers halt before table replacement. |
| Non-negative measures | Renewable and total energy, energy per capita, electricity emissions, population, and derived electricity CO2e per capita must be zero or greater. | Log the row, column, and value; halt. |
| Share ranges | Renewable, fossil-fuel, and low-carbon energy shares must be between 0 and 100 inclusive. | Log the row, column, and value; halt. |
| Measure null rates | No clean fact measure, including derived electricity CO2e per capita, may be more than 85% NULL within a clean run. Identity keys have a 0% NULL threshold. | Pre-load validation and post-load SQL both fail loudly above the threshold. |

The Phase 2 CSV has no total country CO2-per-capita field. The energy/CO2 view therefore compares total energy use per person with **electricity-generation CO2-equivalent emissions per person**, derived from the provided electricity-emissions and population fields. This is a documented proxy and must not be described as total national CO2 emissions per person.

## PostgreSQL checks

`sql/quality_checks.sql` returns PASS/FAIL rows for primary-key uniqueness, entity/raw-row foreign-key integrity, null identity keys, each selected-measure null threshold, numeric/year ranges, and reconciliation between Phase 2 raw rows and Phase 3 fact rows. `clean_transform.py` logs each result to `analytics.data_quality_log`. A failed check raises a quality error, rolls back the fact/dimension replacement transaction, records the failed run and checks, and exits with code 1.

Database constraints additionally enforce primary keys, foreign keys, non-null required identifiers, valid run/check statuses, and non-negative run counts. Range and missingness checks remain explicit SQL checks so the live demo can show a clear FAIL result before rollback.

## Pass/fail verification

Run the clean unit scenarios from the repository root:

```powershell
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" -f "Phase 2/docker-compose.phase3.yml" --profile cleaning run --build --rm --no-deps cleaning python -m unittest discover -s tests -v
```

The passing fixture verifies typed measures, deterministic missing-code handling, and exact-duplicate reconciliation. Failing fixtures inject a conflicting entity/year key, a negative energy value, a share above 100, a missing required column, and an exceeded null threshold.

After a successful database load, run the SQL failure demonstration:

```powershell
docker compose -f docker-compose.yml -f "Phase 2/docker-compose.phase2.yml" -f "Phase 2/docker-compose.phase3.yml" --profile cleaning run --rm cleaning python clean_transform.py --demo-bad-data
```

It temporarily writes a negative renewable-consumption value, runs the exact post-load quality query, confirms `numeric_ranges` fails, and rolls back the transaction. The production loader uses the same check evaluator and exits non-zero on that failure. No corrupt value remains in the analytical tables.
