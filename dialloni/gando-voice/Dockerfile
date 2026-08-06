FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch && pip install --no-cache-dir fastapi "uvicorn[standard]" scipy soundfile numpy transformers
ENV HF_HOME=/tmp/hf
COPY voice_api.py /app/voice_api.py
WORKDIR /app
EXPOSE 7860
CMD ["uvicorn", "voice_api:app", "--host", "0.0.0.0", "--port", "7860"]
