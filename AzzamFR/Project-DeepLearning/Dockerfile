FROM python:3.10-slim

# Buat user dengan UID 1000 untuk keamanan Hugging Face
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Salin semua file proyek ke container dengan kepemilikan user 1000
COPY --chown=user . $HOME/app

# Install dependencies dari requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Jalankan server Gunicorn pada port 7860 (port default Hugging Face Spaces)
CMD ["gunicorn", "-b", "0.0.0.0:7860", "app:app"]
