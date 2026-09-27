import os


DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "inflow_db")
DB_USER = os.getenv("DB_USER", "inflow_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "inflow_pass")

INGESTION_YEAR = int(os.getenv("INGESTION_YEAR", "2024"))
LIMIT_SENADORES = int(os.getenv("LIMIT_SENADORES", "0"))
LEGISLATURE = int(os.getenv("LEGISLATURE", "57"))

