FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend \
    HF_HOME=/tmp/hf_cache \
    TRANSFORMERS_CACHE=/tmp/hf_cache \
    SENTENCE_TRANSFORMERS_HOME=/tmp/hf_cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
    tesseract-ocr tesseract-ocr-vie \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# HF Spaces ghi được vào /app, nhưng bảo đảm các thư mục runtime tồn tại + writable
RUN mkdir -p /app/data/tmp_pdfs /app/index /app/cache /tmp/hf_cache \
    && chmod -R 777 /app/data /app/index /app/cache /tmp/hf_cache

EXPOSE 7860

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "7860"]
