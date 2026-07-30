@echo off
title CHEP Bot - Reiniciar Servidor e Robo
cd /d "%~dp0"
echo ========================================================
echo Reiniciando o CHEP Bot...
echo ========================================================

echo.
echo 1. Fechando servidor Python em segundo plano...
taskkill /F /IM python.exe /T 2>nul
timeout /t 2 /nobreak >nul

echo.
echo 2. Iniciando novo servidor do CHEP Bot...
call iniciar_site.bat
