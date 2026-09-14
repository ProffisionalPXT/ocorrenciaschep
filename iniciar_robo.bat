@echo off
title CHEP Bot - Automacao de Ocorrencias
cd /d "%~dp0"
echo ========================================================
echo CHEP Bot - Automacao de Ocorrencias e Monitoramento
echo ========================================================
echo.

:: 1. Tenta encontrar o Python pelo caminho fixo (mais confiavel)
set PYTHON_EXE=
set PYTHON_PATHS=^
    "C:\Users\TRANSRAP05\AppData\Local\Python\pythoncore-3.14-64\python.exe" ^
    "C:\Users\TRANSRAP05\AppData\Local\Programs\Python\Python312\python.exe" ^
    "C:\Users\TRANSRAP05\AppData\Local\Programs\Python\Python311\python.exe" ^
    "C:\Users\TRANSRAP05\AppData\Local\Programs\Python\Python310\python.exe" ^
    "C:\Python312\python.exe" ^
    "C:\Python311\python.exe" ^
    "C:\Python310\python.exe"

for %%P in (%PYTHON_PATHS%) do (
    if exist %%P (
        set PYTHON_EXE=%%P
        goto :found_python
    )
)

:: 2. Tenta no PATH como fallback
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set PYTHON_EXE=python
    goto :found_python
)

echo.
echo [ERRO] Python nao foi encontrado!
echo Instale o Python 3.10+ e marque "Add Python to PATH".
echo.
pause
exit /b 1

:found_python
echo [OK] Python encontrado: %PYTHON_EXE%
echo.

:: 3. Instala dependencias se necessario (silencioso)
echo [1/3] Verificando dependencias...
%PYTHON_EXE% -m pip install --quiet --upgrade pip
%PYTHON_EXE% -m pip install --quiet flask playwright python-dotenv requests
echo [OK] Dependencias prontas.
echo.

:: 4. Abre o navegador automaticamente apos 3 segundos
start "" cmd /c "timeout /t 3 >nul & start http://localhost:5000"
echo [2/3] Navegador sera aberto em 3 segundos em http://localhost:5000
echo.

:: 5. Derruba qualquer versão anterior que esteja rodando na porta 5000
echo [3/4] Limpando sessoes antigas na porta 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5000" ^| find "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>nul
)

:: 6. Inicia o servidor
echo [4/4] Iniciando servidor CHEP Bot...
echo Para parar, feche esta janela ou pressione CTRL+C
echo.
%PYTHON_EXE% server.py

echo.
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] O servidor parou com um erro!
    echo Verifique se o arquivo server.py esta presente.
) else (
    echo Servidor encerrado normalmente.
)
echo.
pause
