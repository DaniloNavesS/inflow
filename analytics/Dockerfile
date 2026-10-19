FROM python:3.11.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY analytics/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Extensões do DuckDB baixadas no build: em execução o contêiner não depende da internet.
RUN python -c "import duckdb; con = duckdb.connect(); [con.install_extension(e) for e in ('postgres', 'delta')]"

COPY analytics/src/ ./src/
COPY ingestion/src/monitoring/ ./src/monitoring/

WORKDIR /app/src
CMD ["python", "main.py", "check"]
