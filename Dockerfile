# Usar imagem pré-compilada oficial do Playwright com Python e Chromium
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# Copiar dependências e instalar sem compilações
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código do projeto
COPY . .

EXPOSE 5000

ENV PORT=5000

# Executar servidor de produção Gunicorn
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120"]
