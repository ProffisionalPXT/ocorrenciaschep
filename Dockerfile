FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

# Instalar dependências básicas
COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel
RUN pip install --only-binary=:all: greenlet || true
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

ENV PORT=5000

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120"]
