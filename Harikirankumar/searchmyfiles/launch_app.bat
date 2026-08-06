@echo off
setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"
title Portable OCR Studio

if not exist "%USERPROFILE%\Desktop\Portable OCR Studio.lnk" (
  if exist "%~dp0create_desktop_shortcut.bat" call "%~dp0create_desktop_shortcut.bat" >nul 2>&1
)

set "PYTHON_EXE=C:\Users\EKiran\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

set "BUNDLED_TESS=%~dp0portable_tesseract\Tesseract-OCR\tesseract.exe"
set "BUNDLED_TESSDATA=%~dp0portable_tesseract\Tesseract-OCR\tessdata"

if "%TESSERACT_CMD%"=="" (
  if exist "%BUNDLED_TESS%" set "TESSERACT_CMD=%BUNDLED_TESS%"
)
if "%TESSDATA_PREFIX%"=="" (
  if exist "%BUNDLED_TESSDATA%" set "TESSDATA_PREFIX=%BUNDLED_TESSDATA%"
)

echo Starting Portable OCR Studio...
echo.

echo Trying desktop window mode first...
"%PYTHON_EXE%" -c "import webview" >nul 2>&1
if %errorlevel%==0 (
  "%PYTHON_EXE%" desktop_app.py
  goto :end
)

echo Desktop window dependency missing. Falling back to browser mode.
echo Tip: install with: "%PYTHON_EXE%" -m pip install pywebview
start "" "http://127.0.0.1:7860"
"%PYTHON_EXE%" app.py

:end
endlocal
