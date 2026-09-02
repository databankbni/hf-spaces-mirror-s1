FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    MPLBACKEND=Agg \
    PORT=8000 \
    IDF_SESSIONS_DIR=/tmp/idf-sesiones

WORKDIR /app

# Dependencias del sistema mínimas para SciPy y Matplotlib en slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libfreetype6 libpng16-16 libjpeg62-turbo libopenblas0 \
    && rm -rf /var/lib/apt/lists/*

COPY webapp/requirements.txt /app/requirements.txt
# --only-binary garantiza wheels (no compila numpy/scipy/matplotlib desde fuente,
# lo cual se come la RAM del tier free de Render).
# --prefer-binary usa wheels cuando existen (evita compilar numpy/scipy/
# matplotlib, que se come la RAM) pero permite sdist si algún paquete
# transitivo no tiene wheel. Más robusto que --only-binary=:all:.
# --no-cache-dir reduce uso de disco/memoria durante la instalación.
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefer-binary -r requirements.txt

# Código
COPY src /app/src
COPY webapp /app/webapp

EXPOSE 8000

# Gunicorn con 1 worker y 1 thread: matplotlib + reportlab no son
# thread-safe en concurrencia con figuras compartidas. Mejor serializar.
CMD ["sh", "-c", "gunicorn --chdir webapp --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 1 --timeout 240 --graceful-timeout 30 --worker-class sync app:app"]
