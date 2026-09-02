FROM python:3.11-slim

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*
USER user

COPY --chown=user requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . /app

ENV HOST=0.0.0.0
ENV PORT=7860
ENV DB_PATH=/app/data/healthcare.db
ENV UPLOAD_DIR=/app/uploads
# Groq retired llama-3.3-70b-versatile on 2026-08-16; keep a live default in-image.
ENV GROQ_MODEL=openai/gpt-oss-20b
ENV ENABLE_CONTEXT_WEB_SEARCH=1
ENV WEB_SEARCH_ENABLED=1
ENV WEB_SEARCH_TIMEOUT_SECONDS=8

RUN mkdir -p /app/data /app/uploads

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
