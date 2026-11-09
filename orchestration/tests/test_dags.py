"""Contrato do DAG, sem banco, ingestão externa ou escrita no lake."""
import unittest
import json
import os
from types import SimpleNamespace

from airflow.dag_processing.dagbag import DagBag
from airflow.sdk.definitions.param import NOTSET


class DagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bag = DagBag(dag_folder="/opt/airflow/dags")

    def test_imports(self):
        self.assertEqual(self.bag.import_errors, {})
        self.assertEqual(set(self.bag.dags), {"inflow_pipeline", "inflow_freshness", "inflow_backfill"})

    def test_dependencies_and_failure_blocking(self):
        dag = self.bag.dags["inflow_pipeline"]
        self.assertEqual(dag.get_task("ingerir_origem").downstream_task_ids, {"materializar_lake"})
        self.assertEqual(dag.get_task("materializar_lake").downstream_task_ids, {"verificar_freshness"})
        self.assertEqual(dag.get_task("materializar_lake").trigger_rule, "none_failed_min_one_success")
        self.assertEqual(dag.get_task("verificar_freshness").trigger_rule, "all_success")

    def test_schedule_and_no_automatic_backfill(self):
        dag = self.bag.dags["inflow_pipeline"]
        self.assertEqual(dag.schedule, os.getenv("INFLOW_PIPELINE_SCHEDULE", "0 6 * * *"))
        self.assertEqual(dag.timezone.name, "America/Sao_Paulo")
        self.assertFalse(dag.catchup)
        self.assertEqual(dag.max_active_runs, 1)

    def test_retry_and_timeout_on_external_work(self):
        for name in ("ingerir_origem", "materializar_lake", "verificar_freshness"):
            task = self.bag.dags["inflow_pipeline"].get_task(name)
            self.assertEqual(task.retries, 2)
            self.assertEqual(task.retry_delay.total_seconds(), 60)
            self.assertGreater(task.execution_timeout.total_seconds(), 0)

    def test_freshness_has_independent_schedule(self):
        dag = self.bag.dags["inflow_freshness"]
        self.assertEqual(dag.schedule, "15 * * * *")
        self.assertEqual(set(dag.task_ids), {"verificar_freshness"})

    def test_backfill_is_manual_with_required_interval(self):
        dag = self.bag.dags["inflow_backfill"]
        self.assertIsNone(dag.schedule)
        self.assertFalse(dag.catchup)
        self.assertEqual(dag.max_active_runs, 1)
        for name in ("ano_inicio", "ano_fim"):
            self.assertIs(dag.params.get_param(name).value, NOTSET)

    def test_backfill_dependencies_and_failure_blocking(self):
        dag = self.bag.dags["inflow_backfill"]
        self.assertEqual(dag.get_task("validar_periodo").downstream_task_ids, {"ingerir_origem"})
        self.assertEqual(dag.get_task("ingerir_origem").downstream_task_ids, {"materializar_lake"})
        self.assertEqual(dag.get_task("materializar_lake").downstream_task_ids, {"verificar_freshness"})
        for name in ("ingerir_origem", "materializar_lake", "verificar_freshness"):
            self.assertEqual(dag.get_task(name).trigger_rule, "all_success")

    def test_backfill_passes_interval_to_ingestion_without_losing_environment(self):
        task = self.bag.dags["inflow_backfill"].get_task("ingerir_origem")
        self.assertEqual(task.env["INGESTION_START_YEAR"], "{{ params.ano_inicio }}")
        self.assertEqual(task.env["INGESTION_END_YEAR"], "{{ params.ano_fim }}")
        self.assertTrue(task.append_env)

    def test_backfill_validates_interval_before_touching_the_source(self):
        check = self.bag.dags["inflow_backfill"].get_task("validar_periodo").python_callable
        check(params={"ano_inicio": 2023, "ano_fim": 2024})
        with self.assertRaises(ValueError):
            check(params={"ano_inicio": 2024, "ano_fim": 2023})
        with self.assertRaises(ValueError):
            check(params={"ano_inicio": 2000, "ano_fim": 2024})

    def test_loads_share_one_slot_pool(self):
        for dag_id, names in (
            ("inflow_pipeline", ("ingerir_origem", "materializar_lake")),
            ("inflow_backfill", ("ingerir_origem", "materializar_lake")),
        ):
            for name in names:
                self.assertEqual(self.bag.dags[dag_id].get_task(name).pool, "inflow_exclusivo")

    def test_failure_callback_does_not_disclose_exception_or_context_secrets(self):
        task = self.bag.dags["inflow_pipeline"].get_task("materializar_lake")
        ti = SimpleNamespace(dag_id="inflow_pipeline", task_id=task.task_id,
                             run_id="test-failure", try_number=3)
        with self.assertLogs("inflow.orchestration", level="ERROR") as captured:
            for callback in task.on_failure_callback:
                callback({"task_instance": ti,
                          "exception": RuntimeError("password=segredo"),
                          "DB_PASSWORD": "segredo"})
        payload = json.loads(captured.records[0].getMessage())
        self.assertEqual(payload["event"], "task_failed")
        self.assertEqual(payload["attempt"], 3)
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertNotIn("segredo", captured.records[0].getMessage())

    def test_retry_callback_and_failure_callback_cover_every_dag(self):
        for dag in self.bag.dags.values():
            for task in dag.tasks:
                self.assertTrue(task.on_failure_callback)
                self.assertTrue(task.on_retry_callback)
                self.assertTrue(all(callable(cb) for cb in task.on_failure_callback))
                self.assertTrue(all(callable(cb) for cb in task.on_retry_callback))

    def test_failure_callback_accepts_missing_exception(self):
        callbacks = self.bag.dags["inflow_freshness"].get_task("verificar_freshness").on_failure_callback
        with self.assertLogs("inflow.orchestration", level="ERROR") as captured:
            for callback in callbacks:
                callback({})
        self.assertEqual(json.loads(captured.records[0].getMessage())["error_type"], "UnknownError")


if __name__ == "__main__":
    unittest.main()
