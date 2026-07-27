@echo off
echo ===================================================
echo   GRAVADOR DE CLIQUES DO BOT (PLAYWRIGHT CODEGEN)
echo ===================================================
echo.
echo Abra o navegador que ira abrir na tela, faca os cliques
echo na modal (Processo, Tipo de Nota, Prioridade) e copie os
echo seletores que aparecerem no gravador!
echo.
npx -y playwright codegen https://cmaweb.chep.com/bluechat
pause
