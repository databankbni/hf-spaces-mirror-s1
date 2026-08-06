#!/bin/sh
set -e

# On first run (empty data volume), fetch translations and build the index.
if [ ! -f data/verse_emb_int8.npy ]; then
  echo "First run: downloading translations and building the index…"
  python download_versions.py
  python build_index.py
fi

exec uvicorn server:app --host 0.0.0.0 --port 8000
