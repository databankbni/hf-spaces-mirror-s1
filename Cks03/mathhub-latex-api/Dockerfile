FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends pandoc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Run as a non-root user — defense in depth. The app never writes to /app
# at runtime (only reads its own source; temp files for docx uploads go to
# the world-writable /tmp), so this needs no extra permission grants.
RUN useradd --no-create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Hugging Face Spaces requires port 7860 — NOT 8080.
EXPOSE 7860
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "60", "app:app"]
