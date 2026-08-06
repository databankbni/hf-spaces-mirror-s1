from pydantic_settings import BaseSettings
from datetime import date


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    groq_api_key: str = ""
    gemini_api_key: str = ""      # optional free fallback (aistudio.google.com)
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""    # comma-separated whitelist
    google_vision_api_key: str = ""
    apify_api_token: str = ""
    google_fact_check_api_key: str = ""
    huggingface_api_key: str = ""
    govt_start_date: date = date(2026, 5, 11)
    # DMK's tenure ended 2026-05-04. The govt social handles (@CMOTamilnadu,
    # @TNDIPRNEWS) are continuous across administrations, so anything they
    # posted AFTER this date is TVK-era content and must NOT pollute the DMK
    # reference archive (which also feeds credit-steal detection).
    dmk_tenure_end_date: date = date(2026, 5, 4)
    govt_name: str = "TVK"
    admin_secret: str = "change-this"
    allowed_origins: str = "http://localhost:3000"

    @property
    def govt_day_number(self) -> int:
        return (date.today() - self.govt_start_date).days + 1

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
