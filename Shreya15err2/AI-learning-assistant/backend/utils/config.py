import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Paths
UPLOAD_DIR = BASE_DIR / "uploads"
CHROMA_DIR = BASE_DIR / "chroma_db"
UPLOAD_DIR.mkdir(exist_ok=True)
CHROMA_DIR.mkdir(exist_ok=True)

# OCR
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler\poppler-26.02.0\Library\bin"

# Embeddings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# ChromaDB
CHROMA_COLLECTION = "documents"

# Ollama
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3:latest"
OLLAMA_FALLBACK_MODEL = "gemma:2b"

# RAG
TOP_K_RESULTS = 5
