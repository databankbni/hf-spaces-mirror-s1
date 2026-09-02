FROM debian:trixie-slim AS builder

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    ca-certificates \
    pkg-config \
    libopenblas-dev \
    libopenblas64-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN git clone --depth 1 --single-branch --branch master https://github.com/ggml-org/llama.cpp.git

WORKDIR /build/llama.cpp

RUN cmake -B build \
    -DBUILD_SHARED_LIBS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_BLAS=ON \
    -DGGML_BLAS_VENDOR=OpenBLAS \
    -DCMAKE_C_FLAGS="-O3 -march=x86-64-v4 -mtune=icelake-server -flto" \
    -DCMAKE_CXX_FLAGS="-O3 -march=x86-64-v4 -mtune=icelake-server -flto"

RUN cmake --build build --config Release --target llama-server -j $(nproc)

FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 \
    libopenblas64-0 \
    libgomp1 \
    libjemalloc2 \
    ca-certificates \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2
ENV MALLOC_CONF="background_thread:true,metadata_thp:auto,dirty_decay_ms:5000,muzzy_decay_ms:5000"

ENV OMP_NUM_THREADS=2
ENV OPENBLAS_NUM_THREADS=2

WORKDIR /app

EXPOSE 7860

ENTRYPOINT ["llama-server"]

CMD ["-hf", "unsloth/Qwen3.5-0.8B-MTP-GGUF:Q8_0", \
	 "--spec-type", "draft-mtp", \
     "--spec-draft-n-max", "4", \
     "--spec-draft-n-min", "1", \
     "--cpu-strict", "1", \
     "-t", "2", \
     "-tb", "2", \
     "--load-mode", "mmap+mlock", \
     "--rope-scaling", "none", \
     "-kvu", \
     "-ctk", "q8_0", \
     "-ctv", "q8_0", \
     "-ctkd", "q8_0", \
     "-ctvd", "q8_0", \
     "--host", "0.0.0.0", \
     "--port", "7860", \
     "-np", "1", \
     "-fa", "on", \
     "--jinja", \
     "--temp", "0.6", \
     "--top-k", "20", \
     "--min-p", "0.0", \
     "--presence-penalty", "1.5", \
     "--image-min-tokens", "1024"]