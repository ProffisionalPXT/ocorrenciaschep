@echo off
title Rastrear Coordenadas do Mouse
echo ===================================================
echo   INICIANDO CHROME E RASTREADOR DE COORDENADAS
echo ===================================================
echo.
echo [1/2] Abrindo a pagina do CHEP no navegador...
start https://cmaweb.chep.com/bluechat
echo.
echo [2/2] Iniciando monitor do mouse em tempo real...
echo.
python mostrar_coordenadas.py
pause
