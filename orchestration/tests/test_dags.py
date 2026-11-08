"""Contrato do DAG, sem banco, ingestão externa ou escrita no lake."""
import unittest

from airflow.dag_processing.dagbag import DagBag


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
        self.assertEqual(dag.schedule, "0 6 * * *")
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


if __name__ == "__main__":
    unittest.main()
