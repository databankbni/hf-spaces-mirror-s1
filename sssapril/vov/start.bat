@echo off
chcp 65001 >nul 2>&1
title VoV Dev Launcher

set "SHOW_WINDOWS=0"
if /i "%~1"=="show" set "SHOW_WINDOWS=1"

echo ========================================
echo   VoV - Starting Development Servers
echo ========================================
echo.

:: 0. Clean up any leftover processes on our ports
echo [0/2] Checking ports...
call :ensure_port_free 8002 backend
call :ensure_port_free 5173 frontend

:: 1. Start backend server
echo [1/2] Starting backend server (port 8002)...
:: Clear old log to avoid stale output
if exist "%~dp0backend.log" del /f "%~dp0backend.log" >nul 2>&1
if "%SHOW_WINDOWS%"=="1" (
    start "VoV Backend" cmd /k "cd /d %~dp0server && python -m app.main"
) else (
    start "" /b powershell -WindowStyle Hidden -Command "cd '%~dp0server'; python -m app.main *> '%~dp0backend.log'"
)

call :wait_for_port 8002 20
if %PORT_READY%==0 (
    echo       ERROR: Backend failed to start on port 8002.
    if exist "%~dp0backend.log" (
        echo       Last 5 lines of backend.log:
        powershell -Command "Get-Content '%~dp0backend.log' -Tail 5 2>$null"
    ) else (
        echo       backend.log was not created - Python or dependencies may be missing.
    )
) else (
    echo       Backend is ready.
)

:: 2. Start frontend dev server
echo [2/2] Starting frontend dev server (port 5173)...
if "%SHOW_WINDOWS%"=="1" (
    start "VoV Frontend" cmd /k "cd /d %~dp0client && npm run dev"
) else (
    start "" /b powershell -WindowStyle Hidden -Command "cd '%~dp0client'; npm run dev *> '%~dp0frontend.log'"
)

call :wait_for_port 5173 15
if %PORT_READY%==0 (
    echo       ERROR: Frontend failed to start on port 5173.
    echo       Check frontend.log for details.
) else (
    echo       Frontend is ready.
)

echo.
echo ========================================
echo   All servers are running!
echo   Backend:  http://localhost:8002
echo   Frontend: http://localhost:5173
echo ========================================
echo.

if "%SHOW_WINDOWS%"=="1" (
    echo Close the server windows to stop, or run stop.bat
) else (
    echo Logs: backend.log / frontend.log
    echo Use "start.bat show" to open visible windows
    echo Run stop.bat to stop all servers
)
timeout /t 5 /nobreak >nul
exit /b

:: ============================================
:: Subroutines
:: ============================================

:ensure_port_free
set EPF_PORT=%~1
set EPF_NAME=%~2
set EPF_RETRY=0
:epf_loop
netstat -aon | findstr ":%EPF_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 goto :eof
if %EPF_RETRY%==0 echo       Port %EPF_PORT% in use, stopping %EPF_NAME%...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%EPF_PORT% " ^| findstr "LISTENING"') do (
    taskkill /T /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%EPF_PORT% " ^| findstr "LISTENING"') do (
    taskkill /T /F /PID %%a >nul 2>&1
)
set /a EPF_RETRY+=1
if %EPF_RETRY% GTR 5 (
    echo       WARNING: Could not free port %EPF_PORT%
    goto :eof
)
timeout /t 1 /nobreak >nul
goto epf_loop

:wait_for_port
set WFP_PORT=%~1
set WFP_TIMEOUT=%~2
set WFP_COUNT=0
set PORT_READY=0
:wfp_loop
netstat -aon | findstr ":%WFP_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    set PORT_READY=1
    goto :eof
)
set /a WFP_COUNT+=1
if %WFP_COUNT% GTR %WFP_TIMEOUT% goto :eof
timeout /t 1 /nobreak >nul
goto wfp_loop
