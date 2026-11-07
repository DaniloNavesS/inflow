"""Também executável com unittest, sem Docker ou dependências de terceiros."""
import importlib.util
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


SOURCE = Path(__file__).resolve().parents[2] / "analytics/src/freshness.py"
if not SOURCE.exists():  # Imagem analytics: código em /app/src, testes em /tests.
    SOURCE = Path("/app/src/freshness.py")
spec = importlib.util.spec_from_file_location("lake_freshness", SOURCE)
freshness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freshness)


class FreshnessTests(unittest.TestCase):
    now = datetime(2026, 11, 7, 15, tzinfo=timezone.utc)

    def evaluate(self, timestamp, sla=24):
        return freshness.evaluate(timestamp, now=self.now, sla_hours=sla)

    def test_boundary_is_fresh_but_one_second_late_fails(self):
        self.assertEqual(self.evaluate(self.now - timedelta(hours=24))["status"], "fresh")
        late = self.evaluate(self.now - timedelta(hours=24, seconds=1))
        self.assertEqual(late["status"], "stale")
        self.assertEqual(late["age_seconds"], 86401)

    def test_no_success_is_not_fresh(self):
        report = self.evaluate(None)
        self.assertEqual(report["status"], "missing")
        self.assertIsNone(report["age_seconds"])

    def test_future_timestamp_is_not_fresh(self):
        self.assertEqual(self.evaluate(self.now + timedelta(seconds=1))["status"],
                         "invalid_timestamp")

    def test_timezones_represent_same_instant(self):
        local = self.now.astimezone(timezone(timedelta(hours=-3)))
        self.assertEqual(self.evaluate(local)["age_seconds"], 0)

    def test_invalid_sla_is_rejected(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(sla=value), self.assertRaises(ValueError):
                self.evaluate(self.now, value)

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate(self.now.replace(tzinfo=None))

    def test_database_clock_is_used(self):
        db = MagicMock()
        db.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            self.now - timedelta(hours=2), self.now,
        )
        report = freshness.check_database(db, 24)
        self.assertEqual(report["age_seconds"], 7200)
        self.assertEqual(report["status"], "fresh")


if __name__ == "__main__":
    unittest.main()
