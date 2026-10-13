import os
from pathlib import Path

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "inflow_db")
DB_USER = os.getenv("DB_USER", "inflow_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "inflow_pass")

# Raiz da camada analítica (Parquet e Delta), montada a partir de ./lake no host.
LAKE_DIR = Path(os.getenv("LAKE_DIR", "/lake"))
