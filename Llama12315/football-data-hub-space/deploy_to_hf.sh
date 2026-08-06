#!/bin/bash
# HF Data Hub Phase 1 MVP — Deploy Script
# Usage: HF_TOKEN=<token> ./deploy_to_hf.sh
# Requires: hf CLI (pip install huggingface-hub)

set -euo pipefail

echo "=== Phase 1: Create HF Dataset ==="
hf repo create football-data-hub --type dataset --private -y || echo "Repo may already exist"

echo "=== Phase 2: Create HF Space ==="
hf repo create football-data-hub-space --type space --private -y || echo "Space may already exist"
hf space configure football-data-hub-space --docker python:3.11-slim

echo "=== Phase 3: Upload code to Space ==="
# Clean then upload
rm -rf /tmp/hf_deploy_upload
mkdir -p /tmp/hf_deploy_upload
cp -r . /tmp/hf_deploy_upload/
find /tmp/hf_deploy_upload -name "__pycache__" -type d -exec rm -rf {} +
find /tmp/hf_deploy_upload -name ".pytest_cache" -type d -exec rm -rf {} +
find /tmp/hf_deploy_upload -name "*.pyc" -delete
cd /tmp/hf_deploy_upload

# Upload
hf upload football-data-hub-space . --repo-type=space

echo "=== Phase 4: Set Space Variables ==="
hf space variables set football-data-hub-space HF_DATASET_REPO="<HF_USERNAME>/football-data-hub"
hf space variables set football-data-hub-space VENDOR_DIR="vendor/hermes_source"
hf space variables set football-data-hub-space DEFAULT_COMPANY_IDS="3,24,8"
hf space variables set football-data-hub-space MAX_PACKET_KB="15"

echo "=== Phase 5: Set Space Secrets ==="
echo "Run these manually (secrets can't be set via CLI):"
echo "  HF Space -> Settings -> Repository Secrets"
echo "  HF_TOKEN=<your-token>"
echo "  HF_DATA_HUB_API_KEY=<your-api-key>"

echo ""
echo "=== DONE ==="
echo "Wait ~3 min for Space build, then test:"
echo "  curl https://<HF_USERNAME>-football-data-hub-space.hf.space/health"
