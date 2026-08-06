# Use official slim Python image
FROM python:3.12-slim

# Avoid interactive prompts, ensure unbuffered stdout
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Install system packages
RUN apt-get update && apt-get install -y \
    python3-pip \
    build-essential \
    git \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first for efficient layer caching
COPY requirements.txt /tmp/requirements.txt

# Upgrade pip and install Python deps
RUN python3 -m pip install --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /tmp/requirements.txt \
 # sanity-check: print django version (non-fatal)
 && python3 -c "import django; print('DJANGO_VER=', django.__version__)" || true

# Create appuser and make /app writable
RUN useradd -m -u 1000 appuser \
 && mkdir -p /app \
 && chown -R appuser:appuser /app

# Copy application code owned by appuser
COPY --chown=appuser:appuser . /app

# Switch to non-root user for runtime
USER appuser
ENV HOME=/home/appuser
WORKDIR /app

# GEE credentials (pass at runtime via docker run -e or docker-compose)
ENV GEE_SERVICE_ACCOUNT=""
ENV GEE_KEY_FILE="/app/climate-change-0-2dcbf7ec3d1c.json"

# Expose Django default port
EXPOSE 7860

# Start Django
WORKDIR /app
CMD ["sh", "-c", "\
  python manage.py migrate 2>&1 && \
  gunicorn config.wsgi:application \
    --bind 0.0.0.0:7860 \
    --workers 2 \
    --timeout 120 \
"]