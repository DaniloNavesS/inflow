"""Freshness operacional do lake; não mede a idade dos fatos da CEAPS."""
import argparse
import json
import math
import os
import sys
from contextlib import closing
from datetime import datetime, timezone


DEFAULT_PIPELINE = "analytics_lake"
DEFAULT_SLA_HOURS = 26


def evaluate(last_success, *, now, sla_hours, pipeline=DEFAULT_PIPELINE):
    """Sem sucesso anterior ou com relógio inválido, nunca aprova o SLA."""
    if not pipeline or not pipeline.strip():
        raise ValueError("O nome do pipeline não pode ser vazio.")
    if not math.isfinite(sla_hours) or sla_hours <= 0:
        raise ValueError("O SLA deve ser um número finito maior que zero.")
    if now.tzinfo is None or (last_success is not None and last_success.tzinfo is None):
        raise ValueError("Os horários precisam incluir fuso horário.")
    age = (now - last_success).total_seconds() if last_success else None
    status = (
        "missing" if age is None else
        "invalid_timestamp" if age < 0 else
        "fresh" if age <= sla_hours * 3600 else "stale"
    )
    return {
        "pipeline": pipeline,
        "metric": "seconds_since_last_success",
        "checked_at": now.isoformat(),
        "last_success_at": last_success.isoformat() if last_success else None,
        "age_seconds": age,
        "sla_hours": sla_hours,
        "status": status,
    }


def check_database(db, sla_hours, pipeline=DEFAULT_PIPELINE):
    # Usa o relógio do banco para não comparar relógios de hosts diferentes.
    # Falhas posteriores não renovam a data do último sucesso.
    with db.cursor() as cursor:
        cursor.execute("""
            SELECT max(finished_at), CURRENT_TIMESTAMP
            FROM monitoring.pipeline_runs
            WHERE pipeline_name = %s
              AND status = 'success' AND finished_at IS NOT NULL
        """, (pipeline,))
        last_success, now = cursor.fetchone()
    return evaluate(last_success, now=now, sla_hours=sla_hours, pipeline=pipeline)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sla-hours", type=float,
        default=os.getenv("LAKE_FRESHNESS_SLA_HOURS", str(DEFAULT_SLA_HOURS)),
        help="Tempo máximo desde o último sucesso do pipeline (padrão: 26 horas).",
    )
    parser.add_argument(
        "--pipeline", default=DEFAULT_PIPELINE,
        help="Pipeline em monitoring.pipeline_runs (padrão: analytics_lake).",
    )
    args = parser.parse_args(argv)
    try:
        # Valida antes de abrir a conexão.
        evaluate(None, now=datetime.now(timezone.utc), sla_hours=args.sla_hours,
                 pipeline=args.pipeline)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        import psycopg2
        from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

        with closing(psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, connect_timeout=5,
            options="-c statement_timeout=10000 -c default_transaction_read_only=on",
        )) as db:
            report = check_database(db, args.sla_hours, args.pipeline)
    except Exception as exc:
        # Não imprime a conexão nem mensagens que possam conter credenciais.
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        return 2

    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "fresh" else 1


if __name__ == "__main__":
    sys.exit(main())
