@echo off
cd /d "%~dp0"
echo ============================================
echo   Sync downloaded data files
echo ============================================
echo.
venv\Scripts\python.exe tools\sync_data.py
echo.
echo ============================================
echo Done. Press any key to close...
pause > nul
