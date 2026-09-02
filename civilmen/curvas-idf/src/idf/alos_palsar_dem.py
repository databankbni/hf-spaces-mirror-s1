"""DEM ALOS PALSAR RTC 12.5 m vía ASF (Alaska Satellite Facility).

Reemplazo opcional de NASADEM/SRTM 30 m por ALOS PALSAR High-Resolution
Terrain Corrected DEM (12.5 m) cuando la zona tiene cobertura. El producto
es gratuito pero requiere autenticación NASA Earthdata Login (EDL).

Flujo:
1. Buscar escenas que cubren el bbox via `asf_search.search(...)`.
2. Filtrar al producto `RTC_HI_RES` (12.5 m, terrain corrected).
3. Descargar tiles GeoTIFF con credenciales EDL (env: EARTHDATA_USER +
   EARTHDATA_PASS, o EARTHDATA_TOKEN).
4. Cachear localmente bajo `/tmp/alos-cache/` con TTL 24 h.
5. Mosaicar al vuelo si el bbox abarca múltiples escenas; reproyectar a
   EPSG:4326 (lat/lon) para que sea compatible con el resto del pipeline.

Caída a falback: si no hay credenciales, si ASF no responde, si la
zona no tiene cobertura ALOS, o si ocurre cualquier error de descarga,
las funciones devuelven `None` y el pipeline cae a NASADEM/SRTM 30 m
vía GEE sin romper.

Cobertura geográfica: Bolivia tiene cobertura completa ALOS-1 (datos
2006-2011). Para zonas costeras y polares ASF ofrece cobertura más
densa por re-pasos.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# ─────────────────── Configuración ───────────────────

CACHE_DIR = Path(os.environ.get("ALOS_CACHE_DIR", "/tmp/alos-cache"))
CACHE_TTL_HORAS = int(os.environ.get("ALOS_CACHE_TTL_H", 24))
CACHE_MAX_MB = int(os.environ.get("ALOS_CACHE_MAX_MB", 600))
PRODUCTO = "RTC_HI_RES"          # 12.5 m terrain corrected
PLATFORM = "ALOS"
SEARCH_TIMEOUT_S = 30
DOWNLOAD_TIMEOUT_S = 180

_INICIALIZADO: Optional[bool] = None
_ERROR_INIT: Optional[str] = None
_AUTH = None
_descarga_lock = threading.Lock()


def _msg(texto: str) -> None:
    print(f"[ALOS] {texto}", file=sys.stderr, flush=True)


# ─────────────────── Auth + inicialización ───────────────────

def _intentar_inicializar() -> bool:
    """Inicializa la sesión ASF (autenticación EDL). Idempotente."""
    global _INICIALIZADO, _ERROR_INIT, _AUTH
    if _INICIALIZADO is not None:
        return _INICIALIZADO
    try:
        import asf_search as asf
        token = os.environ.get("EARTHDATA_TOKEN")
        user = os.environ.get("EARTHDATA_USER")
        pwd = os.environ.get("EARTHDATA_PASS")
        # Prioridad: usuario+contraseña (no caducan) sobre token (vence a los
        # 60 días). El token queda como respaldo.
        if user and pwd:
            _AUTH = asf.ASFSession().auth_with_creds(user, pwd)
            _msg(f"autenticado con EARTHDATA_USER={user[:3]}...")
        elif token:
            _AUTH = asf.ASFSession().auth_with_token(token)
            _msg("autenticado con EARTHDATA_TOKEN")
        else:
            _ERROR_INIT = ("Faltan credenciales NASA Earthdata. Definir "
                             "EARTHDATA_USER + EARTHDATA_PASS (preferido, no "
                             "caducan) o EARTHDATA_TOKEN como secrets "
                             "del Space en huggingface.co/spaces/civilmen/"
                             "curvas-idf/settings → Variables and secrets.")
            _msg(_ERROR_INIT)
            _INICIALIZADO = False
            return False
        _INICIALIZADO = True
    except ImportError as e:
        _ERROR_INIT = f"asf-search no instalado: {e}"
        _msg(_ERROR_INIT)
        _INICIALIZADO = False
    except Exception as e:  # noqa: BLE001
        _ERROR_INIT = f"{type(e).__name__}: {str(e)[:200]}"
        _msg(f"init failed: {_ERROR_INIT}")
        _INICIALIZADO = False
    return _INICIALIZADO


def disponible() -> bool:
    return _intentar_inicializar()


def estado() -> dict:
    """Diagnóstico expuesto por /alos_status (similar a /gee_status)."""
    ok = _intentar_inicializar()
    token = os.environ.get("EARTHDATA_TOKEN", "")
    user = os.environ.get("EARTHDATA_USER", "")
    return {
        "disponible": ok,
        "error_init": _ERROR_INIT,
        "secrets": {
            "EARTHDATA_TOKEN_set": bool(token),
            "EARTHDATA_TOKEN_chars": len(token),
            "EARTHDATA_USER_set": bool(user),
            "EARTHDATA_USER_value": (user[:3] + "..." if user else None),
            "EARTHDATA_PASS_set": bool(os.environ.get("EARTHDATA_PASS")),
        },
        "cache_dir": str(CACHE_DIR),
        "cache_size_mb": _cache_size_mb(),
        "cache_max_mb": CACHE_MAX_MB,
        "producto": PRODUCTO,
    }


# ─────────────────── Cache local ───────────────────

def _cache_size_mb() -> float:
    if not CACHE_DIR.exists():
        return 0.0
    total = sum(f.stat().st_size for f in CACHE_DIR.rglob("*")
                  if f.is_file())
    return round(total / (1024 * 1024), 1)


def _purgar_cache_si_supera() -> None:
    """Si el cache excede el límite, borra los más viejos primero."""
    if not CACHE_DIR.exists():
        return
    tot = _cache_size_mb()
    if tot <= CACHE_MAX_MB:
        return
    archivos = sorted(CACHE_DIR.rglob("*"),
                        key=lambda p: p.stat().st_mtime if p.is_file() else 0)
    for f in archivos:
        if not f.is_file():
            continue
        f.unlink(missing_ok=True)
        if _cache_size_mb() <= 0.75 * CACHE_MAX_MB:
            break
    _msg(f"cache purgado a {_cache_size_mb():.1f} MB")


def _cache_path(nombre_escena: str) -> Path:
    return CACHE_DIR / f"{nombre_escena}.tif"


def _cache_valido(p: Path) -> bool:
    if not p.exists():
        return False
    edad_h = (time.time() - p.stat().st_mtime) / 3600.0
    return edad_h <= CACHE_TTL_HORAS


# ─────────────────── Búsqueda y descarga ───────────────────

def _wkt_bbox(bbox: dict) -> str:
    return (f"POLYGON(({bbox['oeste']} {bbox['sur']}, "
              f"{bbox['este']} {bbox['sur']}, "
              f"{bbox['este']} {bbox['norte']}, "
              f"{bbox['oeste']} {bbox['norte']}, "
              f"{bbox['oeste']} {bbox['sur']}))")


def _buscar_escenas(bbox: dict) -> list:
    """Devuelve la lista de escenas RTC_HI_RES que cubren el bbox.

    `bbox` debe tener claves oeste/este/sur/norte en grados decimales.
    """
    if not _intentar_inicializar():
        return []
    import asf_search as asf
    wkt = _wkt_bbox(bbox)
    try:
        resultados = asf.search(
            platform=PLATFORM,
            processingLevel=PRODUCTO,
            intersectsWith=wkt,
            maxResults=8,
        )
        _msg(f"búsqueda: {len(resultados)} escenas para bbox {bbox}")
        return list(resultados)
    except Exception as e:  # noqa: BLE001
        _msg(f"búsqueda falló: {type(e).__name__}: {e}")
        return []


def diagnosticar_cobertura(bbox: dict) -> list[dict]:
    """Prueba 6 combinaciones de filtros ASF y reporta cuántas escenas hay.

    Pensado para diagnosticar zonas donde RTC_HI_RES devuelve 0 escenas
    (el producto era on-demand HyP3 hasta 2023 y solo cubre USA + zonas
    seleccionadas, no Bolivia entera).

    Devuelve lista de dicts con cada combo probada: n_escenas, ms,
    primer_filename, primer_sceneName.
    """
    if not _intentar_inicializar():
        return [{"error": "no auth"}]
    import asf_search as asf
    wkt = _wkt_bbox(bbox)
    combos = [
        ("ALOS / RTC_HI_RES (12.5 m)",
            {"platform": "ALOS", "processingLevel": "RTC_HI_RES"}),
        ("ALOS / RTC_LO_RES (30 m)",
            {"platform": "ALOS", "processingLevel": "RTC_LO_RES"}),
        ("ALOS / L1.5",
            {"platform": "ALOS", "processingLevel": "L1.5"}),
        ("ALOS / L1.1",
            {"platform": "ALOS", "processingLevel": "L1.1"}),
        ("ALOS (sin level filter)",
            {"platform": "ALOS"}),
        ("ALOS dataset",
            {"dataset": "ALOS PALSAR"}),
    ]
    out: list[dict] = []
    for nombre, filtros in combos:
        t0 = time.time()
        try:
            r = asf.search(intersectsWith=wkt, maxResults=3, **filtros)
            lst = list(r)
            primer = lst[0].properties if lst else {}
            out.append({
                "combo": nombre, "filtros": filtros, "ok": True,
                "ms": int((time.time() - t0) * 1000),
                "n_escenas": len(lst),
                "primer_filename": primer.get("fileName"),
                "primer_processingLevel": primer.get("processingLevel"),
                "primer_sceneName": primer.get("sceneName"),
            })
            _msg(f"{nombre}: {len(lst)} escenas")
        except Exception as e:  # noqa: BLE001
            out.append({
                "combo": nombre, "filtros": filtros, "ok": False,
                "ms": int((time.time() - t0) * 1000),
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            })
            _msg(f"{nombre} falló: {type(e).__name__}: {e}")
    return out


def _descargar_escena(escena) -> Optional[Path]:
    """Descarga una escena ASF (GeoTIFF DEM). Usa cache local."""
    if not _intentar_inicializar():
        return None
    nombre = escena.properties.get("fileName") or escena.properties.get("sceneName")
    if not nombre:
        return None
    nombre_base = nombre.replace(".zip", "").replace(".tif", "")
    destino = _cache_path(nombre_base)
    if _cache_valido(destino):
        _msg(f"cache hit: {nombre_base}")
        return destino
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _purgar_cache_si_supera()
    with _descarga_lock:
        # Re-chequear dentro del lock (otro thread pudo haber descargado)
        if _cache_valido(destino):
            return destino
        try:
            _msg(f"descargando {nombre_base}…")
            t0 = time.time()
            escena.download(path=str(CACHE_DIR), session=_AUTH)
            t = time.time() - t0
            # asf_search nombra el archivo con su `fileName` original.
            descargado = CACHE_DIR / nombre
            if not descargado.exists():
                # ASF a veces devuelve .zip; abrir y extraer el .dem.tif
                zip_path = CACHE_DIR / f"{nombre_base}.zip"
                if zip_path.exists():
                    import zipfile
                    with zipfile.ZipFile(zip_path) as zf:
                        for n in zf.namelist():
                            if n.endswith(".dem.tif") or n.endswith("_DEM.tif"):
                                zf.extract(n, CACHE_DIR)
                                extraido = CACHE_DIR / n
                                extraido.rename(destino)
                                zip_path.unlink(missing_ok=True)
                                _msg(f"descarga + descompresión OK en "
                                       f"{t:.1f}s: {destino.name}")
                                return destino
                    _msg(f"zip sin .dem.tif: {zip_path}")
                    return None
                _msg(f"download() no produjo archivo esperado: {nombre}")
                return None
            # Si el archivo descargado no es .tif (sino .zip), renombrar
            if descargado.suffix == ".zip":
                import zipfile
                with zipfile.ZipFile(descargado) as zf:
                    for n in zf.namelist():
                        if n.endswith(".dem.tif") or n.endswith("_DEM.tif"):
                            zf.extract(n, CACHE_DIR)
                            (CACHE_DIR / n).rename(destino)
                            descargado.unlink(missing_ok=True)
                            _msg(f"descarga + descompresión OK en "
                                   f"{t:.1f}s: {destino.name}")
                            return destino
                _msg(f"zip sin .dem.tif: {descargado}")
                return None
            descargado.rename(destino)
            _msg(f"descarga OK en {t:.1f}s: {destino.name}")
            return destino
        except Exception as e:  # noqa: BLE001
            _msg(f"descarga falló: {type(e).__name__}: {str(e)[:200]}")
            return None


# ─────────────────── API principal ───────────────────

def obtener_dem_12m(bbox: dict, dst_crs: str = "EPSG:4326"
                       ) -> Optional[tuple]:
    """Descarga, mosaica y reproyecta el DEM ALOS 12.5 m para el bbox.

    Devuelve `(dem_array, transform, crs)` o `None` si no hay cobertura
    o si la auth falla. `dem_array` es float32 (elevación en m, NaN para
    huecos), `transform` es affine.Affine, `crs` es el CRS de salida.

    El consumidor decide si reproyecta o no — para mantener la
    resolución original ALOS conviene pedir UTM (`epsg_utm(lat, lon)`).
    """
    if not _intentar_inicializar():
        return None
    escenas = _buscar_escenas(bbox)
    if not escenas:
        _msg(f"sin cobertura ALOS para bbox {bbox}")
        return None
    tifs: list[Path] = []
    for esc in escenas[:4]:   # tope: 4 tiles por análisis (~200 MB)
        p = _descargar_escena(esc)
        if p is not None:
            tifs.append(p)
    if not tifs:
        return None
    try:
        import numpy as np
        import rasterio
        from rasterio.merge import merge
        from rasterio.warp import calculate_default_transform, reproject, Resampling
        # Abrir y mosaicar
        srcs = [rasterio.open(p) for p in tifs]
        mosaico, mosaico_transform = merge(srcs)
        crs_origen = srcs[0].crs
        for s in srcs:
            s.close()
        # Reproyectar al CRS pedido si no coincide
        if str(crs_origen) != dst_crs:
            dst_t, dst_w, dst_h = calculate_default_transform(
                crs_origen, dst_crs,
                mosaico.shape[2], mosaico.shape[1],
                *_bounds_from(mosaico_transform, mosaico.shape[2],
                                mosaico.shape[1]),
            )
            destino = np.full((dst_h, dst_w), np.nan, dtype=np.float32)
            reproject(
                source=mosaico[0], destination=destino,
                src_transform=mosaico_transform, src_crs=crs_origen,
                dst_transform=dst_t, dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                src_nodata=0, dst_nodata=float("nan"),
            )
            return destino, dst_t, dst_crs
        # Sin reproyección: devolver tal cual
        dem = mosaico[0].astype(np.float32)
        dem[dem == 0] = np.nan
        return dem, mosaico_transform, str(crs_origen)
    except Exception as e:  # noqa: BLE001
        _msg(f"mosaico/reproyección falló: {type(e).__name__}: {e}")
        return None


def _bounds_from(transform, w, h) -> tuple:
    """(west, south, east, north) desde affine.Affine + dimensiones."""
    west = transform.c
    north = transform.f
    east = west + w * transform.a
    south = north + h * transform.e
    return (west, min(south, north), east, max(south, north))


# ─────────────────── Test/diagnóstico ───────────────────

def test_punto(lat: float, lon: float, radio_grados: float = 0.05) -> dict:
    """Test rápido para diagnóstico: busca + descarga 1 tile para el punto.

    Retorna dict con cada paso (init / search / download / open) y
    estadísticas básicas si fue exitoso. Pensado para /alos_test.
    """
    out: dict = {"lat": lat, "lon": lon, "pasos": []}
    t0 = time.time()

    # 1. Init
    ok = _intentar_inicializar()
    out["pasos"].append({
        "paso": "1_init_asf", "ok": ok,
        "ms": int((time.time() - t0) * 1000),
        "error_init": _ERROR_INIT,
    })
    if not ok:
        out["ok"] = False
        out["sugerencia"] = ("Verificar EARTHDATA_USER+EARTHDATA_PASS "
                               "(preferido) o EARTHDATA_TOKEN en los secrets "
                               "del Space.")
        return out

    # 2. Search
    bbox = {"oeste": lon - radio_grados, "este": lon + radio_grados,
              "sur": lat - radio_grados, "norte": lat + radio_grados}
    t1 = time.time()
    escenas = _buscar_escenas(bbox)
    out["pasos"].append({
        "paso": "2_search_asf", "ok": len(escenas) > 0,
        "ms": int((time.time() - t1) * 1000),
        "n_escenas": len(escenas),
        "primer_escena": (escenas[0].properties.get("fileName")
                            if escenas else None),
    })
    if not escenas:
        out["ok"] = False
        out["sugerencia"] = ("Sin cobertura ALOS PALSAR RTC para esta "
                               "zona. Bolivia tiene cobertura completa; "
                               "revisar la API ASF o probar otro punto.")
        return out

    # 3. Download primera escena
    t2 = time.time()
    p = _descargar_escena(escenas[0])
    out["pasos"].append({
        "paso": "3_download_tile",
        "ok": (p is not None and p.exists()),
        "ms": int((time.time() - t2) * 1000),
        "tile_path": str(p) if p else None,
        "tile_size_mb": (round(p.stat().st_size / (1024 * 1024), 1)
                            if p and p.exists() else None),
    })
    if p is None or not p.exists():
        out["ok"] = False
        out["sugerencia"] = ("Descarga falló — ver logs [ALOS] del "
                               "Space para el error específico.")
        return out

    # 4. Open + estadísticas
    t3 = time.time()
    try:
        import rasterio
        with rasterio.open(p) as src:
            arr = src.read(1)
            valid = arr[arr > 0]
            out["pasos"].append({
                "paso": "4_open_geotiff", "ok": True,
                "ms": int((time.time() - t3) * 1000),
                "shape": list(arr.shape),
                "crs": str(src.crs),
                "resolucion_m": [abs(src.transform.a), abs(src.transform.e)],
                "elev_min_m": float(valid.min()) if valid.size else None,
                "elev_max_m": float(valid.max()) if valid.size else None,
                "n_pixels_validos": int(valid.size),
            })
    except Exception as e:  # noqa: BLE001
        out["pasos"].append({
            "paso": "4_open_geotiff", "ok": False,
            "ms": int((time.time() - t3) * 1000),
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        })
        out["ok"] = False
        return out

    out["ok"] = all(p["ok"] for p in out["pasos"])
    out["resumen"] = (f"ALOS PALSAR DEM 12.5 m disponible y descargable "
                        f"para este punto. Cache: {_cache_size_mb():.1f} "
                        f"MB / {CACHE_MAX_MB} MB.")
    return out
