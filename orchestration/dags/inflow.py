"""Base E3: origem -> lake -> freshness."""
from datetime import timedelta
import json
import logging
import os

import pendulum
from airflow.sdk import DAG, Param, task
from airflow.providers.standard.operators.bash import BashOperator


def log_task_event(context, event):
    """Somente metadados permitidos: não serializa contexto ou texto da exceção."""
    ti = context.get("task_instance") or context.get("ti")
    error = context.get("exception")
    payload = {
        "event": event,
        "dag_id": getattr(ti, "dag_id", None),
        "task_id": getattr(ti, "task_id", None),
        "run_id": getattr(ti, "run_id", None),
        "attempt": getattr(ti, "try_number", None),
        "error_type": type(error).__name__ if error is not None else "UnknownError",
    }
    logging.getLogger("inflow.orchestration").error(json.dumps(payload, ensure_ascii=False))


def on_task_failure(context):
    log_task_event(context, "task_failed")


def on_task_retry(context):
    log_task_event(context, "task_retry")


DEFAULT_ARGS = {
    "owner": "manu-yza",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(hours=2),
    "on_failure_callback": on_task_failure,
    "on_retry_callback": on_task_retry,
}


# Um slot serializa tarefas de escrita; não trava um DAG inteiro entre tarefas.
EXCLUSIVE_POOL = "inflow_exclusivo"
MAX_BACKFILL_YEARS = 10


def ingestion_task(env=None):
    return BashOperator(
        task_id="ingerir_origem",
        bash_command="exec /opt/inflow/ingestion-venv/bin/python main.py",
        cwd="/opt/inflow/ingestion",
        env=env,
        append_env=True,
        pool=EXCLUSIVE_POOL,
        do_xcom_push=False,
    )


def lake_task(trigger_rule="none_failed_min_one_success"):
    return BashOperator(
        task_id="materializar_lake",
        bash_command="exec /opt/inflow/analytics-venv/bin/python main.py lake",
        cwd="/opt/inflow/analytics",
        trigger_rule=trigger_rule,
        pool=EXCLUSIVE_POOL,
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
    description="Atualiza origem e lake; integração dbt pendente dos modelos.",
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Sao_Paulo"),
    schedule=os.getenv("INFLOW_PIPELINE_SCHEDULE", "0 6 * * *"),
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
    ingestao = ingestion_task()
    lake = lake_task()
    freshness = freshness_task()
    escolha >> [ingestao, lake]
    ingestao >> lake >> freshness


def validar_periodo(ano_inicio, ano_fim):
    """Falha cedo, antes de tocar na origem, se o intervalo for inválido."""
    if ano_inicio > ano_fim:
        raise ValueError(f"ano_inicio ({ano_inicio}) é posterior a ano_fim ({ano_fim}).")
    if ano_fim - ano_inicio + 1 > MAX_BACKFILL_YEARS:
        raise ValueError(f"O backfill aceita no máximo {MAX_BACKFILL_YEARS} anos por execução.")


# Backfill manual: a fonte (CEAPS) é anual, então o intervalo é de anos. Reprocessa a
# origem (upsert por id, idempotente) e rematerializa o lake COMPLETO; nunca envia um
# recorte a merge_snapshot, que trata ausências como exclusões.
with DAG(
    dag_id="inflow_backfill",
    description="Reprocessa um intervalo explícito de anos e rematerializa o lake.",
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Sao_Paulo"),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    is_paused_upon_creation=True,
    default_args=DEFAULT_ARGS,
    params={
        "ano_inicio": Param(type="integer", minimum=2000, maximum=2100, description="Primeiro ano (inclusive)."),
        "ano_fim": Param(type="integer", minimum=2000, maximum=2100, description="Último ano (inclusive)."),
    },
    tags=["inflow", "e3", "backfill"],
) as backfill:

    @task(task_id="validar_periodo")
    def validar(**context):
        params = context["params"]
        validar_periodo(int(params["ano_inicio"]), int(params["ano_fim"]))

    reingestao = ingestion_task(env={
        "INGESTION_START_YEAR": "{{ params.ano_inicio }}",
        "INGESTION_END_YEAR": "{{ params.ano_fim }}",
    })
    validar() >> reingestao >> lake_task(trigger_rule="all_success") >> freshness_task()


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
