# Hugging Face Spaces (Docker SDK) image for the call-in podcast.
# Uses Pipecat's plain WebSocket transport — audio rides the HTTPS connection,
# so no UDP/TURN is needed behind the Spaces proxy.

FROM python:3.12-slim

# git: pip install from git main; libgomp1: ctranslate2 (faster-whisper);
# libgl1 + libglib2.0-0: opencv (pulled in by the webrtc extra)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR /app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Smaller Whisper model for CPU Spaces; override in Space variables if you
# upgrade the hardware.
ENV WHISPER_MODEL=tiny

# Bake the local STT/TTS models into the image so cold starts are fast.
RUN python -c "from pipecat.services.kokoro.tts import KokoroTTSService as K; K(settings=K.Settings(voice='am_michael')); K(settings=K.Settings(voice='af_heart'))" && \
    python -c "import os; from pipecat.services.whisper.stt import WhisperSTTService as W; W(settings=W.Settings(model=os.environ['WHISPER_MODEL']))"

COPY --chown=user . .

EXPOSE 7860

CMD ["python", "bot.py"]
