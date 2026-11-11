FROM python:3.11.14-slim-bookworm
RUN pip install --no-cache-dir dbt-core==1.12.6 dbt-postgres==1.9.1
WORKDIR /app/dbt
COPY analytics/dbt/dbt_project.yml analytics/dbt/profiles.yml ./
COPY analytics/dbt/models/ ./models/
COPY analytics/dbt/macros/ ./macros/
COPY analytics/dbt/snapshots/ ./snapshots/
COPY analytics/dbt/tests/ ./tests/
COPY analytics/dbt/seeds/ ./seeds/
# Diretórios internos usados também quando não há bind mounts (testes).
# O sticky bit permite UIDs arbitrários sem liberar escrita no projeto.
RUN mkdir -p target logs /tmp/dbt-home && chmod 1777 target logs /tmp/dbt-home
ENV HOME=/tmp/dbt-home
ENV DBT_PROFILES_DIR=/app/dbt
ENV DBT_SEND_ANONYMOUS_USAGE_STATS=false
USER 1000:1000
ENTRYPOINT ["dbt"]
CMD ["build"]
