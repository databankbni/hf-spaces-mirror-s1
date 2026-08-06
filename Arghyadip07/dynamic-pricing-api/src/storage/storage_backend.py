import os
from typing import Any, Dict
from pathlib import Path

from src.core.settings import settings
from . import sqlite_store

# Lazy import of ORM store
_orm_store = None


def _get_orm_store(database_url: str):
    global _orm_store
    if _orm_store is None:
        from .orm_store import ORMStore

        _orm_store = ORMStore(database_url)
    return _orm_store


def _sqlite_db_path() -> Path:
    # prefer env var override
    p = os.getenv("SQLITE_DB_PATH") or getattr(settings, "sqlite_db_path", None)
    return Path(p) if p else Path("data/dpai.sqlite")


def ensure_db_initialized() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        _get_orm_store(database_url)
    else:
        sqlite_store.init_db(_sqlite_db_path())


def insert_competitor_signal(product_id: int, competitor_price: float, source: str | None, timestamp: str | None) -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        store = _get_orm_store(database_url)
        return store.insert_competitor_signal(product_id, competitor_price, source, timestamp)
    return sqlite_store.insert_competitor_signal(_sqlite_db_path(), product_id, competitor_price, source, timestamp)


def get_aggregated_competitor_price(product_id: int) -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        store = _get_orm_store(database_url)
        return store.get_aggregated_competitor_price(product_id)
    return sqlite_store.get_aggregated_competitor_price(_sqlite_db_path(), product_id)


def get_competitor_signals(product_id: int, limit: int = 100) -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        store = _get_orm_store(database_url)
        return store.get_competitor_signals(product_id, limit)
    return sqlite_store.get_competitor_signals(_sqlite_db_path(), product_id, limit)


def insert_ab_assignment(experiment: str, subject_id: str, group: str) -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        store = _get_orm_store(database_url)
        return store.insert_ab_assignment(experiment, subject_id, group)
    return sqlite_store.insert_ab_assignment(_sqlite_db_path(), experiment, subject_id, group)


def insert_ab_outcome(experiment: str, subject_id: str, group: str | None, outcome: dict) -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        store = _get_orm_store(database_url)
        return store.insert_ab_outcome(experiment, subject_id, group, outcome)
    return sqlite_store.insert_ab_outcome(_sqlite_db_path(), experiment, subject_id, group, outcome)


def get_ab_summary(experiment: str) -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        store = _get_orm_store(database_url)
        return store.get_ab_summary(experiment)
    return sqlite_store.get_ab_summary(_sqlite_db_path(), experiment)


def get_ab_outcomes(experiment: str, limit: int = 200) -> Dict[str, Any]:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        store = _get_orm_store(database_url)
        return store.get_ab_outcomes(experiment, limit)
    return sqlite_store.get_ab_outcomes(_sqlite_db_path(), experiment, limit)


def upsert_market_context(product_id: int, inventory: int | None, unit_cost: float | None, updated_at: str) -> Dict[str, Any]:
    """Write live inventory/cost context for a product (used by agent perception)."""
    return sqlite_store.upsert_market_context(_sqlite_db_path(), product_id, inventory, unit_cost, updated_at)


def get_market_context(product_id: int) -> Dict[str, Any]:
    """Read the latest market context for a product. Returns {} if none ingested yet."""
    return sqlite_store.get_market_context(_sqlite_db_path(), product_id)
