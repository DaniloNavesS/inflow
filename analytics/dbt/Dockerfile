FROM python:3.11.14-slim-bookworm
RUN pip install --no-cache-dir dbt-core==1.12.6 dbt-postgres==1.9.1
WORKDIR /app/dbt
COPY analytics/dbt/ ./
ENV DBT_PROFILES_DIR=/app/dbt
ENV DBT_SEND_ANONYMOUS_USAGE_STATS=false
ENTRYPOINT ["dbt"]
CMD ["build"]
