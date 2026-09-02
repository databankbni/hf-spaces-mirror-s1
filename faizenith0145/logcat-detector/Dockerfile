FROM python:3.9-slim

WORKDIR /code

# Salin requirements dan instal dependency
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Salin seluruh isi project
COPY . .

# Informasikan port yang digunakan (Hugging Face mewajibkan 7860)
EXPOSE 7860

# JALANKAN MENGGUNAKAN PYTHON LANGSUNG, JANGAN GUNICORN
CMD ["python", "-u", "app.py"]