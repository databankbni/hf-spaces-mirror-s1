FROM python:3.10-slim

WORKDIR /app

# System deps (if needed)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY . /app

# Install Python deps (include gunicorn for production)
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Expose a common Space port. Hugging Face Spaces forwards 7860 by convention for web apps.
ENV PORT=7860
EXPOSE 7860

# Run with a lightweight Gunicorn server
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:7860", "app:app"]
