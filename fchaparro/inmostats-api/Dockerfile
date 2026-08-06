# Imagen para la API (src/api/) desplegada en Hugging Face Spaces.
#
# NOTA: esta rama (space-deploy) sirve solo para empujar el contenido del
# Space -no es un reflejo 1:1 del Dockerfile de la rama master-. HF Spaces
# rechaza archivos de mas de 10MB por git push, y varios CSV de data/raw/
# (necesarios para entrenar desde cero, como hace el Dockerfile de master)
# superan ese limite. Se probo empujar el modelo ya entrenado via Git LFS,
# pero el build de HF fallo al resolverlo (COPY con "cache miss"); en vez
# de depender de esa caja negra, el modelo se descarga de un GitHub
# Release (sin limite de tamano ni LFS) durante el build. Esta rama nunca
# se mergea a master.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

# python:3.12-slim no trae curl instalado; se usa requests (ya en
# requirements.txt) para no depender de apt-get.
# Cache-bust: modelo actualizado 2026-07-30 (reentrenado sobre 82.336
# anuncios tras el crecimiento del dataset del cron). Docker cachea este
# RUN por su texto exacto -sin cambiar algo aca, redesplegar con el mismo
# Dockerfile reusaria la capa vieja y NO volveria a descargar el modelo
# nuevo aunque el asset del Release ya se haya actualizado.
RUN mkdir -p models \
    && python -c "import requests; \
open('models/price_model.joblib', 'wb').write(requests.get('https://github.com/FaiberCh/inmostats/releases/download/model-v1/price_model.joblib').content); \
open('models/feature_config.json', 'wb').write(requests.get('https://github.com/FaiberCh/inmostats/releases/download/model-v1/feature_config.json').content)"

EXPOSE 7860

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "7860"]
