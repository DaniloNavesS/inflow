import os

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "inflow_db")
DB_USER = os.getenv("DB_USER", "inflow_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "inflow_pass")

INGESTION_YEAR = int(os.getenv("INGESTION_YEAR", "2024"))
LIMIT_SENADORES = int(os.getenv("LIMIT_SENADORES", "0"))  # 0 para processar todos

# Dados abertos do CNPJ (Receita Federal): sócios e empresas dos fornecedores da CEAPS
ENABLE_CNPJ_OWNERS = os.getenv("ENABLE_CNPJ_OWNERS", "1") == "1"
RFB_CNPJ_BASE_URL = os.getenv(
    "RFB_CNPJ_BASE_URL",
    "https://arquivos.receitafederal.gov.br/public.php/webdav/Dados/Cadastros/CNPJ",
)
RFB_CNPJ_TOKEN = os.getenv("RFB_CNPJ_TOKEN", "gn672Ad4CF8N6TK")  
RFB_CNPJ_MONTH = os.getenv("RFB_CNPJ_MONTH", "")  
CNPJ_CACHE_DIR = os.getenv("CNPJ_CACHE_DIR", "/cache/cnpj")
CNPJ_OWNER_MAX_DEPTH = int(os.getenv("CNPJ_OWNER_MAX_DEPTH", "5"))

REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}
