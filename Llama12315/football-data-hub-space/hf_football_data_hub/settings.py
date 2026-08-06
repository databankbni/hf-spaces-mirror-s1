from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys


@dataclass(frozen=True)
class Settings:
    hf_dataset_repo: str | None = os.getenv("FOOTBALL_HF_DATASET_REPO") or os.getenv("HF_DATASET_REPO") or None
    hf_token: str | None = os.getenv("HF_TOKEN") or None
    data_dir: Path = Path(os.getenv("HF_DATA_DIR", "/tmp/hf_football_data_hub_data"))
    api_key: str | None = os.getenv("HF_DATA_HUB_API_KEY") or None
    python_bin: str = os.getenv("PYTHON_BIN", sys.executable)
    vendor_dir: Path = Path(os.getenv("VENDOR_DIR", "vendor/hermes_source"))
    default_company_ids: str = os.getenv("DEFAULT_COMPANY_IDS", "3,24,8")
    max_packet_kb: int = int(os.getenv("MAX_PACKET_KB", "15"))

    @property
    def has_remote_dataset(self) -> bool:
        return bool(self.hf_dataset_repo and self.hf_token)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
