FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRADIO_SERVER_NAME=0.0.0.0 \
    GRADIO_SERVER_PORT=7860

WORKDIR /app
COPY requirements.txt packages.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install -r requirements.txt
COPY . .
EXPOSE 7860
CMD ["python", "app.py"]
