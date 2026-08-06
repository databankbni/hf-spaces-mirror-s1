#!/bin/bash
#
# OCR Automation Script for olmocr.allenai.org (split & combine, parallel)
#
# Wraps olmocr-split-combine.py, which splits the PDF into chunks of < 10
# pages, processes each chunk through the olmOCR demo in parallel (N
# concurrent browser contexts), and combines the per-page results into
# a single ocr-result.json.
#
# Bypasses the demo's hard 10-page limit. Works on PDFs of any size.
#
# Usage:
#   ./ocr-automation.sh [PDF_PATH] [OUTPUT_JSON] [PAGES_PER_CHUNK] [CONCURRENCY]
#
# Defaults:
#   PDF_PATH         = tests/ocrwitholmcor/92d1b467-89a5-43ec-b155-74a815680461.pdf
#   OUTPUT_JSON      = ocr-result.json
#   PAGES_PER_CHUNK  = 6   (safe margin under the 10-page demo cap)
#   CONCURRENCY      = 2   (parallel browser contexts; 1..4)
#
# Requirements:
#   - python3 with pypdf and playwright installed
#   - playwright chromium browser installed
#       (python3 -m playwright install chromium)
#
# Side effects:
#   - Writes chunk PDFs to ./temp-split/  (cleaned up on success)
#   - Writes a per-run folder under ./outputs/run-<ts>-split-combine/
#   - Copies ocr-result.json to OUTPUT_JSON
#   - Writes ocr-result.txt alongside it

set -eu

PDF_PATH="${1:-/teamspace/studios/this_studio/works/tests/ocrwitholmcor/92d1b467-89a5-43ec-b155-74a815680461.pdf}"
OUTPUT_JSON="${2:-/teamspace/studios/this_studio/works/ocr-result.json}"
PAGES_PER_CHUNK="${3:-6}"
CONCURRENCY="${4:-2}"

# Resolve paths relative to this script's location (now inside ocr-automation/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/olmocr-split-combine.py"
OUT_BASE="$SCRIPT_DIR/outputs"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

command -v python3 >/dev/null 2>&1 || fail "python3 not found"
[ -f "$PY_SCRIPT" ] || fail "split-combine script not found: $PY_SCRIPT"
[ -f "$PDF_PATH" ] || fail "PDF not found: $PDF_PATH"

python3 -c "import pypdf, playwright" 2>/dev/null \
  || fail "missing python deps; run: pip install pypdf playwright && python3 -m playwright install chromium"

log "PDF            : $PDF_PATH"
log "Output JSON    : $OUTPUT_JSON"
log "Pages/chunk    : $PAGES_PER_CHUNK"
log "Concurrency    : $CONCURRENCY  (parallel browser contexts)"
log "Engine script  : $PY_SCRIPT"

# Run the proven split-combine flow.
# OCR_OUTPUT_DIR is consumed by the Python script for its per-run folder.
log "Step 1/3: Running split & combine (this may take several minutes)..."
OCR_PDF_PATH="$PDF_PATH" \
OCR_PAGES_PER_CHUNK="$PAGES_PER_CHUNK" \
OCR_CONCURRENCY="$CONCURRENCY" \
OCR_OUTPUT_DIR="$OUT_BASE" \
python3 "$PY_SCRIPT" "$PDF_PATH" "$PAGES_PER_CHUNK" "$CONCURRENCY"
PY_RC=$?
[ $PY_RC -eq 0 ] || fail "split-combine script exited with code $PY_RC"

# Locate the most recent per-run folder written by the Python script.
RUN_DIR="$(ls -1dt "$OUT_BASE"/run-*-split-combine 2>/dev/null | head -1)"
[ -n "$RUN_DIR" ] && [ -f "$RUN_DIR/ocr-result.json" ] \
  || fail "could not find run-*-split-combine/ocr-result.json under $OUT_BASE"

log "Step 2/3: Run folder: $RUN_DIR"
PAGES_EXTRACTED=$(python3 -c "import json; print(len(json.load(open('$RUN_DIR/ocr-result.json'))['content']['pages']))")
log "Extracted pages: $PAGES_EXTRACTED"

# Step 3: copy the combined result + plain text to the requested locations.
log "Step 3/3: Writing outputs"
cp "$RUN_DIR/ocr-result.json" "$OUTPUT_JSON"
if [ -f "$RUN_DIR/ocr-result.txt" ]; then
  cp "$RUN_DIR/ocr-result.txt" "${OUTPUT_JSON%.json}.txt"
fi

log "Done."
log "  JSON : $OUTPUT_JSON"
[ -f "${OUTPUT_JSON%.json}.txt" ] && log "  Text : ${OUTPUT_JSON%.json}.txt"
log "  Run  : $RUN_DIR"
