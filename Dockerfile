# Usar imagem oficial do Python com Playwright pré-instalado
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# Instalar compiladores C/C++ de build essenciais
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Atualizar pip, setuptools e wheel para garantir rodas binárias pré-compiladas
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

ENV PORT=5000

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120"]
