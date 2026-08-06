# HF Spaces (Docker SDK) — servicio de NER (Capa 1b).
# Presidio + spaCy es_core_news_lg. Imagen más pesada que la Capa 1 (por eso
# el NER no va en Vercel), pero el modelo carga UNA vez al arrancar.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Modelo de spaCy en español (no es un paquete pip normal).
RUN python -m spacy download es_core_news_lg

COPY app.py ./

# HF Spaces expone el puerto 7860.
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
