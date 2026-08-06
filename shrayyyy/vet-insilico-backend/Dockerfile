FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install build deps + OpenBabel + boost (Vina needs boost to compile)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake \
    libboost-all-dev libeigen3-dev \
    libgomp1 libfreetype6 libxft-dev libffi-dev \
    openbabel libopenbabel-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Build Vina from source (lightweight, ~2 min)
RUN git clone --depth 1 https://github.com/ccsb-scripps/AutoDock-Vina.git /tmp/vina \
    && cd /tmp/vina/build/linux/release \
    && make \
    && cp vina /usr/local/bin/vina \
    && cp vina_split /usr/local/bin/vina_split \
    && rm -rf /tmp/vina

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY . .

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
