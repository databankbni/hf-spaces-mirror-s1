"""MDE bare-earth (terreno sin dosel) para delineación de drenaje.

La red de drenaje y las pendientes deben derivarse del terreno real, NO
del DSM (modelo de superficie con copas de árboles y edificios). En
cuencas con cobertura densa (yungas) el DSM «inventa» quebradas por las
copas. Dos rutas:

1. FABDEM (Hawker et al. 2022): bare-earth global por ML que remueve
   bosque/edificios del COP-DEM. En dosel denso el error mediano baja a
   0.45 m (vs 2.95 m MERIT, 12.95 m COP-DEM GLO-30). PERO su licencia es
   CC BY-NC-SA 4.0 (NO comercial) → riesgo legal para un EDTP entregado
   bajo contrato. Por eso es OPT-IN: solo se usa si la env var
   HYDROFRA_USE_FABDEM=1 está activa (uso interno / académico).

2. DIY comercial-safe: COP-DEM GLO-30 (DSM) − altura de dosel
   (ETH Global Canopy Height 10 m, licencia abierta). Bare-earth
   aproximado con datasets 100 % abiertos → apto para deliverable.

Por defecto se usa la ruta DIY (comercial-safe). FABDEM solo si el
operador lo habilita explícitamente y asume la restricción de licencia.
"""

from __future__ import annotations

import os
import sys


def _msg(t: str) -> None:
    print(f"[BAREEARTH] {t}", file=sys.stderr, flush=True)


FABDEM_ASSET = "projects/sat-io/open-datasets/FABDEM"
ETH_CANOPY_ASSET = "users/nlang/ETH_GlobalCanopyHeight_2020_10m_v1"
# Alternativa de altura de dosel (Meta/WRI) si ETH no responde:
META_CANOPY_ASSET = "projects/meta-forest-monitoring-okw37/assets/CanopyHeight"


def fabdem_habilitado() -> bool:
    """True si el operador habilitó FABDEM (uso interno) vía env var."""
    return os.environ.get("HYDROFRA_USE_FABDEM", "0").lower() in (
        "1", "true", "yes", "si")


def dem_bare_earth(crs_utm: str | None = None):
    """Devuelve (ee.Image bare-earth, fuente_str) o (None, motivo).

    - Si FABDEM está habilitado (env var) → FABDEM (mejor, pero NC).
    - Si no → COP-DEM GLO-30 − altura de dosel ETH (DIY comercial-safe).
    Reproyecta a UTM si se da crs_utm (para pendientes correctas).
    """
    try:
        from .gee import _intentar_inicializar
        if not _intentar_inicializar():
            return None, "GEE no inicializa"
        import ee

        if fabdem_habilitado():
            try:
                fab = ee.ImageCollection(FABDEM_ASSET).mosaic().rename(["elevation"])
                if crs_utm:
                    fab = fab.reproject(crs=crs_utm, scale=30)
                _msg("usando FABDEM (uso interno; licencia CC BY-NC-SA)")
                return fab, "FABDEM (bare-earth ML; CC BY-NC-SA, uso interno)"
            except Exception as e:  # noqa: BLE001
                _msg(f"FABDEM falló: {type(e).__name__}: {e}; cae a DIY")

        # Ruta DIY comercial-safe: COP-DEM − altura de dosel.
        dsm = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"]))
        canopy = None
        for asset in (ETH_CANOPY_ASSET, META_CANOPY_ASSET):
            try:
                c = ee.Image(asset)
                _ = c.bandNames().getInfo()   # valida que exista
                canopy = c.select([0]).rename(["h"]).unmask(0)
                break
            except Exception:  # noqa: BLE001
                continue
        if canopy is None:
            _msg("sin dataset de dosel — se usa COP-DEM DSM crudo")
            dem = dsm
            if crs_utm:
                dem = dem.reproject(crs=crs_utm, scale=30)
            return dem, "COP-DEM GLO-30 (DSM, sin corrección de dosel)"
        # Restar la altura de dosel (clamp a [0, 60] m para evitar artefactos)
        h = canopy.clamp(0, 60)
        bare = dsm.subtract(h).rename(["elevation"])
        if crs_utm:
            bare = bare.reproject(crs=crs_utm, scale=30)
        _msg("usando COP-DEM − dosel ETH (DIY comercial-safe)")
        return bare, "COP-DEM GLO-30 − altura de dosel ETH (bare-earth, abierto)"
    except Exception as e:  # noqa: BLE001
        _msg(f"dem_bare_earth falló: {type(e).__name__}: {e}")
        return None, f"error: {type(e).__name__}"
