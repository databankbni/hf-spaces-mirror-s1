FROM python:3.9

# 1. Cài đặt các thư viện hệ thống cần thiết (Dùng quyền root mặc định của Docker build)
USER root
RUN apt-get update && apt-get install -y \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 2. Thiết lập thư mục làm việc và User
WORKDIR /app
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# 3. Cài đặt thư viện Python
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# 4. Copy toàn bộ code (cloakbrowser sẽ tự động download binary khi khởi tạo)
COPY --chown=user . .

# 5. Sinh Prisma Client Python trước khi chạy ứng dụng
RUN python3 -m prisma py generate

# 6. Chạy ứng dụng trên cổng 7860
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
