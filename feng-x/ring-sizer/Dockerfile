FROM python:3.11-slim

# System deps required by OpenCV and MediaPipe
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 libgles2 libegl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure upload/result dirs exist
RUN mkdir -p web_demo/uploads web_demo/results

ENV PORT=7860
ENV PYTHONUNBUFFERED=1

EXPOSE ${PORT}

CMD gunicorn --bind 0.0.0.0:${PORT} --timeout 120 --workers 2 web_demo.app:app
