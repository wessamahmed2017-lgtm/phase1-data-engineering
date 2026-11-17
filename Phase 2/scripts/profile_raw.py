"""Profile the preserved raw CSV without mutating it."""

import csv
import json
import os
from collections import Counter
from pathlib import Path

path = Path(os.getenv("RAW_DATA_DIR", "/data/raw")) / "owid_energy.csv"
with path.open("r", encoding="utf-8-sig", newline="") as stream:
    reader = csv.DictReader(stream)
    fields = reader.fieldnames or []
    missing = Counter()
    numeric_invalid = Counter()
    hashes = set()
    duplicate_rows = 0
    rows = 0
    checked_numeric = [c for c in fields if c in {"year", "population", "gdp"} or "energy" in c or "co2" in c]
    for row in reader:
        rows += 1
        canonical = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if canonical in hashes:
            duplicate_rows += 1
        hashes.add(canonical)
        for name, value in row.items():
            if value is None or not value.strip():
                missing[name] += 1
        for name in checked_numeric:
            value = row.get(name, "")
            if value and value.strip():
                try:
                    parsed = float(value)
                    if name == "year" and not parsed.is_integer():
                        raise ValueError("year must be an integer")
                except ValueError:
                    numeric_invalid[name] += 1

missing_columns = {k: v for k, v in missing.most_common()}
print(json.dumps({
    "file": str(path),
    "rows": rows,
    "columns": len(fields),
    "duplicate_full_rows": duplicate_rows,
    "columns_with_missing_values_count": len(missing_columns),
    "top_10_missing_columns": dict(list(missing_columns.items())[:10]),
    "identity_column_missing_values": {k: missing_columns.get(k, 0) for k in ("country", "iso_code", "year")},
    "invalid_numeric_values_in_checked_columns": dict(numeric_invalid),
    "checked_numeric_columns": checked_numeric,
}, indent=2))
