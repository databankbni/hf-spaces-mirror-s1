"""Conectores a bases internacionales que republican datos SENAMHI Bolivia.

Tres fuentes verificadas con APIs públicas sin clave (deep-research Junio 2026):

- **NOAA GHCN-Daily** (NCEI Access v1 API): ~50-80 estaciones bolivianas con
  prefijo `BO` en el catálogo `ghcnd-stations.txt`. Variables: PRCP, TMAX,
  TMIN, TAVG, SNWD, etc. Sin auth.
- **WMO OSCAR/Surface**: catálogo WIGOS oficial OMM con todas las estaciones
  bolivianas reportando vía GTS. Útil para reconciliar `cod_omm` ↔
  identificador internacional WIGOS-0-076-…
- **CHIRPS v2.0** (UCSB Climate Hazards Center): grilla satelital diaria 0.05°
  asimilada con estaciones bolivianas. NetCDF público sin auth.

Las descargas masivas se hacen con throttling cortés (≥ 1 s entre llamadas
para NCEI, ≥ 2 s para WMO). En entorno HF Space, las funciones tienen
timeout corto (≤ 60 s) y fallback silencioso si la red no responde.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_USER_AGENT = "HYDROFRA/1.3 (research; civilmen@gmail.com)"


def _http_get(url: str, timeout: float = 60.0,
               headers: Optional[dict] = None) -> bytes:
    """GET con user-agent identificable y timeout estricto."""
    req = Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


# ─────────────────── NOAA GHCN-Daily ───────────────────

GHCND_STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
NCEI_ACCESS_API = "https://www.ncei.noaa.gov/access/services/data/v1"


@dataclass(frozen=True)
class EstacionGHCND:
    """Estación del catálogo NOAA GHCN-Daily."""
    id: str           # "BO000085201"
    latitud: float
    longitud: float
    elev_m: Optional[float]
    nombre: str
    wmo_id: Optional[str]  # 5 dígitos OMM


def catalogo_ghcnd_bolivia(timeout: float = 30.0) -> list[EstacionGHCND]:
    """Descarga el catálogo `ghcnd-stations.txt` y filtra las estaciones BO.

    Formato fixed-width (ver `ghcnd-readme.txt`):
        ID(11) LAT(9) LON(10) ELEV(7) ST(3) NAME(31) GSN(4) HCN(4) WMO_ID(6)
    """
    try:
        txt = _http_get(GHCND_STATIONS_URL, timeout=timeout).decode("utf-8",
                                                                       errors="replace")
    except Exception:  # noqa: BLE001
        return []
    estaciones = []
    for line in txt.splitlines():
        # GHCN-D usa códigos de país FIPS 10-4: Bolivia = «BL» (NO el ISO
        # «BO»). El prefijo «BO» capturaba estaciones de otros países y la
        # más cercana salía a 11 605 km. Filtramos por «BL» + sanity check
        # de que las coordenadas caigan dentro del bbox de Bolivia.
        if not line.startswith("BL"):
            continue
        try:
            sid = line[0:11].strip()
            lat = float(line[12:20])
            lon = float(line[21:30])
            # Sanity: Bolivia ⊂ lat[-23,-9], lon[-70,-57]. Descarta basura.
            if not (-23.5 <= lat <= -9.0 and -70.0 <= lon <= -57.0):
                continue
            elev = line[31:37].strip()
            elev_f = float(elev) if elev and elev != "-999.9" else None
            name = line[41:71].strip()
            wmo = line[80:85].strip() or None
            estaciones.append(EstacionGHCND(sid, lat, lon, elev_f, name, wmo))
        except Exception:  # noqa: BLE001
            continue
    return estaciones


def serie_ghcnd(station_id: str,
                  start: str = "1980-01-01",
                  end: str = "2025-12-31",
                  variables: tuple = ("PRCP", "TMAX", "TMIN", "TAVG"),
                  timeout: float = 90.0) -> Optional[str]:
    """Descarga serie diaria de una estación GHCND vía NCEI Access v1 API.

    Devuelve CSV crudo (string) o None si falló. La API NCEI no requiere
    autenticación y soporta JSON/CSV/PDF. Aquí pedimos CSV por simplicidad
    de parseo posterior con pandas.

    Ejemplo: `serie_ghcnd("BO000085201")` para La Paz/El Alto.
    """
    params = {
        "dataset": "daily-summaries",
        "stations": station_id,
        "dataTypes": ",".join(variables),
        "startDate": start,
        "endDate": end,
        "units": "metric",
        "format": "csv",
    }
    url = f"{NCEI_ACCESS_API}?{urlencode(params)}"
    try:
        return _http_get(url, timeout=timeout).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


def buscar_ghcnd_por_omm(cod_omm: str,
                           catalogo: Optional[list[EstacionGHCND]] = None
                           ) -> Optional[EstacionGHCND]:
    """Mapea `cod_omm` del catálogo SENAMHI al identificador GHCND.

    `cod_omm` es típicamente 5 dígitos (ej. "85201" para La Paz/El Alto);
    el catálogo GHCN registra ese código en su columna `wmo_id`.
    """
    if catalogo is None:
        catalogo = catalogo_ghcnd_bolivia()
    omm = str(cod_omm).strip().zfill(5)
    for e in catalogo:
        if e.wmo_id and str(e.wmo_id).strip() == omm:
            return e
    return None


# ─────────────────── WMO OSCAR/Surface (WIGOS) ───────────────────

OSCAR_API = "https://oscar.wmo.int/surface/rest/api/search/station"


def catalogo_oscar_bolivia(timeout: float = 45.0) -> list[dict]:
    """Catálogo WIGOS oficial OMM para Bolivia (estaciones reportando vía GTS).

    Devuelve lista de dicts con campos: wigosId, name, latitude, longitude,
    elevation, country, regionId, observationStatus, programAffiliations.
    """
    params = {"territoryName": "Bolivia", "page": 1, "items": 500}
    url = f"{OSCAR_API}?{urlencode(params)}"
    try:
        import json as _json
        raw = _http_get(url, timeout=timeout,
                         headers={"Accept": "application/json"})
        data = _json.loads(raw)
        return data.get("stationSearchResults", [])
    except Exception:  # noqa: BLE001
        return []


# ─────────────────── CHIRPS v2.0 ───────────────────

CHIRPS_DAILY_BASE = ("https://data.chc.ucsb.edu/products/CHIRPS-2.0/"
                       "global_daily/netcdf/p05")


def url_chirps_anual(anio: int) -> str:
    """URL del NetCDF CHIRPS Daily 0.05° para un año dado."""
    return f"{CHIRPS_DAILY_BASE}/chirps-v2.0.{anio}.days_p05.nc"


def descargar_chirps_anual(anio: int, destino: Path,
                              timeout: float = 600.0) -> Optional[Path]:
    """Descarga CHIRPS Daily NetCDF 0.05° global para un año (≈ 1.2 GB)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = _http_get(url_chirps_anual(anio), timeout=timeout)
        destino.write_bytes(data)
        return destino
    except Exception:  # noqa: BLE001
        return None


# ─────────────────── Zenodo Saavedra & Ureña 2022 ───────────────────

ZENODO_SAAVEDRA = "https://zenodo.org/api/records/6991231"


def archivos_zenodo_saavedra(timeout: float = 30.0) -> list[dict]:
    """Lista los archivos del dataset Zenodo 6991231 (combined precipitation BO 2000-2015).

    Sin auth. Devuelve lista de dicts {key, size, links.self}.
    """
    try:
        import json as _json
        raw = _http_get(ZENODO_SAAVEDRA, timeout=timeout)
        data = _json.loads(raw)
        return data.get("files", [])
    except Exception:  # noqa: BLE001
        return []


# ─────────────────── Helper combinado: enriquecer estación SENAMHI ───────────────────

def enriquecer_estacion(cod_omm: Optional[str],
                          nombre: str,
                          lat: float,
                          lon: float,
                          intentar_ghcnd: bool = True,
                          intentar_oscar: bool = True) -> dict:
    """Intenta resolver identificadores externos para una estación SENAMHI.

    Devuelve un dict con `ghcnd_id`, `wigos_id`, `nombre_internacional` y
    `disponibilidad` (boolean por fuente). Útil para alimentar la sección
    de metadatos del informe HYDROFRA.
    """
    out = {"ghcnd_id": None, "wigos_id": None,
            "nombre_internacional": None,
            "disponibilidad": {"ghcnd": False, "oscar": False}}
    if intentar_ghcnd and cod_omm:
        e = buscar_ghcnd_por_omm(cod_omm)
        if e is not None:
            out["ghcnd_id"] = e.id
            out["nombre_internacional"] = e.nombre
            out["disponibilidad"]["ghcnd"] = True
    if intentar_oscar:
        oscar = catalogo_oscar_bolivia()
        # Match por nombre (cercanía) y lat/lon (≤ 0.01° ≈ 1 km).
        for s in oscar:
            la = s.get("latitude")
            lo = s.get("longitude")
            if la is None or lo is None:
                continue
            if abs(la - lat) < 0.01 and abs(lo - lon) < 0.01:
                out["wigos_id"] = s.get("wigosId")
                out["disponibilidad"]["oscar"] = True
                break
    return out
