FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# Copy application code
COPY app ./app

# Copy env file (fallback — HF Secrets override these at runtime)
# Note: In production on HF Spaces, set all vars in the Secrets UI instead.
# This .env is a local fallback for the Docker image.

# Expose Hugging Face Spaces default port
EXPOSE 7860

# Run application on port 7860 (HF Spaces standard)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--log-level", "info"]
