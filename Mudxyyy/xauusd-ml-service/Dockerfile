FROM python:3.9

# Membuat user baru agar aman sesuai regulasi Hugging Face
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# 1. Copy & Install Requirements duluan (biar build lebih cepat)
COPY --chown=user ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

# 2. Copy semua file ml-service ke dalam container
COPY --chown=user . /app

# 3. Jalankan aplikasi menggunakan lokasi folder app.main kamu
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]