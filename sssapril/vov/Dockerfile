# AgentFlow 公网部署 Dockerfile
# 多阶段构建: 前端构建 → Python 运行时

# ============ Stage 1: 前端构建 ============
FROM node:20-alpine AS frontend-build

WORKDIR /app/client

# 复制 package 文件先行, 利用 Docker 缓存
COPY client/package.json client/package-lock.json* ./

# 使用 npmmirror 加速（与本地开发一致）
RUN npm config set registry https://registry.npmmirror.com/ \
    && npm install --no-audit --no-fund

# 复制前端源码并构建
COPY client/ ./
RUN npm run build

# ============ Stage 2: Python 运行时 ============
FROM python:3.11-slim AS runtime

# 系统依赖（gcc 用于编译部分 Python 包，tzdata 用于时区）
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc tzdata \
    && rm -rf /var/lib/apt/lists/*

# 时区设为上海（与项目规则一致）
ENV TZ=Asia/Shanghai

WORKDIR /app

# 1) 先装 agentflow SDK（非 editable，稳定）
COPY agentflow/ /app/agentflow/
RUN pip install --no-cache-dir /app/agentflow

# 2) 装后端依赖（移除 requirements.txt 里的 editable 行）
COPY server/ /app/server/
WORKDIR /app/server
RUN sed -i '/-e \.\.\/agentflow/d' requirements.txt \
    && pip install --no-cache-dir -r requirements.txt

# 3) 把前端构建产物搬到预期位置
#    main.py 的 _get_static_dir() 在非 frozen 模式下指向 <repo>/client/dist
COPY --from=frontend-build /app/client/dist /app/client/dist

# 4) 持久化数据目录（Render Persistent Disk 挂载点）
RUN mkdir -p /data
ENV SQLITE_PATH=/data/agentflow.db

# Python 容器必要配置
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBUG=false

# HF Spaces 固定 7860（必须在 README.md YAML 的 app_port 字段保持一致）
EXPOSE 7860

WORKDIR /app/server

# 启动：HF Spaces 必须监听 7860（平台反向代理转发到该端口）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
