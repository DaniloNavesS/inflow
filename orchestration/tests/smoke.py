"""Executa o DAG com o OLTP existente; escreve no lake e no monitoramento."""
import json
import subprocess


if __name__ == "__main__":
    subprocess.run(
        ["airflow", "dags", "test", "inflow_pipeline",
         "--conf", json.dumps({"recarregar_origem": False})],
        check=True,
    )
