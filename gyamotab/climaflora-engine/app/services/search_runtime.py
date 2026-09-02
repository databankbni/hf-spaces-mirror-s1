from __future__ import annotations

import hashlib
import json
import math
from time import perf_counter
from typing import Any, Callable

from app.domain.models import ClimateProfile, SoilProfile

CLIMATE_SCORING_VARIABLES = ("bio01", "bio05", "bio06", "bio12", "bio15")


def elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000.0, 3)


def timed_call(callable_: Callable[..., Any], *args: Any) -> tuple[Any, float, Exception | None]:
    """Execute one independent provider call and retain timing on failure."""
    started = perf_counter()
    try:
        return callable_(*args), elapsed_ms(started), None
    except Exception as exc:  # noqa: BLE001 - caller owns source-specific fallback
        return None, elapsed_ms(started), exc


def _canonical(value: Any) -> Any:
    """Return a JSON-safe representation that preserves exact float64 identity."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"float": "nan"}
        if math.isinf(value):
            return {"float": "+inf" if value > 0 else "-inf"}
        return {"float": value.hex()}
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return str(value)


def _signature(payload: dict[str, Any]) -> str:
    raw = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def climate_scientific_signature(profile: ClimateProfile) -> str:
    """Identity of the climate data that can affect the current scientific score.

    Latitude/longitude are deliberately absent. Scientific reuse is allowed only
    when the resolved CHELSA source identity and the five scoring values are the
    same, which is stricter and more meaningful than arbitrary coordinate rounding.
    """
    provenance = profile.provenance or {}
    payload = {
        "format": "climate-score-input-v1",
        "provider": profile.provider,
        "dataset": provenance.get("dataset"),
        "dataset_version": provenance.get("version"),
        "manifest_revision": provenance.get("manifest_revision"),
        "horizon": str(profile.horizon),
        "scenario": str(profile.scenario),
        "period": profile.period,
        "model": profile.model,
        "scenario_mapping": provenance.get("scenario_mapping"),
        "variables": {
            variable: profile.variables.get(variable)
            for variable in CLIMATE_SCORING_VARIABLES
        },
    }
    return _signature(payload)


def soil_scientific_signature(profile: SoilProfile) -> str:
    """Identity of the resolved soil inputs that can affect soil scoring.

    The signature is based on resolved properties plus source/depth/quantile
    identity. Coordinate rounding and fallback distance are intentionally absent.
    Manual and gridded profiles with identical resolved scoring inputs may share a
    future SoilScoreVector; page-level provenance remains attached to the profile.
    """
    provenance = profile.provenance or {}
    payload = {
        "format": "soil-score-input-v1",
        "provider": profile.provider,
        "depth": profile.depth,
        "resolution_m": profile.resolution_m,
        "access": provenance.get("access"),
        "prediction": provenance.get("prediction"),
        "wcs_base": provenance.get("wcs_base"),
        "properties": profile.properties,
    }
    return _signature(payload)
