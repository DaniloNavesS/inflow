"""Base E3: origem -> lake -> freshness."""
from datetime import timedelta

import pendulum
from airflow.sdk import DAG, Param, task
from airflow.providers.standard.operators.bash import BashOperator


DEFAULT_ARGS = {
    "owner": "manu-yza",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(hours=2),
}


def lake_task():
    return BashOperator(
        task_id="materializar_lake",
        bash_command="exec /opt/inflow/analytics-venv/bin/python main.py lake",
        cwd="/opt/inflow/analytics",
        trigger_rule="none_failed_min_one_success",
        do_xcom_push=False,
    )


def freshness_task():
    return BashOperator(
        task_id="verificar_freshness",
        bash_command="exec /opt/inflow/analytics-venv/bin/python freshness.py",
        cwd="/opt/inflow/analytics",
        execution_timeout=timedelta(minutes=2),
        do_xcom_push=False,
    )


with DAG(
    dag_id="inflow_pipeline",
    description="Atualiza origem e lake; ainda não inclui dbt/SQLMesh.",
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Sao_Paulo"),
    schedule="0 6 * * *",
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    is_paused_upon_creation=True,
    default_args=DEFAULT_ARGS,
    params={
        "recarregar_origem": Param(True, type="boolean", description="False usa o OLTP já carregado."),
    },
    tags=["inflow", "e3"],
) as pipeline:

    @task.branch(task_id="escolher_origem")
    def escolher_origem(**context):
        return "ingerir_origem" if context["params"]["recarregar_origem"] else "materializar_lake"

    escolha = escolher_origem()
    ingestao = BashOperator(
        task_id="ingerir_origem",
        bash_command="exec /opt/inflow/ingestion-venv/bin/python main.py",
        cwd="/opt/inflow/ingestion",
        do_xcom_push=False,
    )
    lake = lake_task()
    freshness = freshness_task()
    escolha >> [ingestao, lake]
    ingestao >> lake >> freshness


# Independente: detecta atraso mesmo quando o pipeline principal não roda.
with DAG(
    dag_id="inflow_freshness",
    description="Verifica o SLA operacional do lake, sem materializar dados.",
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Sao_Paulo"),
    schedule="15 * * * *",
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    default_args=DEFAULT_ARGS,
    tags=["inflow", "monitoramento"],
) as freshness_monitor:
    freshness_task()
