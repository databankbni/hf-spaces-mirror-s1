FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Hugging Face Spaces default port
EXPOSE 7860

# Run Uvicorn server
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
