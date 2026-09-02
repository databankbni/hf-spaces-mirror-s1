# Push hf-space/ to Hugging Face Spaces.
# Usage: $env:HF_TOKEN = "hf_..."; .\backend\scripts\deploy_hf_space.ps1

param(
    [string]$Token = $env:HF_TOKEN,
    [string]$SpaceRepo = "Behrang987/Report-Genius"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $Token) {
    $envFile = Join-Path $RepoRoot ".env.hf"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            $line = $_.Trim()
            if (-not $line -or $line.StartsWith("#")) { return }
            if ($line -match '^HF_TOKEN=(.+)$') {
                $Token = $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
}
$SpaceDir = Join-Path $RepoRoot "hf-space"
& (Join-Path $RepoRoot "backend\scripts\sync_hf_space.ps1")

if (-not $Token) {
    Write-Host "HF write token required. Set `$env:HF_TOKEN, pass -Token, or put HF_TOKEN in .env.hf."
    exit 1
}

Set-Location $SpaceDir
if (-not (Test-Path ".git")) { git init; git branch -M main }

$remoteUrl = "https://Behrang987:$Token@huggingface.co/spaces/$SpaceRepo"
$remotes = @(git remote 2>$null)
if ($remotes -contains "origin") { git remote set-url origin $remoteUrl }
else { git remote add origin $remoteUrl }

git add Dockerfile README.md .dockerignore backend frontend scripts
$status = git status --porcelain
if ($status) {
    git commit -m "Deploy RICS v2 (senior baseline, CPU Spaces Dockerfile)"
}
Write-Host "Pushing to huggingface.co/spaces/$SpaceRepo ..."
git push -u origin main --force
Write-Host "Done: https://huggingface.co/spaces/$SpaceRepo"
