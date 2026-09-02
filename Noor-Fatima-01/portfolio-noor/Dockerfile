FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose the Hugging Face Space port
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port = int(os.getenv('PORT', '7860')); urllib.request.urlopen(f'http://localhost:{port}/health', timeout=5).read()" || exit 1

# Run the application - respects PORT environment variable from platform
CMD ["python", "app.py"]
