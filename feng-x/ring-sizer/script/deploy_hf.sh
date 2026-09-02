#!/usr/bin/env bash
# Deploy current working directory to Hugging Face Spaces
set -euo pipefail

REPO_ID="Feng-X/ring-sizer"
IGNORE='[".venv/*", ".git/*", "__pycache__/*", "*.pyc", "output/*", "web_demo/uploads/*", "web_demo/results/*", "doc/*", ".claude/*", "input/*"]'

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Deployment environment not found: ${PYTHON_BIN}" >&2
    echo "Create it with: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

cd "${REPO_ROOT}"

"${PYTHON_BIN}" -c "
from huggingface_hub import HfApi
HfApi().upload_folder(
    folder_path='.',
    repo_id='${REPO_ID}',
    repo_type='space',
    ignore_patterns=${IGNORE},
)
print('Deployed to https://huggingface.co/spaces/${REPO_ID}')
"
