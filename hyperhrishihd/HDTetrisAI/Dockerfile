FROM python:3.11-slim

WORKDIR /app

COPY . /app

# Install Flask, Gunicorn, Requests, PyTorch (CPU)
RUN pip install --no-cache-dir flask gunicorn requests torch huggingface_hub --extra-index-url https://download.pytorch.org/whl/cpu

# Expose the port Hugging Face expects
EXPOSE 7860

# Run the app with Gunicorn (Updated to look for app.py)
CMD ["gunicorn", "-b", "0.0.0.0:7860", "--workers", "1", "--threads", "8", "app:app"]