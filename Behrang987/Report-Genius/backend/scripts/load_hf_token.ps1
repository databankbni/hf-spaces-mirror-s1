# Load HF_TOKEN from repo-root .env.hf into this PowerShell session.
# Usage (from repo root or anywhere):
#   . .\backend\scripts\load_hf_token.ps1
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$EnvFile = Join-Path $RepoRoot ".env.hf"
if (-not (Test-Path $EnvFile)) {
    Write-Host "Missing $EnvFile — add HF_TOKEN=hf_... there (gitignored)."
    return
}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $i = $line.IndexOf("=")
    if ($i -lt 1) { return }
    $name = $line.Substring(0, $i).Trim()
    $value = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
    if ($name -eq "HF_TOKEN" -and $value) {
        $env:HF_TOKEN = $value
        Write-Host "HF_TOKEN loaded from .env.hf"
    }
}
