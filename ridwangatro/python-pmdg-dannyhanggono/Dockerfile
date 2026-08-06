# Hugging Face Space - Python PDF Service
# FastAPI service for PDF generation
# HF Space requires port 7860

FROM python:3.12-slim

# HF Space requires port 7860
ENV PORT=7860

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user (HF Space requirement)
RUN useradd -m -u 1000 user
USER user

EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health')"

# Run with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
