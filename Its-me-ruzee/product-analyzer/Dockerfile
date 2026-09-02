FROM python:3.11-slim

WORKDIR /app

# Fix UTF-8 encoding for Tamil/Sinhala characters in prohibited.json
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# System dependencies for Pillow
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

EXPOSE 7860

# No local models to pre-download — all inference via HF Inference API.
# Startup is instant. Just launch uvicorn.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
