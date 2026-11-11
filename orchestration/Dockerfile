FROM apache/airflow:3.4.0-python3.12

USER root
RUN mkdir -p /opt/inflow /opt/airflow/state && chown -R airflow:0 /opt/inflow /opt/airflow/state
USER airflow

# As duas aplicações têm pins diferentes: não instalar suas libs no Airflow.
COPY --chown=airflow:0 ingestion/requirements.txt /opt/inflow/ingestion-requirements.txt
COPY --chown=airflow:0 analytics/requirements.txt /opt/inflow/analytics-requirements.txt
RUN python -m venv /opt/inflow/ingestion-venv \
    && /opt/inflow/ingestion-venv/bin/pip install --no-cache-dir -r /opt/inflow/ingestion-requirements.txt
RUN python -m venv /opt/inflow/analytics-venv \
    && /opt/inflow/analytics-venv/bin/pip install --no-cache-dir -r /opt/inflow/analytics-requirements.txt
# Mesmas versões do serviço modeling (analytics/dbt/Dockerfile).
RUN python -m venv /opt/inflow/dbt-venv \
    && /opt/inflow/dbt-venv/bin/pip install --no-cache-dir dbt-core==1.12.6 dbt-postgres==1.9.1
RUN /opt/inflow/analytics-venv/bin/python -c "import duckdb; con = duckdb.connect(); [con.install_extension(e) for e in ('postgres', 'delta')]"

COPY --chown=airflow:0 ingestion/src/ /opt/inflow/ingestion/
COPY --chown=airflow:0 analytics/src/ /opt/inflow/analytics/
COPY --chown=airflow:0 ingestion/src/monitoring/ /opt/inflow/analytics/monitoring/
COPY --chown=airflow:0 analytics/dbt/dbt_project.yml analytics/dbt/profiles.yml /opt/inflow/dbt/
COPY --chown=airflow:0 analytics/dbt/models/ /opt/inflow/dbt/models/
COPY --chown=airflow:0 analytics/dbt/macros/ /opt/inflow/dbt/macros/
COPY --chown=airflow:0 analytics/dbt/snapshots/ /opt/inflow/dbt/snapshots/
COPY --chown=airflow:0 analytics/dbt/tests/ /opt/inflow/dbt/tests/
COPY --chown=airflow:0 analytics/dbt/seeds/ /opt/inflow/dbt/seeds/
COPY --chown=airflow:0 orchestration/bin/ /opt/inflow/orchestration/
COPY --chown=airflow:0 orchestration/dags/ /opt/airflow/dags/
COPY --chown=airflow:0 orchestration/tests/ /opt/inflow/tests/

ENV AIRFLOW_HOME=/opt/airflow/state
ENV AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags
ENV PYTHONUNBUFFERED=1
ENV DBT_PROFILES_DIR=/opt/inflow/dbt
ENV DBT_SEND_ANONYMOUS_USAGE_STATS=false
