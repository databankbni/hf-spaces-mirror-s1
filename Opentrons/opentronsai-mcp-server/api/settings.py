"""
Settings and configuration for the Opentrons AI MCP Server.
"""

from pydantic_settings import BaseSettings
from pydantic import SecretStr


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # AI Model Configuration
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model_name: str = "claude-sonnet-4-5-20250929"
    model_helper: str = "claude-sonnet-4-5-20250929"  # For doc lookup (faster model)

    # HuggingFace (for simulator)
    huggingface_api_key: SecretStr = SecretStr("")
    simulator_url: str = "https://Opentrons-simulator.hf.space/protocol"

    # Application Settings
    environment: str = "development"
    log_level: str = "INFO"
    logger_name: str = "opentrons-ai-mcp"

    # Protocol Settings
    max_tokens: int = 20000

    class Config:
        env_file = ".env"
        extra = "ignore"


# Global settings instance
settings = Settings()
