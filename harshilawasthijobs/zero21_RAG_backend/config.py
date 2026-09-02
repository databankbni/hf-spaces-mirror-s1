import os
from openai import AsyncOpenAI

# --- API and Model Configuration ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT")

# --- Logging Configuration ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_VERBOSE = os.getenv("LOG_VERBOSE", "false").lower() == "true"

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# UPDATED: Llama-3.3-70b was decommissioned on Aug 16, 2026.
# Replaced with GPT-OSS 120B, OpenAI's flagship open-weight model on Groq's Production tier.
CHAT_MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")

# --- Agent-Specific Configurations ---
VECTOR_INDEX_NAME = "rag-index" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

AGENT_CONFIG = {
    "IDEA VALIDATOR": {
        "index_name": VECTOR_INDEX_NAME,
        "namespace": "ceo", 
        "data_file": os.path.join(BASE_DIR, "sample_data", "ceo", "conversation.txt"),
    },
    "CEO": {
        "index_name": VECTOR_INDEX_NAME, 
        "namespace": "ceo", 
        "data_file": os.path.join(BASE_DIR, "sample_data", "ceo", "conversation.txt"),
    },
    "CTO": {
        "index_name": VECTOR_INDEX_NAME,
        "namespace": "cto", 
        "data_file": os.path.join(BASE_DIR, "sample_data", "cto", "conversation.txt"),
    },
    "CFO": {
        "index_name": VECTOR_INDEX_NAME,
        "namespace": "cfo", 
        "data_file": os.path.join(BASE_DIR, "sample_data", "cfo", "conversation.txt"),
    },
    "CMO": {
        "index_name": VECTOR_INDEX_NAME,
        "namespace": "cmo", 
        "data_file": os.path.join(BASE_DIR, "sample_data", "cmo", "conversation.txt"),
    },
}

# --- Function to Get LLM Client ---
def get_llm_client() -> AsyncOpenAI:
    """Initializes and returns an AsyncOpenAI client targeting Groq's API."""
    if not GROQ_API_KEY:
        raise ValueError(
            "GROQ_API_KEY environment variable is not set. Please set it as a secret."
        )
    return AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=GROQ_API_KEY,
    )