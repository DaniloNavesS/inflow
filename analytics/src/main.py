"""Camada analítica do InFlow: materializa dados do OLTP em formatos abertos.

Uso:
    python main.py check     # verifica conexão com o Postgres, extensões e pasta do lake
    python main.py parquet   # materializa despesas_enriquecidas em Parquet particionado
"""
import argparse
import logging
import sys
from contextlib import closing

import deltalake
import duckdb

from config import LAKE_DIR
from duck import PG, connect
from parquet_export import export_despesas_enriquecidas
from delta_export import export_despesas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("inflow_analytics")

SOURCE_TABLES = ("senadores", "fornecedores", "despesas", "empresas", "socios")


def check() -> None:
    logger.info("duckdb %s · deltalake %s", duckdb.__version__, deltalake.__version__)

    con = connect()
    con.load_extension("delta")
    for table in SOURCE_TABLES:
        count = con.execute(f"SELECT count(*) FROM {PG}.oltp.{table}").fetchone()[0]
        logger.info("Postgres via DuckDB: oltp.%-14s %8d linhas", table, count)

    LAKE_DIR.mkdir(parents=True, exist_ok=True)
    probe = LAKE_DIR / ".write_probe"
    probe.write_text("ok")
    probe.unlink()
    logger.info("Pasta do lake gravável: %s", LAKE_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="Camada analítica do InFlow")
    parser.add_argument("command", choices=["check", "parquet", "delta", "lake"])
    args = parser.parse_args()

    if args.command == "check":
        check()
    elif args.command == "parquet":
        with closing(connect()) as con:
            export_despesas_enriquecidas(con, LAKE_DIR)
    elif args.command == "delta":
        with closing(connect()) as con:
            logger.info("Delta: %s", export_despesas(con, LAKE_DIR))
    elif args.command == "lake":
        from pipeline import run_lake
        run_lake()


if __name__ == "__main__":
    main()
