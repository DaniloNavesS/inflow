FROM python:3.11.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Extensões do DuckDB baixadas no build: em execução o contêiner não depende da internet.
RUN python -c "import duckdb; con = duckdb.connect(); [con.install_extension(e) for e in ('postgres', 'delta')]"

COPY src/ ./src/

WORKDIR /app/src
CMD ["python", "main.py", "check"]
