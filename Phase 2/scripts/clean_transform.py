"""Clean the Phase 2 raw OWID snapshot and load relational Phase 3 tables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

METRIC_COLUMNS = (
    "renewables_energy_twh",
    "renewables_energy_share_pct",
    "fossil_fuels_energy_share_pct",
    "low_carbon_energy_share_pct",
    "total_energy_twh",
    "total_energy_per_capita_kwh",
    "electricity_co2e_per_capita_tonnes",
)
PERCENT_COLUMNS = frozenset(
    {"renewables_energy_share_pct", "fossil_fuels_energy_share_pct", "low_carbon_energy_share_pct"}
)
SOURCE_MEASURE_COLUMNS = frozenset(
    {
        "renewables_energy_twh",
        "renewables_energy_share_pct",
        "fossil_fuels_energy_share_pct",
        "low_carbon_energy_share_pct",
        "total_energy_twh",
        "total_energy_per_capita_kwh",
        "population",
        "electricity_emissions_mtco2eq",
    }
)
REQUIRED_COLUMNS = frozenset({"country", "iso_code", "year", *SOURCE_MEASURE_COLUMNS})
MAX_METRIC_NULL_PCT = Decimal("85")
MIN_VALID_YEAR = 1700
MAX_VALID_YEAR = 2100
RAW_FILE = Path(os.getenv("RAW_DATA_DIR", "/data/raw")) / "owid_energy.csv"
_DEFAULT_SQL_DIR = Path(__file__).resolve().parent / "sql"
if not _DEFAULT_SQL_DIR.exists():
    _DEFAULT_SQL_DIR = _DEFAULT_SQL_DIR.parent / "sql"
SQL_DIR = Path(os.getenv("SQL_DIR", str(_DEFAULT_SQL_DIR)))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logging.Formatter.converter = time.gmtime
logger = logging.getLogger("phase3.cleaning")


class InputValidationError(ValueError):
    """Raised when the raw input cannot safely be represented in the clean layer."""


class QualityCheckError(RuntimeError):
    """Raised when one or more post-load SQL quality checks fail."""

    def __init__(self, checks: list[tuple[str, str, str]]) -> None:
        self.checks = checks
        failed = [f"{name}: {details}" for name, status, details in checks if status == "FAIL"]
        super().__init__("; ".join(failed) or "Post-load quality checks failed")


class DemoRollback(Exception):
    """Internal signal used to roll back the intentional bad-data demo."""


def _parse_decimal(value: str | None, column: str, row_number: int) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise InputValidationError(
            f"row {row_number}: {column} is not numeric: {text!r}"
        ) from exc
    if not parsed.is_finite():
        raise InputValidationError(f"row {row_number}: {column} must be a finite number")
    if column in PERCENT_COLUMNS and not Decimal("0") <= parsed <= Decimal("100"):
        raise InputValidationError(
            f"row {row_number}: {column} must be between 0 and 100; got {parsed}"
        )
    if column not in PERCENT_COLUMNS and parsed < 0:
        raise InputValidationError(f"row {row_number}: {column} cannot be negative; got {parsed}")
    return parsed


def _entity_identity(country: str, iso_code: str | None, row_number: int) -> tuple[str, str | None, str]:
    code = (iso_code or "").strip().upper() or None
    if code and not re.fullmatch(r"[A-Z0-9_-]{1,32}", code):
        raise InputValidationError(f"row {row_number}: invalid iso_code value {code!r}")
    if code:
        entity_code = code
    else:
        digest = hashlib.sha256(country.casefold().encode("utf-8")).hexdigest()[:16].upper()
        entity_code = f"NOISO_{digest}"

    if code and re.fullmatch(r"[A-Z]{3}", code):
        entity_type = "country"
    elif code and code.startswith("OWID_"):
        entity_type = "aggregate"
    else:
        entity_type = "other"
    return entity_code, code, entity_type


def transform_rows(
    rows: Iterable[tuple[int, Mapping[str | None, str | None]]],
    fieldnames: list[str] | None,
    source_run_id: UUID | str,
) -> tuple[dict[str, dict[str, str | None]], list[dict[str, object]], int]:
    """Validate and normalize CSV rows while preserving missing indicators as NULL."""
    if not fieldnames:
        raise InputValidationError("CSV header is empty")
    if len(fieldnames) != len(set(fieldnames)):
        raise InputValidationError("CSV header contains duplicate column names")
    missing = sorted(REQUIRED_COLUMNS - set(fieldnames))
    if missing:
        raise InputValidationError(f"CSV is missing required columns: {', '.join(missing)}")

    entities: dict[str, dict[str, str | None]] = {}
    facts_by_key: dict[tuple[str, int], dict[str, object]] = {}
    seen_rows: set[str] = set()
    duplicate_rows = 0

    for row_number, row in rows:
        if None in row:
            raise InputValidationError(f"row {row_number}: row has more fields than the CSV header")
        canonical = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if canonical in seen_rows:
            duplicate_rows += 1
            continue
        seen_rows.add(canonical)

        country = (row.get("country") or "").strip()
        if not country:
            raise InputValidationError(f"row {row_number}: country is required")
        year_text = (row.get("year") or "").strip()
        try:
            year = int(year_text)
        except ValueError as exc:
            raise InputValidationError(f"row {row_number}: year must be an integer; got {year_text!r}") from exc
        if not MIN_VALID_YEAR <= year <= MAX_VALID_YEAR:
            raise InputValidationError(
                f"row {row_number}: year must be between {MIN_VALID_YEAR} and {MAX_VALID_YEAR}; got {year}"
            )

        entity_code, iso_code, entity_type = _entity_identity(country, row.get("iso_code"), row_number)
        entity = {
            "entity_code": entity_code,
            "iso_code": iso_code,
            "country_name": country,
            "entity_type": entity_type,
        }
        existing_entity = entities.get(entity_code)
        if existing_entity and existing_entity["country_name"] != country:
            raise InputValidationError(
                f"row {row_number}: code {entity_code!r} maps to multiple entity names"
            )
        entities[entity_code] = entity

        fact: dict[str, object] = {
            "entity_code": entity_code,
            "year": year,
            "source_run_id": source_run_id,
            "source_row_number": row_number,
        }
        for column in METRIC_COLUMNS[:-1]:
            fact[column] = _parse_decimal(row.get(column), column, row_number)
        population = _parse_decimal(row.get("population"), "population", row_number)
        electricity_emissions = _parse_decimal(
            row.get("electricity_emissions_mtco2eq"), "electricity_emissions_mtco2eq", row_number
        )
        if population is not None and population > 0 and electricity_emissions is not None:
            fact["electricity_co2e_per_capita_tonnes"] = (
                electricity_emissions * Decimal("1000000") / population
            )
        else:
            fact["electricity_co2e_per_capita_tonnes"] = None

        natural_key = (entity_code, year)
        if natural_key in facts_by_key:
            previous = facts_by_key[natural_key]
            raise InputValidationError(
                f"row {row_number}: conflicting duplicate key ({entity_code}, {year}); "
                f"first seen on source row {previous['source_row_number']}"
            )
        facts_by_key[natural_key] = fact

    if not facts_by_key:
        raise InputValidationError("CSV contains no usable data rows")
    return entities, list(facts_by_key.values()), duplicate_rows


def validate_null_thresholds(facts: list[dict[str, object]]) -> None:
    total = len(facts)
    for column in METRIC_COLUMNS:
        missing = sum(fact[column] is None for fact in facts)
        missing_pct = Decimal(missing) * Decimal("100") / Decimal(total)
        if missing_pct > MAX_METRIC_NULL_PCT:
            raise InputValidationError(
                f"{column} missingness is {missing_pct:.2f}% ({missing}/{total}); "
                f"threshold is {MAX_METRIC_NULL_PCT}%"
            )


def read_raw_csv(path: Path) -> tuple[list[str] | None, list[tuple[int, dict[str | None, str | None]]]]:
    if not path.is_file():
        raise InputValidationError(f"raw CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = [(row_number, row) for row_number, row in enumerate(reader, start=1)]
    return fieldnames, rows


def _quality_sql() -> str:
    path = SQL_DIR / "quality_checks.sql"
    if not path.is_file():
        raise InputValidationError(f"quality SQL file not found: {path}")
    return path.read_text(encoding="utf-8")


def _checks_as_tuples(rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    return [(str(name), str(status), str(details)) for name, status, details in rows]


def _assert_quality_passed(checks: list[tuple[str, str, str]]) -> None:
    if any(status != "PASS" for _, status, _ in checks):
        raise QualityCheckError(checks)


def _persist_failure(
    database_url: str,
    cleaning_run_id: UUID | None,
    checks: list[tuple[str, str, str]],
    error: Exception,
) -> None:
    if cleaning_run_id is None:
        return
    try:
        import psycopg

        if not checks:
            checks = [("preload_validation", "FAIL", str(error)[:2000])]
        with psycopg.connect(database_url) as conn:
            conn.execute(
                """UPDATE analytics.cleaning_runs
                   SET status='failed', finished_at=%s, error=%s
                   WHERE cleaning_run_id=%s""",
                (datetime.now(timezone.utc), str(error)[:2000], cleaning_run_id),
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO analytics.data_quality_log
                       (cleaning_run_id, check_name, status, details, checked_at)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (cleaning_run_id, check_name) DO UPDATE
                       SET status=EXCLUDED.status, details=EXCLUDED.details, checked_at=EXCLUDED.checked_at""",
                    [
                        (cleaning_run_id, name, status, details[:2000], datetime.now(timezone.utc))
                        for name, status, details in checks
                    ],
                )
    except Exception:
        logger.exception("could_not_record_failed_cleaning_run run_id=%s", cleaning_run_id)


def run_pipeline() -> int:
    try:
        import psycopg
    except ImportError as exc:
        logger.error("psycopg is required; install dependencies from Phase 2/requirements.txt")
        return 1

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is required")
        return 1

    cleaning_run_id: UUID | None = None
    source_run_id: UUID | None = None
    failed_checks: list[tuple[str, str, str]] = []
    try:
        schema_sql_path = SQL_DIR / "clean_schema.sql"
        if not schema_sql_path.is_file():
            raise InputValidationError(f"schema SQL file not found: {schema_sql_path}")
        views_sql_path = SQL_DIR / "analytics_views.sql"
        if not views_sql_path.is_file():
            raise InputValidationError(f"analytics view SQL file not found: {views_sql_path}")
        with psycopg.connect(database_url) as conn:
            conn.execute(schema_sql_path.read_text(encoding="utf-8"), prepare=False)
            conn.commit()
            conn.execute(views_sql_path.read_text(encoding="utf-8"), prepare=False)
            conn.commit()
            source_run = conn.execute(
                """SELECT run_id, rows_fetched FROM raw.ingestion_runs
                   WHERE status='succeeded'
                   ORDER BY finished_at DESC NULLS LAST, started_at DESC LIMIT 1"""
            ).fetchone()
            if source_run is None:
                raise InputValidationError("no successful Phase 2 ingestion run exists in raw.ingestion_runs")
            source_run_id, recorded_rows = source_run
            db_raw_rows = conn.execute(
                "SELECT COUNT(*) FROM raw.energy_observations WHERE run_id=%s", (source_run_id,)
            ).fetchone()[0]
            if db_raw_rows != recorded_rows:
                raise InputValidationError(
                    f"raw database count mismatch: ingestion_runs={recorded_rows}, observations={db_raw_rows}"
                )

            cleaning_run_id = uuid4()
            conn.execute(
                """INSERT INTO analytics.cleaning_runs
                   (cleaning_run_id, source_ingestion_run_id, started_at, status)
                   VALUES (%s,%s,%s,'running')""",
                (cleaning_run_id, source_run_id, datetime.now(timezone.utc)),
            )

        fieldnames, rows = read_raw_csv(RAW_FILE)
        if len(rows) != recorded_rows:
            raise InputValidationError(
                f"raw CSV row count mismatch: file={len(rows)}, ingestion_runs={recorded_rows}"
            )
        entities, facts, duplicate_rows = transform_rows(rows, fieldnames, source_run_id)
        validate_null_thresholds(facts)
        if len(facts) != len(rows) - duplicate_rows:
            raise InputValidationError(
                f"row reconciliation failed: source={len(rows)}, duplicates={duplicate_rows}, clean={len(facts)}"
            )

        insert_entity_sql = """INSERT INTO analytics.dim_country
            (entity_code, iso_code, country_name, entity_type) VALUES (%s,%s,%s,%s)"""
        fact_columns = ("entity_code", "year", *METRIC_COLUMNS, "source_run_id", "source_row_number", "cleaning_run_id")
        fact_sql = "INSERT INTO analytics.fact_energy_metrics (" + ",".join(fact_columns) + ") VALUES (" + ",".join(["%s"] * len(fact_columns)) + ")"
        quality_sql = _quality_sql()

        with psycopg.connect(database_url) as conn:
            with conn.transaction():
                conn.execute("DELETE FROM analytics.fact_energy_metrics")
                conn.execute("DELETE FROM analytics.dim_country")
                with conn.cursor() as cursor:
                    cursor.executemany(
                        insert_entity_sql,
                        [
                            (entity["entity_code"], entity["iso_code"], entity["country_name"], entity["entity_type"])
                            for entity in entities.values()
                        ],
                    )
                    cursor.executemany(
                        fact_sql,
                        [tuple(fact[column] for column in fact_columns[:-1]) + (cleaning_run_id,) for fact in facts],
                    )
                conn.execute(
                    """UPDATE analytics.cleaning_runs SET raw_rows=%s, duplicate_rows=%s, cleaned_rows=%s
                       WHERE cleaning_run_id=%s""",
                    (len(rows), duplicate_rows, len(facts), cleaning_run_id),
                )
                failed_checks = _checks_as_tuples(conn.execute(quality_sql).fetchall())
                _assert_quality_passed(failed_checks)
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO analytics.data_quality_log
                           (cleaning_run_id, check_name, status, details, checked_at)
                           VALUES (%s,%s,%s,%s,%s)""",
                        [
                            (cleaning_run_id, name, status, details[:2000], datetime.now(timezone.utc))
                            for name, status, details in failed_checks
                        ],
                    )
                conn.execute(
                    """UPDATE analytics.cleaning_runs SET status='succeeded', finished_at=%s, error=NULL
                       WHERE cleaning_run_id=%s""",
                    (datetime.now(timezone.utc), cleaning_run_id),
                )

        logger.info(
            "cleaning_status=succeeded run_id=%s source_run_id=%s raw_rows=%s exact_duplicates=%s cleaned_rows=%s",
            cleaning_run_id,
            source_run_id,
            len(rows),
            duplicate_rows,
            len(facts),
        )
        for name, status, details in failed_checks:
            logger.info("quality_check=%s status=%s details=%s", name, status, details)
        return 0
    except Exception as exc:
        if isinstance(exc, QualityCheckError):
            failed_checks = exc.checks
        logger.exception("cleaning_status=failed run_id=%s source_run_id=%s", cleaning_run_id, source_run_id)
        _persist_failure(database_url, cleaning_run_id, failed_checks, exc)
        return 1


def run_bad_data_demo() -> int:
    """Prove that the same SQL checks detect a bad value, then roll it back."""
    try:
        import psycopg
    except ImportError:
        logger.error("psycopg is required; install dependencies from Phase 2/requirements.txt")
        return 1
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is required")
        return 1

    try:
        with psycopg.connect(database_url) as conn:
            current = conn.execute(
                """SELECT cleaning_run_id FROM analytics.cleaning_runs
                   WHERE status='succeeded' ORDER BY started_at DESC LIMIT 1"""
            ).fetchone()
            if current is None:
                raise InputValidationError("run the clean pipeline successfully before the bad-data demo")
            run_id = current[0]
            target = conn.execute(
                """SELECT entity_code, year FROM analytics.fact_energy_metrics
                   WHERE cleaning_run_id=%s AND renewables_energy_twh IS NOT NULL
                   ORDER BY entity_code, year LIMIT 1""",
                (run_id,),
            ).fetchone()
            if target is None:
                raise InputValidationError("no renewable-consumption row is available for the demo")

            try:
                with conn.transaction():
                    conn.execute(
                        """UPDATE analytics.fact_energy_metrics SET renewables_energy_twh=-1
                           WHERE entity_code=%s AND year=%s AND cleaning_run_id=%s""",
                        (target[0], target[1], run_id),
                    )
                    checks = _checks_as_tuples(conn.execute(_quality_sql()).fetchall())
                    try:
                        _assert_quality_passed(checks)
                    except QualityCheckError as exc:
                        if not any(name == "numeric_ranges" for name, status, _ in exc.checks if status == "FAIL"):
                            raise
                        for name, status, details in exc.checks:
                            logger.info("bad_data_demo_check=%s status=%s details=%s", name, status, details)
                        raise DemoRollback
                    raise InputValidationError("bad-data demo failed: the SQL checks did not stop the bad row")
            except DemoRollback:
                pass
        logger.info(
            "bad_data_demo=passed injected_negative_value_was_detected=true transaction_rolled_back=true"
        )
        return 0
    except Exception:
        logger.exception("bad_data_demo=failed")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo-bad-data",
        action="store_true",
        help="inject a negative metric inside a transaction, run SQL checks, and roll it back",
    )
    args = parser.parse_args()
    return run_bad_data_demo() if args.demo_bad_data else run_pipeline()


if __name__ == "__main__":
    sys.exit(main())
