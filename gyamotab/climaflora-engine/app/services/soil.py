from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Any

import httpx
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import xy as transform_xy
from rasterio.warp import transform

from app.domain.models import Confidence, SoilProfile

# SoilGrids 2.0 WCS. The 5-15 cm interval is used as a pragmatic topsoil
# descriptor for interactive point queries. Values are medians (Q0.5).
SOILGRIDS_DEPTH = "5-15cm"
SOILGRIDS_QUANTILE = "Q0.5"
SOILGRIDS_IGH = CRS.from_string("+proj=igh +lat_0=0 +lon_0=0 +datum=WGS84 +units=m +no_defs")
SOILGRIDS_CRS_URI = "http://www.opengis.net/def/crs/EPSG/0/152160"
SOILGRIDS_WINDOW_HALF_M = 1250.0
SOILGRIDS_MAX_FALLBACK_M = 1800.0

# Factors follow SoilGrids encoding. v1.6 taxon niches use the same physical
# units, so local point profiles can now evaluate all seven shared variables.
PROPERTY_SPECS: dict[str, dict[str, Any]] = {
    "ph": {"layer": "phh2o", "factor": 10.0, "unit": "pH", "min": 0.1, "max": 14.0},
    "clay_pct": {"layer": "clay", "factor": 10.0, "unit": "%", "min": 0.1, "max": 100.0},
    "sand_pct": {"layer": "sand", "factor": 10.0, "unit": "%", "min": 0.1, "max": 100.0},
    "silt_pct": {"layer": "silt", "factor": 10.0, "unit": "%", "min": 0.1, "max": 100.0},
    "cec_cmol_kg": {"layer": "cec", "factor": 10.0, "unit": "cmol(+)/kg", "min": 0.1, "max": 200.0},
    "coarse_fragments_pct": {"layer": "cfvo", "factor": 10.0, "unit": "% vol.", "min": 0.0, "max": 100.0},
    "soc_g_kg": {"layer": "soc", "factor": 10.0, "unit": "g/kg", "min": 0.0, "max": 1000.0},
    "nitrogen_g_kg": {"layer": "nitrogen", "factor": 100.0, "unit": "g/kg", "min": 0.0, "max": 100.0},
}


def texture_label(properties: dict[str, float | str | None]) -> str | None:
    clay = properties.get("clay_pct")
    sand = properties.get("sand_pct")
    silt = properties.get("silt_pct")
    if not all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in (clay, sand, silt)):
        return None
    clay, sand, silt = float(clay), float(sand), float(silt)
    if clay >= 40:
        return "argileux"
    if sand >= 70:
        return "sableux"
    if silt >= 60:
        return "limoneux"
    if clay >= 27:
        return "argilo-mixte"
    if sand >= 50:
        return "sablo-mixte"
    if silt >= 40:
        return "limono-mixte"
    return "texture mixte"


def ecocrop_texture_class(properties: dict[str, float | str | None]) -> str | None:
    """Broad heavy/medium/light crosswalk for ECOCROP compatibility."""
    clay = properties.get("clay_pct")
    sand = properties.get("sand_pct")
    if not all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in (clay, sand)):
        return None
    clay, sand = float(clay), float(sand)
    if clay >= 35:
        return "heavy"
    if sand >= 65:
        return "light"
    return "medium"


def _valid_scaled_value(key: str, value: float | None) -> bool:
    if value is None or not math.isfinite(float(value)):
        return False
    spec = PROPERTY_SPECS[key]
    return float(spec["min"]) <= float(value) <= float(spec["max"])


def _profile_plausibility(properties: dict[str, float | str | None]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    ph = properties.get("ph")
    if not isinstance(ph, (int, float)) or not (0.1 <= float(ph) <= 14.0):
        reasons.append("invalid_ph")
    fractions = [properties.get(k) for k in ("sand_pct", "silt_pct", "clay_pct")]
    numeric = [float(v) for v in fractions if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if len(numeric) < 2:
        reasons.append("insufficient_texture")
    elif sum(numeric) < 20.0:
        reasons.append("implausible_texture_sum")
    cec = properties.get("cec_cmol_kg")
    if cec is not None and (not isinstance(cec, (int, float)) or float(cec) <= 0):
        reasons.append("invalid_cec")
    return not reasons, reasons


class SoilGridsWcsProvider:
    def __init__(
        self,
        base_url: str = "https://maps.isric.org/mapserv",
        *,
        depth: str = SOILGRIDS_DEPTH,
        quantile: str = SOILGRIDS_QUANTILE,
        timeout_seconds: float = 20.0,
        cache_size: int = 1024,
        cache_ttl_seconds: int = 86400,
    ):
        self.base_url = base_url.rstrip("?")
        self.depth = depth
        self.quantile = quantile
        self.timeout_seconds = timeout_seconds
        self.cache_size = max(1, cache_size)
        self.cache_ttl_seconds = max(1, cache_ttl_seconds)
        self._cache: OrderedDict[tuple, tuple[float, SoilProfile]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def readiness(self) -> dict[str, Any]:
        return {
            "ready": bool(self.base_url.startswith("https://")),
            "provider": "SoilGrids 2.0 WCS",
            "depth": self.depth,
            "resolution_m": 250,
            "source": "ISRIC SoilGrids",
            "properties": list(PROPERTY_SPECS),
        }

    @staticmethod
    def _project(lat: float, lon: float) -> tuple[float, float]:
        xs, ys = transform("EPSG:4326", SOILGRIDS_IGH, [lon], [lat])
        return float(xs[0]), float(ys[0])

    def _request_params(self, layer: str, x: float, y: float) -> list[tuple[str, str]]:
        half = SOILGRIDS_WINDOW_HALF_M
        coverage = f"{layer}_{self.depth}_{self.quantile}"
        return [
            ("map", f"/map/{layer}.map"),
            ("SERVICE", "WCS"),
            ("VERSION", "2.0.1"),
            ("REQUEST", "GetCoverage"),
            ("COVERAGEID", coverage),
            ("FORMAT", "GEOTIFF_INT16"),
            ("SUBSET", f"X({x-half:.3f},{x+half:.3f})"),
            ("SUBSET", f"Y({y-half:.3f},{y+half:.3f})"),
            ("SUBSETTINGCRS", SOILGRIDS_CRS_URI),
            ("OUTPUTCRS", SOILGRIDS_CRS_URI),
        ]

    @staticmethod
    def _nearest_valid_value(dataset, key: str, x: float, y: float) -> tuple[float | None, float | None]:
        spec = PROPERTY_SPECS[key]
        band = dataset.read(1, masked=True)
        candidates: list[tuple[float, float]] = []
        for row, col in np.argwhere(~np.ma.getmaskarray(band)):
            raw = float(band[row, col])
            if dataset.nodata is not None and raw == float(dataset.nodata):
                continue
            scaled = raw / float(spec["factor"])
            if not _valid_scaled_value(key, scaled):
                continue
            px, py = transform_xy(dataset.transform, int(row), int(col), offset="center")
            distance = math.hypot(float(px) - x, float(py) - y)
            if distance <= SOILGRIDS_MAX_FALLBACK_M:
                candidates.append((distance, scaled))
        if not candidates:
            return None, None
        distance, scaled = min(candidates, key=lambda item: item[0])
        return round(float(scaled), 3), round(float(distance), 1)

    def _sample_property(self, key: str, x: float, y: float) -> tuple[float | None, float | None]:
        spec = PROPERTY_SPECS[key]
        params = self._request_params(spec["layer"], x, y)
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(self.base_url, params=params, headers={"Accept": "image/tiff,*/*;q=0.8"})
            response.raise_for_status()
            payload = response.content
        if not payload:
            return None, None
        with MemoryFile(payload) as mem:
            with mem.open() as dataset:
                sampled = next(dataset.sample([(x, y)], masked=True))[0]
                if not np.ma.is_masked(sampled):
                    raw = float(sampled)
                    if dataset.nodata is None or raw != float(dataset.nodata):
                        scaled = raw / float(spec["factor"])
                        if _valid_scaled_value(key, scaled):
                            return round(float(scaled), 3), 0.0
                return self._nearest_valid_value(dataset, key, x, y)

    @staticmethod
    def _manual_values(overrides: dict[str, Any] | None) -> dict[str, float | str]:
        if not overrides:
            return {}
        out: dict[str, float | str] = {}
        for key in PROPERTY_SPECS:
            value = overrides.get(key)
            if value is None or value == "":
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and _valid_scaled_value(key, number):
                out[key] = number
        drainage = str(overrides.get("drainage") or "").strip().lower()
        if drainage in {"well_drained", "moderate", "poor", "excessive"}:
            out["drainage"] = drainage
        return out

    def _cache_key(self, lat: float, lon: float, manual: dict[str, float | str]) -> tuple:
        return (round(lat, 3), round(lon, 3), tuple(sorted(manual.items())))

    def profile(self, lat: float, lon: float, overrides: dict[str, Any] | None = None) -> SoilProfile:
        manual = self._manual_values(overrides)
        key = self._cache_key(lat, lon, manual)
        now = time.time()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= self.cache_ttl_seconds:
                self._cache.move_to_end(key)
                return cached[1].model_copy(deep=True)

        x, y = self._project(lat, lon)
        properties: dict[str, float | str | None] = {}
        errors: list[str] = []
        fallback_distances: dict[str, float] = {}
        pending = [property_key for property_key in PROPERTY_SPECS if property_key not in manual]
        for property_key in PROPERTY_SPECS:
            if property_key in manual:
                properties[property_key] = float(manual[property_key])

        with ThreadPoolExecutor(max_workers=min(3, max(1, len(pending)))) as executor:
            futures = {executor.submit(self._sample_property, property_key, x, y): property_key for property_key in pending}
            for future in as_completed(futures):
                property_key = futures[future]
                try:
                    sampled = future.result()
                    if isinstance(sampled, tuple):
                        value, distance = sampled
                    else:
                        value, distance = sampled, 0.0
                    properties[property_key] = value
                    if distance is not None and distance > 0:
                        fallback_distances[property_key] = float(distance)
                except Exception as exc:  # noqa: BLE001
                    properties[property_key] = None
                    errors.append(f"{property_key}: {type(exc).__name__}")
        if "drainage" in manual:
            properties["drainage"] = manual["drainage"]
        properties["texture"] = texture_label(properties)
        properties["texture_class"] = ecocrop_texture_class(properties)

        plausible, plausibility_reasons = _profile_plausibility(properties)
        known_grid = sum(properties.get(k) is not None for k in PROPERTY_SPECS)
        if manual:
            confidence = Confidence.B
        elif plausible and known_grid >= 6:
            confidence = Confidence.C
        elif plausible and known_grid:
            confidence = Confidence.D
        else:
            confidence = Confidence.UNKNOWN

        warnings = ["SoilGrids est un modèle global à 250 m : le profil estimé ne remplace pas une analyse de sol de parcelle."]
        if fallback_distances:
            maximum = max(fallback_distances.values())
            warnings.append(f"Le pixel exact était NoData pour certaines propriétés ; cellule SoilGrids valide la plus proche utilisée (jusqu’à {maximum:.0f} m).")
        if not plausible and not manual:
            warnings.append("Profil SoilGrids non plausible/NoData : aucune compatibilité édaphique ne doit être déduite de ces valeurs.")
        if errors:
            warnings.append("Certaines propriétés SoilGrids sont indisponibles : " + ", ".join(errors))

        result = SoilProfile(
            latitude=lat,
            longitude=lon,
            provider="SoilGrids 2.0 / ISRIC",
            depth=self.depth,
            resolution_m=250,
            properties=properties,
            confidence=confidence,
            manual_override=bool(manual),
            provenance={
                "access": "WCS 2.0.1",
                "prediction": self.quantile,
                "wcs_base": self.base_url,
                "license": "CC-BY 4.0",
                "user_override_fields": sorted(manual),
                "sampling_strategy": "exact_pixel_then_nearest_valid_within_1.8km",
                "fallback_distance_m": fallback_distances,
                "profile_plausible": plausible,
                "plausibility_reasons": plausibility_reasons,
            },
            warnings=warnings,
        )
        with self._cache_lock:
            self._cache[key] = (now, result.model_copy(deep=True))
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return result


class UnavailableSoilProvider:
    def readiness(self) -> dict[str, Any]:
        return {"ready": False, "provider": "UNAVAILABLE", "properties": list(PROPERTY_SPECS)}

    def profile(self, lat: float, lon: float, overrides: dict[str, Any] | None = None) -> SoilProfile:
        manual = SoilGridsWcsProvider._manual_values(overrides)
        properties: dict[str, float | str | None] = {key: manual.get(key) for key in PROPERTY_SPECS}
        if "drainage" in manual:
            properties["drainage"] = manual["drainage"]
        properties["texture"] = texture_label(properties)
        properties["texture_class"] = ecocrop_texture_class(properties)
        return SoilProfile(
            latitude=lat,
            longitude=lon,
            provider="USER" if manual else "UNAVAILABLE",
            properties=properties,
            confidence=Confidence.B if manual else Confidence.UNKNOWN,
            manual_override=bool(manual),
            provenance={"user_override_fields": sorted(manual)},
            warnings=[] if manual else ["Profil de sol indisponible."],
        )


@lru_cache(maxsize=8)
def make_soil_provider(name: str, base_url: str = "https://maps.isric.org/mapserv"):
    if name.strip().lower() in {"soilgrids", "soilgrids_wcs", "isric"}:
        return SoilGridsWcsProvider(base_url)
    return UnavailableSoilProvider()
