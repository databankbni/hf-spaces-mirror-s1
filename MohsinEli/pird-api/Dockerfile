FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Spaces containers run as an arbitrary non-root user; keep HF cache writable.
ENV HF_HOME=/tmp/hf
ENV OMP_NUM_THREADS=2

EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
