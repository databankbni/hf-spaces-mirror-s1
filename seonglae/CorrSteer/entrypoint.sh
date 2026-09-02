#!/bin/bash
set -e

echo "Starting CorrSteer HF Space..."

# Start Flask backend via gunicorn in background
cd /backend
gunicorn --bind 0.0.0.0:5001 --workers 1 --threads 2 --timeout 120 server:app &

# Wait for backend
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:5001/api/health > /dev/null 2>&1; then
        echo "API ready."
        break
    fi
    sleep 1
done

# Start nginx in foreground
exec nginx -g 'daemon off;'
