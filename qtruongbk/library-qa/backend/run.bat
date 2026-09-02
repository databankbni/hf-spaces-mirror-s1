@echo off
REM Khởi động backend bằng Python trong venv (Windows CMD).
REM Dùng: run.bat [port]
SETLOCAL
SET "PORT=%~1"
IF "%PORT%"=="" SET "PORT=8000"

SET "HERE=%~dp0"
SET "VPY=%HERE%venv\Scripts\python.exe"
IF NOT EXIST "%VPY%" SET "VPY=%HERE%..\venv\Scripts\python.exe"

IF NOT EXIST "%VPY%" (
    echo Khong tim thay venv o backend\venv hoac root venv
    echo Tao venv: python -m venv venv ^&^& venv\Scripts\activate ^&^& pip install -r backend\requirements.txt
    exit /b 1
)

echo Dung Python: %VPY%

cd /d "%HERE%"
"%VPY%" -m uvicorn api:app --host 0.0.0.0 --port %PORT% --reload
ENDLOCAL
