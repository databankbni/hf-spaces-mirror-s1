param(
    [string]$Message = "Update Stremio catalog addon"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        $safeArguments = ($Arguments -join ' ') -replace 'hf_[A-Za-z0-9]+', 'hf_***'
        throw "Comando fallito: $Command $safeArguments"
    }
}

if (-not $env:HF_TOKEN) {
    $env:HF_TOKEN = [Environment]::GetEnvironmentVariable("HF_TOKEN", "User")
}

if (-not $env:HF_TOKEN) {
    Write-Host "HF_TOKEN non trovato." -ForegroundColor Yellow
    Write-Host "Crea un token su https://huggingface.co/settings/tokens con permesso Write,"
    Write-Host "poi esegui in PowerShell: [Environment]::SetEnvironmentVariable('HF_TOKEN','hf_xxx','User')"
    exit 1
}

$remote = "https://vito200204:$env:HF_TOKEN@huggingface.co/spaces/vito200204/stremio-trakt-personal.hf.space"

Invoke-Checked python @("-m", "py_compile", "app.py")

$gitName = git config user.name
if (-not $gitName) {
    Invoke-Checked git @("config", "user.name", "Vito")
}

$gitEmail = git config user.email
if (-not $gitEmail) {
    Invoke-Checked git @("config", "user.email", "vito200204@users.noreply.huggingface.co")
}

Invoke-Checked git @("fetch", $remote, "main")
$filesToAdd = @(
    "app.py", "README.md", "Dockerfile", "requirements.txt", ".gitignore", "deploy.ps1",
    "nuvio-film-saga-collection.json", "nuvio-marvel-collection.json",
    "stream_sources.json", "legal_torrent_sources.json"
) | Where-Object { Test-Path $_ }
Invoke-Checked git (@("add") + $filesToAdd)

$changes = git diff --cached --name-only
if (-not $changes) {
    $localHead = git rev-parse HEAD
    $remoteHead = git rev-parse FETCH_HEAD
    if ($localHead -eq $remoteHead) {
        Write-Host "Nessuna modifica da pubblicare."
        exit 0
    }

    Write-Host "Nessuna nuova modifica locale, ma ci sono commit pronti da pubblicare."
    Invoke-Checked git @("push", $remote, "HEAD:main")
    Write-Host "Pubblicato su Hugging Face. Lo Space inizierà il rebuild automatico." -ForegroundColor Green
    Write-Host "Manifest: https://vito200204-stremio-trakt-personal-hf-space.hf.space/manifest.json"
    exit 0
}

Invoke-Checked git @("commit", "-m", $Message)
Invoke-Checked git @("rebase", "FETCH_HEAD")
Invoke-Checked git @("push", $remote, "HEAD:main")

Write-Host "Pubblicato su Hugging Face. Lo Space inizierà il rebuild automatico." -ForegroundColor Green
Write-Host "Manifest: https://vito200204-stremio-trakt-personal-hf-space.hf.space/manifest.json"
