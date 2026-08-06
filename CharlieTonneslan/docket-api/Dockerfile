FROM python:3.12-slim
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV FASTEMBED_CACHE_PATH=/tmp/fastembed_cache HF_HOME=/tmp/hf DATABASE_PATH=/tmp/tasks.db
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
