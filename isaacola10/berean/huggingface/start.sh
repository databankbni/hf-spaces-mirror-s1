#!/bin/sh
set -e

# Start the backend in the background so the PUBLIC port binds immediately
# (HF marks the Space healthy as soon as :7860 accepts connections; the UI
# shows "Warming up…" until the backend is ready).
(
  cd /app/backend
  # The index is baked into the image. Only rebuild if it's somehow missing
  # (slow on a free CPU — avoid by shipping the prebuilt index).
  if [ ! -f data/verse_emb_int8.npy ]; then
    echo "No prebuilt index found — building (this is slow on CPU)…"
    /opt/venv/bin/python download_versions.py
    /opt/venv/bin/python build_index.py
  fi
  exec /opt/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
) &

# Public Next.js server on the HF Space port (binds right away).
cd /app/web
exec node server.js
