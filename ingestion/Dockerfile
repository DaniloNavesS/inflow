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

# Copia os módulos do pipeline
COPY . .

# Comando padrão de execução
CMD ["python", "main.py"]
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
