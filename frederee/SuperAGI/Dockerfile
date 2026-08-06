FROM python:3.12-slim

ARG INSTALL_SUPERAGI_DEPS=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/python_backend \
    PORT=7860 \
    SUPERAGI_HOST=0.0.0.0 \
    SUPERAGI_CHAT_DB=/data/chat.sqlite3

WORKDIR /app

COPY python_backend/requirements.txt python_backend/requirements.txt
COPY python_backend/requirements-superagi.txt python_backend/requirements-superagi.txt
COPY Dockerfile Makefile huggingface.README.md ./

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r python_backend/requirements.txt \
    && if [ "$INSTALL_SUPERAGI_DEPS" = "true" ]; then \
         pip install --no-cache-dir -r python_backend/requirements-superagi.txt; \
       fi

COPY python_backend python_backend

RUN mkdir -p /data \
    && useradd --create-home --shell /usr/sbin/nologin superagi \
    && chown -R superagi:superagi /app /data

USER superagi

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=3).read()"

CMD ["python", "-m", "superagi_backend.production"]
