@echo off
chcp 65001 >nul 2>&1
title AgentFlow Build

echo ========================================
echo   AgentFlow - Build Desktop App
echo ========================================
echo.

REM 0. Check prerequisites
echo [0/4] Checking prerequisites...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found
    pause
    exit /b 1
)

echo       OK.

REM 1. Build frontend
echo.
echo [1/4] Building frontend...
cd /d "%~dp0client"
call npm run build
if %errorlevel% neq 0 (
    echo [ERROR] Frontend build failed.
    pause
    exit /b 1
)

REM 2. Install Python dependencies
echo.
echo [2/4] Installing dependencies...
cd /d "%~dp0server"
pip install -r requirements.txt -q
pip install pyinstaller -q

REM 3. Kill old process
echo.
echo [3/5] Cleaning up...
taskkill /F /IM AgentFlow.exe >nul 2>&1
timeout /t 3 /nobreak >nul

REM 4. PyInstaller - use fresh output dir to avoid lock
echo.
echo [4/5] Packaging...
cd /d "%~dp0"

REM Try to remove old dist, if locked use dist_new
set "OUTDIR=dist"
if exist dist\AgentFlow (
    rmdir /s /q dist\AgentFlow 2>nul
    if exist dist\AgentFlow (
        echo       dist\AgentFlow locked, using dist_new
        set "OUTDIR=dist_new"
    )
)

pyinstaller --clean --noconfirm --distpath "%OUTDIR%" build.spec
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller failed.
    pause
    exit /b 1
)

REM 5. Done
echo.
echo ========================================
echo   Build complete!
echo   Output: %OUTDIR%\AgentFlow\AgentFlow.exe
echo ========================================
echo.

explorer "%~dp0%OUTDIR%\AgentFlow"
pause
