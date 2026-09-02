FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 安装 git 和基础依赖
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# 从 GitHub 克隆项目
RUN git clone https://github.com/Sophomoresty/gemini-web2api.git .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制配置文件（如果需要自定义配置，可以取消下面的注释）
# 注意：config.example.json 已经在仓库中，我们直接复制一份作为正式配置
RUN cp config.example.json config.json

# 暴露端口（Hugging Face 会通过环境变量 PORT 覆盖，但这里保持 8081）
EXPOSE 8081

# 启动命令
CMD ["python", "-m", "gemini_web2api", "--config", "/app/config.json"]
