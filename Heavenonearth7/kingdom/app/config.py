from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Core application settings
    app_name: str = Field(default="Heaven on Earth CMS", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")
    environment: str = Field(default="production", alias="ENVIRONMENT")
    
    # Server Settings
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    allowed_origins: str = Field(
        default="http://localhost:8080,http://localhost:3000",
        alias="ALLOWED_ORIGINS"
    )
    
    # Database settings
    database_url: str = Field(..., alias="DATABASE_URL")
    database_pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=20, alias="DATABASE_MAX_OVERFLOW")
    
    # Supabase Configuration
    supabase_url: str = Field(..., alias="SUPABASE_URL")
    supabase_key: str = Field(..., alias="SUPABASE_KEY")
    supabase_bucket: str = Field(default="gallery", alias="SUPABASE_BUCKET")
    
    # JWT authentication settings
    jwt_secret_key: str = Field(..., alias="JWT_SECRET_KEY", min_length=32)
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=30,
        alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7,
        alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS"
    )
    
    # Initial admin user (used for first-time setup)
    admin_email: str = Field(..., alias="ADMIN_EMAIL")
    admin_password: str = Field(..., alias="ADMIN_PASSWORD", min_length=8)
    admin_full_name: str = Field(default="Super Admin", alias="ADMIN_FULL_NAME")
    
    # Password Hashing
    password_hash_rounds: int = Field(default=12, alias="PASSWORD_HASH_ROUNDS")
    
    # Rate Limiting
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")
    
    # File Upload Settings
    max_upload_size_mb: int = Field(default=10, alias="MAX_UPLOAD_SIZE_MB")
    allowed_image_types: str = Field(
        default="image/jpeg,image/png,image/webp,image/gif",
        alias="ALLOWED_IMAGE_TYPES"
    )
    upload_dir: str = Field(default="uploads", alias="UPLOAD_DIR")
    
    # Email Settings (Optional)
    smtp_host: Optional[str] = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from_email: Optional[str] = Field(default=None, alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(
        default="Heaven on Earth CMS", 
        alias="SMTP_FROM_NAME"
    )
    
    # Chatbot / AI settings
    groq_api_key: str = Field(..., alias="GROQ_API_KEY")
    chatbot_rate_limit: int = Field(default=30, alias="CHATBOT_RATE_LIMIT")
    chat_session_ttl_minutes: int = Field(default=30, alias="CHAT_SESSION_TTL_MINUTES")
    knowledge_base_refresh_days: int = Field(default=15, alias="KNOWLEDGE_BASE_REFRESH_DAYS")
    chatbot_crawl_urls: str = Field(..., alias="CHATBOT_CRAWL_URLS")
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL",
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    
    @property
    def allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",")]
    
    @property
    def allowed_image_types_list(self) -> List[str]:
        return [t.strip() for t in self.allowed_image_types.split(",")]
    
    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def chatbot_crawl_urls_list(self) -> List[str]:
        return [url.strip() for url in self.chatbot_crawl_urls.split(",") if url.strip()]
    
    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        if "your-super-secret" in v.lower() or "changeme" in v.lower():
            raise ValueError("JWT_SECRET_KEY appears to be a default value. Please set a secure secret.")
        return v
    
    @field_validator("admin_password")
    @classmethod
    def validate_admin_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("ADMIN_PASSWORD must be at least 8 characters long")
        if "changethis" in v.lower() or "password" in v.lower():
            raise ValueError("ADMIN_PASSWORD appears to be a default value. Please set a secure password.")
        return v
    
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


settings = get_settings()
