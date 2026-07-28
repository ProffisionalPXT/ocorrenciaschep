@echo off
title Criar Atalho na Area de Trabalho
cd /d "%~dp0"
echo ========================================================
echo Criando Atalho do CHEP Bot na Area de Trabalho (Desktop)...
echo ========================================================

powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'CHEP Bot.lnk')); $s.TargetPath='%~dp0iniciar_site.bat'; $s.WorkingDirectory='%~dp0'; $s.Save()"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ Atalho 'CHEP Bot' criado na Area de Trabalho com sucesso!
) else (
    echo.
    echo ❌ Erro ao criar o atalho.
)
echo.
pause
