import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration loaded from .env file."""

    # MySQL / TiDB Cloud
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "f1db")
    MYSQL_SSL = os.getenv("MYSQL_SSL", "false").lower() == "true"

    # Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    # Flask
    FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-prod")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "True").lower() == "true"

    # RAG Settings
    TOP_K_SCHEMA_RESULTS = 7
    MAX_RETRY_ATTEMPTS = 2
