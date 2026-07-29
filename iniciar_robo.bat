@echo off
title CHEP Bot - Automação de Ocorrências
cd /d "%~dp0"
echo ========================================================
echo CHEP Bot - Automação de Ocorrências e Monitoramento
echo ========================================================
echo.

:: 1. Verifica se o Python está instalado no sistema
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Python não foi encontrado no PATH deste computador.
    echo Por favor, instale o Python 3.10+ marcando a caixa 'Add Python to PATH'.
    pause
    exit /b 1
)

:: 2. Instala dependências básicas caso necessário
echo 📦 Verificando dependências do sistema...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet flask playwright

:: 3. Abre o navegador automaticamente em 3 segundos
start "" cmd /c "timeout /t 3 >nul && start http://localhost:5000"

:: 4. Inicia o servidor do robô
echo 🚀 Iniciando Servidor CHEP Bot em http://localhost:5000...
echo.
python server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Ocorreu um erro ao executar o CHEP Bot.
    pause
)
