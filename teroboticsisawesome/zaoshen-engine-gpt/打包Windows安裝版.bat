@echo off
chcp 65001 >nul
title 造神引擎 RPA Windows 安裝版打包
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0打包Windows安裝版.ps1"
echo.
pause
