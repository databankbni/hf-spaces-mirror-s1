#!/bin/sh
set -e

MODEL_PATH="${MODEL_PATH:-/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf}"
PORT="${PORT:-7860}"

mkdir -p /models

if [ ! -f "$MODEL_PATH" ]; then
  echo "[llm] Downloading Qwen2.5-7B-Instruct Q4_K_M (~4.4GB) ..."
  curl -L --retry 5 --retry-delay 5 -o "$MODEL_PATH" "$MODEL_URL"
  echo "[llm] Download complete."
else
  echo "[llm] Model already present — skipping download."
fi

echo "[llm] Starting FastAPI server on port ${PORT} ..."
exec python /app/app.py
