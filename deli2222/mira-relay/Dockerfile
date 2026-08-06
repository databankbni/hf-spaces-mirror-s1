FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py dashboard.html .

EXPOSE 7860
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:7860", "--worker-class", "gevent", "--workers", "1", "--worker-connections", "100", "--timeout", "300"]
