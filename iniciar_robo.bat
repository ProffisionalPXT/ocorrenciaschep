@echo off
title CHEP Bot - Automação de Ocorrências
cd /d "%~dp0"
echo ========================================================
echo Iniciando o aplicativo CHEP Bot...
echo ========================================================

IF EXIST "C:\Users\TRANSRAP05\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
    "C:\Users\TRANSRAP05\AppData\Local\Python\pythoncore-3.14-64\python.exe" server.py
) ELSE (
    python server.py
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Ocorreu um erro ao abrir o aplicativo.
    pause
)
