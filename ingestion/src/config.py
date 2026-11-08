import os

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "inflow_db")
DB_USER = os.getenv("DB_USER", "inflow_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "inflow_pass")

MAX_INGESTION_YEARS = 10


def resolve_ingestion_years(environ=os.environ) -> tuple:
    """Anos a ingerir. A API da CEAPS é anual, então o período explícito também é.

    Sem INGESTION_START_YEAR/INGESTION_END_YEAR, vale só INGESTION_YEAR (comportamento
    anterior). Com apenas um dos limites, o outro assume o mesmo ano.
    """
    def read(name):
        raw = (environ.get(name) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"{name} deve ser um ano inteiro (recebido: {raw!r}).") from None

    start, end = read("INGESTION_START_YEAR"), read("INGESTION_END_YEAR")
    if start is None and end is None:
        return (read("INGESTION_YEAR") or 2024,)
    start, end = start or end, end or start
    if start > end:
        raise ValueError(f"INGESTION_START_YEAR ({start}) é posterior a INGESTION_END_YEAR ({end}).")
    if end - start + 1 > MAX_INGESTION_YEARS:
        raise ValueError(f"O período excede {MAX_INGESTION_YEARS} anos.")
    return tuple(range(start, end + 1))


INGESTION_YEARS = resolve_ingestion_years()
# Último ano do período: mantém o significado de INGESTION_YEAR para quem o importa.
INGESTION_YEAR = INGESTION_YEARS[-1]
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

# Dado atrasado: meses que uma janela mensal de despesas segue aberta depois que a
# competência avança (medição em documentation/docs/metrics/dado-atrasado.mdx)
LATE_DATA_ALLOWED_MONTHS = int(os.getenv("LATE_DATA_ALLOWED_MONTHS", "2"))

REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}
