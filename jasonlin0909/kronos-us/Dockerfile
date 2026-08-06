FROM python:3.11-slim

WORKDIR /app

# HF Spaces runs as a non-root user (uid 1000); cache HF downloads in a writable dir.
ENV HF_HOME=/app/.cache/huggingface \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/.cache && chmod -R 777 /app/.cache

EXPOSE 7860
CMD ["python", "app.py"]
