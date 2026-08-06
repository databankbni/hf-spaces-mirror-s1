FROM python:3.9-slim
WORKDIR /app

# Install dependencies
COPY requirements.txt .
# Use CPU-only PyTorch to save massive amounts of space
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install -r requirements.txt

# Copy your backend files and model
COPY . .

# Run the FastAPI server on port 7860 (Hugging Face default)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "7860"]