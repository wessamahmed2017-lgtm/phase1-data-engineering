CREATE OR REPLACE VIEW analytics.v_renewables_by_country_year AS
SELECT
    d.iso_code AS country_code,
    d.country_name,
    f.year,
    f.renewables_energy_twh,
    f.renewables_energy_share_pct,
    LAG(f.renewables_energy_twh) OVER (PARTITION BY f.entity_code ORDER BY f.year)
        AS previous_year_renewables_energy_twh,
    CASE
        WHEN LAG(f.renewables_energy_twh) OVER (PARTITION BY f.entity_code ORDER BY f.year) > 0
        THEN (f.renewables_energy_twh
              - LAG(f.renewables_energy_twh) OVER (PARTITION BY f.entity_code ORDER BY f.year))
             * 100.0
             / LAG(f.renewables_energy_twh) OVER (PARTITION BY f.entity_code ORDER BY f.year)
        ELSE NULL
    END AS year_over_year_growth_pct
FROM analytics.fact_energy_metrics AS f
JOIN analytics.dim_country AS d ON d.entity_code = f.entity_code
WHERE d.entity_type = 'country';

CREATE OR REPLACE VIEW analytics.v_fastest_renewables_growth AS
WITH points AS (
    SELECT
        f.entity_code,
        d.iso_code AS country_code,
        d.country_name,
        f.year AS decade_end_year,
        FIRST_VALUE(f.year) OVER w AS decade_start_year,
        FIRST_VALUE(f.renewables_energy_twh) OVER w AS start_renewables_energy_twh,
        f.renewables_energy_twh AS end_renewables_energy_twh,
        COUNT(*) OVER w AS points_in_window
    FROM analytics.fact_energy_metrics AS f
    JOIN analytics.dim_country AS d ON d.entity_code = f.entity_code
    WHERE d.entity_type = 'country' AND f.renewables_energy_twh IS NOT NULL
    WINDOW w AS (
        PARTITION BY f.entity_code ORDER BY f.year
        ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
    )
), latest_complete_decade AS (
    SELECT DISTINCT ON (entity_code) *
    FROM points
    WHERE points_in_window = 10 AND decade_end_year - decade_start_year = 9
    ORDER BY entity_code, decade_end_year DESC
)
SELECT
    country_code,
    country_name,
    decade_start_year,
    decade_end_year,
    start_renewables_energy_twh,
    end_renewables_energy_twh,
    (end_renewables_energy_twh - start_renewables_energy_twh) * 100.0
        / NULLIF(start_renewables_energy_twh, 0) AS decade_growth_pct
FROM latest_complete_decade
WHERE start_renewables_energy_twh > 0
ORDER BY decade_growth_pct DESC;

CREATE OR REPLACE VIEW analytics.v_energy_co2_by_country_year AS
SELECT
    d.iso_code AS country_code,
    d.country_name,
    f.year,
    f.total_energy_per_capita_kwh,
    f.electricity_co2e_per_capita_tonnes
FROM analytics.fact_energy_metrics AS f
JOIN analytics.dim_country AS d ON d.entity_code = f.entity_code
WHERE d.entity_type = 'country'
  AND f.total_energy_per_capita_kwh IS NOT NULL
  AND f.electricity_co2e_per_capita_tonnes IS NOT NULL;

CREATE OR REPLACE VIEW analytics.v_energy_co2_correlation_by_year AS
SELECT
    year,
    COUNT(*) AS country_count,
    CORR(total_energy_per_capita_kwh, electricity_co2e_per_capita_tonnes)
        AS energy_electricity_co2e_correlation
FROM analytics.v_energy_co2_by_country_year
GROUP BY year
ORDER BY year;

CREATE OR REPLACE VIEW analytics.v_fossil_vs_low_carbon_mix AS
SELECT
    d.iso_code AS country_code,
    d.country_name,
    f.year,
    f.total_energy_twh,
    f.fossil_fuels_energy_share_pct,
    f.low_carbon_energy_share_pct,
    f.renewables_energy_share_pct
FROM analytics.fact_energy_metrics AS f
JOIN analytics.dim_country AS d ON d.entity_code = f.entity_code
WHERE d.entity_type = 'country'
  AND (f.fossil_fuels_energy_share_pct IS NOT NULL OR f.low_carbon_energy_share_pct IS NOT NULL);
