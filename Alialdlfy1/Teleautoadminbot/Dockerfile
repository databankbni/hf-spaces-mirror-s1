FROM python:3.11-slim

WORKDIR /code

# إنشاء مجلد البيانات الدائمة
RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]