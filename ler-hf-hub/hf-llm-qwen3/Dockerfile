# hf-llm/Dockerfile
# Hugging Face Spaces - Docker SDK
# 目标: T4 small (16GB VRAM) Community Grant
#
# ⚠️ HF Spaces Docker 硬件说明:
#   - CPU basic (2vCPU/16GB RAM) - 免费默认
#   - T4 small (4vCPU/15GB RAM/16GB VRAM) - Community Grant 免费，需申请
#   - Zero GPU (H200 分片) - 需 PRO 或 approved 公开 Space
#
# 本 Dockerfile 用官方 nvidia/cuda 基础镜像，同时兼容 CPU/GPU 硬件档位。

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    # HF Spaces 默认工作目录 & 缓存目录
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    # 让 transformers/sentence-transformers 用 HF 官方缓存位置，Space 持久化
    HF_HOME=/home/user/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/user/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/user/.cache/huggingface

# ---------- 系统依赖 ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip python3.10-venv \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# ---------- HF Spaces 约定的非 root 用户 ----------
RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/app

# ---------- Python 依赖 ----------
COPY --chown=user:user requirements.txt .
RUN pip install --user --upgrade pip && \
    pip install --user -r requirements.txt

# ---------- 代码 ----------
COPY --chown=user:user app.py .

# ---------- 端口 & 启动 ----------
EXPOSE 7860
CMD ["python", "app.py"]
