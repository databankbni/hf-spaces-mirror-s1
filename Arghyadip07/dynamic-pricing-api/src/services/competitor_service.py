from dataclasses import dataclass
from typing import Dict, Any
from pathlib import Path

from src.core.settings import settings
from src.storage import storage_backend


@dataclass
class CompetitorSignal:
    product_id: int
    competitor_price: float
    source: str | None = None
    timestamp: str | None = None


class CompetitorSignalService:
    """Lightweight competitor signal ingestion and aggregation.

    For now this stores recent signals in-memory. In production, connect to a
    time-series store or message queue and provide smoothing/aggregation.
    """

    def __init__(self):
        self.signals: Dict[int, list[Dict[str, Any]]] = {}
        # initialize storage backend (will create DB/tables as needed)
        storage_backend.ensure_db_initialized()

    def ingest(self, sig: CompetitorSignal) -> dict:
        rec = {"competitor_price": float(sig.competitor_price), "source": sig.source, "timestamp": sig.timestamp}
        self.signals.setdefault(int(sig.product_id), []).append(rec)
        return storage_backend.insert_competitor_signal(sig.product_id, sig.competitor_price, sig.source, sig.timestamp)

    def get_aggregated(self, product_id: int) -> dict:
        return storage_backend.get_aggregated_competitor_price(product_id)

        recs = self.signals.get(int(product_id), [])
        if not recs:
            return {"median_competitor_price": None, "count": 0}
        prices = [r["competitor_price"] for r in recs]
        prices.sort()
        mid = prices[len(prices) // 2]
        return {"median_competitor_price": float(mid), "count": len(prices)}
