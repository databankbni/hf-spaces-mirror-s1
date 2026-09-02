# Start the v2 RICS backend for local testing.
# Run from repo root:  .\backend\scripts\start_server.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $RepoRoot

$DataDir = Join-Path $RepoRoot ".rics_v2_data"
New-Item -ItemType Directory -Force -Path (Join-Path $DataDir "tmp") | Out-Null

$env:DATA_DIR = $DataDir
$env:MASTER_TEMPLATE_AUTO_INGEST = "false"
# Reference ingest follows .env (REFERENCE_AUTO_INGEST_ENABLED=true loads past reports).
# jina-reranker-v3 warmup off locally: lazy-loads on first reference mapping
# (small Windows paging file can hard-abort an eager startup load).
$env:REFERENCE_CROSS_ENCODER_WARMUP = "false"
$env:SPACY_MODEL = "en_core_web_sm"
# Use CUDA only when torch was built with GPU support; CPU-only torch crashes on device=cuda.
$cudaOk = & python -c "import torch; print('1' if torch.cuda.is_available() else '0')" 2>$null
if ($cudaOk -eq "1") {
    $env:LOCAL_EMBEDDING_DEVICE = "cuda"
} else {
    $env:LOCAL_EMBEDDING_DEVICE = "cpu"
    Write-Host "LOCAL_EMBEDDING_DEVICE=cpu (no CUDA torch/GPU)"
}
$env:LOCAL_EMBEDDING_BATCH_SIZE = "4"
$env:LOCAL_EMBEDDING_DTYPE = "bfloat16"
# Cap parallel section workers (default 54 OOM-kills the process on 4 GB GPU / small paging file).
# 2 is safer for long 26–30 section runs on 16 GB RAM + small Windows paging file.
$env:SECTION_CONCURRENCY = "2"
$env:MAX_CONCURRENT_LLM_CALLS = "2"
# Regex-only PII during generation — spaCy NER + jina embedder + reranker exhaust host RAM mid-run.
$env:PII_USE_SPACY = "false"
# jina-reranker-v3 on CPU: it cannot share the 4 GB card with the resident embedder
# (native CUDA/driver hard-abort mid-generation). Embedder stays on cuda above.
$env:REFERENCE_CROSS_ENCODER_DEVICE = "cpu"

Write-Host "DATA_DIR=$($env:DATA_DIR)"
Write-Host "REFERENCE_CROSS_ENCODER_WARMUP=$($env:REFERENCE_CROSS_ENCODER_WARMUP)"
Write-Host "SPACY_MODEL=$($env:SPACY_MODEL)"
Write-Host "Starting http://127.0.0.1:8000 ..."
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
