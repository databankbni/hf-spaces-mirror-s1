FROM python:3.10-slim

# Evita prompts interativos durante a instalação do sistema
ENV DEBIAN_FRONTEND=noninteractive

# 🔥 LIMITADOR DE CONCORRÊNCIA CONTRA OOMKilled (Exit Code 137)
# Força o compilador GCC/G++ a usar apenas 1 thread de compilação.
# Isso garante que a compilação consuma pouca RAM e passe direto pelo build!
ENV MAKEFLAGS="-j1"
ENV CMAKE_BUILD_PARALLEL_LEVEL=1
ENV CMAKE_ARGS="-DLLAMA_BLAS=OFF -DLLAMA_CUDA=OFF"

# Instala ferramentas essenciais do Linux necessárias para compilar o llama.cpp
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Copia e instala primeiro os requerimentos para aproveitar o cache do Docker
COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copia todo o restante do código
COPY . .

# Expõe a porta padrão exigida pelo Hugging Face Spaces
EXPOSE 7860

# Inicializa o servidor FastAPI de forma estável
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]