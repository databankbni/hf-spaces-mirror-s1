FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements file first
COPY requirements.txt /app/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# COPY ALL BACKEND FILES (app.py, model file, etc.) INTO THE CONTAINER
COPY . /app

# Expose Hugging Face default port
EXPOSE 7860

# Run Gunicorn server
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:7860", "app:superkart_api"]
