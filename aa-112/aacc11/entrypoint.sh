#!/bin/sh
set -e

if [ -n "$AUTH_FILES_B64" ]; then
    echo "Importing auth files from AUTH_FILES_B64..."
    echo "$AUTH_FILES_B64" | base64 -d | tar -xz -C /app/auth/
fi

exec /app/cli-proxy-api -config /app/config.yaml
