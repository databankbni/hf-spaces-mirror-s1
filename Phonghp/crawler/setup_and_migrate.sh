#!/usr/bin/env bash
set -euo pipefail

# Script to activate the existing venv at backend/venv, install requirements,
# run prisma codegen and run the migration to add RefreshToken.
# Usage: from repo root run `bash backend/setup_and_migrate.sh`

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-venv}"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "Virtualenv not found at $VENV_DIR. Please create or point VENV_DIR to a valid venv." >&2
  exit 2
fi

echo "Activating venv: $VENV_DIR"
. "$VENV_DIR/bin/activate"

LOGFILE="/tmp/web-convert-setup.log"
echo "Logging output to $LOGFILE"

echo "Upgrading pip/setuptools/wheel..." | tee "$LOGFILE"
python -m pip install --upgrade pip setuptools wheel 2>&1 | tee -a "$LOGFILE"

echo "Installing requirements..." | tee -a "$LOGFILE"
python -m pip install -r requirements.txt 2>&1 | tee -a "$LOGFILE"

echo "Running prisma codegen..." | tee -a "$LOGFILE"
python -m prisma py generate 2>&1 | tee -a "$LOGFILE"

echo "Running prisma migrate dev --name add_refresh_token (interactive)..." | tee -a "$LOGFILE"
echo "If prisma prompts, follow the interactive prompts. Press Ctrl+C to cancel." | tee -a "$LOGFILE"
python -m prisma migrate dev --name add_refresh_token 2>&1 | tee -a "$LOGFILE"

echo "Done. See $LOGFILE for full output. If migration succeeded, start the app with:"
echo "  uvicorn main:app --reload"
