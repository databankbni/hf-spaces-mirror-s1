"""Mapa 9.6 de pendientes calculado desde COP-DEM 12.5 m con `np.gradient`.

Reemplaza `mapa_pendientes_gee` (que usa `Terrain.slope` server-side
en GEE sobre el DEM nativo COP-DEM 30 m) por un cálculo Python sobre
el array downscaled a 12.5 m — mejor consistencia visual con el 9.1
y morfometría, y permite aplicar el mismo formato cartográfico
HYDROFRA (grilla UTM, leyenda, escala, norte, proyección).

También expone las clases y % de área por clase para que el informe
y la morfometría puedan reportar el dato.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

_log = logging.getLogger(__name__)

# Mismas clases y paleta que el 9.6 anterior (mapas_gee._SLOPE_*)
SLOPE_BORDES = [0, 3, 8, 15, 30, 50, 1e9]
SLOPE_NOMBRE = ["0–3 % (plano)", "3–8 % (suave)", "8–15 % (moderado)",
                  "15–30 % (fuerte)", "30–50 % (escarpado)", "> 50 % (muy escarpado)"]
SLOPE_COLOR = ["#edf8e9", "#bae4b3", "#74c476", "#fdae61",
                 "#f46d43", "#a50026"]


def calcular_pendientes(dem: np.ndarray, paso_m: float = 12.5) -> np.ndarray:
    """Pendiente en % a partir del DEM (elevación en metros).

    Usa np.gradient con paso_m en X e Y para obtener dz/dx y dz/dy en
    m/m, y combina con tan⁻¹ del gradiente magnitud. Resultado en
    porcentaje (= tan(β) × 100).

    Manejo robusto (v1.3):
    1. Rellena los NaN (fuera de cuenca) con el vecino válido más cercano
       ANTES del gradiente. Sin esto, np.gradient en píxeles de borde
       (válido junto a NaN) produce saltos espurios de miles de %.
    2. Suaviza el DEM con un filtro gaussiano leve (σ=1 px) para quitar
       el ruido de alta frecuencia que el downscaling cubic-spline
       introduce (ondulaciones de Runge) y que infla los gradientes.
    3. Restaura NaN donde el DEM original no tenía dato.
    4. Recorta a un máximo físico (200 % ≈ 63°); por encima son
       artefactos (acantilados verticales no existen en una cuenca).
    """
    from scipy.ndimage import gaussian_filter, distance_transform_edt
    nan_mask = ~np.isfinite(dem)
    if nan_mask.all():
        return np.full(dem.shape, np.nan, dtype="float32")
    # 1) Rellenar NaN con el valor válido más cercano (nearest)
    if nan_mask.any():
        idx = distance_transform_edt(nan_mask, return_distances=False,
                                       return_indices=True)
        dem_fill = dem[tuple(idx)]
    else:
        dem_fill = dem
    # 2) Suavizado leve anti-ruido-cubic
    dem_smooth = gaussian_filter(dem_fill.astype("float64"), sigma=1.0)
    # 3) Gradiente → pendiente en %
    gy, gx = np.gradient(dem_smooth, paso_m, paso_m)
    slope_pct = np.sqrt(gx**2 + gy**2) * 100.0
    # 4) Restaurar NaN + recortar outliers físicos
    slope_pct[nan_mask] = np.nan
    slope_pct = np.where(np.isfinite(slope_pct),
                            np.clip(slope_pct, 0.0, 200.0), np.nan)
    return slope_pct.astype("float32")


def clasificar(slope_pct: np.ndarray) -> np.ndarray:
    """Devuelve array uint8 con la clase 0–5 de cada pixel (NaN = 255)."""
    out = np.digitize(slope_pct, SLOPE_BORDES[1:-1], right=False
                          ).astype(np.uint8)
    out[~np.isfinite(slope_pct)] = 255
    return out


def estadisticas_pendiente(slope_pct: np.ndarray) -> dict:
    """Reporta media, mediana, std + % de área por clase."""
    valid = slope_pct[np.isfinite(slope_pct)]
    if valid.size == 0:
        return {"media_pct": None, "mediana_pct": None, "std_pct": None,
                "pct_por_clase": {k: 0.0 for k in range(6)},
                "n_validos": 0}
    cls = clasificar(slope_pct)
    cls_valid = cls[cls != 255]
    total = cls_valid.size
    pct_por_clase = {int(k): round(100 * (cls_valid == k).sum() / total, 1)
                       for k in range(6)}
    return {
        "media_pct": round(float(valid.mean()), 2),
        "mediana_pct": round(float(np.median(valid)), 2),
        "std_pct": round(float(valid.std()), 2),
        "min_pct": round(float(valid.min()), 2),
        "max_pct": round(float(valid.max()), 2),
        "pct_por_clase": pct_por_clase,
        "n_validos": int(total),
    }


def _dibujar_capa(dem: np.ndarray, slope_pct: np.ndarray, bbox: dict,
                     out_path: Path,
                     poligono_lonlat: Optional[np.ndarray] = None) -> Path:
    """Render PNG de la CAPA del mapa (sin chrome cartográfico).

    Genera la imagen del DEM clasificado por pendiente como RGBA puro
    + contorno de cuenca opcional. El decorado cartográfico (grilla
    UTM, leyenda formal, escala, norte) lo aplica el caller via
    `_decorar_mapa_cartografico`.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba

    h, w = slope_pct.shape
    cls = clasificar(slope_pct)
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[..., 3] = 0.0   # transparente por default
    for k in range(6):
        m = cls == k
        if not m.any():
            continue
        r, g, b, _ = to_rgba(SLOPE_COLOR[k])
        rgba[m, 0] = r
        rgba[m, 1] = g
        rgba[m, 2] = b
        rgba[m, 3] = 0.92
    # Sin píxel válido → transparente (queda blanco)
    fig, ax = plt.subplots(figsize=(8, 8), dpi=120)
    extent = [bbox["oeste"], bbox["este"], bbox["sur"], bbox["norte"]]
    ax.imshow(rgba, extent=extent, origin="upper",
                interpolation="nearest")
    if poligono_lonlat is not None:
        pol = np.asarray(poligono_lonlat)
        if pol.ndim == 2 and pol.shape[1] == 2 and len(pol) >= 3:
            if not np.allclose(pol[0], pol[-1]):
                pol = np.vstack([pol, pol[0]])
            ax.plot(pol[:, 0], pol[:, 1], color="#cc0000", lw=1.2,
                      alpha=0.9)
    ax.set_xlim(bbox["oeste"], bbox["este"])
    ax.set_ylim(bbox["sur"], bbox["norte"])
    ax.axis("off")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(out_path, dpi=140, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    return out_path


def generar_mapa_9_6(poligono_lonlat, out_path: Path, autor: str = "",
                        res_target_m: float = 12.5) -> Optional[dict]:
    """Entry-point del 9.6: descarga COP-DEM, calcula slope, decora.

    Devuelve dict con path, stats de pendiente y la entrada de leyenda
    para que el informe agregue la pendiente media a la tabla
    morfométrica.
    """
    from .copernicus_dem import obtener_dem_cuenca, RESOLUCION_NATIVA_M
    from .gee import _decorar_mapa_cartografico
    # Pendientes sobre el DEM 30 m NATIVO (no el downscaled 12.5 m): el
    # remuestreo cubic introduce ondulaciones que inflan los gradientes y
    # daban pendientes irreales (media 60 %, máx 3000 %). El 30 m nativo
    # es la resolución real del dato → pendientes físicamente correctas.
    cop = obtener_dem_cuenca(poligono_lonlat,
                                res_target_m=float(RESOLUCION_NATIVA_M))
    if cop is None:
        return None
    dem = cop["array"]
    bbox = cop["bbox"]
    paso_m = cop["resolucion_m"]
    slope_pct = calcular_pendientes(dem, paso_m=paso_m)
    stats = estadisticas_pendiente(slope_pct)
    if stats["n_validos"] == 0:
        return None
    # PNG capa-only
    _dibujar_capa(dem, slope_pct, bbox, out_path,
                     poligono_lonlat=poligono_lonlat)
    # Aplicar chrome cartográfico HYDROFRA estándar
    leyenda = []
    for k in range(6):
        pct = stats["pct_por_clase"].get(k, 0.0)
        if pct >= 0.5:   # ocultamos clases marginales (<0.5 %)
            leyenda.append({"etiqueta": SLOPE_NOMBRE[k],
                              "color": SLOPE_COLOR[k], "pct": pct})
    resumen = (f"Pendiente media = {stats['media_pct']:.1f} % · "
                 f"mediana = {stats['mediana_pct']:.1f} % · "
                 f"máx = {stats['max_pct']:.1f} %  "
                 f"(COP-DEM GLO-30 30 m, np.gradient suavizado)")
    _decorar_mapa_cartografico(
        out_path, bbox, autor=autor,
        titulo="9.6 Pendientes del terreno (COP-DEM GLO-30, np.gradient)",
        entradas_leyenda=leyenda or None,
        resumen=resumen,
    )
    return {
        "path": out_path,
        "pendiente_media_pct": stats["media_pct"],
        "pendiente_mediana_pct": stats["mediana_pct"],
        "pendiente_max_pct": stats["max_pct"],
        "pct_por_clase": stats["pct_por_clase"],
        "n_pixels": stats["n_validos"],
        "fuente": ("COP-DEM GLO-30 downscaled cubic 12.5 m, "
                     "pendiente por np.gradient"),
    }
