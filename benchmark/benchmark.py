#!/usr/bin/env python3
"""Benchmark PostgreSQL x MariaDB com a forma da carga dos jobs do InFlow.

O teste deliberadamente não chama as APIs do Senado: rede, parsing e os sleeps dos
jobs esconderiam a parcela que pertence ao banco. Os dados são determinísticos e
as operações reproduzem os upserts e leituras dos jobs senators, committees,
sessions, expenses e staff.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg2
import pymysql


TABLES = (
    "estrutura_gabinete",
    "despesas",
    "fornecedores",
    "sessoes_presenca",
    "participacoes_comissao",
    "comissoes",
    "senadores",
)
TOUCH_ON_UPDATE = {
    "senadores", "comissoes", "fornecedores", "despesas", "estrutura_gabinete"
}


@dataclass
class Engine:
    name: str
    connection: Any

    @property
    def postgres(self) -> bool:
        return self.name == "postgresql"

    def qualified(self, table: str) -> str:
        return f"benchmark.{table}"

    def execute(self, sql: str, params: Sequence[Any] | None = None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)

    def scalar(self, sql: str, params: Sequence[Any] | None = None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()[0]

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def connect_engines() -> list[Engine]:
    pg = psycopg2.connect(
        host=env("POSTGRES_HOST", "localhost"),
        port=int(env("POSTGRES_BENCHMARK_PORT", "5433")),
        dbname=env("POSTGRES_DB", "inflow_db"),
        user=env("POSTGRES_USER", "inflow_user"),
        password=env("POSTGRES_PASSWORD", "inflow_pass"),
    )
    maria = pymysql.connect(
        host=env("MARIADB_HOST", "localhost"),
        port=int(env("MARIADB_BENCHMARK_PORT", "3307")),
        database=env("MARIADB_DATABASE", "benchmark"),
        user=env("MARIADB_USER", "inflow_user"),
        password=env("MARIADB_PASSWORD", "inflow_pass"),
        charset="utf8mb4",
        autocommit=False,
    )
    return [Engine("postgresql", pg), Engine("mariadb", maria)]


def setup(engine: Engine) -> None:
    if engine.postgres:
        engine.execute("CREATE SCHEMA IF NOT EXISTS benchmark")
        id_column = "BIGSERIAL PRIMARY KEY"
        timestamp = "TIMESTAMPTZ"
        boolean = "BOOLEAN"
    else:
        # MARIADB_DATABASE cria este database no primeiro start do container.
        id_column = "BIGINT AUTO_INCREMENT PRIMARY KEY"
        timestamp = "TIMESTAMP"
        boolean = "BOOLEAN"
        engine.execute("SET FOREIGN_KEY_CHECKS = 0")

    for table in TABLES:
        engine.execute(f"DROP TABLE IF EXISTS {engine.qualified(table)}")

    if not engine.postgres:
        engine.execute("SET FOREIGN_KEY_CHECKS = 1")

    q = engine.qualified
    statements = [
        f"""CREATE TABLE {q('senadores')} (
            id INT PRIMARY KEY, nome VARCHAR(150) NOT NULL,
            nome_completo VARCHAR(255), partido VARCHAR(50) NOT NULL,
            uf CHAR(2) NOT NULL, status VARCHAR(50) NOT NULL,
            timestamp_ingestao {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE {q('comissoes')} (
            id INT PRIMARY KEY, sigla VARCHAR(50) NOT NULL,
            nome VARCHAR(255) NOT NULL, casa VARCHAR(20) NOT NULL,
            timestamp_ingestao {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE {q('participacoes_comissao')} (
            id {id_column}, senador_id INT NOT NULL,
            comissao_id INT NOT NULL, cargo VARCHAR(100) NOT NULL,
            data_inicio DATE NOT NULL, data_fim DATE,
            timestamp_ingestao {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_participacao UNIQUE
                (senador_id, comissao_id, cargo, data_inicio),
            CONSTRAINT fk_part_sen FOREIGN KEY (senador_id)
                REFERENCES {q('senadores')}(id) ON DELETE CASCADE,
            CONSTRAINT fk_part_com FOREIGN KEY (comissao_id)
                REFERENCES {q('comissoes')}(id) ON DELETE CASCADE
        )""",
        f"""CREATE TABLE {q('sessoes_presenca')} (
            id {id_column}, sessao_id BIGINT NOT NULL,
            senador_id INT NOT NULL, data_sessao DATE NOT NULL,
            presenca VARCHAR(50) NOT NULL, tipo_sessao VARCHAR(50),
            timestamp_ingestao {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_sessao UNIQUE (sessao_id, senador_id, data_sessao),
            CONSTRAINT fk_sess_sen FOREIGN KEY (senador_id)
                REFERENCES {q('senadores')}(id) ON DELETE CASCADE
        )""",
        f"""CREATE TABLE {q('fornecedores')} (
            id {id_column}, cnpj_cpf VARCHAR(20) NOT NULL UNIQUE,
            razao_social VARCHAR(255) NOT NULL,
            timestamp_ingestao {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE {q('despesas')} (
            id BIGINT PRIMARY KEY, senador_id INT NOT NULL,
            fornecedor_id BIGINT NOT NULL, data_despesa DATE NOT NULL,
            ano SMALLINT NOT NULL, mes SMALLINT NOT NULL,
            tipo_despesa VARCHAR(255) NOT NULL,
            tipo_documento VARCHAR(100), num_documento VARCHAR(100),
            detalhamento TEXT, valor DECIMAL(14,2) NOT NULL,
            timestamp_ingestao {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_desp_sen FOREIGN KEY (senador_id)
                REFERENCES {q('senadores')}(id),
            CONSTRAINT fk_desp_forn FOREIGN KEY (fornecedor_id)
                REFERENCES {q('fornecedores')}(id)
        )""",
        f"""CREATE TABLE {q('estrutura_gabinete')} (
            id {id_column}, senador_id INT NOT NULL, ano SMALLINT NOT NULL,
            qtd_pessoal_gabinete INT NOT NULL,
            qtd_pessoal_escritorio INT NOT NULL,
            auxilio_moradia {boolean} NOT NULL,
            imovel_funcional {boolean} NOT NULL,
            timestamp_ingestao {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            atualizado_em {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_estrutura UNIQUE (senador_id, ano),
            CONSTRAINT fk_est_sen FOREIGN KEY (senador_id)
                REFERENCES {q('senadores')}(id) ON DELETE CASCADE
        )""",
        f"CREATE INDEX idx_part_sen ON {q('participacoes_comissao')}(senador_id)",
        f"CREATE INDEX idx_sess_sen_data ON {q('sessoes_presenca')}(senador_id, data_sessao)",
        f"CREATE INDEX idx_desp_sen_data ON {q('despesas')}(senador_id, data_despesa)",
        f"CREATE INDEX idx_desp_forn ON {q('despesas')}(fornecedor_id)",
        f"CREATE INDEX idx_desp_tipo ON {q('despesas')}(tipo_despesa)",
        f"CREATE INDEX idx_desp_ano_mes ON {q('despesas')}(ano, mes)",
    ]
    for statement in statements:
        engine.execute(statement)
    engine.commit()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def chunks(rows: Sequence[tuple], size: int) -> Iterable[Sequence[tuple]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def upsert(
    engine: Engine,
    table: str,
    columns: Sequence[str],
    rows: Sequence[tuple],
    conflict: Sequence[str],
    updates: Sequence[str],
    batch_size: int,
) -> None:
    for batch in chunks(rows, batch_size):
        row_placeholder = "(" + ",".join(["%s"] * len(columns)) + ")"
        values = ",".join([row_placeholder] * len(batch))
        flat = [value for row in batch for value in row]
        if engine.postgres:
            update_sql = ",".join(f"{col}=EXCLUDED.{col}" for col in updates)
            clause = f"ON CONFLICT ({','.join(conflict)}) DO UPDATE SET {update_sql}"
        else:
            update_sql = ",".join(f"{col}=VALUES({col})" for col in updates)
            clause = f"ON DUPLICATE KEY UPDATE {update_sql}"
        if table in TOUCH_ON_UPDATE:
            clause += ",atualizado_em=CURRENT_TIMESTAMP"
        engine.execute(
            f"INSERT INTO {engine.qualified(table)} ({','.join(columns)}) "
            f"VALUES {values} {clause}",
            flat,
        )
    engine.commit()


def make_data(scale: int) -> dict[str, list[tuple]]:
    senator_count = 81
    committee_count = 425
    supplier_count = 3516 * scale
    expense_count = 21430 * scale
    membership_count = 7189 * scale
    session_count = 81 * 30 * scale
    base = date(2024, 1, 1)
    senators = [
        (i, f"Senador {i}", f"Nome Completo {i}", f"P{i % 12}", "DF", "Em Exercício")
        for i in range(1, senator_count + 1)
    ]
    committees = [
        (i, f"C{i}", f"Comissão {i}", "SF")
        for i in range(1, committee_count + 1)
    ]
    memberships = [
        (
            (i % senator_count) + 1,
            (i % committee_count) + 1,
            ("Titular", "Suplente", "Membro")[i % 3],
            base + timedelta(days=i // 34425),
            None,
        )
        for i in range(membership_count)
    ]
    sessions = [
        (100000 + i // senator_count, (i % senator_count) + 1,
         base + timedelta(days=(i // senator_count) % 365), "Presente", "Deliberativa")
        for i in range(session_count)
    ]
    suppliers = [
        (f"{i:014d}", f"Fornecedor {i}") for i in range(1, supplier_count + 1)
    ]
    expenses = [
        (
            i + 1,
            (i % senator_count) + 1,
            (i % supplier_count) + 1,
            base + timedelta(days=i % 365),
            2024,
            (i % 12) + 1,
            f"Tipo {i % 8}",
            "NOTA FISCAL",
            f"NF-{i}",
            f"Despesa sintética determinística {i}",
            round(25 + (i % 10000) / 7, 2),
        )
        for i in range(expense_count)
    ]
    staff = [
        (i, 2024, 10 + i % 20, i % 8, bool(i % 2), bool((i + 1) % 2))
        for i in range(1, senator_count + 1)
    ]
    return {
        "senators": senators,
        "committees": committees,
        "memberships": memberships,
        "sessions": sessions,
        "suppliers": suppliers,
        "expenses": expenses,
        "staff": staff,
    }


def timed_job(name: str, rows: int, function) -> dict[str, Any]:
    started = time.perf_counter()
    function()
    seconds = time.perf_counter() - started
    return {
        "job": name,
        "rows": rows,
        "seconds": round(seconds, 6),
        "rows_per_second": round(rows / seconds, 2),
    }


def run_jobs(engine: Engine, data: dict[str, list[tuple]], batch_size: int) -> list[dict]:
    q = engine.qualified
    results = []
    results.append(timed_job("senators", len(data["senators"]), lambda: upsert(
        engine, "senadores", ("id", "nome", "nome_completo", "partido", "uf", "status"),
        data["senators"], ("id",), ("nome", "nome_completo", "partido", "uf", "status"), batch_size,
    )))

    def committees_job():
        upsert(engine, "comissoes", ("id", "sigla", "nome", "casa"), data["committees"],
               ("id",), ("sigla", "nome", "casa"), batch_size)
        upsert(engine, "participacoes_comissao",
               ("senador_id", "comissao_id", "cargo", "data_inicio", "data_fim"),
               data["memberships"], ("senador_id", "comissao_id", "cargo", "data_inicio"),
               ("data_fim",), batch_size)
    results.append(timed_job("committees", len(data["committees"]) + len(data["memberships"]), committees_job))
    results.append(timed_job("sessions", len(data["sessions"]), lambda: upsert(
        engine, "sessoes_presenca",
        ("sessao_id", "senador_id", "data_sessao", "presenca", "tipo_sessao"),
        data["sessions"], ("sessao_id", "senador_id", "data_sessao"),
        ("presenca", "tipo_sessao"), batch_size,
    )))

    def expenses_job():
        upsert(engine, "fornecedores", ("cnpj_cpf", "razao_social"), data["suppliers"],
               ("cnpj_cpf",), ("razao_social",), batch_size)
        upsert(engine, "despesas",
               ("id", "senador_id", "fornecedor_id", "data_despesa", "ano", "mes",
                "tipo_despesa", "tipo_documento", "num_documento", "detalhamento", "valor"),
               data["expenses"], ("id",),
               ("valor", "tipo_despesa", "tipo_documento", "num_documento", "detalhamento"),
               batch_size)
    results.append(timed_job("expenses", len(data["suppliers"]) + len(data["expenses"]), expenses_job))
    results.append(timed_job("staff", len(data["staff"]), lambda: upsert(
        engine, "estrutura_gabinete",
        ("senador_id", "ano", "qtd_pessoal_gabinete", "qtd_pessoal_escritorio",
         "auxilio_moradia", "imovel_funcional"),
        data["staff"], ("senador_id", "ano"),
        ("qtd_pessoal_gabinete", "qtd_pessoal_escritorio", "auxilio_moradia", "imovel_funcional"),
        batch_size,
    )))
    # Evita que um otimizador elimine trabalho por falta de leitura das tabelas.
    assert engine.scalar(f"SELECT COUNT(*) FROM {q('despesas')}") == len(data["expenses"])
    return results


def measure_queries(engine: Engine, repetitions: int) -> list[dict[str, Any]]:
    queries = {
        "aggregate_senator_type": (
            f"SELECT senador_id, tipo_despesa, SUM(valor) FROM {engine.qualified('despesas')} "
            "WHERE ano=%s GROUP BY senador_id, tipo_despesa",
            (2024,),
        ),
        "indexed_senator_period": (
            f"SELECT id, data_despesa, valor FROM {engine.qualified('despesas')} "
            "WHERE senador_id=%s AND data_despesa BETWEEN %s AND %s ORDER BY data_despesa",
            (42, date(2024, 1, 1), date(2024, 12, 31)),
        ),
        "supplier_totals": (
            f"SELECT fornecedor_id, SUM(valor) FROM {engine.qualified('despesas')} "
            "GROUP BY fornecedor_id ORDER BY SUM(valor) DESC LIMIT 20",
            (),
        ),
    }
    output = []
    for name, (sql, params) in queries.items():
        durations = []
        # Aquecimento explícito; as medições seguintes representam cache quente.
        with engine.connection.cursor() as cursor:
            cursor.execute(sql, params)
            cursor.fetchall()
        for _ in range(repetitions):
            started = time.perf_counter()
            with engine.connection.cursor() as cursor:
                cursor.execute(sql, params)
                cursor.fetchall()
            durations.append((time.perf_counter() - started) * 1000)
        output.append({
            "query": name,
            "runs": repetitions,
            "p50_ms": round(statistics.median(durations), 3),
            "p95_ms": round(percentile(durations, 0.95), 3),
            "min_ms": round(min(durations), 3),
        })
    return output


def database_size(engine: Engine) -> int:
    if engine.postgres:
        return int(engine.scalar("SELECT pg_total_relation_size(%s::regclass)", ("benchmark.despesas",)))
    # InnoDB atualiza as estimativas de tamanho de forma assíncrona. Sem o
    # ANALYZE, uma tabela recém-carregada costuma aparecer como apenas 80 KiB.
    engine.execute(f"ANALYZE TABLE {engine.qualified('despesas')}")
    return int(engine.scalar(
        "SELECT COALESCE(data_length + index_length, 0) FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name='despesas'",
        (env("MARIADB_DATABASE", "benchmark"),),
    ))


def version(engine: Engine) -> str:
    return str(engine.scalar("SELECT version()"))


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Benchmark PostgreSQL × MariaDB — InFlow",
        "",
        f"Executado em `{report['generated_at']}`; escala `{report['configuration']['scale']}x`, "
        f"lote `{report['configuration']['batch_size']}`.",
        "",
        "> Resultados locais: não generalizar para outra máquina sem repetir o teste.",
        "",
        "## Versões",
        "",
        "| Banco | Versão | Tamanho de `despesas` |",
        "|---|---|---:|",
    ]
    for result in report["engines"]:
        lines.append(f"| {result['engine']} | `{result['version']}` | {result['despesas_size_bytes']} bytes |")
    for phase in ("cold_load", "warm_upsert"):
        title = "Carga inicial" if phase == "cold_load" else "Reprocessamento idempotente"
        lines += ["", f"## {title}", "", "| Banco | Job | Linhas | Tempo (s) | Linhas/s |", "|---|---|---:|---:|---:|"]
        for result in report["engines"]:
            for job in result[phase]:
                lines.append(
                    f"| {result['engine']} | {job['job']} | {job['rows']} | "
                    f"{job['seconds']:.3f} | {job['rows_per_second']:.0f} |"
                )
    lines += ["", "## Consultas (cache quente)", "", "| Banco | Consulta | p50 (ms) | p95 (ms) |", "|---|---|---:|---:|"]
    for result in report["engines"]:
        for query in result["queries"]:
            lines.append(f"| {result['engine']} | {query['query']} | {query['p50_ms']:.3f} | {query['p95_ms']:.3f} |")
    lines += [
        "",
        "## Escopo",
        "",
        "A medição reproduz os upserts e consultas relacionais dos jobs, com as cardinalidades do "
        "workload documentado. Ela exclui chamadas HTTP, parsing de JSON/PDF, sleeps e escrita da "
        "camada bronze; portanto mede o SGBD e o driver, não o tempo total do pipeline.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=int, default=1, help="multiplica tabelas de fatos (padrão: 1)")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--query-runs", type=int, default=30)
    parser.add_argument("--output", default="/results")
    args = parser.parse_args()
    if args.scale < 1 or args.batch_size < 1 or args.query_runs < 1:
        parser.error("scale, batch-size e query-runs devem ser positivos")

    data = make_data(args.scale)
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "configuration": {
            "scale": args.scale,
            "batch_size": args.batch_size,
            "query_runs": args.query_runs,
            "cardinalities": {key: len(value) for key, value in data.items()},
        },
        "engines": [],
    }
    engines = connect_engines()
    try:
        for engine in engines:
            print(f"==> {engine.name}: preparando schema isolado", flush=True)
            setup(engine)
            cold = run_jobs(engine, data, args.batch_size)
            warm = run_jobs(engine, data, args.batch_size)
            queries = measure_queries(engine, args.query_runs)
            report["engines"].append({
                "engine": engine.name,
                "version": version(engine),
                "cold_load": cold,
                "warm_upsert": warm,
                "queries": queries,
                "despesas_size_bytes": database_size(engine),
            })
    finally:
        for engine in engines:
            engine.close()

    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    json_path = destination / f"benchmark-{stamp}.json"
    md_path = destination / f"benchmark-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    print(f"Arquivos: {json_path} e {md_path}", flush=True)


if __name__ == "__main__":
    main()
