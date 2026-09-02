# Sync repo -> hf-space/ for Hugging Face Spaces deploy.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dest = Join-Path $RepoRoot "hf-space"

New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $RepoRoot "Dockerfile") -Destination $dest -Force
Copy-Item (Join-Path $RepoRoot "README.md") -Destination $dest -Force
Copy-Item (Join-Path $RepoRoot ".dockerignore") -Destination $dest -Force

robocopy (Join-Path $RepoRoot "backend") (Join-Path $dest "backend") /MIR /XD tests __pycache__ .pytest_cache .mypy_cache .ruff_cache /XF *.log /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
robocopy (Join-Path $RepoRoot "frontend") (Join-Path $dest "frontend") /MIR /XD node_modules __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
# LlamaParse / Textract extractors are loaded from REPO_ROOT/scripts/ at runtime.
robocopy (Join-Path $RepoRoot "scripts") (Join-Path $dest "scripts") /MIR /XD __pycache__ /XF *.log /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

Write-Host "Synced repo -> hf-space ($dest)"
