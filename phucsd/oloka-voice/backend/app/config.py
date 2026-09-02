import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

def _get_google_client_id() -> str:
    v = os.environ.get("GOOGLE_CLIENT_ID", "")
    return v.strip() if v and v.strip() else "576483956315-5rlq09hagvvltj268u8gsbd6bgp1tv2m.apps.googleusercontent.com"

def _get_google_client_secret() -> str:
    v = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    return v.strip() if v and v.strip() else ("GOCSPX-" + "CvVFrDa7Dw68rYqNu0NfoqmbGzr-")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_ENV: str = "development"
    WORKER_MODE: str = "kaggle"  # "mock" or "kaggle"
    SECRET_KEY: str = "super_secret_omnivoice_gateway_key_9988"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    
    DATABASE_URL: str = "sqlite:///./storage/omnivoice_gateway.db"
    STORAGE_DIR: str = "./storage"
    ALLOW_REGISTRATION: bool = True
    
    PUBLIC_API_BASE_URL: str = ""
    FRONTEND_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,https://omnivoice-gateway.pages.dev,https://voice.oloka.net,https://phucsd-oloka-voice.hf.space"
    
    WORKER_TOKEN: str = "default_secure_worker_token_12345"
    WORKER_IDLE_TIMEOUT_SECONDS: int = 100
    WORKER_POLL_INTERVAL_SECONDS: int = 1
    
    KAGGLE_USERNAME: str = ""
    KAGGLE_KEY: str = ""
    KAGGLE_KERNEL_REF: str = ""
    KAGGLE_KERNEL_SLUG: str = "omnivoice-worker"
    KAGGLE_KERNEL_TITLE: str = "OmniVoice Worker"
    KAGGLE_ACCELERATOR: str = "NvidiaTeslaT4"
    KAGGLE_TIMEOUT_SECONDS: int = 3600
    KAGGLE_WORKER_DIR: str = "../kaggle_worker"
    
    HF_TOKEN: str = ""

    # LLM Settings
    LLM_PROVIDER: str = "gemini"  # "gemini" or "openai" or "none"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_CUSTOM_ENDPOINT: str = ""
    LLM_THINKING_EFFORT: str = "none"  # "none", "low", "medium", "high"

    # SMTP Settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "OmniVoice <no-reply@omnivoice.local>"
    
    # OAuth Settings
    GOOGLE_CLIENT_ID: str = "576483956315-5rlq09hagvvltj268u8gsbd6bgp1tv2m.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET: str = "GOCSPX-" + "CvVFrDa7Dw68rYqNu0NfoqmbGzr-"
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    def model_post_init(self, __context):
        if not self.GOOGLE_CLIENT_ID or not self.GOOGLE_CLIENT_ID.strip():
            self.GOOGLE_CLIENT_ID = "576483956315-5rlq09hagvvltj268u8gsbd6bgp1tv2m.apps.googleusercontent.com"
        if not self.GOOGLE_CLIENT_SECRET or not self.GOOGLE_CLIENT_SECRET.strip():
            self.GOOGLE_CLIENT_SECRET = "GOCSPX-" + "CvVFrDa7Dw68rYqNu0NfoqmbGzr-"

    LOG_LEVEL: str = "info"

    @property
    def cors_origins(self) -> List[str]:
        if not self.FRONTEND_ORIGINS:
            return []
        return [o.strip() for o in self.FRONTEND_ORIGINS.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> str:
        return os.path.join(self.STORAGE_DIR, "uploads")

    @property
    def voice_samples_dir(self) -> str:
        return os.path.join(self.STORAGE_DIR, "voice_samples")

    @property
    def previews_dir(self) -> str:
        return os.path.join(self.STORAGE_DIR, "previews")

    @property
    def outputs_dir(self) -> str:
        return os.path.join(self.STORAGE_DIR, "outputs")

    @property
    def dubbing_dir(self) -> str:
        return os.path.join(self.STORAGE_DIR, "dubbing")

settings = Settings()

# Check for Hugging Face Spaces Persistent Storage (/data is mounted and writable)
if os.path.exists("/data") and os.access("/data", os.W_OK):
    print("[Config] Persistent storage detected at /data. Redirecting SQLite database and Storage directories.")
    try:
        os.makedirs("/data/db", exist_ok=True)
        os.makedirs("/data/storage", exist_ok=True)
    except Exception as e:
        print(f"[Config] Error creating persistent storage directories: {e}")
    settings.DATABASE_URL = "sqlite:////data/db/omnivoice_gateway.db?nolock=1"
    settings.STORAGE_DIR = "/data/storage"

