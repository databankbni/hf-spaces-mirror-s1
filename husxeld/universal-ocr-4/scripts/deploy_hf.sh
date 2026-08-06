#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Load only the deployment variables via python-dotenv. Do not source arbitrary .env files.
eval "$(python - <<'PY'
from pathlib import Path
from dotenv import load_dotenv
import os, shlex
root = Path.cwd()
path = root / '.env'
if path.exists():
    load_dotenv(path, override=False)
for name in ('HF_TOKEN','HF_USERNAME','HF_SPACE_NAME','HF_SPACE_REPO_ID'):
    value = os.getenv(name)
    if value:
        print(f'{name}={shlex.quote(value)}')
PY
)"

: "${HF_TOKEN:?Missing HF_TOKEN in .env or environment}"
: "${HF_USERNAME:?Missing HF_USERNAME in .env or environment}"

SPACE_NAME="${HF_SPACE_NAME:-ocr-mcq-automation}"
REPO_ID="${HF_SPACE_REPO_ID:-${HF_USERNAME}/${SPACE_NAME}}"

printf 'Logging into Hugging Face as %s...\n' "$HF_USERNAME"
hf auth login --token "$HF_TOKEN" --add-to-git-credential >/dev/null

printf 'Creating/updating private Docker Space: %s\n' "$REPO_ID"
hf repo create "$REPO_ID" \
  --type space \
  --space-sdk docker \
  --private \
  --flavor cpu-basic \
  --sleep-time 300 \
  --exist-ok \
  --token "$HF_TOKEN"

printf 'Setting Space secrets and variables (values hidden)...\n'
python scripts/set_hf_space_secrets.py "$REPO_ID"

printf 'Uploading app files to Space...\n'
hf upload "$REPO_ID" . . \
  --repo-type space \
  --token "$HF_TOKEN" \
  --commit-message "Deploy OCR MCQ Automation Studio" \
  --exclude ".git/*" \
  --exclude "__pycache__/*" \
  --exclude "app/__pycache__/*" \
  --exclude "scripts/__pycache__/*" \
  --exclude "outputs/*" \
  --exclude "temp-split/*" \
  --exclude ".env" \
  --exclude ".pytest_cache/*" \
  --exclude ".ruff_cache/*"

printf '\nDone. Space: https://huggingface.co/spaces/%s\n' "$REPO_ID"
printf 'App URL after build: https://%s-%s.hf.space\n' "$HF_USERNAME" "$SPACE_NAME"
printf 'Build logs: hf spaces logs %s --build\n' "$REPO_ID"
