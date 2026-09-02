# Dockerfile
# Use a lightweight and secure Python base image
FROM python:3.11-slim

# --- Set Environment Variables ---
# Ensures Python output is unbuffered and paths for Poetry/Sentence-Transformers are set.
# UPDATED: Added LOG_LEVEL and LOG_VERBOSE defaults here.
ENV PIP_NO_CACHE_DIR=off \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYTHONUNBUFFERED=1 \
    SENTENCE_TRANSFORMERS_HOME="/app/.cache" \
    LOG_LEVEL="DEBUG" \
    LOG_VERBOSE="true"

# Install system dependencies (curl for Poetry installation)
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

# Set the application's working directory
WORKDIR /app

# --- OPTIMIZED CACHED LAYER: Dependencies ---
# 1. Copy dependency files.
# Note: It is best practice to copy poetry.lock if it exists to ensure reproducible builds.
COPY pyproject.toml poetry.lock* ./

# If you don't have a lock file yet, generate it.
RUN if [ ! -f poetry.lock ]; then poetry lock; fi

# Installs dependencies including 'pinecone-client' and 'sentence-transformers'
RUN poetry install --no-root

# 2. Pre-download the SentenceTransformer model.
# This avoids a large I/O operation at runtime, ensuring fast worker start-up.
# The model is saved into the /app/.cache directory, which is cached in the image.
RUN poetry run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# --- APPLICATION LAYER: Copy Runtime Code ---
# 3. Copy only the necessary runtime code.
# The files for local ingestion (ingest.py, run_ingestion.py) and sample_data are omitted.
# Note: app.py, agents.py, and retriever.py will connect to the external Pinecone service.
COPY app.py agents.py config.py embeddings.py chunker.py retriever.py start.sh logging_config.py ./

# --- Final Configuration ---
# Make the startup script executable
RUN chmod +x ./start.sh

# Expose the port that the Gunicorn server will run on
EXPOSE 7860

# Set the startup script as the final command to run the application
CMD ["./start.sh"]