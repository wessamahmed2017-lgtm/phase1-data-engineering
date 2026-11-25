WITH latest_run AS (
    SELECT cleaning_run_id, source_ingestion_run_id, raw_rows, duplicate_rows, cleaned_rows
    FROM analytics.cleaning_runs
    ORDER BY started_at DESC
    LIMIT 1
), current_facts AS (
    SELECT f.*
    FROM analytics.fact_energy_metrics AS f
    JOIN latest_run AS r ON r.cleaning_run_id = f.cleaning_run_id
), row_counts AS (
    SELECT
        r.cleaning_run_id,
        r.source_ingestion_run_id,
        r.raw_rows AS logged_raw_rows,
        r.duplicate_rows,
        r.cleaned_rows AS logged_clean_rows,
        (SELECT COUNT(*) FROM raw.energy_observations AS ro
         WHERE ro.run_id = r.source_ingestion_run_id) AS actual_raw_rows,
        (SELECT COUNT(*) FROM current_facts) AS actual_clean_rows
    FROM latest_run AS r
), key_issues AS (
    SELECT COUNT(*) AS duplicate_keys
    FROM (
        SELECT entity_code, year
        FROM current_facts
        GROUP BY entity_code, year
        HAVING COUNT(*) > 1
    ) AS duplicates
), link_issues AS (
    SELECT COUNT(*) AS broken_links
    FROM current_facts AS f
    LEFT JOIN analytics.dim_country AS d ON d.entity_code = f.entity_code
    LEFT JOIN raw.energy_observations AS ro
      ON ro.run_id = f.source_run_id AND ro.row_number = f.source_row_number
    WHERE d.entity_code IS NULL OR ro.row_number IS NULL
), null_issues AS (
    SELECT COUNT(*) AS missing_keys
    FROM current_facts
    WHERE entity_code IS NULL OR year IS NULL
), measure_nulls AS (
    SELECT measure_name, COUNT(*) FILTER (WHERE is_missing) AS missing_count, COUNT(*) AS row_count
    FROM current_facts AS f
    CROSS JOIN LATERAL (VALUES
        ('renewables_energy_twh', f.renewables_energy_twh IS NULL),
        ('renewables_energy_share_pct', f.renewables_energy_share_pct IS NULL),
        ('fossil_fuels_energy_share_pct', f.fossil_fuels_energy_share_pct IS NULL),
        ('low_carbon_energy_share_pct', f.low_carbon_energy_share_pct IS NULL),
        ('total_energy_twh', f.total_energy_twh IS NULL),
        ('total_energy_per_capita_kwh', f.total_energy_per_capita_kwh IS NULL),
        ('electricity_co2e_per_capita_tonnes', f.electricity_co2e_per_capita_tonnes IS NULL)
    ) AS m(measure_name, is_missing)
    GROUP BY measure_name
), range_issues AS (
    SELECT COUNT(*) AS invalid_values
    FROM current_facts
    WHERE year < 1700 OR year > 2100
       OR renewables_energy_twh < 0
       OR total_energy_twh < 0
       OR total_energy_per_capita_kwh < 0
       OR electricity_co2e_per_capita_tonnes < 0
       OR renewables_energy_share_pct < 0 OR renewables_energy_share_pct > 100
       OR fossil_fuels_energy_share_pct < 0 OR fossil_fuels_energy_share_pct > 100
       OR low_carbon_energy_share_pct < 0 OR low_carbon_energy_share_pct > 100
)
SELECT 'primary_key_uniqueness' AS check_name,
       CASE WHEN duplicate_keys = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
       format('duplicate entity/year keys=%s; threshold=0', duplicate_keys) AS details
FROM key_issues
UNION ALL
SELECT 'foreign_key_integrity', CASE WHEN broken_links = 0 THEN 'PASS' ELSE 'FAIL' END,
       format('broken dimension/raw references=%s; threshold=0', broken_links)
FROM link_issues
UNION ALL
SELECT 'required_key_nulls', CASE WHEN missing_keys = 0 THEN 'PASS' ELSE 'FAIL' END,
       format('rows with null entity_code/year=%s; threshold=0', missing_keys)
FROM null_issues
UNION ALL
SELECT 'null_threshold_' || measure_name,
       CASE WHEN row_count > 0 AND missing_count * 100.0 / row_count <= 85 THEN 'PASS' ELSE 'FAIL' END,
       format('missing=%s/%s (%s%%); maximum=85%%', missing_count, row_count,
              round(COALESCE(missing_count * 100.0 / NULLIF(row_count, 0), 100), 2))
FROM measure_nulls
UNION ALL
SELECT 'numeric_ranges', CASE WHEN invalid_values = 0 THEN 'PASS' ELSE 'FAIL' END,
       format('invalid year/share/negative measure rows=%s; threshold=0', invalid_values)
FROM range_issues
UNION ALL
SELECT 'raw_vs_clean_row_counts',
       CASE WHEN actual_raw_rows = logged_raw_rows
                  AND actual_clean_rows = logged_clean_rows
                  AND logged_clean_rows = logged_raw_rows - duplicate_rows
            THEN 'PASS' ELSE 'FAIL' END,
       format('raw actual/logged=%s/%s; exact duplicates=%s; clean actual/logged=%s/%s; expected clean=raw-duplicates=%s',
              actual_raw_rows, logged_raw_rows, duplicate_rows,
              actual_clean_rows, logged_clean_rows, logged_raw_rows - duplicate_rows)
FROM row_counts
ORDER BY check_name;
