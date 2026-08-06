FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SWMM_WORKER_PYTHON=/opt/swmm-venv/bin/python \
    SWMM_SESSION_ROOT=/tmp/swmm_sessions \
    PYTHONFAULTHANDLER=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt worker-requirements.txt /app/

# Main server environment: MCP + FastAPI. OpenSWMM is intentionally absent.
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /app/requirements.txt

# Native SWMM environment: used only by the one-shot crash-isolated worker.
RUN python -m venv /opt/swmm-venv \
    && /opt/swmm-venv/bin/python -m pip install --upgrade pip setuptools wheel \
    && /opt/swmm-venv/bin/python -m pip install -r /app/worker-requirements.txt \
    && /opt/swmm-venv/bin/python -c "from openswmm.engine import Solver; print('Isolated OpenSWMM worker verified')"

COPY . /app

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /tmp/swmm_sessions \
    && chown -R appuser:appuser /app /opt/swmm-venv /tmp/swmm_sessions

USER appuser
EXPOSE 7860

CMD ["python", "-X", "faulthandler", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
