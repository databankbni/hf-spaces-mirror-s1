# =========================================================
# Worker Health AI - Hugging Face Docker Space
# =========================================================

FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Debug: show project files
RUN echo "===== PROJECT FILES =====" && \
    find /app -maxdepth 2 -type f -print

# Test the actual FastAPI module: adv_app.py
RUN python -c "import adv_app; print('===== FASTAPI IMPORT SUCCESS =====')"

EXPOSE 7860

CMD ["uvicorn", "adv_app:app", "--host", "0.0.0.0", "--port", "7860"]
