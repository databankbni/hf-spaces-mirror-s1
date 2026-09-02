"""DEM Copernicus GLO-30 (30 m) vía GEE + downscaling cubic a 12.5 m.

Reemplazo/upgrade de SRTM 30 m para los mapas 9.1 (cuenca + hillshade)
y 9.6 (pendientes) + morfometría. Mejora respecto a SRTM:
- Cobertura global completa sin huecos (SRTM tiene huecos > 60°N/S).
- Calidad vertical mejor en zonas altas y costeras.
- Más reciente (2011-2015 vs SRTM 2000) → mejor representación de
  cambios antropicos urbanos.

El "downscaling" a 12.5 m es interpolación cubic-spline con
`rasterio.warp.Resampling.cubic_spline`. **No agrega información real**
— sólo suaviza la salida. Útil para mapas visuales más densos, pero la
pendiente, curvatura y morfometría siguen reflejando el DEM original
30 m. El reporte declara explícitamente que es interpolación.

Auth: usa el `GEE_SERVICE_ACCOUNT_JSON` + `GEE_PROJECT_ID` ya
configurados en el Space (mismo que `src/idf/gee.py`). No requiere
credenciales adicionales.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .gee import _intentar_inicializar as _init_gee, _msg as _msg_gee, epsg_utm

_log = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("COPDEM_CACHE_DIR", "/tmp/copdem-cache"))
CACHE_TTL_HORAS = int(os.environ.get("COPDEM_CACHE_TTL_H", 24))
CACHE_MAX_MB = int(os.environ.get("COPDEM_CACHE_MAX_MB", 300))
DATASET = "COPERNICUS/DEM/GLO30"
RESOLUCION_NATIVA_M = 30
RESOLUCION_TARGET_M = float(os.environ.get("COPDEM_TARGET_RES_M", 12.5))

_descarga_lock = threading.Lock()

# Diagnóstico: último error de downscale capturado, para que /dem_test
# pueda reportarlo en el JSON sin perder el detalle.
_ULTIMO_ERROR_DOWNSCALE: Optional[str] = None


def _msg(texto: str) -> None:
    print(f"[COPDEM] {texto}", file=sys.stderr, flush=True)


# ─────────────────── Diagnóstico ───────────────────

def disponible() -> bool:
    """OK si GEE inicializa (no requiere credenciales adicionales)."""
    return _init_gee()


def estado() -> dict:
    """Diagnóstico expuesto por /dem_status."""
    ok = _init_gee()
    # Probar imports y reportar versiones — confirma qué lector está disponible
    libs = {}
    for pkg in ("tifffile", "imageio", "PIL", "scipy"):
        try:
            mod = __import__(pkg)
            libs[pkg] = getattr(mod, "__version__", "?")
        except ImportError:
            libs[pkg] = "no instalado"
    return {
        "disponible": ok,
        "dataset": DATASET,
        "resolucion_nativa_m": RESOLUCION_NATIVA_M,
        "resolucion_target_m": RESOLUCION_TARGET_M,
        "downscaling_metodo": "scipy.ndimage.zoom (cubic-spline, order=3)",
        "downscaling_es_interpolacion_no_resolucion_real": True,
        "cache_dir": str(CACHE_DIR),
        "cache_size_mb": _cache_size_mb(),
        "cache_max_mb": CACHE_MAX_MB,
        "auth_requerida": "GEE_SERVICE_ACCOUNT_JSON (compartido con GEE)",
        "libs_disponibles": libs,
        "version_modulo": "9a38d9b+lector_diag",
    }


def _cache_size_mb() -> float:
    if not CACHE_DIR.exists():
        return 0.0
    total = sum(f.stat().st_size for f in CACHE_DIR.rglob("*")
                  if f.is_file())
    return round(total / (1024 * 1024), 1)


def _cache_key(bbox: dict, res_m: float) -> str:
    """Hash determinístico del bbox + resolución (cache key estable)."""
    s = (f"{bbox['oeste']:.4f}_{bbox['este']:.4f}_"
           f"{bbox['sur']:.4f}_{bbox['norte']:.4f}_{res_m:.1f}m")
    return s.replace(".", "p").replace("-", "n")


def _cache_path(bbox: dict, res_m: float) -> Path:
    # Resultado downscaled se guarda como .npz (sin GDAL); el 30 m
    # original sigue como .tif.
    ext = ".npz" if res_m < RESOLUCION_NATIVA_M else ".tif"
    return CACHE_DIR / f"copdem_{_cache_key(bbox, res_m)}{ext}"


def _cache_valido(p: Path) -> bool:
    if not p.exists():
        return False
    edad_h = (time.time() - p.stat().st_mtime) / 3600.0
    return edad_h <= CACHE_TTL_HORAS


def _purgar_cache_si_supera() -> None:
    if not CACHE_DIR.exists():
        return
    if _cache_size_mb() <= CACHE_MAX_MB:
        return
    archivos = sorted(CACHE_DIR.rglob("*"),
                        key=lambda p: p.stat().st_mtime if p.is_file() else 0)
    for f in archivos:
        if not f.is_file():
            continue
        f.unlink(missing_ok=True)
        if _cache_size_mb() <= 0.75 * CACHE_MAX_MB:
            break


# ─────────────────── Descarga COP-DEM 30 m vía GEE ───────────────────

def _descargar_copdem_30m(bbox: dict, dst_path: Path,
                              dst_crs_utm: str) -> Optional[Path]:
    """Descarga COP-DEM 30 m clipeado al bbox, proyectado en UTM."""
    if not _init_gee():
        return None
    import ee
    from urllib.request import urlopen
    geom = ee.Geometry.Rectangle([
        bbox["oeste"], bbox["sur"], bbox["este"], bbox["norte"]])
    img = (ee.ImageCollection(DATASET)
              .filterBounds(geom)
              .select(["DEM"])
              .mosaic()
              .clip(geom)
              .toFloat())   # fuerza Float32 sin sample-format ambiguo
    try:
        url = img.getDownloadURL({
            "region": geom,
            "scale": RESOLUCION_NATIVA_M,
            "crs": dst_crs_utm,
            "format": "GEO_TIFF",
            # Explicitamos la única banda esperada — evita que GEE
            # incluya bandas auxiliares de máscara que confundan al
            # lector Python. `filePerBand: False` consolida todo en un
            # único TIFF.
            "bands": [{"id": "DEM"}],
            "filePerBand": False,
        })
    except Exception as e:  # noqa: BLE001
        _msg(f"getDownloadURL falló: {type(e).__name__}: {e}")
        return None
    try:
        _msg(f"descargando COP-DEM 30 m (CRS={dst_crs_utm})…")
        t0 = time.time()
        with urlopen(url, timeout=120) as resp, open(dst_path, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        _msg(f"COP-DEM 30 m bajado en {time.time() - t0:.1f}s "
               f"({dst_path.stat().st_size // 1024} KB)")
        return dst_path
    except Exception as e:  # noqa: BLE001
        _msg(f"descarga COP-DEM falló: {type(e).__name__}: {e}")
        return None


# ─────────────────── Downscaling cubic 30 → 12.5 m ───────────────────
#
# Reemplazamos `rasterio.warp.reproject` por `scipy.ndimage.zoom` porque
# rasterio requiere libexpat1/libgdal30 nativos que la imagen base
# python:3.11-slim no incluye, y la integración con HF Spaces para
# rebuildear el Dockerfile es frágil. scipy ya está instalado y hace
# cubic-spline puro sobre arrays — no necesita GDAL.
#
# Costo: perdemos el manejo de CRS/transform que hacía rasterio, pero
# como el COP-DEM 30 m lo pedimos a GEE ya proyectado en UTM (zona del
# centro del bbox), la transform de salida la calculamos manualmente
# desde el bbox + nueva resolución: es exacta y reversible.

_ULTIMO_LECTOR: Optional[str] = None  # set por _abrir_geotiff_basico
_ULTIMO_DIAG_LECTURA: Optional[dict] = None  # dump diagnóstico crudo


def _abrir_geotiff_basico(src_path: Path):
    """Lee un GeoTIFF sin rasterio/GDAL. Devuelve el array.

    COP-DEM viene en float32. Probamos primero `tifffile` (pure-Python,
    soporta float32 correctamente); si no está disponible, caemos a
    `imageio.v3` y validamos rango razonable (-1000 a 10000 m para
    elevación terrestre). PIL solo lo usamos para uint8/16 TIFFs.
    Setea `_ULTIMO_LECTOR` con el nombre del lector efectivamente
    usado, para diagnóstico en /dem_test.
    """
    import numpy as np
    global _ULTIMO_LECTOR
    # 1) tifffile — preferido para float32 (no malinterpreta el dtype).
    try:
        import tifffile
        arr = tifffile.imread(src_path)
        _ULTIMO_LECTOR = f"tifffile {tifffile.__version__}"
        return arr.astype(np.float32)
    except ImportError:
        pass
    # 2) imageio v3
    try:
        import imageio.v3 as iio
        arr = iio.imread(src_path)
        _ULTIMO_LECTOR = "imageio.v3"
        return arr.astype(np.float32)
    except ImportError:
        pass
    # 3) PIL fallback (no recomendado para float32)
    from PIL import Image
    arr = np.array(Image.open(src_path))
    _ULTIMO_LECTOR = "PIL.Image"
    return arr.astype(np.float32)


def _downscale_cubic(src_path: Path, dst_path: Path,
                       res_target_m: float, dst_crs_utm: str,
                       bbox: dict, res_origen_m: int = RESOLUCION_NATIVA_M
                       ) -> Optional[Path]:
    """Resample cubic-spline 30 → res_target_m sin rasterio/GDAL.

    Guarda el resultado como `.npz` (numpy compressed) con array +
    metadata (bbox, crs, transform). Más portable que un GeoTIFF porque
    no requiere GDAL para leer; cuando hace falta exportar a GeoTIFF
    real, usar `_exportar_geotiff()` aparte.
    """
    try:
        import numpy as np
        from scipy.ndimage import zoom
        arr_raw = _abrir_geotiff_basico(src_path)
        # Dump de diagnóstico: dtype + shape + primeras 5 muestras
        # crudas, ANTES de cualquier limpieza. Esto se loguea siempre
        # para correlacionar con los valores reportados al frontend.
        _msg(f"raw read: dtype={arr_raw.dtype}, shape={arr_raw.shape}, "
               f"samples[0:5]={arr_raw.flatten()[:5].tolist()}, "
               f"min_raw={float(arr_raw.min()):.2f}, "
               f"max_raw={float(arr_raw.max()):.2f}, "
               f"median_raw={float(np.median(arr_raw)):.2f}, "
               f"lector={_ULTIMO_LECTOR}")
        global _ULTIMO_DIAG_LECTURA
        _ULTIMO_DIAG_LECTURA = {
            "dtype": str(arr_raw.dtype),
            "shape": list(arr_raw.shape),
            "samples_primeros": [float(x) for x in arr_raw.flatten()[:5]],
            "min_raw": float(arr_raw.min()),
            "max_raw": float(arr_raw.max()),
            "median_raw": float(np.median(arr_raw)),
            "lector": _ULTIMO_LECTOR,
        }
        arr = arr_raw.copy()
        # Validación de rango razonable para elevación terrestre:
        # Mariana Trench -11 km, Everest +8.85 km. COP-DEM real está
        # entre -500 m y +9000 m. Cualquier valor fuera de eso es
        # malinterpretación del dtype por un lector que no entiende
        # el float32 (PIL/imageio sin tifffile).
        arr[(arr == 0) | (arr < -500) | (arr > 9000)] = np.nan
        # Factor de zoom = res_origen / res_target. Para 30 → 12.5 = 2.4.
        factor = res_origen_m / res_target_m
        # order=3 = cubic spline. mode='nearest' evita extrapolación
        # en los bordes; cval=NaN preserva el nodata.
        # Como zoom no maneja NaN bien, los reemplazamos por la mediana
        # antes y los restauramos por máscara después.
        nan_mask = np.isnan(arr)
        if nan_mask.any():
            mediana = float(np.nanmedian(arr)) if (~nan_mask).any() else 0.0
            arr_safe = np.where(nan_mask, mediana, arr)
        else:
            arr_safe = arr
        arr_hires = zoom(arr_safe, factor, order=3, mode="nearest"
                            ).astype(np.float32)
        # Restauramos NaN en zonas donde lo había en el original
        if nan_mask.any():
            mask_hires = zoom(nan_mask.astype(np.float32), factor,
                                  order=0).astype(bool)
            arr_hires[mask_hires] = np.nan
        new_h, new_w = arr_hires.shape
        # Transform: affine 6-tupla (a, b, c, d, e, f)
        #   x = a·col + b·row + c
        #   y = d·col + e·row + f
        west, north = bbox["oeste"], bbox["norte"]
        # En UTM la transform va en metros; usamos el factor pixel/m.
        # Pero como no tenemos UTM del bbox original (es lat/lon), guardamos
        # bbox + shape, suficiente para reconstruir.
        np.savez_compressed(
            dst_path,
            array=arr_hires,
            bbox_oeste=bbox["oeste"], bbox_este=bbox["este"],
            bbox_sur=bbox["sur"], bbox_norte=bbox["norte"],
            crs=dst_crs_utm,
            resolucion_m=res_target_m,
            resolucion_origen_m=res_origen_m,
            shape=arr_hires.shape,
        )
        _msg(f"downscaled 30 → {res_target_m:.1f} m "
               f"({new_w}×{new_h} px), guardado en {dst_path.name}")
        return dst_path
    except Exception as e:  # noqa: BLE001
        global _ULTIMO_ERROR_DOWNSCALE
        import traceback as _tb
        _ULTIMO_ERROR_DOWNSCALE = (f"{type(e).__name__}: {e}\n"
                                       + _tb.format_exc()[-1500:])
        _msg(f"downscale falló: {type(e).__name__}: {e}")
        return None


# ─────────────────── API principal ───────────────────

def obtener_dem_hires(bbox: dict,
                          res_target_m: float = RESOLUCION_TARGET_M
                          ) -> Optional[dict]:
    """Devuelve el DEM downscalado y metadatos.

    Devuelve dict con:
        path: Path al GeoTIFF en cache.
        array: np.ndarray (float32, NaN para nodata).
        transform: rasterio Affine.
        crs: str (EPSG UTM).
        resolucion_real_m: int (siempre 30 — el DEM base).
        resolucion_interpolada_m: float (res_target_m).
        n_pixels: (h, w).
        elev_min_m, elev_max_m, elev_media_m.

    `None` si GEE no responde o el bbox no tiene cobertura.
    """
    if not _init_gee():
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _purgar_cache_si_supera()
    lat_c = (bbox["sur"] + bbox["norte"]) / 2
    lon_c = (bbox["oeste"] + bbox["este"]) / 2
    dst_crs = epsg_utm(lat_c, lon_c)
    final_path = _cache_path(bbox, res_target_m)
    if _cache_valido(final_path):
        _msg(f"cache hit: {final_path.name}")
        return _abrir(final_path, res_target_m)
    with _descarga_lock:
        if _cache_valido(final_path):
            return _abrir(final_path, res_target_m)
        tmp30 = CACHE_DIR / f"_tmp30_{_cache_key(bbox, 30)}.tif"
        if _descargar_copdem_30m(bbox, tmp30, dst_crs) is None:
            return None
        if abs(res_target_m - RESOLUCION_NATIVA_M) < 0.5:
            tmp30.rename(final_path)
        else:
            if _downscale_cubic(tmp30, final_path, res_target_m,
                                  dst_crs, bbox) is None:
                tmp30.unlink(missing_ok=True)
                return None
            tmp30.unlink(missing_ok=True)
    return _abrir(final_path, res_target_m)


def obtener_dem_cuenca(poligono_lonlat,
                          res_target_m: float = RESOLUCION_TARGET_M
                          ) -> Optional[dict]:
    """Descarga COP-DEM clipeado AL POLÍGONO (no al bbox) y downscalado.

    Los píxeles fuera de la cuenca vienen como NaN — listos para
    estadísticas (np.nanmin, np.nanmean, etc.). Adecuado para
    recalcular morfometría sobre los ~750 k píxeles del DEM 12.5 m
    en lugar de los ~120 k del DEM 30 m.

    Devuelve dict con: array (UTM, NaN fuera de cuenca), bbox,
    crs, resolución, paso_pixel_m_x/y (para cálculo de pendiente con
    gradiente), hmin/hmax/hmedia/pendiente_media_pct. None si GEE
    no responde.
    """
    if not _init_gee():
        return None
    import ee
    import numpy as np
    pol = np.asarray(poligono_lonlat, dtype=float)
    if pol.ndim != 2 or pol.shape[1] != 2 or len(pol) < 4:
        _msg(f"polígono inválido (shape={pol.shape})")
        return None
    # bbox para el caché key + CRS UTM por centroide
    bbox = {
        "oeste": float(pol[:, 0].min()), "este": float(pol[:, 0].max()),
        "sur": float(pol[:, 1].min()), "norte": float(pol[:, 1].max()),
    }
    lat_c = (bbox["sur"] + bbox["norte"]) / 2
    lon_c = (bbox["oeste"] + bbox["este"]) / 2
    dst_crs = epsg_utm(lat_c, lon_c)

    cache_key = f"cuenca_{_cache_key(bbox, res_target_m)}_{len(pol)}v"
    final_path = CACHE_DIR / f"{cache_key}.npz"
    if _cache_valido(final_path):
        _msg(f"cache hit: {final_path.name}")
        return _abrir_cuenca(final_path)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _purgar_cache_si_supera()
    with _descarga_lock:
        if _cache_valido(final_path):
            return _abrir_cuenca(final_path)
        # GEE: clipear con el polígono de la cuenca; píxeles fuera → NaN.
        coords_ee = [[float(c[0]), float(c[1])] for c in pol]
        geom_pol = ee.Geometry.Polygon([coords_ee])
        img = (ee.ImageCollection(DATASET)
                  .filterBounds(geom_pol)
                  .select(["DEM"]).mosaic().clip(geom_pol).toFloat())
        try:
            url = img.getDownloadURL({
                "region": geom_pol, "scale": RESOLUCION_NATIVA_M,
                "crs": dst_crs, "format": "GEO_TIFF",
                "bands": [{"id": "DEM"}], "filePerBand": False,
            })
        except Exception as e:  # noqa: BLE001
            _msg(f"getDownloadURL (cuenca) falló: {type(e).__name__}: {e}")
            return None
        from urllib.request import urlopen
        tmp30 = CACHE_DIR / f"_tmp_cuenca_{cache_key}_30m.tif"
        try:
            _msg(f"descargando COP-DEM cuenca (CRS={dst_crs}, "
                   f"poligono={len(pol)}v)…")
            t0 = time.time()
            with urlopen(url, timeout=120) as resp, open(tmp30, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            _msg(f"COP-DEM cuenca bajado en {time.time() - t0:.1f}s "
                   f"({tmp30.stat().st_size // 1024} KB)")
        except Exception as e:  # noqa: BLE001
            _msg(f"descarga COP-DEM cuenca falló: {type(e).__name__}: {e}")
            return None
        # Downscale + cálculo de morfometría
        try:
            from scipy.ndimage import zoom
            arr30 = _abrir_geotiff_basico(tmp30)
            arr30[(arr30 == 0) | (arr30 < -500) | (arr30 > 9000)] = np.nan
            arr30[np.isinf(arr30)] = np.nan
            factor = RESOLUCION_NATIVA_M / res_target_m
            mask_nan = np.isnan(arr30)
            mediana = (float(np.nanmedian(arr30))
                          if (~mask_nan).any() else 0.0)
            arr_safe = np.where(mask_nan, mediana, arr30)
            arr_h = zoom(arr_safe, factor, order=3,
                            mode="nearest").astype(np.float32)
            mask_h = zoom(mask_nan.astype(np.float32), factor,
                             order=0).astype(bool)
            arr_h[mask_h] = np.nan
            tmp30.unlink(missing_ok=True)
            # Morfometría sobre el array de la cuenca
            validos = arr_h[~np.isnan(arr_h)]
            if validos.size < 100:
                _msg(f"cuenca COP-DEM con muy pocos píxeles válidos "
                       f"({validos.size})")
                return None
            hmin = float(validos.min())
            hmax = float(validos.max())
            hmedia = float(validos.mean())
            # Pendiente: gradiente sobre array UTM (en metros).
            # zoom puede haber generado celdas no-cuadradas; asumimos
            # la resolución target tanto en X como en Y.
            gy, gx = np.gradient(arr_h, res_target_m, res_target_m)
            slope_pct = np.sqrt(gx**2 + gy**2) * 100.0
            slope_validos = slope_pct[~np.isnan(slope_pct) &
                                          ~np.isnan(arr_h)]
            pendiente_media_pct = (float(slope_validos.mean())
                                       if slope_validos.size else None)
            np.savez_compressed(
                final_path, array=arr_h,
                bbox_oeste=bbox["oeste"], bbox_este=bbox["este"],
                bbox_sur=bbox["sur"], bbox_norte=bbox["norte"],
                crs=dst_crs, resolucion_m=res_target_m,
                resolucion_origen_m=RESOLUCION_NATIVA_M,
                hmin=hmin, hmax=hmax, hmedia=hmedia,
                pendiente_media_pct=(pendiente_media_pct or 0.0),
                n_validos=validos.size,
            )
            return _abrir_cuenca(final_path)
        except Exception as e:  # noqa: BLE001
            _msg(f"cálculo cuenca falló: {type(e).__name__}: {e}")
            tmp30.unlink(missing_ok=True)
            return None


def _abrir_cuenca(path: Path) -> Optional[dict]:
    import numpy as np
    try:
        npz = np.load(path, allow_pickle=False)
        return {
            "path": path,
            "array": npz["array"].astype("float32"),
            "bbox": {
                "oeste": float(npz["bbox_oeste"]),
                "este": float(npz["bbox_este"]),
                "sur": float(npz["bbox_sur"]),
                "norte": float(npz["bbox_norte"]),
            },
            "crs": str(npz["crs"]),
            "resolucion_m": float(npz["resolucion_m"]),
            "resolucion_origen_m": int(npz["resolucion_origen_m"]),
            "hmin_m": float(npz["hmin"]),
            "hmax_m": float(npz["hmax"]),
            "hmedia_m": float(npz["hmedia"]),
            "desnivel_m": float(npz["hmax"]) - float(npz["hmin"]),
            "pendiente_media_pct": float(npz["pendiente_media_pct"]),
            "n_pixels_validos": int(npz["n_validos"]),
        }
    except Exception as e:  # noqa: BLE001
        _msg(f"_abrir_cuenca falló: {type(e).__name__}: {e}")
        return None


def _abrir(path: Path, res_target_m: float) -> Optional[dict]:
    """Abre cache: .npz (downscaled, formato numpy) o .tif (origen 30 m).

    NO usa rasterio — para .tif usa imageio/PIL y reconstruye metadata
    desde el filename + bbox cacheado en disco si lo hay.
    """
    try:
        import numpy as np
        if str(path).endswith(".npz"):
            npz = np.load(path, allow_pickle=False)
            arr = npz["array"].astype("float32")
            bbox = {
                "oeste": float(npz["bbox_oeste"]),
                "este": float(npz["bbox_este"]),
                "sur": float(npz["bbox_sur"]),
                "norte": float(npz["bbox_norte"]),
            }
            crs = str(npz["crs"])
            res_real = int(npz["resolucion_origen_m"])
            res_target = float(npz["resolucion_m"])
        else:
            arr = _abrir_geotiff_basico(path)
            arr[(arr == 0) | (arr < -500) | (arr > 9000)] = np.nan
            bbox = None
            crs = "EPSG:32720"   # placeholder; el caller que lo sobre-escriba
            res_real = RESOLUCION_NATIVA_M
            res_target = float(res_target_m)
        validos = arr[np.isfinite(arr)]
        return {
            "path": path,
            "array": arr,
            "bbox": bbox,
            "crs": crs,
            "resolucion_real_m": res_real,
            "resolucion_interpolada_m": res_target,
            "n_pixels": tuple(arr.shape),
            "elev_min_m": (float(validos.min())
                              if validos.size else None),
            "elev_max_m": (float(validos.max())
                              if validos.size else None),
            "elev_media_m": (float(validos.mean())
                                if validos.size else None),
            "pct_validos": (round(100 * validos.size / arr.size, 1)
                              if arr.size else 0.0),
        }
    except Exception as e:  # noqa: BLE001
        _msg(f"abrir falló: {type(e).__name__}: {e}")
        return None


# ─────────────────── Test/diagnóstico ───────────────────

def test_punto(lat: float, lon: float, radio_grados: float = 0.05) -> dict:
    """Test 4 pasos: init GEE → bbox → descarga 30 m → downscale a 12.5 m."""
    out: dict = {"lat": lat, "lon": lon, "pasos": []}

    t0 = time.time()
    ok = _init_gee()
    out["pasos"].append({
        "paso": "1_init_gee", "ok": ok,
        "ms": int((time.time() - t0) * 1000),
    })
    if not ok:
        out["ok"] = False
        out["sugerencia"] = "Ver /gee_status"
        return out

    bbox = {"oeste": lon - radio_grados, "este": lon + radio_grados,
              "sur": lat - radio_grados, "norte": lat + radio_grados}
    out["bbox"] = bbox

    # Descarga 30 m
    t1 = time.time()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp30 = CACHE_DIR / f"_test30_{_cache_key(bbox, 30)}.tif"
    dst_crs = epsg_utm(lat, lon)
    p30 = _descargar_copdem_30m(bbox, tmp30, dst_crs)
    out["pasos"].append({
        "paso": "2_descarga_copdem_30m",
        "ok": p30 is not None and p30.exists(),
        "ms": int((time.time() - t1) * 1000),
        "size_kb": (p30.stat().st_size // 1024 if p30 and p30.exists()
                      else None),
        "crs": dst_crs,
    })
    if not (p30 and p30.exists()):
        out["ok"] = False
        out["sugerencia"] = ("GEE no devolvió el COP-DEM — verificar "
                               "cuota / cobertura / logs [COPDEM] del Space.")
        return out

    # Downscale a 12.5 m
    global _ULTIMO_ERROR_DOWNSCALE
    _ULTIMO_ERROR_DOWNSCALE = None
    t2 = time.time()
    p12 = CACHE_DIR / f"_test12_{_cache_key(bbox, 12.5)}.npz"
    r = _downscale_cubic(p30, p12, 12.5, dst_crs, bbox)
    paso3 = {
        "paso": "3_downscale_cubic_12.5m",
        "ok": r is not None and p12.exists(),
        "ms": int((time.time() - t2) * 1000),
        "size_kb": (p12.stat().st_size // 1024 if p12.exists() else None),
    }
    if _ULTIMO_ERROR_DOWNSCALE:
        paso3["error_detalle"] = _ULTIMO_ERROR_DOWNSCALE
    out["pasos"].append(paso3)
    if not p12.exists():
        out["ok"] = False
        out["sugerencia"] = ("Downscale falló — ver `error_detalle` del "
                               "paso 3 para el traceback exacto.")
        return out

    # Abrir y stats
    t3 = time.time()
    meta = _abrir(p12, 12.5)
    if meta is None:
        out["pasos"].append({
            "paso": "4_abrir_geotiff", "ok": False,
            "ms": int((time.time() - t3) * 1000),
        })
        out["ok"] = False
        return out
    out["pasos"].append({
        "paso": "4_abrir_geotiff", "ok": True,
        "ms": int((time.time() - t3) * 1000),
        "shape": list(meta["n_pixels"]),
        "crs": meta["crs"],
        "elev_min_m": meta["elev_min_m"],
        "elev_max_m": meta["elev_max_m"],
        "elev_media_m": meta["elev_media_m"],
        "pct_validos": meta["pct_validos"],
        "resolucion_real_m": meta["resolucion_real_m"],
        "resolucion_interpolada_m": meta["resolucion_interpolada_m"],
        "lector_usado": _ULTIMO_LECTOR,
        "dump_lectura_cruda": _ULTIMO_DIAG_LECTURA,
    })
    # Limpiar archivos de test (no cachear)
    tmp30.unlink(missing_ok=True)
    p12.unlink(missing_ok=True)
    out["ok"] = all(p["ok"] for p in out["pasos"])
    out["resumen"] = (
        f"COP-DEM 30 m + downscaling cubic a 12.5 m funcionando. "
        f"Cuenca {meta['n_pixels'][0]}×{meta['n_pixels'][1]} px, "
        f"elevación {meta['elev_min_m']:.0f}–{meta['elev_max_m']:.0f} m. "
        f"IMPORTANTE: la resolución real sigue siendo 30 m; el 12.5 m es "
        f"interpolación cubic-spline.")
    return out
