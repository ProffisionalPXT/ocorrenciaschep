@echo off
title CHEP Bot - Limpar Host / Sessao / Processos
cd /d "%~dp0"
echo ========================================================
echo Limpando Processos, Cache e Perfil do Chrome do Host...
echo ========================================================

echo.
echo 1. Encerrando processos de background (Chrome e Python)...
taskkill /F /IM python.exe /T 2>nul
taskkill /F /IM chrome.exe /T 2>nul
timeout /t 2 /nobreak >nul

echo.
echo 2. Removendo pastas de perfil e sessao do Chrome do CHEP Bot...
if exist "%USERPROFILE%\.chep_bot_chrome_profile_purm2" (
    rmdir /s /q "%USERPROFILE%\.chep_bot_chrome_profile_purm2" 2>nul
    echo    [OK] Perfil PURM2 removido.
)
if exist "%USERPROFILE%\.chep_bot_chrome_profile_purm3" (
    rmdir /s /q "%USERPROFILE%\.chep_bot_chrome_profile_purm3" 2>nul
    echo    [OK] Perfil PURM3 removido.
)

echo.
echo 3. Limpando prints temporarios de debug...
if exist "static\*.png" (
    del /q "static\*.png" 2>nul
    echo    [OK] Cache de imagens limpo.
)

echo ========================================================
echo ✅ Limpeza do Host concluida com sucesso!
echo ========================================================
echo.
pause
