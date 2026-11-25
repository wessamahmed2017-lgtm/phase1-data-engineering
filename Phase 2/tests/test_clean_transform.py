"""Unit tests for Phase 3 raw-to-clean validation, with no database required."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from clean_transform import (  # noqa: E402
    InputValidationError,
    REQUIRED_COLUMNS,
    transform_rows,
    validate_null_thresholds,
)


SOURCE_RUN_ID = UUID("00000000-0000-0000-0000-000000000001")


def sample_row(**overrides: str) -> dict[str, str]:
    row = {column: "" for column in REQUIRED_COLUMNS}
    row.update(
        {
            "country": "Exampleland",
            "iso_code": "EXM",
            "year": "2020",
            "renewables_energy_twh": "12.5",
            "renewables_energy_share_pct": "25.0",
            "fossil_fuels_energy_share_pct": "60.0",
            "low_carbon_energy_share_pct": "40.0",
            "total_energy_twh": "100.0",
            "total_energy_per_capita_kwh": "1500.0",
            "population": "2000000",
            "electricity_emissions_mtco2eq": "6.5",
        }
    )
    row.update(overrides)
    return row


class TransformRowsTests(unittest.TestCase):
    def transform(self, rows: list[dict[str, str]]):
        return transform_rows(
            [(number, row) for number, row in enumerate(rows, start=1)],
            list(rows[0]) if rows else list(REQUIRED_COLUMNS),
            SOURCE_RUN_ID,
        )

    def test_valid_row_is_typed_and_keeps_entity_relationship(self) -> None:
        entities, facts, duplicates = self.transform([sample_row()])
        self.assertEqual(duplicates, 0)
        self.assertEqual(entities["EXM"]["country_name"], "Exampleland")
        self.assertEqual(facts[0]["year"], 2020)
        self.assertEqual(str(facts[0]["renewables_energy_twh"]), "12.5")
        self.assertEqual(str(facts[0]["electricity_co2e_per_capita_tonnes"]), "3.25")
        self.assertEqual(facts[0]["source_row_number"], 1)

    def test_exact_duplicate_rows_are_counted_and_removed(self) -> None:
        entities, facts, duplicates = self.transform([sample_row(), sample_row()])
        self.assertEqual(len(entities), 1)
        self.assertEqual(len(facts), 1)
        self.assertEqual(duplicates, 1)

    def test_missing_iso_code_gets_stable_entity_key(self) -> None:
        first = sample_row(iso_code="")
        second = sample_row(iso_code="")
        first_entities, _, _ = self.transform([first])
        second_entities, _, _ = self.transform([second])
        first_key = next(iter(first_entities))
        self.assertEqual(first_key, next(iter(second_entities)))
        self.assertTrue(first_key.startswith("NOISO_"))
        self.assertEqual(first_entities[first_key]["entity_type"], "other")

    def test_conflicting_entity_year_key_fails(self) -> None:
        with self.assertRaisesRegex(InputValidationError, "conflicting duplicate key"):
            self.transform([sample_row(), sample_row(renewables_energy_twh="13.0")])

    def test_negative_energy_value_fails(self) -> None:
        with self.assertRaisesRegex(InputValidationError, "cannot be negative"):
            self.transform([sample_row(renewables_energy_twh="-1")])

    def test_share_above_one_hundred_fails(self) -> None:
        with self.assertRaisesRegex(InputValidationError, "between 0 and 100"):
            self.transform([sample_row(fossil_fuels_energy_share_pct="101")])

    def test_missing_required_header_fails(self) -> None:
        row = sample_row()
        del row["country"]
        with self.assertRaisesRegex(InputValidationError, "missing required columns"):
            transform_rows([(1, row)], list(row), SOURCE_RUN_ID)

    def test_measure_null_threshold_fails(self) -> None:
        _, facts, _ = self.transform([sample_row(total_energy_twh="")])
        with self.assertRaisesRegex(InputValidationError, "total_energy_twh missingness"):
            validate_null_thresholds(facts)


if __name__ == "__main__":
    unittest.main()
