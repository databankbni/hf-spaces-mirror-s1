#!/bin/bash
# ... (omitted) ...
echo "--- ✅ Setup complete. Starting Gunicorn server... ---"

# MODIFIED: Added --preload flag
# This loads the app (and the embedding model) once in the master process
# before forking workers, saving significant RAM.
LEVEL=$(echo "${LOG_LEVEL:-debug}" | tr '[:upper:]' '[:lower:]')

exec poetry run gunicorn -w 2 -k uvicorn.workers.UvicornWorker \
  --preload \
  --max-requests 500 \
  --bind "0.0.0.0:${PORT:-7860}" \
  --log-level "$LEVEL" \
  --access-logfile - \
  --error-logfile - \
  app:app