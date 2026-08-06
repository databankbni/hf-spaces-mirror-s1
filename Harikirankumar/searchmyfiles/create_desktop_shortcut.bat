@echo off
setlocal ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

set "SHORTCUT_NAME=Portable OCR Studio.lnk"
set "DESKTOP_PATH=%USERPROFILE%\Desktop"
set "TARGET_BAT=%~dp0launch_app.bat"
set "ICON_PATH=%~dp0assets\app_icon.ico"

if not exist "%TARGET_BAT%" (
  echo [ERROR] launch_app.bat not found.
  pause
  exit /b 1
)

if not exist "%ICON_PATH%" (
  echo [WARN] Icon not found at %ICON_PATH%
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws=New-Object -ComObject WScript.Shell;" ^
  "$s=$ws.CreateShortcut((Join-Path $env:USERPROFILE 'Desktop\Portable OCR Studio.lnk'));" ^
  "$s.TargetPath='%TARGET_BAT%';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%ICON_PATH%';" ^
  "$s.Description='Launch Portable OCR Studio';" ^
  "$s.Save()"

if errorlevel 1 (
  echo [ERROR] Could not create desktop shortcut.
  pause
  exit /b 1
)

echo [OK] Desktop shortcut created: "%DESKTOP_PATH%\%SHORTCUT_NAME%"
endlocal
