# ═══════════════════════════════════════════════════════════════════
# Dockerfile — Hardware Vision API
# Otimizado para Hugging Face Spaces (porta 7860)
# ═══════════════════════════════════════════════════════════════════

FROM python:3.11-slim

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código e os modelos
COPY main.py .
COPY best_v3.pt .
COPY best_v2.pt .

# Valida que o modelo principal carrega corretamente (sem rede necessária)
RUN python3 -c "from ultralytics import YOLO; m = YOLO('best_v3.pt'); print('OK:', list(m.names.values()))"

# Hugging Face Spaces usa porta 7860
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 7860"]