@echo off
chcp 65001 >nul
title 造神引擎GPT版本機預覽

echo ========================================
echo   造神引擎GPT版 - 本機預覽
echo ========================================
echo.
echo 正在啟動，請保留這個視窗不要關閉...

start "" cmd /c "timeout /t 8 /nobreak >nul & start "" "http://127.0.0.1:8800/login""

wsl.exe -d Ubuntu -- bash -lc "cd '/mnt/c/Users/HP-PC/Documents/WAYNE共享專案/造神引擎GPT版' && python3 -m uvicorn backend:app --host 0.0.0.0 --port 8800"

echo.
echo 服務已停止或啟動失敗。
echo 請將上方錯誤訊息截圖交給我。
pause
