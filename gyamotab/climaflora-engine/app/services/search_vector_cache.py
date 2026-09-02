from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
import os
from pathlib import Path
from threading import Event, RLock
from typing import Callable, Generic, TypeVar

import numpy as np

from app.domain.models import ClimateProfile, SoilProfile
from app.services.search_runtime import climate_scientific_signature, soil_scientific_signature
from app.services.search_soil_vector import (
    CombinedScoreVector,
    SoilScoreVector,
    combine_score_vectors,
    score_soil_vector,
)
from app.services.search_vector import (
    ClimateRuntimeMatrix,
    ClimateScoreVector,
    load_climate_runtime_matrix,
    score_climate_vector,
)
from app.version import METHOD_VERSION, SEARCH_CACHE_FORMAT_VERSION

T = TypeVar("T")


@dataclass(frozen=True)
class CacheResult(Generic[T]):
    value: T
    key: str
    cache_hit: bool


@dataclass
class _Flight:
    event: Event
    error: BaseException | None = None


def _object_nbytes(value: object) -> int:
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if is_dataclass(value):
        return sum(_object_nbytes(getattr(value, field.name)) for field in fields(value))
    if isinstance(value, dict):
        return sum(_object_nbytes(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_object_nbytes(item) for item in value)
    return 0


def _digest(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _catalog_runtime_identity(matrix: ClimateRuntimeMatrix) -> dict[str, object]:
    sidecar = Path(matrix.sidecar_path)
    stat = sidecar.stat()
    return {
        "sidecar": str(sidecar.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


class ScientificVectorCache:
    """Process-local byte-bounded LRU with per-key single-flight protection."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max(1, int(max_bytes))
        self._lock = RLock()
        self._items: OrderedDict[str, tuple[object, int]] = OrderedDict()
        self._bytes = 0
        self._flights: dict[str, _Flight] = {}
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._waits = 0

    def get(self, key: str) -> object | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self._misses += 1
                return None
            self._hits += 1
            self._items.move_to_end(key)
            return item[0]

    def put(self, key: str, value: object) -> None:
        size = max(1, _object_nbytes(value))
        with self._lock:
            existing = self._items.pop(key, None)
            if existing is not None:
                self._bytes -= existing[1]
            # Objects larger than the whole budget are useful for this request
            # but cannot safely be retained.
            if size > self.max_bytes:
                return
            self._items[key] = (value, size)
            self._bytes += size
            while self._bytes > self.max_bytes and self._items:
                _, (_, removed_size) = self._items.popitem(last=False)
                self._bytes -= removed_size
                self._evictions += 1

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> tuple[T, bool]:
        cached = self.get(key)
        if cached is not None:
            return cached, True  # type: ignore[return-value]

        with self._lock:
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight(Event())
                self._flights[key] = flight
                owner = True
            else:
                self._waits += 1
                owner = False

        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            with self._lock:
                item = self._items.get(key)
                if item is None:
                    # The computed object may exceed the memory budget. In that
                    # unusual case the waiter recomputes rather than receiving
                    # an unavailable payload.
                    pass
                else:
                    self._hits += 1
                    self._items.move_to_end(key)
                    return item[0], True  # type: ignore[return-value]
            return compute(), False

        try:
            value = compute()
            self.put(key, value)
            return value, False
        except BaseException as exc:  # noqa: BLE001 - propagate same error to waiters
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(key, None)
                flight.event.set()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0
            self._flights.clear()
            self._hits = self._misses = self._evictions = self._waits = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._items),
                "bytes": self._bytes,
                "max_bytes": self.max_bytes,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "single_flight_waits": self._waits,
                "inflight": len(self._flights),
            }


def _default_budget_bytes() -> int:
    raw = os.environ.get("CLIMAFLORA_SEARCH_VECTOR_CACHE_MB", "192")
    try:
        megabytes = max(32, int(raw))
    except ValueError:
        megabytes = 192
    return megabytes * 1024 * 1024


_CACHE = ScientificVectorCache(_default_budget_bytes())


def climate_vector_key(
    matrix: ClimateRuntimeMatrix,
    profile: ClimateProfile,
    *,
    min_known_weight: float,
) -> str:
    return _digest(
        {
            "kind": "climate",
            "cache_format": SEARCH_CACHE_FORMAT_VERSION,
            "method": METHOD_VERSION,
            "runtime": _catalog_runtime_identity(matrix),
            "scientific_signature": climate_scientific_signature(profile),
            "min_known_weight": float(min_known_weight).hex(),
        }
    )


def soil_vector_key(
    matrix: ClimateRuntimeMatrix,
    profile: SoilProfile,
    *,
    min_known_weight: float,
) -> str:
    return _digest(
        {
            "kind": "soil",
            "cache_format": SEARCH_CACHE_FORMAT_VERSION,
            "method": METHOD_VERSION,
            "runtime": _catalog_runtime_identity(matrix),
            "scientific_signature": soil_scientific_signature(profile),
            "min_known_weight": float(min_known_weight).hex(),
        }
    )


def combined_vector_key(
    matrix: ClimateRuntimeMatrix,
    climate_key: str,
    soil_key: str,
) -> str:
    return _digest(
        {
            "kind": "combined-ranking",
            "cache_format": SEARCH_CACHE_FORMAT_VERSION,
            "method": METHOD_VERSION,
            "runtime": _catalog_runtime_identity(matrix),
            "climate_key": climate_key,
            "soil_key": soil_key,
        }
    )


def get_climate_score_vector(
    catalog_path: str | Path,
    profile: ClimateProfile,
    *,
    min_known_weight: float = 0.50,
) -> tuple[ClimateRuntimeMatrix, CacheResult[ClimateScoreVector]]:
    matrix = load_climate_runtime_matrix(catalog_path)
    key = climate_vector_key(matrix, profile, min_known_weight=min_known_weight)
    value, hit = _CACHE.get_or_compute(
        key,
        lambda: score_climate_vector(
            matrix,
            profile.variables,
            min_known_weight=min_known_weight,
        ),
    )
    return matrix, CacheResult(value=value, key=key, cache_hit=hit)


def get_soil_score_vector(
    catalog_path: str | Path,
    matrix: ClimateRuntimeMatrix,
    profile: SoilProfile,
    *,
    min_known_weight: float = 0.50,
) -> CacheResult[SoilScoreVector]:
    key = soil_vector_key(matrix, profile, min_known_weight=min_known_weight)
    value, hit = _CACHE.get_or_compute(
        key,
        lambda: score_soil_vector(
            catalog_path,
            matrix,
            profile.properties,
            min_known_weight=min_known_weight,
        ),
    )
    return CacheResult(value=value, key=key, cache_hit=hit)


def get_combined_score_vector(
    matrix: ClimateRuntimeMatrix,
    climate: CacheResult[ClimateScoreVector],
    soil: CacheResult[SoilScoreVector],
) -> CacheResult[CombinedScoreVector]:
    key = combined_vector_key(matrix, climate.key, soil.key)
    value, hit = _CACHE.get_or_compute(
        key,
        lambda: combine_score_vectors(matrix, climate.value, soil.value),
    )
    return CacheResult(value=value, key=key, cache_hit=hit)


def vector_cache_stats() -> dict[str, int]:
    return _CACHE.stats()


def clear_vector_cache() -> None:
    _CACHE.clear()
