# Usar imagem oficial do Python com Playwright pré-instalado
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

# Configurar diretório de trabalho
WORKDIR /app

# Copiar arquivo de dependências
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código-fonte da aplicação
COPY . .

# Expor a porta 5000 do Flask/Gunicorn
EXPOSE 5000

# Variável de ambiente para porta padrão no Render/Docker
ENV PORT=5000

# Comando para iniciar o servidor web
CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120"]
