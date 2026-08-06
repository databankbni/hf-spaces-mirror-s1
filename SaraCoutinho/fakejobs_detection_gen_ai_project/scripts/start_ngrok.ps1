$ErrorActionPreference = "Stop"

$ngrok = Get-Command ngrok -ErrorAction SilentlyContinue

if (-not $ngrok) {
    Write-Host "ngrok nao encontrado no PATH."
    Write-Host "Instale em https://ngrok.com/download e rode:"
    Write-Host "  ngrok config add-authtoken SEU_TOKEN"
    exit 1
}

Write-Host "Abrindo tunnel publico para http://127.0.0.1:8000"
Write-Host "Deixe o servidor local rodando em outro terminal: .\scripts\start_local.ps1"
& $ngrok.Source http 8000
