"""Download the pinned OWID Energy CSV, preserve it, and land every row as JSONB."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

SOURCE_URL = os.getenv(
    "OWID_CSV_URL",
    "https://catalog.ourworldindata.org/garden/energy/2026-09-10/owid_energy/owid_energy.csv",
)
RAW_DIR = Path(os.getenv("RAW_DATA_DIR", "/data/raw"))
RAW_FILE = RAW_DIR / "owid_energy.csv"
DATABASE_URL = os.environ["DATABASE_URL"]
INSERT_BATCH_SIZE = int(os.getenv("INSERT_BATCH_SIZE", "500"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logging.Formatter.converter = time.gmtime
logger = logging.getLogger("phase2.ingest")


def download_csv() -> tuple[int, str]:
    """Download with a timeout and atomically replace the raw snapshot."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    request = Request(SOURCE_URL, headers={"User-Agent": "phase2-energy-ingestion/1.0"})
    digest = hashlib.sha256()
    status = 0
    started = time.monotonic()
    temp_name: str | None = None
    try:
        with urlopen(request, timeout=60) as response:
            status = response.status
            if status != 200:
                raise RuntimeError(f"Source returned HTTP {status}")
            with tempfile.NamedTemporaryFile(dir=RAW_DIR, delete=False) as temp:
                temp_name = temp.name
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    temp.write(chunk)
        os.replace(temp_name, RAW_FILE)
        elapsed = time.monotonic() - started
        logger.info(
            "source_status=success http_status=%s bytes=%s sha256=%s elapsed_seconds=%.2f",
            status,
            RAW_FILE.stat().st_size,
            digest.hexdigest(),
            elapsed,
        )
        return status, digest.hexdigest()
    except HTTPError as exc:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
        logger.exception("source_status=failed http_status=%s url=%s", exc.code, SOURCE_URL)
        raise
    except (URLError, TimeoutError, OSError, RuntimeError):
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
        logger.exception("source_status=failed url=%s", SOURCE_URL)
        raise


def create_tables(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
        cur.execute(
            """CREATE TABLE IF NOT EXISTS raw.ingestion_runs (
                run_id UUID PRIMARY KEY,
                source_url TEXT NOT NULL,
                source_http_status INTEGER NOT NULL,
                source_sha256 TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ,
                status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
                rows_fetched BIGINT NOT NULL DEFAULT 0,
                error TEXT
            )"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS raw.energy_observations (
                run_id UUID NOT NULL REFERENCES raw.ingestion_runs(run_id),
                row_number BIGINT NOT NULL,
                source_row JSONB NOT NULL,
                PRIMARY KEY (run_id, row_number)
            )"""
        )
    conn.commit()


def ingest_csv(conn: psycopg.Connection, run_id) -> int:
    count = 0
    batch: list[tuple] = []
    with RAW_FILE.open("r", encoding="utf-8-sig", newline="") as source, conn.cursor() as cur:
        reader = csv.DictReader(source)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV header is empty or contains duplicate column names")
        for row in reader:
            count += 1
            # DictReader returns source values as text, preserving raw field values.
            batch.append((run_id, count, Jsonb(row)))
            if len(batch) >= INSERT_BATCH_SIZE:
                cur.executemany(
                    "INSERT INTO raw.energy_observations(run_id,row_number,source_row) VALUES (%s,%s,%s)",
                    batch,
                )
                conn.commit()
                batch.clear()
        if batch:
            cur.executemany(
                "INSERT INTO raw.energy_observations(run_id,row_number,source_row) VALUES (%s,%s,%s)",
                batch,
            )
            conn.commit()
    return count


def main() -> int:
    run_id = uuid4()
    started_at = datetime.now(timezone.utc)
    logger.info("ingestion_started run_id=%s source_url=%s", run_id, SOURCE_URL)
    http_status = 0
    sha256 = ""
    try:
        # Initialize the log tables and persist the run before contacting the source.
        with psycopg.connect(DATABASE_URL) as conn:
            create_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO raw.ingestion_runs
                       (run_id,source_url,source_http_status,source_sha256,started_at,status)
                       VALUES (%s,%s,0,'',%s,'running')""",
                    (run_id, SOURCE_URL, started_at),
                )
            conn.commit()

        http_status, sha256 = download_csv()
        with psycopg.connect(DATABASE_URL) as conn:
            rows = ingest_csv(conn, run_id)
            finished_at = datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE raw.ingestion_runs SET finished_at=%s,status='succeeded',rows_fetched=%s
                       WHERE run_id=%s""",
                    (finished_at, rows, run_id),
                )
            conn.commit()
        logger.info(
            "ingestion_status=succeeded run_id=%s started_at=%s finished_at=%s rows_fetched=%s raw_file=%s",
            run_id,
            started_at.isoformat(),
            finished_at.isoformat(),
            rows,
            RAW_FILE,
        )
        return 0
    except Exception as exc:
        if isinstance(exc, HTTPError):
            http_status = exc.code
        logger.exception("ingestion_status=failed run_id=%s", run_id)
        try:
            with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO raw.ingestion_runs
                       (run_id,source_url,source_http_status,source_sha256,started_at,finished_at,status,error)
                       VALUES (%s,%s,%s,%s,%s,%s,'failed',%s)
                       ON CONFLICT (run_id) DO UPDATE SET finished_at=EXCLUDED.finished_at,
                       status='failed', error=EXCLUDED.error""",
                    (run_id, SOURCE_URL, http_status, sha256, started_at, datetime.now(timezone.utc), str(exc)[:2000]),
                )
                conn.commit()
        except Exception:
            logger.exception("could_not_record_failed_run run_id=%s", run_id)
        return 1


if __name__ == "__main__":
    sys.exit(main())
