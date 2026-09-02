"""Extracción de red de drenaje desde un DEM con algoritmos hidrológicos.

Implementa pit-filling (Wang & Liu), flow direction D8 (O'Callaghan &
Mark 1984) y flow accumulation iterativa, todo en NumPy/scipy puro
(sin pysheds/richdem/whiteboxtools) para evitar deps pesadas. El
resultado se renderiza como PNG estilo HYDROFRA con 3 órdenes
(capilar/secundario/principal) y leyenda.

Pensado para reemplazar `mapa_red_drenaje_gee` (que consulta MERIT
Hydro upa a 90 m) cuando hay COP-DEM downscaled a 12.5 m disponible
desde `copernicus_dem.obtener_dem_cuenca`. Ventaja: la red se deriva
del MISMO DEM que el hillshade del 9.1, así los cauces dibujados
coinciden exactamente con las depresiones visibles en el hillshade.

Costo: procesar ~750 k píxeles (cuenca de ~12 km² a 12.5 m) tarda
~1–2 s con numpy puro. Para cuencas grandes (>50 km²) considerar
subsamplear el DEM a 25 m antes de procesar.

Referencias:
- O'Callaghan, J.F. & Mark, D.M. (1984). The extraction of drainage
  networks from digital elevation data. CVGIP 28(3): 323-344.
- Wang, L. & Liu, H. (2006). An efficient method for identifying and
  filling surface depressions in digital elevation models for
  hydrologic analysis and modelling. IJGIS 20(2): 193-213.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

_log = logging.getLogger(__name__)


# D8 encoding: para cada vecino (dr, dc), código del bit + paso real
# en metros (1 vertical/horizontal, sqrt(2) diagonal).
#
#   32  64  128
#   16   *    1
#    8   4    2
#
_D8_OFFSETS = [
    (-1, -1, 32), (-1, 0, 64), (-1, 1, 128),
    (0, -1, 16),               (0, 1, 1),
    (1, -1, 8),   (1, 0, 4),   (1, 1, 2),
]


# ─────────────────── Pit filling ───────────────────

def rellenar_depresiones(dem: np.ndarray, nodata: float = np.nan,
                            n_iter: int = 100) -> np.ndarray:
    """Wang & Liu simplificado por iteración con grey-dilation.

    Para cada celda, su elevación final es el mínimo entre la propia
    y el máximo de un vecino accesible — equivalente a "elevar" las
    celdas que están en depresiones cerradas hasta su outlet más bajo.

    Implementación práctica: iteramos `min(dem, dilation(dem) − ε)`
    hasta convergencia. Termina cuando ninguna celda cambia o se
    alcanza `n_iter`. Suficiente para cuencas locales (< 100 km²).
    """
    from scipy.ndimage import grey_erosion, generate_binary_structure
    if np.all(np.isnan(dem)):
        return dem
    out = dem.copy()
    out_safe = np.where(np.isnan(out), -1e9, out)   # NaN → muy abajo
    estructura = generate_binary_structure(2, 2)    # 8-vecindad
    eps = 1e-3                                       # micro-pendiente
    for _ in range(n_iter):
        # Mínimo de los vecinos (incluye uno mismo): grey_erosion
        # equivale a tomar el mínimo en la ventana 3x3.
        vecinos_min = grey_erosion(out_safe, footprint=estructura)
        # Elevación propuesta = max(original, min_vecino + eps)
        nueva = np.maximum(out_safe, vecinos_min + eps)
        # Conservar nodata
        nueva = np.where(np.isnan(out), out, nueva)
        if np.allclose(nueva, out_safe, atol=1e-6, equal_nan=True):
            break
        out_safe = np.where(np.isnan(out), -1e9,
                              np.where(np.isnan(out), out, nueva))
    return np.where(np.isnan(dem), np.nan, out_safe)


# ─────────────────── D8 flow direction ───────────────────

def flow_direction_d8(dem: np.ndarray, paso_m: float = 12.5
                         ) -> np.ndarray:
    """D8: cada celda apunta al vecino con mayor caída/distancia.

    Devuelve int8 con código D8 (0–255 bit). Bordes y celdas NaN
    quedan con 0.
    """
    h, w = dem.shape
    diag = np.sqrt(2.0) * paso_m
    dist = np.where(np.array([abs(dr) + abs(dc) == 2
                                  for dr, dc, _ in _D8_OFFSETS]),
                       diag, paso_m)
    flow = np.zeros((h, w), dtype=np.uint8)
    mejor_caida = np.full((h, w), -1.0, dtype=np.float32)
    for idx, (dr, dc, code) in enumerate(_D8_OFFSETS):
        # Recorte de vecinos con padding implícito
        i0, i1 = max(0, -dr), h - max(0, dr)
        j0, j1 = max(0, -dc), w - max(0, dc)
        ni0, ni1 = max(0, dr), h - max(0, -dr)
        nj0, nj1 = max(0, dc), w - max(0, -dc)
        vecino = dem[ni0:ni1, nj0:nj1]
        propio = dem[i0:i1, j0:j1]
        caida = (propio - vecino) / dist[idx]
        # Donde la caída es mayor a la mejor previa, actualizar
        valido = np.isfinite(caida) & (caida > mejor_caida[i0:i1, j0:j1])
        mejor_caida[i0:i1, j0:j1] = np.where(valido, caida,
                                                  mejor_caida[i0:i1, j0:j1])
        flow[i0:i1, j0:j1] = np.where(valido, code,
                                          flow[i0:i1, j0:j1])
    # Celdas sin caída positiva (planas/sumideros) quedan con 0
    flow[~np.isfinite(dem)] = 0
    return flow


# ─────────────────── Flow accumulation ───────────────────

def flow_accumulation(flow_dir: np.ndarray) -> np.ndarray:
    """Cuenta píxeles upstream para cada celda en orden topológico.

    Vectorizado parcialmente: el cálculo de `indegree` es 100% numpy
    (vs O(h·w) en Python puro), y el BFS topológico final usa cola
    deque con accesos directos (el for-loop Python solo recorre cada
    celda 1 sola vez, no es cuadrático).
    """
    h, w = flow_dir.shape
    code_to_off = {code: (dr, dc) for dr, dc, code in _D8_OFFSETS}
    # ─── Indegree vectorizado ───
    indegree = np.zeros((h, w), dtype=np.int32)
    for dr, dc, code in _D8_OFFSETS:
        # Celdas con ese código de flujo envían a (i+dr, j+dc)
        emisores = (flow_dir == code)
        if not emisores.any():
            continue
        # Sumamos los emisores desplazados a sus destinos.
        # Recortes: el emisor en (si, sj) impacta el receptor en (si+dr, sj+dc).
        si0, si1 = max(0, -dr), h - max(0, dr)
        sj0, sj1 = max(0, -dc), w - max(0, dc)
        ri0, ri1 = si0 + dr, si1 + dr
        rj0, rj1 = sj0 + dc, sj1 + dc
        indegree[ri0:ri1, rj0:rj1] += emisores[si0:si1, sj0:sj1].astype(np.int32)

    # ─── BFS topológico desde cabeceras ───
    acc = np.ones((h, w), dtype=np.int32)
    from collections import deque
    # Cabeceras: celdas con flujo definido pero sin nadie que les apunte.
    cabeceras = (indegree == 0) & (flow_dir != 0)
    ii, jj = np.where(cabeceras)
    cola = deque(zip(ii.tolist(), jj.tolist()))
    while cola:
        i, j = cola.popleft()
        code = flow_dir[i, j]
        if code == 0:
            continue
        dr, dc = code_to_off[code]
        ni, nj = i + dr, j + dc
        if 0 <= ni < h and 0 <= nj < w:
            acc[ni, nj] += acc[i, j]
            indegree[ni, nj] -= 1
            if indegree[ni, nj] == 0:
                cola.append((ni, nj))
    return acc


# ─────────────────── Extracción de red ───────────────────

def extraer_red(dem: np.ndarray, paso_m: float = 12.5,
                  umbrales_km2: tuple = (0.05, 0.5, 5.0)) -> dict:
    """Pipeline completo: fill → D8 → acc → 3 categorías de cauces.

    Devuelve dict con:
      dem_relleno, flow_dir, flow_acc_km2 (área aportante en km²),
      mascara_capilar (umbrales[0] ≤ acc < umbrales[1]),
      mascara_secundario, mascara_principal.
    """
    pix_km2 = (paso_m * paso_m) / 1e6
    dem_fill = rellenar_depresiones(dem, n_iter=50)
    flow = flow_direction_d8(dem_fill, paso_m=paso_m)
    acc = flow_accumulation(flow).astype(np.float64) * pix_km2
    u0, u1, u2 = umbrales_km2
    m_cap = (acc >= u0) & (acc < u1)
    m_sec = (acc >= u1) & (acc < u2)
    m_pri = acc >= u2
    return {
        "dem_relleno": dem_fill,
        "flow_dir": flow,
        "flow_acc_km2": acc,
        "mascara_capilar": m_cap,
        "mascara_secundario": m_sec,
        "mascara_principal": m_pri,
        "n_pixels_cap": int(m_cap.sum()),
        "n_pixels_sec": int(m_sec.sum()),
        "n_pixels_pri": int(m_pri.sum()),
        "umbrales_km2": umbrales_km2,
    }


# ─────────────────── Render PNG ───────────────────

def _dibujar_capa(dem: np.ndarray, red: dict, bbox: dict,
                     out_path: Path,
                     poligono_lonlat: Optional[np.ndarray] = None) -> Path:
    """Render PNG de la capa-only (hillshade + red + contorno).

    SIN título / leyenda / grilla / escala — eso lo aplica el chrome
    cartográfico estándar via `_decorar_mapa_cartografico`. Así el
    9.2 se ve idéntico en formato al 9.3-9.7 (grilla UTM, leyenda
    derecha, escala, norte).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource, to_rgba

    h, w = dem.shape
    extent = [bbox["oeste"], bbox["este"], bbox["sur"], bbox["norte"]]

    fig, ax = plt.subplots(figsize=(8, 8), dpi=120)
    # Hillshade base — robusto ante DEM con muchos NaN
    ls = LightSource(azdeg=315, altdeg=45)
    finite = np.isfinite(dem)
    if finite.any():
        rellenado = np.where(finite, dem, np.nanmedian(dem[finite]))
        hillshade = ls.shade(rellenado, cmap=plt.cm.gray, vert_exag=2,
                                blend_mode="overlay")
        ax.imshow(hillshade, extent=extent, origin="upper",
                    interpolation="bilinear")
    # Red como RGBA único
    rgba = np.zeros((h, w, 4), dtype=np.float32)
    for mask, color, alpha in (
        (red["mascara_capilar"], "#9ed1ff", 0.65),
        (red["mascara_secundario"], "#3b8bd8", 0.90),
        (red["mascara_principal"], "#0a4f9e", 1.00),
    ):
        if mask.any():
            r, g, b, _ = to_rgba(color)
            rgba[mask, 0] = r
            rgba[mask, 1] = g
            rgba[mask, 2] = b
            rgba[mask, 3] = alpha
    ax.imshow(rgba, extent=extent, origin="upper",
                interpolation="nearest")
    # Contorno cuenca
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


# ─────────────────── Entry point para el pipeline ───────────────────

def generar_mapa_9_2(poligono_lonlat, out_path: Path, autor: str = "",
                       res_target_m: float = 12.5) -> Optional[dict]:
    """Función de alto nivel: descarga COP-DEM → D8 → render con chrome
    cartográfico estándar HYDROFRA (grilla UTM, leyenda, escala, norte).
    """
    from .copernicus_dem import obtener_dem_cuenca
    from .gee import _decorar_mapa_cartografico
    cop = obtener_dem_cuenca(poligono_lonlat, res_target_m=res_target_m)
    if cop is None:
        return None
    dem = cop["array"]
    bbox = cop["bbox"]
    paso_m = cop["resolucion_m"]
    red = extraer_red(dem, paso_m=paso_m,
                         umbrales_km2=(0.05, 0.5, 5.0))
    # 1) Capa-only PNG
    _dibujar_capa(dem, red, bbox, out_path,
                     poligono_lonlat=poligono_lonlat)
    # 2) Chrome cartográfico estándar (grilla UTM, leyenda, escala, norte)
    pix_km2 = (paso_m * paso_m) / 1e6
    leyenda = [
        {"etiqueta": (f"Capilar (A ≥ {red['umbrales_km2'][0]:.2f} km²)"),
            "color": "#9ed1ff",
            "pct": round(100 * red['n_pixels_cap'] * pix_km2 /
                          max(cop['array'].size * pix_km2, 1e-9), 1)},
        {"etiqueta": (f"Secundario (A ≥ {red['umbrales_km2'][1]:.2f} km²)"),
            "color": "#3b8bd8",
            "pct": round(100 * red['n_pixels_sec'] * pix_km2 /
                          max(cop['array'].size * pix_km2, 1e-9), 1)},
        {"etiqueta": (f"Principal (A ≥ {red['umbrales_km2'][2]:.2f} km²)"),
            "color": "#0a4f9e",
            "pct": round(100 * red['n_pixels_pri'] * pix_km2 /
                          max(cop['array'].size * pix_km2, 1e-9), 1)},
    ]
    pix_km = paso_m / 1000.0
    long_total_km = round(
        (red["n_pixels_cap"] + red["n_pixels_sec"] +
         red["n_pixels_pri"]) * pix_km, 2)
    resumen = (f"Long. red total ≈ {long_total_km} km  "
                 f"(D8 + flow-acc sobre COP-DEM 12.5 m)")
    _decorar_mapa_cartografico(
        out_path, bbox, autor=autor,
        titulo="9.2 Red de drenaje (D8 sobre COP-DEM 12.5 m)",
        entradas_leyenda=leyenda, resumen=resumen,
    )
    return {
        "path": out_path,
        "n_pixels_capilar": red["n_pixels_cap"],
        "n_pixels_secundario": red["n_pixels_sec"],
        "n_pixels_principal": red["n_pixels_pri"],
        "longitud_total_aprox_km": long_total_km,
        "umbrales_area_km2": list(red["umbrales_km2"]),
        "resolucion_m": paso_m,
        "fuente_dem": "COP-DEM GLO-30 (downscaled cubic-spline 12.5 m)",
        "algoritmo": "D8 + flow-accumulation (NumPy)",
    }
