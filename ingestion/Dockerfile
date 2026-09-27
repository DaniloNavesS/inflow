FROM python:3.11-slim

# Evita .pyc e mantém logs sem buffer
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências de sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código modularizado
COPY src/ ./src/

# Executa a partir da pasta src para preservar imports como:
# from config import ...
# from clients.senate import ...
WORKDIR /app/src

CMD ["python", "main.py"]