# Dockerfile para Hugging Face Spaces (Docker SDK).
# HF ejecuta el contenedor como usuario UID 1000; solo /tmp y HOME son escribibles.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp \
    IDF_SESSIONS_DIR=/tmp/idf-sesiones \
    IDF_DEFAULT_COMPLETO=1 \
    IDF_SAT_TIMEOUT=45 \
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
        libfreetype6 libpng16-16 libjpeg62-turbo libopenblas0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY webapp/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY src /app/src
COPY webapp /app/webapp
# VERSION lo escribe el workflow de GitHub Actions antes de upload_folder
# con el commit SHA actual; el endpoint /version lo expone para verificar
# qué versión está corriendo. COPY con bracket sintax para que no aborte
# si el archivo no existe (dev local).
COPY *VERSION* /app/

EXPOSE 7860

# HF tiene 2 vCPU / 16 GB: 2 workers para concurrencia (cada uno su matplotlib).
CMD ["sh", "-c", "gunicorn --chdir webapp --bind 0.0.0.0:${PORT:-7860} --workers 2 --threads 1 --timeout 300 --worker-class sync app:app"]
