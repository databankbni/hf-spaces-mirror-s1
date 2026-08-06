FROM python:3.10-slim

# Install system compilation tools plus required BLAS/LAPACK libraries for FAISS
RUN apt-get update && apt-get install -y \
    build-essential \
    libopenblas-dev \
    liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

# Set up the secure non-root user required by Hugging Face
RUN useradd -m -u 1000 user
USER user

# Configure path variables and redirect the model cache to a writable partition
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/tmp/hf_cache

WORKDIR $HOME/app

# Copy dependency records and compile safely as the user
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Bring in the application logic files
COPY --chown=user . .

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]