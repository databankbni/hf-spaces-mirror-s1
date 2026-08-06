param(
    [switch]$SkipNodeInstall
)

$ErrorActionPreference = 'Stop'

function Test-CommandExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host '[1/4] Checking Node.js...' -ForegroundColor Cyan
if (-not (Test-CommandExists -Name 'node')) {
    if ($SkipNodeInstall) {
        throw 'Node.js is not installed. Install Node.js LTS first, then re-run this script.'
    }

    if (-not (Test-CommandExists -Name 'winget')) {
        throw 'Node.js is missing and winget is unavailable. Install Node.js LTS manually and re-run.'
    }

    Write-Host 'Node.js not found. Installing Node.js LTS with winget...' -ForegroundColor Yellow
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

if (-not (Test-CommandExists -Name 'node')) {
    throw 'Node.js is still not available on PATH after installation. Restart terminal and run again.'
}
if (-not (Test-CommandExists -Name 'npm')) {
    throw 'npm is not available even though Node.js exists. Reinstall Node.js LTS.'
}

Write-Host '[2/4] Installing npm dependencies...' -ForegroundColor Cyan
npm install

Write-Host '[3/4] Compiling extension...' -ForegroundColor Cyan
npm run compile

Write-Host '[4/4] Packaging VSIX...' -ForegroundColor Cyan
npx @vscode/vsce package --no-dependencies

$vsix = Get-ChildItem -Path $scriptDir -Filter '*.vsix' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $vsix) {
    throw 'Packaging finished but no .vsix file was found.'
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green
Write-Host ("VSIX: " + $vsix.FullName) -ForegroundColor Green
Write-Host 'Install it in VS Code: Extensions view (...) -> Install from VSIX...' -ForegroundColor Green
