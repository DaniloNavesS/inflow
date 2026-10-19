import json
from contextlib import closing

import pytest

pytest.importorskip("duckdb")
from duck import connect
from delta_export import export_despesas
from consumption import compare
from parquet_export import export_despesas_enriquecidas


def test_consumption_matches_postgres(tmp_path, db):
    with closing(connect()) as con:
        export_despesas_enriquecidas(con, tmp_path)
        export_despesas(con, tmp_path)
        report = compare(con, db, tmp_path)
        print("\nConsultas de gestão — cenário de teste (4 despesas):")
        print(f"{'Consulta':35} {'PostgreSQL':>12} {'Parquet':>12} {'Delta':>12}  Resultado")
        for name, result in report.items():
            print(f"{name:35} {result['postgres_ms']:9.3f} ms {result['parquet_ms']:9.3f} ms "
                  f"{result['delta_ms']:9.3f} ms  IGUAL")
        print("Estes tempos validam a execução; use make benchmark-lake para avaliar escala.", flush=True)
        assert len(report) == 2
        assert all(row["linhas"] > 0 for row in report.values())
        assert json.loads((tmp_path / "consumo.json").read_text())


def test_pipeline_is_monitored_and_rerunnable(tmp_path, db, monkeypatch):
    import pipeline
    monkeypatch.setattr(pipeline, "LAKE_DIR", tmp_path)
    pipeline.run_lake()
    pipeline.run_lake()
    with db.cursor() as cur:
        cur.execute("""
            SELECT status FROM monitoring.pipeline_runs
            WHERE pipeline_name = 'analytics_lake' ORDER BY started_at DESC LIMIT 2
        """)
        assert cur.fetchall() == [("success",), ("success",)]
        cur.execute("""
            SELECT job_name, status FROM monitoring.job_runs
            WHERE run_id = (SELECT run_id FROM monitoring.pipeline_runs
                WHERE pipeline_name = 'analytics_lake' ORDER BY started_at DESC LIMIT 1)
            ORDER BY id
        """)
        assert cur.fetchall() == [("lake_parquet", "success"), ("lake_delta", "success"),
                                  ("lake_consumption", "success")]


def test_pipeline_failure_is_recorded(tmp_path, db, monkeypatch):
    import pipeline
    monkeypatch.setattr(pipeline, "LAKE_DIR", tmp_path)
    def fail(*args):
        raise RuntimeError("Falha de materialização simulada")
    monkeypatch.setattr(pipeline, "export_despesas", fail)
    with pytest.raises(RuntimeError, match="simulada"):
        pipeline.run_lake()
    with db.cursor() as cur:
        cur.execute("""
            SELECT status, error_message FROM monitoring.pipeline_runs
            WHERE pipeline_name = 'analytics_lake' ORDER BY started_at DESC LIMIT 1
        """)
        status, error = cur.fetchone()
    assert status == "failed" and "simulada" in error
