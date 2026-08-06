# Phase 1 Deployment Preflight

## Required before Hugging Face Space deployment

1. Set Space SDK to Docker.
2. Set Variables:
   - `HF_DATASET_REPO=<your-username>/football-data-hub`
   - `VENDOR_DIR=vendor/hermes_source`
   - `DEFAULT_COMPANY_IDS=3,24,8`
   - `PYTHON_BIN=/usr/local/bin/python`
3. Set Secrets:
   - `HF_TOKEN=<write-capable token for the dataset repo>`
   - `HF_DATA_HUB_API_KEY=<your private refresh/write key>`
4. Verify `/health` after deployment.
5. Call `/refresh-match` for a known match id.
6. Verify `/match-packet` returns `raw_returned=false`, packet size <= 15KB, and no `final_pick`/bankroll fields.

## Free-HF operating mode

This project does not require HF Jobs. Trigger refreshes externally with Hermes, keepalive, local cron, or GitHub Actions.

## Runtime note

`PYTHON_BIN` now defaults to the running interpreter via `sys.executable`. On Docker Space, `/usr/local/bin/python` is set explicitly. On local Hermes, set `PYTHON_BIN` to the Hermes bundled Python if needed.
