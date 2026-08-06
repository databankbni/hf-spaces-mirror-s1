# Use an official Python runtime with a matching version
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies (needed for certain Hugging Face/PyTorch operations)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker's build cache
COPY requirements.txt .

# Install dependencies directly into the container environment
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port Gradio runs on by default
EXPOSE 7860

# Tell Gradio to listen on all network interfaces inside the container
ENV GRADIO_SERVER_NAME="0.0.0.0"

# Run the app
CMD ["python", "app.py"]