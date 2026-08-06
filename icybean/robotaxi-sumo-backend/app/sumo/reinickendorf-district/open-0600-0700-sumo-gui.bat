@echo off
set "SUMO_GUI=C:\Program Files (x86)\Eclipse\Sumo\bin\sumo-gui.exe"
set "SCENARIO_DIR=%~dp0"

if not exist "%SUMO_GUI%" (
  echo Could not find SUMO-GUI at:
  echo %SUMO_GUI%
  echo.
  echo Please edit this launcher if SUMO is installed somewhere else.
  pause
  exit /b 1
)

start "" "%SUMO_GUI%" -c "%SCENARIO_DIR%reinickendorf-district-0600-0700.sumocfg"
