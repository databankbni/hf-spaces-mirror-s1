from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path

class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "Revenue Recovery Intelligence (RRI)"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    PORT: int = 7860
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./rri_data.db"
    
    # NVIDIA NIM
    NVIDIA_API_KEY: Optional[str] = None
    NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    PRIMARY_MODEL: str = "deepseek-ai/deepseek-v4-pro-0813"
    FAST_MODEL: str = "deepseek-ai/deepseek-v4-flash-0731"
    
    # Razorpay Test Mode
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None
    RAZORPAY_WEBHOOK_SECRET: Optional[str] = None
    
    # Hugging Face
    HF_SPACE_NAME: Optional[str] = None
    HF_SPACE_URL: Optional[str] = None
    
    model_config = {
        "env_file": str(Path(__file__).resolve().parent.parent.parent / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

settings = Settings()
