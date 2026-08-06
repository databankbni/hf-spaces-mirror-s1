FROM python:3.10-slim

# Install system dependencies (FFmpeg required for video slicing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements or install directly
COPY requirements.txt* ./
RUN pip install --no-cache-dir fastapi uvicorn yt-dlp pydantic requests SpeechRecognition static-ffmpeg || true

# Copy application files
COPY . /app

# Create clips output directory
RUN mkdir -p /app/clips

EXPOSE 7860

# Start Uvicorn server on Hugging Face default port 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
