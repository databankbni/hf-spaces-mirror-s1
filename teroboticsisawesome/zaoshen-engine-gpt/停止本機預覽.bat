@echo off
chcp 65001 >nul
title 停止造神引擎GPT版本機預覽
wsl.exe -d Ubuntu -- bash -lc "pkill -f 'uvicorn backend:app.*8800' || true"
echo 已送出停止指令。
timeout /t 2 /nobreak >nul
