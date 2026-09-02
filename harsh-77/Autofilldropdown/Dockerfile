# Use official Python 3.10 slim image
FROM python:3.10-slim

# Set environment variables
# - PYTHONUNBUFFERED: Prevents Python from buffering stdout/stderr
# - PYTHONDONTWRITEBYTECODE: Prevents Python from writing .pyc files
# - HF_HOME: Specifies the directory where Hugging Face downloads and caches models
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/model_cache \
    PORT=8000

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies
# Note: ffmpeg is required by faster-whisper for handling audio uploads and conversions
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file to the container
COPY requirements.txt .

# Upgrade pip and install Python packages
# This is cached by Docker unless requirements.txt changes
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the application source code
COPY . .

# Expose the application port
EXPOSE 8000

# Run the FastAPI server via Uvicorn
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
