FROM python:3.10

# تثبيت حزم النظام الأساسية للصوت والفيديو
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# إعداد المستخدم والبيئة
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# نسخ ملف المتطلبات وتثبيتها
COPY --chown=user requirements.txt $HOME/app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات التطبيق
COPY --chown=user . $HOME/app

CMD ["python", "app.py"]