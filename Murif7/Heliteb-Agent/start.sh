#!/bin/bash
set -e

echo "=== HELITEB AI Agent — HF Spaces Startup ==="

mkdir -p /data/.cache/huggingface

echo "[start.sh] Starting FastAPI on port 8000..."
uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir /app/agent &
UVICORN_PID=$!

echo "[start.sh] Waiting for FastAPI..."
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "[start.sh] FastAPI ready (after ${i}s)"
        break
    fi
    [ $i -eq 60 ] && echo "[start.sh] WARNING: FastAPI not ready within 60s"
    sleep 1
done

echo "[start.sh] Starting NGINX on port 7860..."
echo "[start.sh] Container ready."

trap 'echo "[start.sh] Shutting down..."; kill ${UVICORN_PID} 2>/dev/null; exit 0' EXIT INT TERM
exec nginx -c /app/nginx.conf -g 'daemon off;'
