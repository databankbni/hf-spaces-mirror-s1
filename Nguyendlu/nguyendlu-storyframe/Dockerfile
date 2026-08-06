FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-vie \
    git \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user and set workspace
RUN useradd -m -u 1000 user
WORKDIR /app

# Clone storyframe-plus repository and install it
RUN git clone https://github.com/nguyennhuanhle/storyframe-plus.git /app/storyframe-plus

# Copy our patched cli.py file to bypass SSL in yt-dlp
COPY cli.py /app/storyframe-plus/storyframe_cli/cli.py

RUN cd /app/storyframe-plus && pip install --no-cache-dir -e ".[local]"

# Copy requirements and install backend dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Configure yt-dlp to bypass SSL verification globally
RUN mkdir -p /etc && echo "--no-check-certificate" > /etc/yt-dlp.conf && \
    mkdir -p /root/.config/yt-dlp && echo "--no-check-certificate" > /root/.config/yt-dlp/config && \
    mkdir -p /home/user/.config/yt-dlp && echo "--no-check-certificate" > /home/user/.config/yt-dlp/config && \
    chown -R user:user /home/user

# Copy local backend app
COPY app.py /app/app.py

# Set permissions for Hugging Face compatibility
RUN mkdir -p /app/outputs && chown -R user:user /app

# Switch to non-root user
USER user

# Expose port (Hugging Face default)
EXPOSE 7860

# Run FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
