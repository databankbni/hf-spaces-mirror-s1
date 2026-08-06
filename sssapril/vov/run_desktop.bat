@echo off
chcp 65001 >nul 2>&1
title AgentFlow Desktop
cd /d "%~dp0server"
python -m app.desktop
pause
