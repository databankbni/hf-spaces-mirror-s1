# Hugging Face Spaces Docker image with Chromium + Playwright dependencies included.
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OCR_DATA_DIR=/data/ocr-automation \
    OCR_DEFAULT_ENGINE=auto \
    OCR_HF_STORAGE=1 \
    OCR_HF_STORAGE_PRIVATE=1 \
    OCR_HF_STORAGE_PULL=1 \
    OCR_AI_TIMEOUT_SECONDS=900 \
    OCR_PAGES_PER_CHUNK=6 \
    OCR_CHUNK_CONCURRENCY=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/outputs/api /data/ocr-automation /tmp/ocr-automation && \
    chown -R 1000:1000 /app /data/ocr-automation /tmp/ocr-automation

COPY --chown=1000:1000 . /app

USER 1000

# Hugging Face Spaces Docker apps must listen on 7860.
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
