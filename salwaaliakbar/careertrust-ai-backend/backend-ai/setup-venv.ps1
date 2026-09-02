<#
.SYNOPSIS
  Creates a Python virtual environment in backend-ai/.venv and installs dependencies.

.DESCRIPTION
  This PowerShell script sets up a Python virtual environment in the current directory,
  upgrades pip, setuptools, wheel, installs dependencies from requirements.txt or via
  Packages parameter. It handles Windows-specific package installation quirks for uvicorn.

.EXAMPLE
  cd backend-ai
  .\setup-venv.ps1

.EXAMPLE
  .\setup-venv.ps1 -Packages fastapi,uvicorn[standard],pillow,numpy,python-multipart,insightface
#>

param(
  [string]$VenvDir = ".venv",
  [string]$Requirements = "requirements.txt",
  [string[]]$Packages
)

$ErrorActionPreference = "Stop"

# Set working directory to script location
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

Write-Host "Setting up Python virtual environment in directory: $VenvDir"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "Python not found in PATH. Please install Python 3.8+ and ensure 'python' command is available."
  exit 1
}

if (-not (Test-Path $VenvDir)) {
  python -m venv $VenvDir
  if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create virtual environment at $VenvDir"
    exit 1
  }
} else {
  Write-Host "Virtual environment already exists at $VenvDir"
}

# Allow script activation for this session
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

Write-Host "Activating virtual environment..."
& .\$VenvDir\Scripts\Activate.ps1

Write-Host "Upgrading pip, setuptools, wheel..."
pip install --upgrade pip setuptools wheel

# On Windows, replace uvicorn[standard] with plain uvicorn to avoid build issues
$tempReq = "$env:TEMP\backend_ai_requirements.txt"
if (Test-Path $Requirements) {
  Get-Content $Requirements | ForEach-Object {
    if ($IsWindows -and $_ -match "^uvicorn\[standard\]") {
      "uvicorn"
    } else {
      $_
    }
  } | Set-Content $tempReq -Encoding UTF8
}

# Install packages
if (Test-Path $Requirements) {
  Write-Host "Installing packages from $Requirements..."
  pip install -r $tempReq
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "pip install failed from requirements.txt, check error messages above."
    exit 1
  }
} elseif ($Packages -and $Packages.Count -gt 0) {
  Write-Host "Installing packages specified via -Packages parameter: $($Packages -join ', ')"
  pip install $Packages
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "pip install failed for packages: $($Packages -join ', ')"
    exit 1
  }
  Write-Host "Freezing installed packages to requirements.txt"
  pip freeze > requirements.txt
} else {
  Write-Warning "No requirements.txt found and no packages specified. Nothing installed."
}

Write-Host ""
Write-Host "Setup complete! To activate the virtual environment in this session later, run:"
Write-Host "    .\$VenvDir\Scripts\Activate.ps1"
Write-Host "To start FastAPI microservice, run something like:"
Write-Host "    .\$VenvDir\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
Write-Host ""
Write-Host "For further assistance, see README.md or documentation."

Exit 0
