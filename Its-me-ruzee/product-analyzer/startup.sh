#!/bin/sh
set -e

echo "===== Product Analyzer v2.0 ====="

# Fix DNS resolution for HF Inference API (runtime, not build)
echo "nameserver 8.8.8.8" > /etc/resolv.conf 2>/dev/null || true
echo "nameserver 8.8.4.4" >> /etc/resolv.conf 2>/dev/null || true

# Validate HF token
python -c "import os; t=os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN'); print(f'Token: {t[:8]}...' if t else 'WARNING: HF_TOKEN not set')" 2>/dev/null || true

echo "--- Starting uvicorn ---"
exec uvicorn main:app --host 0.0.0.0 --port 7860
