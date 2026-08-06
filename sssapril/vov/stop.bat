@echo off
chcp 65001 >nul 2>&1
title VoV - Stop Servers

echo Stopping VoV development servers...

:: Kill backend processes on port 8002 (with process tree)
set BK_RETRY=0
:kill_backend
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8002 " ^| findstr "LISTENING"') do (
    taskkill /T /F /PID %%a >nul 2>&1
    echo Backend process stopped (PID %%a)
)
netstat -aon | findstr ":8002 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    set /a BK_RETRY+=1
    if %BK_RETRY% GTR 5 (
        echo WARNING: Port 8002 still occupied after 5 retries
        goto kill_frontend
    )
    timeout /t 1 /nobreak >nul
    goto kill_backend
)

:: Kill frontend processes on port 5173 (with process tree)
:kill_frontend
set FT_RETRY=0
:kill_frontend_loop
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    taskkill /T /F /PID %%a >nul 2>&1
    echo Frontend process stopped (PID %%a)
)
netstat -aon | findstr ":5173 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    set /a FT_RETRY+=1
    if %FT_RETRY% GTR 5 (
        echo WARNING: Port 5173 still occupied after 5 retries
        goto stop_db
    )
    timeout /t 1 /nobreak >nul
    goto kill_frontend_loop
)

:stop_db
:: Stop PostgreSQL container
docker compose -f "%~dp0docker-compose.yml" down 2>nul
echo PostgreSQL stopped.

echo Done.
timeout /t 2 /nobreak >nul
