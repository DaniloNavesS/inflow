FROM python:3.11.14-slim-bookworm

# Evita geração de bytecode .pyc e força flush imediato dos logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências de sistema necessárias
# Dependências de sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia apenas a implementação canônica do pipeline
COPY src/ ./src/

# Executa a partir de src para preservar os imports dos módulos do pipeline
WORKDIR /app/src
CMD ["python", "main.py"]
