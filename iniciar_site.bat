@echo off
title CHEP Bot - Servidor Web & Celular
cd /d "%~dp0"
echo ========================================================
echo Iniciando o Servidor Web do CHEP Bot...
echo Acesse no PC:      http://localhost:5000
echo Acesse no Celular: http://10.0.0.76:5000
echo ========================================================

:: Abre o navegador Chrome/Padrão automaticamente no localhost:5000
start "" "http://localhost:5000"

IF EXIST "C:\Users\TRANSRAP05\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
    "C:\Users\TRANSRAP05\AppData\Local\Python\pythoncore-3.14-64\python.exe" server.py
) ELSE (
    python server.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Ocorreu um erro ao iniciar o servidor web.
    pause
)
