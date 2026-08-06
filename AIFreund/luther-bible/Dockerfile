FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY luther_mcp/ ./luther_mcp/

# Pre-download the embedding model so it's baked into the image
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

ENV CHROMA_PATH=/app/bible_chroma_db

# Download pre-built ChromaDB index from latest GitHub Release
RUN python -m luther_mcp download

# HuggingFace Spaces sets PORT=7860 automatically
CMD ["python", "-m", "luther_mcp", "--sse"]
