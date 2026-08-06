"""集中設定：金鑰與模型字串一律讀 .env，程式不寫死。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def _runtime_path(env_name: str, default_name: str) -> Path:
    configured = os.getenv(env_name, "").strip()
    path = Path(configured).expanduser() if configured else REPO_ROOT / default_name
    return path if path.is_absolute() else REPO_ROOT / path


DATA_DIR = _runtime_path("RAG_DATA_DIR", "data")
LOGS_DIR = _runtime_path("RAG_LOGS_DIR", "logs")


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_retention_days(value: str | None) -> int | None:
    normalized = (value or "30").strip()
    return None if normalized.lower() == "none" else int(normalized)


@dataclass(frozen=True)
class Settings:
    google_api_key: str
    openai_api_key: str
    hf_token: str
    discord_webhook_url: str
    gemini_model: str
    gemini_lite_model: str
    openai_model: str
    ollama_model: str
    embedding_model: str
    embedding_baseline_model: str
    reranker_model: str
    shadow_adaptive_enabled: bool
    shadow_adaptive_refinement: bool
    trace_sample_rate: float
    trace_redact_pii: bool
    trace_retention_days: int | None
    trace_keep_errors: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        hf_token=os.getenv("HF_TOKEN", ""),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        gemini_lite_model=os.getenv("GEMINI_LITE_MODEL", "gemini-3.1-flash-lite"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        ollama_model=os.getenv("OLLAMA_MODEL", "taide-gemma3-12b"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "taide/embeddinggemma-GTAIDE-300m-2605"),
        embedding_baseline_model=os.getenv("EMBEDDING_BASELINE_MODEL", "BAAI/bge-m3"),
        reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        shadow_adaptive_enabled=_parse_bool(os.getenv("RAG_SHADOW_ADAPTIVE")),
        shadow_adaptive_refinement=_parse_bool(os.getenv("RAG_SHADOW_REFINEMENT")),
        trace_sample_rate=float(os.getenv("RAG_TRACE_SAMPLE_RATE", "1.0")),
        trace_redact_pii=_parse_bool(os.getenv("RAG_TRACE_REDACT_PII")),
        trace_retention_days=_parse_retention_days(
            os.getenv("RAG_TRACE_RETENTION_DAYS", "30")
        ),
        trace_keep_errors=_parse_bool(
            os.getenv("RAG_TRACE_KEEP_ERRORS"), default=True
        ),
    )
