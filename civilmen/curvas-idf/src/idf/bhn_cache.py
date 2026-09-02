"""Lector del caché BHN persistido por el scraper offline.

El scraper `scripts/scrape_bhn.py` consolida los registros parseados de los
PDFs descargados en `src/idf/bhn_estaciones_cache.json` (committeable). La
webapp llama solo a `cache_climatologia_hidro(nombre, lat, lon)` que devuelve
estadísticos derivados (Q medio, Q mín, n años, alerta más reciente) por
estación o None si no hay datos para ese sitio en el caché.

Formato del JSON (estructura mínima):
{
  "fecha_actualizacion": "2026-06-17T22:30:00Z",
  "estaciones": {
    "Villa Montes": {
      "rio": "Pilcomayo",
      "n_observaciones": 1240,
      "fecha_primera": "2020-01-01",
      "fecha_ultima": "2026-06-15",
      "nivel_medio_m": 1.85, "nivel_min_m": 0.62, "nivel_max_m": 5.41,
      "caudal_medio_m3s": 180.5, "caudal_min_m3s": 12.3, "caudal_max_m3s": 4200.0,
      "alerta_recientes": ["ROJA", "AMARILLA", ...]   // últimas 30
    },
    ...
  }
}

Si el caché no existe, todas las funciones devuelven None silenciosamente; el
pipeline cae a la climatología regional sintética.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_CACHE_FILE = Path(__file__).parent / "bhn_estaciones_cache.json"


@dataclass
class ClimatologiaBHN:
    nombre: str
    rio: Optional[str]
    n_observaciones: int
    fecha_primera: str
    fecha_ultima: str
    nivel_medio_m: Optional[float]
    nivel_min_m: Optional[float]
    nivel_max_m: Optional[float]
    caudal_medio_m3s: Optional[float]
    caudal_min_m3s: Optional[float]
    caudal_max_m3s: Optional[float]
    alertas_recientes: list[str]


_cache_dict: Optional[dict] = None
_cache_intentado: bool = False


def _cargar_cache() -> dict:
    global _cache_dict, _cache_intentado
    if _cache_intentado:
        return _cache_dict or {}
    _cache_intentado = True
    if not _CACHE_FILE.exists():
        return {}
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            _cache_dict = json.load(f)
    except Exception:  # noqa: BLE001
        _cache_dict = {}
    return _cache_dict or {}


def estaciones_disponibles() -> list[str]:
    return list(_cargar_cache().get("estaciones", {}).keys())


def climatologia_de(nombre_estacion: str) -> Optional[ClimatologiaBHN]:
    """Busca en el caché por nombre exacto o por coincidencia parcial."""
    cache = _cargar_cache()
    est_dict = cache.get("estaciones", {})
    raw = est_dict.get(nombre_estacion)
    if raw is None:
        # Match parcial case-insensitive
        target = nombre_estacion.strip().lower()
        for k, v in est_dict.items():
            if target in k.lower() or k.lower() in target:
                raw = v
                break
    if raw is None:
        return None
    return ClimatologiaBHN(
        nombre=nombre_estacion,
        rio=raw.get("rio"),
        n_observaciones=int(raw.get("n_observaciones", 0)),
        fecha_primera=raw.get("fecha_primera", ""),
        fecha_ultima=raw.get("fecha_ultima", ""),
        nivel_medio_m=raw.get("nivel_medio_m"),
        nivel_min_m=raw.get("nivel_min_m"),
        nivel_max_m=raw.get("nivel_max_m"),
        caudal_medio_m3s=raw.get("caudal_medio_m3s"),
        caudal_min_m3s=raw.get("caudal_min_m3s"),
        caudal_max_m3s=raw.get("caudal_max_m3s"),
        alertas_recientes=list(raw.get("alertas_recientes", [])),
    )


def info_cache() -> dict:
    """Devuelve metadata del caché para mostrar en el reporte."""
    cache = _cargar_cache()
    return {
        "disponible": bool(cache),
        "fecha_actualizacion": cache.get("fecha_actualizacion"),
        "n_estaciones": len(cache.get("estaciones", {})),
    }
