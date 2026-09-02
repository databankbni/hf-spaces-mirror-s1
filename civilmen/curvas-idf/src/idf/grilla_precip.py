"""Climatología de precipitación gridded sobre Bolivia.

Provee precipitación media anual, distribución mensual y máximos en 24 h
interpolados al punto de estudio desde una grilla pre-computada. Reemplaza
o complementa la información satelital de GEE (CHIRPS / ERA5) cuando esta
no está disponible (sin credenciales, sin red, o fuera del rango operativo
del Space).

El grid se carga al import desde `grilla_precip_bolivia.json.gz` en el mismo
directorio (≤ 200 KB gzipped, sin dependencias de NetCDF/xarray). Cada celda
contiene:

    {
      "lat": -17.4, "lon": -66.2,
      "p_anual_mm": 480.0,
      "p_mensual_mm": [98, 88, 65, 30, ..., 80],   # 12 valores enero-diciembre
      "p24_media_mm": 38.0,
      "p24_desv_mm": 11.0,
      "fuente": "SENAMHI_IDW"   # SENAMHI_IDW / SAAVEDRA_ZENODO / WORLDCLIM
    }

Para producción se recomienda regenerar el grid con
`scripts/build_grilla_precip.py` consumiendo el dataset Zenodo 6991231 de
Saavedra & Ureña (CHIRPS+GSMaP+SENAMHI merged 0.05° diario Bolivia
2000-2015, CC-BY 4.0).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Optional


_GRID_FILE = Path(__file__).parent / "grilla_precip_bolivia.json.gz"


@dataclass
class CeldaGrilla:
    lat: float
    lon: float
    p_anual_mm: float
    p_mensual_mm: list[float]
    p24_media_mm: float
    p24_desv_mm: float
    fuente: str


@dataclass
class ClimatologiaPunto:
    """Climatología interpolada al sitio de estudio."""
    lat: float
    lon: float
    p_anual_mm: float
    p_mensual_mm: list[float]
    p24_media_mm: float
    p24_desv_mm: float
    fuente: str           # "SENAMHI_IDW" / "SAAVEDRA_ZENODO" / etc.
    distancia_a_celda_km: float
    celdas_usadas: int


_grid_cache: Optional[list[CeldaGrilla]] = None
_grid_intentado: bool = False


def _cargar_grilla() -> list[CeldaGrilla]:
    global _grid_cache, _grid_intentado
    if _grid_intentado:
        return _grid_cache or []
    _grid_intentado = True
    if not _GRID_FILE.exists():
        return []
    try:
        with gzip.open(_GRID_FILE, "rt", encoding="utf-8") as f:
            rows = json.load(f)
        _grid_cache = [CeldaGrilla(**r) for r in rows]
    except Exception:  # noqa: BLE001
        _grid_cache = []
    return _grid_cache or []


def _haversine_km(la1: float, lo1: float, la2: float, lo2: float) -> float:
    R = 6371.0088
    la1, lo1, la2, lo2 = map(radians, (la1, lo1, la2, lo2))
    a = (sin((la2 - la1) / 2) ** 2
          + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * asin(sqrt(a))


def climatologia_punto(lat: float, lon: float,
                          k: int = 4) -> Optional[ClimatologiaPunto]:
    """IDW (1/d²) de las k celdas más cercanas para interpolar al sitio.

    Devuelve None si la grilla no está cargada o está vacía. Si una celda
    cae < 1 km del sitio, devuelve directamente sus valores.
    """
    grid = _cargar_grilla()
    if not grid:
        return None
    distancias = [(_haversine_km(lat, lon, c.lat, c.lon), c) for c in grid]
    distancias.sort(key=lambda x: x[0])
    if distancias[0][0] < 1.0:
        c = distancias[0][1]
        return ClimatologiaPunto(
            lat=lat, lon=lon, p_anual_mm=c.p_anual_mm,
            p_mensual_mm=list(c.p_mensual_mm),
            p24_media_mm=c.p24_media_mm, p24_desv_mm=c.p24_desv_mm,
            fuente=c.fuente, distancia_a_celda_km=distancias[0][0],
            celdas_usadas=1)
    seleccion = distancias[:k]
    w_sum = 0.0
    p_anual = 0.0
    p24_media = 0.0
    p24_desv = 0.0
    p_mes = [0.0] * 12
    fuentes = []
    for d, c in seleccion:
        w = 1.0 / max(d, 0.5) ** 2
        w_sum += w
        p_anual += w * c.p_anual_mm
        p24_media += w * c.p24_media_mm
        p24_desv += w * c.p24_desv_mm
        for i in range(12):
            p_mes[i] += w * (c.p_mensual_mm[i]
                              if i < len(c.p_mensual_mm) else 0)
        fuentes.append(c.fuente)
    fuente_dom = max(set(fuentes), key=fuentes.count) if fuentes else "—"
    return ClimatologiaPunto(
        lat=lat, lon=lon,
        p_anual_mm=p_anual / w_sum,
        p_mensual_mm=[v / w_sum for v in p_mes],
        p24_media_mm=p24_media / w_sum,
        p24_desv_mm=p24_desv / w_sum,
        fuente=fuente_dom,
        distancia_a_celda_km=seleccion[0][0],
        celdas_usadas=k,
    )


def info_grilla() -> dict:
    grid = _cargar_grilla()
    if not grid:
        return {"disponible": False, "n_celdas": 0}
    lats = [c.lat for c in grid]
    lons = [c.lon for c in grid]
    fuentes = {}
    for c in grid:
        fuentes[c.fuente] = fuentes.get(c.fuente, 0) + 1
    return {
        "disponible": True,
        "n_celdas": len(grid),
        "lat_min": min(lats), "lat_max": max(lats),
        "lon_min": min(lons), "lon_max": max(lons),
        "fuentes": fuentes,
    }
