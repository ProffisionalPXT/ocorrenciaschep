@echo off
title Abrir Chrome com Conexao Bot (Porta 9222)
echo Abrindo o Google Chrome no modo de conexao para o Robo CHEP...
start "" "chrome.exe" --remote-debugging-port=9222 https://cmaweb.chep.com/bluechat
