.PHONY: install server dev hf test test-with-server deploy-hf docker-build docker-run clean ocr ocr-c4 ocr-test

PYTHON ?= python3
APP ?= app.main:app
HOST ?= 0.0.0.0
PORT ?= 4033

install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m playwright install chromium

# ---------------------------------------------------------------------------
# HTTP server (FastAPI) — full REST API + browser UI + MCQ generation
# ---------------------------------------------------------------------------
server:
	uvicorn $(APP) --host $(HOST) --port $(PORT)

dev:
	uvicorn $(APP) --host $(HOST) --port $(PORT) --reload

hf:
	uvicorn $(APP) --host 0.0.0.0 --port 7860

test:
	$(PYTHON) scripts/smoke_test.py --base-url http://127.0.0.1:$(PORT)

test-with-server:
	bash -lc 'set -euo pipefail; uvicorn $(APP) --host 127.0.0.1 --port $(PORT) > /tmp/ocr-automation-$(PORT).log 2>&1 & pid=$$!; trap "kill $$pid 2>/dev/null || true" EXIT; $(PYTHON) scripts/smoke_test.py --base-url http://127.0.0.1:$(PORT)'

# ---------------------------------------------------------------------------
# CLI wrapper — split & combine in parallel, no server needed
# ---------------------------------------------------------------------------
#   make ocr                   → 17-page test PDF, c=2, → ../ocr-result.json
#   make ocr PDF=mine.pdf      → custom PDF
#   make ocr-c4                → c=4 for max speed
#   make ocr-test              → quick smoke test (one chunk only)
OCR_PDF ?= /teamspace/studios/this_studio/works/tests/ocrwitholmcor/92d1b467-89a5-43ec-b155-74a815680461.pdf
OCR_OUT ?= /teamspace/studios/this_studio/works/ocr-result.json
OCR_PPC ?= 6
OCR_CONC ?= 2

ocr:
	bash ./ocr-automation.sh "$(OCR_PDF)" "$(OCR_OUT)" "$(OCR_PPC)" "$(OCR_CONC)"

ocr-c4:
	$(MAKE) ocr OCR_CONC=4

ocr-test:
	$(PYTHON) ./olmocr-split-combine.py "$(OCR_PDF)" 6 1

# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------
deploy-hf:
	bash scripts/deploy_hf.sh

docker-build:
	docker build -t ocr-automation-hf .

docker-run:
	docker run --rm -p 7860:7860 ocr-automation-hf

clean:
	rm -rf outputs/api .pytest_cache __pycache__ app/__pycache__ scripts/__pycache__
