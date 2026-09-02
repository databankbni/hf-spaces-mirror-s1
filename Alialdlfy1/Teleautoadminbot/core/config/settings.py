"""Central, extensible settings loaded from environment without hard-coding secrets."""
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Settings:
    data_dir: str = os.getenv("APP_DATA_DIR", "data")
    runtime_dir: str = os.getenv("APP_RUNTIME_DIR", "runtime")
    db_path: str = os.getenv("APP_DB_PATH", "data/app.sqlite3")
    log_level: str = os.getenv("APP_LOG_LEVEL", "INFO")
    timezone: str = os.getenv("APP_TIMEZONE", "UTC")
    auto_repair_enabled: bool = os.getenv("AUTO_REPAIR_ENABLED", "false").lower() in {"1","true","yes","on"}
    auto_repair_apply: bool = os.getenv("AUTO_REPAIR_APPLY", "false").lower() in {"1","true","yes","on"}
    max_repair_attempts: int = int(os.getenv("AUTO_REPAIR_MAX_ATTEMPTS", "2"))

settings = Settings()
