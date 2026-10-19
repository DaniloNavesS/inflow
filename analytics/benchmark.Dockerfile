FROM python:3.11.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY scripts/adr/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import duckdb; con = duckdb.connect(); [con.install_extension(e) for e in ('postgres', 'delta', 'iceberg')]"
COPY analytics/src/ ./src/
WORKDIR /app/src
ENTRYPOINT ["python", "benchmark.py"]
