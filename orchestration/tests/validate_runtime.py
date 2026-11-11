"""Evidências reais no projeto Docker isolado inflow-e3-validation.

Não usa mocks. Retry/exhausted desligam SOMENTE seu postgres de validação.
Backfill consulta as fontes reais e pode demorar. Executar na máquina host.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-p", "inflow-e3-validation", "-f", "docker-compose.yml",
           "-f", "orchestration/tests/compose.validation.yml"]
EVIDENCE = ROOT / "resultados/e3-orquestracao"


def command(*args, check=True):
    result = subprocess.run(COMPOSE + list(args), cwd=ROOT, text=True, encoding="utf-8",
                            errors="replace", capture_output=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result


def metadata(query):
    result = command("exec", "-T", "airflow-db", "psql", "-U", "airflow", "-d", "airflow",
                     "-At", "-v", "ON_ERROR_STOP=1", "-c", query)
    return json.loads(result.stdout.strip())


def snapshot():
    code = '''
import json, os, psycopg2, pyarrow.compute as pc
from deltalake import DeltaTable
db = psycopg2.connect(host=os.environ['DB_HOST'], dbname=os.environ['DB_NAME'],
                     user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'])
with db.cursor() as c:
    c.execute('SELECT count(*), count(DISTINCT id), coalesce(sum(valor),0) FROM oltp.despesas')
    rows, ids, total = c.fetchone()
models = None
with db.cursor() as c:
    c.execute("SELECT to_regclass('analytics_marts.fct_despesas') IS NOT NULL")
    if c.fetchone()[0]:
        c.execute('SELECT count(*), coalesce(sum(valor),0) FROM analytics_marts.fct_despesas')
        model_rows, model_total = c.fetchone()
        models = {'rows': model_rows, 'sum': str(model_total)}
report = {'postgres': {'rows': rows, 'unique_ids': ids, 'sum': str(total)}, 'fct_despesas': models}
if DeltaTable.is_deltatable('/lake/delta/despesas'):
    table = DeltaTable('/lake/delta/despesas').to_pyarrow_table()
    report['delta'] = {'rows': table.num_rows, 'unique_ids': len(pc.unique(table['id'])),
                       'sum': str(pc.sum(table['valor']).as_py() or 0)}
else:
    report['delta'] = None
db.close()
print(json.dumps(report))
'''
    return json.loads(command("exec", "-T", "airflow", "/opt/inflow/analytics-venv/bin/python",
                              "-c", code).stdout)


def validate(scenario, start_year, end_year, expect_unchanged=False):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}-{scenario}"
    report = {"scenario": scenario, "started_at": datetime.now(timezone.utc).isoformat()}
    dag = "inflow_backfill" if scenario == "backfill" else "inflow_pipeline"
    params = ({"ano_inicio": start_year, "ano_fim": end_year}
              if scenario == "backfill" else {"recarregar_origem": False})
    baseline = metadata("SELECT coalesce(max(id),0) FROM dag_run")
    report["before"] = snapshot()
    report["params"] = params
    log = EVIDENCE / f"{name}.log"
    stopped = False
    process = None
    observed_retry = False
    try:
        if scenario in ("retry", "exhausted"):
            command("stop", "postgres")
            stopped = True
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                COMPOSE + ["exec", "-T", "airflow", "airflow", "dags", "test", dag,
                           "--conf", json.dumps(params)], cwd=ROOT, stdout=output, stderr=output,
            )
            deadline = time.monotonic() + 1800
            last_state = None
            heartbeat = 0
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise TimeoutError("Execução excedeu 30 minutos; consultar logs e estado no Airflow.")
                runs = metadata(f"""
                    SELECT coalesce(json_agg(r), '[]'::json) FROM (
                      SELECT d.run_id, d.state, t.task_id, t.state AS task_state, t.try_number
                      FROM dag_run d JOIN task_instance t ON t.dag_id=d.dag_id AND t.run_id=d.run_id
                      WHERE d.id > {baseline} AND d.dag_id='{dag}' ORDER BY t.task_id, t.try_number
                    ) r
                """)
                if runs != last_state or time.monotonic() > heartbeat:
                    print(json.dumps(runs, ensure_ascii=False), flush=True)
                    last_state, heartbeat = runs, time.monotonic() + 30
                waiting = any(r["task_id"] == "materializar_lake" and r["task_state"] == "up_for_retry"
                              for r in runs)
                if waiting:
                    observed_retry = True
                    if scenario == "retry" and stopped:
                        command("start", "postgres")
                        stopped = False
                        print("PostgreSQL isolado religado após observar up_for_retry.", flush=True)
                time.sleep(2)
            report["exit_code"] = process.returncode
        report["tasks"] = metadata(f"""
            SELECT coalesce(json_agg(r),'[]'::json) FROM (
              SELECT d.run_id, d.state AS run_state, t.task_id, t.state, t.try_number,
                     t.start_date, t.end_date
              FROM dag_run d JOIN task_instance t ON t.dag_id=d.dag_id AND t.run_id=d.run_id
              WHERE d.id > {baseline} AND d.dag_id='{dag}' ORDER BY t.task_id, t.try_number
            ) r
        """)
        tasks = {t["task_id"]: t for t in report["tasks"]}
        lake = tasks["materializar_lake"]
        if scenario == "exhausted":
            assert lake["state"] == "failed" and lake["try_number"] == 3, lake
            for task_id in ("transformar_modelos", "verificar_freshness", "verificar_freshness_modelos"):
                assert tasks[task_id]["state"] == "upstream_failed", tasks
            assert lake["run_state"] == "failed", lake
        else:
            assert lake["run_state"] == "success", tasks
            for task_id in ("transformar_modelos", "verificar_freshness", "verificar_freshness_modelos"):
                assert tasks[task_id]["state"] == "success", tasks
            if scenario == "retry":
                assert observed_retry and lake["try_number"] == 2, lake
        report["validated"] = True
    except Exception as exc:
        report["validated"] = False
        report["error_type"] = type(exc).__name__
        raise
    finally:
        if stopped:
            command("start", "postgres")
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["log"] = log.name
        (EVIDENCE / f"{name}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["after"] = snapshot()
    if expect_unchanged:
        report["unchanged"] = report["before"] == report["after"]
        report["validated"] = report["validated"] and report["unchanged"]
    (EVIDENCE / f"{name}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    if expect_unchanged and not report["unchanged"]:
        raise AssertionError("Contagem/soma/IDs mudaram; comparar alterações da fonte antes de concluir idempotência.")


def validate_freshness():
    """Consulta real: atraso e pipeline sem histórico, sem alterar o banco."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    reports = []
    for args, expected, status in [
        (["--sla-hours", "26"], 0, "fresh"),
        (["--sla-hours", "0.001"], 1, "stale"),
        (["--pipeline", "dbt_models", "--sla-hours", "26"], 0, "fresh"),
        (["--pipeline", "dbt_models", "--sla-hours", "0.001"], 1, "stale"),
        (["--pipeline", "e3_pipeline_sem_execucoes", "--sla-hours", "26"], 1, "missing"),
    ]:
        result = command("exec", "-T", "airflow", "/opt/inflow/analytics-venv/bin/python",
                         "/opt/inflow/analytics/freshness.py", *args, check=False)
        report = {"args": args, "exit_code": result.returncode,
                  "result": json.loads(result.stdout)}
        reports.append(report)
        assert result.returncode == expected and report["result"]["status"] == status, report
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-freshness.json")
    (EVIDENCE / name).write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(json.dumps(reports, indent=2), flush=True)


def validate_scheduler():
    """Agenda um horário próximo só no ambiente isolado e pausa após terminar."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    baseline = metadata("SELECT coalesce(max(id),0) FROM dag_run")
    local = datetime.now(timezone(timedelta(hours=-3))) + timedelta(minutes=2)
    cron = f"{local.minute} {local.hour} {local.day} {local.month} *"
    override = EVIDENCE / "schedule-once.yml"
    override.write_text(
        f'services:\n  airflow:\n    environment:\n      INFLOW_PIPELINE_SCHEDULE: "{cron}"\n',
        encoding="utf-8",
    )
    report = {"scenario": "scheduler", "cron": cron, "timezone": "America/Sao_Paulo",
              "started_at": datetime.now(timezone.utc).isoformat()}
    COMPOSE.extend(["-f", str(override)])
    try:
        command("up", "-d", "--no-deps", "--wait", "airflow")
        command("exec", "-T", "airflow", "airflow", "dags", "reserialize")
        command("exec", "-T", "airflow", "airflow", "dags", "unpause", "inflow_pipeline")
        deadline, heartbeat = time.monotonic() + 1800, 0
        while time.monotonic() < deadline:
            runs = metadata(f"""SELECT coalesce(json_agg(r),'[]'::json) FROM (
                SELECT run_id, state, run_type, start_date, end_date FROM dag_run
                WHERE id > {baseline} AND dag_id='inflow_pipeline' AND run_type='scheduled'
                ORDER BY id) r""")
            if time.monotonic() > heartbeat:
                print(json.dumps(runs), flush=True)
                heartbeat = time.monotonic() + 30
            if runs and runs[0]["state"] in ("success", "failed"):
                report["runs"] = runs
                report["validated"] = runs[0]["state"] == "success"
                assert report["validated"], runs
                return
            time.sleep(3)
        raise TimeoutError("Nenhuma execução agendada terminou em 30 minutos.")
    finally:
        command("exec", "-T", "airflow", "airflow", "dags", "pause", "inflow_pipeline", check=False)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-scheduler.json")
        (EVIDENCE / name).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        del COMPOSE[-2:]
        # Restaura o overlay padrão, mantendo o DAG pausado.
        command("up", "-d", "--no-deps", "--wait", "airflow")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["smoke", "backfill", "retry", "exhausted", "scheduler", "freshness"])
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--expect-unchanged", action="store_true")
    args = parser.parse_args()
    if args.scenario == "freshness":
        validate_freshness()
    elif args.scenario == "scheduler":
        validate_scheduler()
    else:
        validate(args.scenario, args.start_year, args.end_year, args.expect_unchanged)
