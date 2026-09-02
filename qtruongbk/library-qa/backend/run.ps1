#!/usr/bin/env pwsh
# Khởi động backend bằng Python trong venv để đảm bảo các package
# như pymupdf (fitz), pdfplumber, sentence-transformers... đều có sẵn.
#
# Cách dùng:
#   .\run.ps1                    -> chạy reload mode, port 8000
#   .\run.ps1 -Port 7860         -> đổi port
#   .\run.ps1 -NoReload          -> tắt --reload

param(
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $here

# Ưu tiên venv ở backend\venv, fallback sang venv ở root project
$venvPython = Join-Path $here "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Không tìm thấy venv ở $here\venv hoặc $projectRoot\venv" -ForegroundColor Red
    Write-Host "Tạo venv: python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r backend\requirements.txt"
    exit 1
}

Write-Host "Dùng Python: $venvPython" -ForegroundColor Cyan

$args = @("-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "$Port")
if (-not $NoReload) { $args += "--reload" }

Push-Location $here
try {
    & $venvPython @args
} finally {
    Pop-Location
}
