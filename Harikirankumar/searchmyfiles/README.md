---
title: SearchMyFiles
emoji: 🔍
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
short_description: OCR doc search for PDFs & images
---

## Environment

Set these in Space Variables/Secrets:

- `OCR_API_PASSWORD`: optional. If set, all `/api/*` OCR routes require auth.
- `HF_TOKEN`: used only for local deploy script.
- `HF_SPACE_NAME`: optional local deploy target name.

## Desktop App (Windows EXE)

This project can be packaged as a desktop application that opens in a native window.

### What was added

- Desktop launcher: `desktop_app.py`
- Windows icon: `assets/app_icon.ico`
- Desktop build requirements: `requirements-desktop.txt`
- Build scripts:
	- `build_desktop.ps1`
	- `build_desktop.bat`

### Build EXE

From project root, run either:

```powershell
./build_desktop.ps1
```

or double-click:

- `build_desktop.bat`

Output:

- `dist/PortableOCRStudio.exe`

### Run desktop app

- Launch `dist/PortableOCRStudio.exe`
- It opens a desktop window and starts the local OCR server internally.
- Portable Tesseract from `portable_tesseract/Tesseract-OCR` is used automatically when available.

## API Authentication

If `OCR_API_PASSWORD` is set, call with one of:

- Header `X-API-Key: <password>`
- Header `Authorization: Bearer <password>`
- Query `?api_key=<password>` (supported for image preview route)

## External API Examples

Use your Space runtime URL as base (not the Hugging Face page URL):

- `https://<username>-<space-name>.hf.space`

Example:

- `https://harikirankumar-searchmyfiles.hf.space`

Upload file:

```bash
BASE_URL="https://harikirankumar-searchmyfiles.hf.space"

curl -X POST "$BASE_URL/api/upload" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-F "file=@sample.pdf"
```

OCR one page:

```bash
curl -X POST "$BASE_URL/api/ocr" \
	-H "Content-Type: application/json" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-d '{"file_id":"<FILE_ID>","page":1,"lang":"eng","psm":3}'
```

One-shot OCR with base64 input, no file storage, no file_id:

```bash
FILE_B64=$(base64 -w 0 sample.pdf)

curl -X POST "$BASE_URL/api/ocr_once" \
	-H "Content-Type: application/json" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-d "{\"filename\":\"sample.pdf\",\"file_base64\":\"$FILE_B64\",\"page\":1,\"lang\":\"eng\",\"psm\":3}"
```

If you want all pages in one call:

```bash
FILE_B64=$(base64 -w 0 sample.pdf)

curl -X POST "$BASE_URL/api/ocr_once" \
	-H "Content-Type: application/json" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-d "{\"filename\":\"sample.pdf\",\"file_base64\":\"$FILE_B64\",\"start_page\":1,\"end_page\":3,\"lang\":\"eng\",\"psm\":3}"
```

Request fields for `/api/ocr_once`:

- `file_base64`: required, raw base64 string or full data URL
- `filename`: optional but recommended, used to detect pdf/image type
- `file_type`: optional override, either `pdf` or `image`
- `page`: optional single-page OCR
- `start_page`, `end_page`: optional range OCR when `page` is not provided
- `region`: optional crop object for single-page OCR: `{"x":120,"y":200,"w":600,"h":280}`
- `lang`: optional, default `eng`
- `psm`: optional, default `3`

The `/api/ocr_once` route does not create a server session and returns `stored: false` in the response.

OCR selected region:

```bash
curl -X POST "$BASE_URL/api/ocr" \
	-H "Content-Type: application/json" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-d '{"file_id":"<FILE_ID>","page":1,"lang":"eng","psm":6,"region":{"x":120,"y":200,"w":600,"h":280}}'
```

OCR all pages:

```bash
curl -X POST "$BASE_URL/api/ocr_all" \
	-H "Content-Type: application/json" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-d '{"file_id":"<FILE_ID>","lang":"eng","psm":3,"start_page":1,"end_page":10}'
```

Generate searchable PDF (async, recommended for larger files):

```bash
# 1) Start job
curl -X POST "$BASE_URL/api/download_ocr_pdf_start" \
	-H "Content-Type: application/json" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-d '{"file_id":"<FILE_ID>","lang":"eng","psm":3}'

# Response -> {"job_id":"...","status":"queued","total_pages":N}

# 2) Poll status
curl "$BASE_URL/api/download_ocr_pdf_status/<JOB_ID>" \
	-H "X-API-Key: YOUR_PASSWORD"

# 3) Download when status is done
curl "$BASE_URL/api/download_ocr_pdf_result/<JOB_ID>" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-o searchable_ocr.pdf
```

Generate searchable PDF (single blocking call, only for smaller files):

```bash
curl "$BASE_URL/api/download_ocr_pdf/<FILE_ID>?lang=eng&psm=3" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-o searchable_ocr.pdf
```

Batch searchable PDF export (multiple uploaded files as ZIP):

```bash
# 1) Start batch job
curl -X POST "$BASE_URL/api/download_ocr_pdf_batch_start" \
	-H "Content-Type: application/json" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-d '{"file_ids":["<FILE_ID_1>","<FILE_ID_2>"],"lang":"eng","psm":3}'

# Response -> {"job_id":"...","status":"queued","total_docs":N,"total_pages":M}

# 2) Poll batch status
curl "$BASE_URL/api/download_ocr_pdf_batch_status/<JOB_ID>" \
	-H "X-API-Key: YOUR_PASSWORD"

# 3) Download ZIP when status is done
curl "$BASE_URL/api/download_ocr_pdf_batch_result/<JOB_ID>" \
	-H "X-API-Key: YOUR_PASSWORD" \
	-o searchable_ocr_batch.zip
```

Quality dashboard APIs:

```bash
# Per-page quality metrics
curl "$BASE_URL/api/quality/<FILE_ID>/1" \
	-H "X-API-Key: YOUR_PASSWORD"

# Full document quality summary and flagged pages
curl "$BASE_URL/api/quality_summary/<FILE_ID>" \
	-H "X-API-Key: YOUR_PASSWORD"
```
