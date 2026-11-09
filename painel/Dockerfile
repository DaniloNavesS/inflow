FROM python:3.11.14-slim-bookworm
WORKDIR /app
COPY painel/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY painel/ ./
RUN useradd --create-home --uid 1000 painel
USER painel
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
