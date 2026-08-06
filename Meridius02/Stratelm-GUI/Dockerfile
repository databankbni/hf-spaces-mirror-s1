# Start with a Python image
FROM python:3.10-slim

# Install Node.js (needed to build the Vite frontend)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs git && \
    rm -rf /var/lib/apt/lists/*

# Hugging Face requires the container to run as a non-root user (UID 1000)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Set up the working directory
WORKDIR /app

# Copy your entire project into the container and change ownership to 'user'
COPY --chown=user:user . /app/

# 1. Build the React Frontend
RUN cd Stratelm-GUI/frontend && npm install && npm run build

# 2. Install the backend dependencies and digital_twin
RUN pip install --no-cache-dir -e . && \
    cd Stratelm-GUI/backend && pip install --no-cache-dir -r requirements.txt

# Hugging Face Spaces mandates port 7860
EXPOSE 7860

# Add /app and backend to PYTHONPATH so backend can import digital_twin and its own modules
ENV PYTHONPATH="/app:/app/Stratelm-GUI/backend"

# Start the FastAPI server on port 7860
WORKDIR /app/Stratelm-GUI/backend
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
