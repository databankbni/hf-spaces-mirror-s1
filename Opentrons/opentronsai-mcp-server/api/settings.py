"""
Settings and configuration for the Opentrons AI MCP Server.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AI Model Configuration
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model_name: str = "claude-sonnet-4-5-20250929"
    model_helper: str = "claude-sonnet-4-5-20250929"  # For doc lookup (faster model)
    # Used only during `make sync-knowledge` to write api_docs_struct <about> blurbs.
    knowledge_about_model: str = "claude-sonnet-5"

    # HuggingFace (for simulator)
    huggingface_api_key: SecretStr = SecretStr("")
    simulator_url: str = "https://Opentrons-simulator.hf.space/protocol"

    # Pinned knowledge corpus version (must match storage/api_docs/.knowledge-version).
    # Refresh docs with: make sync-knowledge KNOWLEDGE_VERSION=<version>
    knowledge_version: str = "9.0.0-k1"

    # Application Settings
    environment: str = "development"
    log_level: str = "INFO"
    logger_name: str = "opentrons-ai-mcp"

    # Protocol Settings
    max_tokens: int = 20000


# Global settings instance
settings = Settings()
