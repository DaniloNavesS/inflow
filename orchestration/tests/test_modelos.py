"""Wrapper do dbt: registra sucesso ou falha em pipeline_runs, sem banco real."""
import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

PATH = os.getenv("INFLOW_MODELOS_PATH", "/opt/inflow/orchestration/modelos.py")


def load():
    spec = importlib.util.spec_from_file_location("modelos", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModelosTests(unittest.TestCase):
    def setUp(self):
        self.modelos = load()
        self.calls = []
        fake_metrics = SimpleNamespace(
            start_pipeline=lambda db, name: self.calls.append(("start", name)) or "run-1",
            finish_pipeline=lambda db, run_id, d: self.calls.append(("finish", run_id)),
            fail_pipeline=lambda db, run_id, d, msg: self.calls.append(("fail", run_id, msg)),
        )
        patches = [
            mock.patch.dict(sys.modules, {"monitoring.metrics": fake_metrics,
                                          "monitoring": SimpleNamespace(metrics=fake_metrics)}),
            mock.patch.object(self.modelos, "connect", return_value=mock.MagicMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_with(self, **subprocess_kwargs):
        with mock.patch.object(self.modelos.subprocess, "run", **subprocess_kwargs) as run:
            return self.modelos.main([]), run

    def test_success_records_dbt_models_pipeline_and_runs_build(self):
        code, run = self.run_with(return_value=SimpleNamespace(returncode=0))
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0][1:], ["build"])
        self.assertEqual(self.calls, [("start", "dbt_models"), ("finish", "run-1")])

    def test_dbt_failure_is_recorded_and_propagated(self):
        code, _ = self.run_with(return_value=SimpleNamespace(returncode=1))
        self.assertEqual(code, 1)
        self.assertEqual(self.calls[-1], ("fail", "run-1", "dbt build terminou com código 1"))

    def test_missing_dbt_binary_fails_without_disclosing_details(self):
        code, _ = self.run_with(side_effect=FileNotFoundError("/segredo/dbt"))
        self.assertEqual(code, 1)
        self.assertEqual(self.calls[-1], ("fail", "run-1", "dbt não executou: FileNotFoundError"))


if __name__ == "__main__":
    unittest.main()
