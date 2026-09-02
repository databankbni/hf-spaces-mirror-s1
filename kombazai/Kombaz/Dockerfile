FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data && chmod -R 777 /app/data
EXPOSE 7860
CMD ["python", "app.py"]