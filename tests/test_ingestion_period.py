"""Período de ingestão: o padrão anual é preservado e o intervalo é validado."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "ingestion" / "src"))

from config import resolve_ingestion_years  # noqa: E402


class IngestionPeriodTests(unittest.TestCase):
    def test_default_keeps_single_configured_year(self):
        self.assertEqual(resolve_ingestion_years({}), (2024,))
        self.assertEqual(resolve_ingestion_years({"INGESTION_YEAR": "2023"}), (2023,))

    def test_explicit_interval_is_inclusive(self):
        env = {"INGESTION_START_YEAR": "2022", "INGESTION_END_YEAR": "2024"}
        self.assertEqual(resolve_ingestion_years(env), (2022, 2023, 2024))

    def test_one_bound_alone_selects_that_year(self):
        self.assertEqual(resolve_ingestion_years({"INGESTION_START_YEAR": "2021"}), (2021,))
        self.assertEqual(resolve_ingestion_years({"INGESTION_END_YEAR": "2021"}), (2021,))

    def test_interval_overrides_ingestion_year(self):
        env = {"INGESTION_YEAR": "2024", "INGESTION_START_YEAR": "2020", "INGESTION_END_YEAR": "2021"}
        self.assertEqual(resolve_ingestion_years(env), (2020, 2021))

    def test_blank_values_are_ignored(self):
        env = {"INGESTION_START_YEAR": "", "INGESTION_END_YEAR": " ", "INGESTION_YEAR": "2023"}
        self.assertEqual(resolve_ingestion_years(env), (2023,))

    def test_rejects_inverted_interval(self):
        env = {"INGESTION_START_YEAR": "2024", "INGESTION_END_YEAR": "2022"}
        with self.assertRaises(ValueError):
            resolve_ingestion_years(env)

    def test_rejects_non_integer_and_oversized_period(self):
        with self.assertRaises(ValueError):
            resolve_ingestion_years({"INGESTION_START_YEAR": "2024-01"})
        with self.assertRaises(ValueError):
            resolve_ingestion_years({"INGESTION_START_YEAR": "2000", "INGESTION_END_YEAR": "2024"})


if __name__ == "__main__":
    unittest.main()
