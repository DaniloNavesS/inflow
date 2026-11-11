"""Executa o dbt e registra o resultado em monitoring.pipeline_runs.

Assim a freshness dos modelos é medida à parte da do lake: um lake bem-sucedido
não esconde uma falha das transformações. Os argumentos são repassados ao dbt
(padrão: ``build``, o mesmo comando de ``make models``).
"""
import os
import subprocess
import sys
import time
from contextlib import closing

# Reaproveita config e monitoramento da camada analítica copiados na imagem.
sys.path.insert(0, os.getenv("INFLOW_ANALYTICS_DIR", "/opt/inflow/analytics"))

PIPELINE = "dbt_models"
DBT_BIN = os.getenv("DBT_BIN", "/opt/inflow/dbt-venv/bin/dbt")
DBT_PROJECT_DIR = os.getenv("DBT_PROJECT_DIR", "/opt/inflow/dbt")


def connect():
    import psycopg2
    from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

    return psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                            user=DB_USER, password=DB_PASSWORD, connect_timeout=10)


def main(argv=None):
    from monitoring.metrics import start_pipeline, finish_pipeline, fail_pipeline

    args = list(argv if argv is not None else sys.argv[1:]) or ["build"]
    # Conexões curtas: o dbt pode levar minutos e não deve segurar uma sessão ociosa.
    with closing(connect()) as db:
        run_id = start_pipeline(db, PIPELINE)
    started = time.perf_counter()
    try:
        code = subprocess.run([DBT_BIN, *args], cwd=DBT_PROJECT_DIR, check=False).returncode
        error = None if code == 0 else f"dbt {args[0]} terminou com código {code}"
    except Exception as exc:
        code, error = 1, f"dbt não executou: {type(exc).__name__}"

    with closing(connect()) as db:
        if error is None:
            finish_pipeline(db, run_id, time.perf_counter() - started)
        else:
            fail_pipeline(db, run_id, time.perf_counter() - started, error)
    return code


if __name__ == "__main__":
    sys.exit(main())
