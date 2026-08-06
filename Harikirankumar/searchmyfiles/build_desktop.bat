@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=C:\Users\EKiran\AppData\Local\Programs\Python\Python311\python.exe

"%PYTHON_EXE%" -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :fail

"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --name PortableOCRStudio ^
  --icon assets\app_icon.ico ^
  --add-data "index.html;." ^
  --add-data "tutorial_quickstart.gif;." ^
  --add-data "portable_tesseract;portable_tesseract" ^
  desktop_app.py
if errorlevel 1 goto :fail

echo Build complete: dist\PortableOCRStudio.exe
exit /b 0

:fail
echo Build failed.
exit /b 1
