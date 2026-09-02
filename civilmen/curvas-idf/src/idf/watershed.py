"""Delineación watershed real al punto desde MERIT Hydro v1.0.1.

A diferencia de `morfologia_desde_gee` (que devuelve la sub-cuenca completa
de HydroBASINS L12 que contiene el punto), este módulo hace **delineación
hidrológica real**: descarga el tile de flow-direction MERIT Hydro a 90 m
alrededor del punto y aplica un flood-fill D8 hacia aguas arriba desde el
píxel de cierre. El resultado es la cuenca de aporte verdadera al punto,
con su polígono, área, perímetro, Hmax/Hmin reales.

Sin nuevas dependencias: NumPy + scipy.ndimage + matplotlib.contour.

Encoding D8 estándar (1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE),
usado por MERIT Hydro, ESRI, HydroSHEDS y la mayoría de SIG.
"""

from __future__ import annotations

import io
import math
import sys
from collections import deque
from dataclasses import dataclass
from typing import Optional
from urllib.request import urlopen

import numpy as np


def _msg(texto: str) -> None:
    print(f"[watershed] {texto}", file=sys.stderr, flush=True)


# Convención: row crece hacia el SUR (eje Y invertido respecto a lat).
# _D8[code] = (drow, dcol) del píxel DESTINO al que apunta `code`.
_D8 = {
    1:   (0, 1),    # E
    2:   (1, 1),    # SE
    4:   (1, 0),    # S
    8:   (1, -1),   # SW
    16:  (0, -1),   # W
    32:  (-1, -1),  # NW
    64:  (-1, 0),   # N
    128: (-1, 1),   # NE
}

# Inversa para BFS upstream: si el vecino en (drow, dcol) tiene flow_dir
# igual a _UPSTREAM[(drow, dcol)], drena al píxel actual.
_UPSTREAM = {(-dr, -dc): code for code, (dr, dc) in _D8.items()}


@dataclass
class CuencaDelineada:
    """Resultado de la delineación: polígono lat/lon + morfología real."""
    poligono_latlon: np.ndarray  # (N, 2) array de [lon, lat]
    area_km2: float
    perimetro_km: float
    cota_mayor_m: float
    cota_menor_m: float
    desnivel_m: float
    pendiente_media_mm: float
    long_cauce_km: float
    # bbox del polígono (oeste, sur, este, norte) en grados
    bbox: tuple
    # punto efectivo (lat, lon) tras el snap al cauce — útil para diagnóstico
    punto_snap_latlon: tuple
    # Arrays 1D de los píxeles DENTRO de la cuenca (para morfometría e
    # hipsométrica locales, sin round-trips extra a GEE):
    elev_dentro_m: np.ndarray = None       # elevaciones (m)
    pendiente_dentro_pct: np.ndarray = None  # pendiente por píxel (%)
    area_pixel_m2: float = 0.0             # área de un píxel del tile (m²)
    long_cauce_total_km: float = 0.0       # longitud total de cauces (Dd)
    red_drenaje: dict = None               # Strahler, Rb, cauce principal, sinuosidad
    truncada: bool = False                 # True si la máscara tocó borde del tile


def _descargar_tile_merit(lat: float, lon: float, radio_grados: float):
    """Descarga DIR + ELV + UPA de MERIT Hydro como NPY (NumPy structured array).

    Devuelve (dir, elv, upa, transform) o None si GEE no responde.
    `transform` = (west, north, paso_lon_por_pixel, paso_lat_por_pixel),
    con paso_lat NEGATIVO porque row crece hacia el sur.
    """
    try:
        from .gee import _intentar_inicializar
        if not _intentar_inicializar():
            _msg("GEE no inicializado")
            return None
        import ee
        region = ee.Geometry.Rectangle([
            lon - radio_grados, lat - radio_grados,
            lon + radio_grados, lat + radio_grados,
        ])
        clip = ee.Image("MERIT/Hydro/v1_0_1").select(["dir", "elv", "upa"])
        url = clip.getDownloadURL({
            "region": region,
            "scale": 90,
            "format": "NPY",
            "crs": "EPSG:4326",
        })
        _msg(f"descargando MERIT Hydro tile…")
        raw = urlopen(url, timeout=120).read()
        data = np.load(io.BytesIO(raw), allow_pickle=False)
        dir_arr = np.asarray(data["dir"]).astype(np.int16)
        elv_arr = np.asarray(data["elv"]).astype(np.float32)
        upa_arr = np.asarray(data["upa"]).astype(np.float32)
        n_rows, n_cols = dir_arr.shape
        west, south = lon - radio_grados, lat - radio_grados
        east, north = lon + radio_grados, lat + radio_grados
        paso_lon = (east - west) / n_cols
        paso_lat = -(north - south) / n_rows
        _msg(f"tile MERIT {n_rows}x{n_cols} px descargado")
        return dir_arr, elv_arr, upa_arr, (west, north, paso_lon, paso_lat)
    except Exception as e:  # noqa: BLE001
        _msg(f"descarga MERIT falló: {type(e).__name__}: {e}")
        return None


def _snap_a_cauce(upa: np.ndarray, i0: int, j0: int, ventana: int = 3,
                    max_factor: float = 10.0):
    """Mueve el punto al píxel de mayor flow-accumulation en una ventana cuadrada.

    Versión defensiva: ventana pequeña por defecto (3×3 ≈ ±90 m, GPS típico)
    y descarta el snap si arrastraría el punto a un cauce mucho mayor
    (factor > `max_factor`). Esto evita que un punto sobre una tributaria
    de 40 km² sea atraído al cauce principal regional (p. ej. Bermejo) que
    pasa a 200-300 m, lo que delineaba una cuenca decenas de miles de km²
    mayor que la pretendida.
    """
    h, w = upa.shape
    r = ventana // 2
    i_min, i_max = max(0, i0 - r), min(h, i0 + r + 1)
    j_min, j_max = max(0, j0 - r), min(w, j0 + r + 1)
    sub = upa[i_min:i_max, j_min:j_max]
    if sub.size == 0:
        return i0, j0
    di, dj = np.unravel_index(int(np.argmax(sub)), sub.shape)
    snap_upa = float(sub[di, dj]) if np.isfinite(sub[di, dj]) else 0.0
    orig_upa_val = upa[i0, j0]
    orig_upa = float(orig_upa_val) if np.isfinite(orig_upa_val) else 0.0
    # Si el punto original ya está sobre cauce no trivial (upa ≥ 1 km²) y
    # el snap saltaría a un cauce mucho mayor, preservamos el original.
    if orig_upa >= 1.0 and snap_upa > max_factor * orig_upa:
        return i0, j0
    if snap_upa >= 0.5:
        return i_min + di, j_min + dj
    return i0, j0


def _watershed_d8(flow_dir: np.ndarray, i_out: int, j_out: int,
                   max_pixels: int = 5_000_000) -> np.ndarray:
    """Flood-fill upstream D8 desde (i_out, j_out). Devuelve máscara bool."""
    h, w = flow_dir.shape
    mask = np.zeros((h, w), dtype=bool)
    mask[i_out, j_out] = True
    cola = deque([(i_out, j_out)])
    while cola:
        i, j = cola.popleft()
        for (drow, dcol), code in _UPSTREAM.items():
            ni, nj = i + drow, j + dcol
            if 0 <= ni < h and 0 <= nj < w and not mask[ni, nj]:
                if flow_dir[ni, nj] == code:
                    mask[ni, nj] = True
                    cola.append((ni, nj))
        if mask.sum() > max_pixels:
            break
    return mask


def _mascara_a_poligono(mask: np.ndarray, transform):
    """Extrae el contorno principal de la máscara y lo proyecta a lat/lon.

    Usa matplotlib.contour (level=0.5 sobre la máscara como float) y se queda
    con el path más largo, que corresponde al perímetro exterior de la cuenca.
    Devuelve array (N, 2) en formato [lon, lat] o None si no hay contorno.

    Compat: usa `cs.get_paths()` (API estable desde mpl 3.5). El acceso a
    `cs.allsegs[0]` quedó como fallback ya que en matplotlib ≥ 3.8 puede
    devolver un numpy array y `if not paths` revienta con
    «truth value of an array … ambiguous».
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    west, north, paso_lon, paso_lat = transform
    fig, ax = plt.subplots()
    cs = ax.contour(mask.astype(float), levels=[0.5])
    plt.close(fig)
    # Extracción robusta del contorno: API nueva preferida, fallback legacy.
    paths: list[np.ndarray] = []
    try:
        for p in cs.get_paths():
            v = np.asarray(p.vertices)
            if len(v) >= 4:
                paths.append(v)
    except Exception:  # noqa: BLE001
        pass
    if len(paths) == 0 and hasattr(cs, "allsegs") and len(cs.allsegs) > 0:
        legacy = cs.allsegs[0]
        # En mpl ≥ 3.8 esto puede ser ndarray (no list); convertir.
        if isinstance(legacy, (list, tuple)):
            paths = [np.asarray(s) for s in legacy if len(s) >= 4]
        elif hasattr(legacy, "__len__") and len(legacy) >= 4:
            paths = [np.asarray(legacy)]
    if len(paths) == 0:
        return None
    mejor = max(paths, key=len)
    if len(mejor) < 4:
        return None
    cols = mejor[:, 0]
    rows = mejor[:, 1]
    lons = west + (cols + 0.5) * paso_lon
    lats = north + (rows + 0.5) * paso_lat
    return np.column_stack([lons, lats])


def _analisis_red(flow_dir, upa, mask, i_out, j_out,
                  paso_lon_m, paso_lat_m, umbral_km2=0.5):
    """Orden de Strahler, conteo de corrientes, Rb, longitud de cauce principal.

    Procesa los píxeles de cauce (upa ≥ umbral) en orden topológico (por upa)
    y propaga el orden de Strahler; cuenta corrientes por orden, calcula la
    relación de bifurcación media, la longitud total de cauces y, siguiendo el
    flujo D8 hasta el exutorio, la longitud del cauce principal y su sinuosidad.
    """
    h, w = upa.shape
    stream = mask & np.isfinite(upa) & (upa >= umbral_km2)
    coords = np.argwhere(stream)
    if len(coords) < 3:
        return None
    # Para cuencas muy grandes (Mamoré / Bermejo) el Strahler completo sobre
    # decenas de miles de píxeles de cauce bloquea al worker. Subimos el
    # umbral upa progresivamente para acotar el trabajo a ~5000 píxeles,
    # manteniendo la representatividad del orden máximo (dominado por los
    # cauces principales).
    if len(coords) > 5000:
        for nuevo_umbral in (5.0, 25.0, 100.0, 500.0):
            stream2 = mask & np.isfinite(upa) & (upa >= nuevo_umbral)
            n2 = int(stream2.sum())
            if n2 < 5000:
                stream = stream2
                coords = np.argwhere(stream)
                _msg(f"Strahler: serie reducida con umbral upa ≥ "
                     f"{nuevo_umbral} km² → {n2} px de cauce")
                break
    paso_med = (paso_lon_m + paso_lat_m) / 2.0
    diag = paso_med * math.sqrt(2.0)
    diag_codes = {2, 8, 32, 128}

    # --- Strahler: ascendente por upa (aguas arriba primero) ---
    vals = upa[stream]
    asc = np.argsort(vals, kind="stable")
    strahler = {}
    n_por_orden = {}
    for k in asc:
        i, j = int(coords[k][0]), int(coords[k][1])
        ups = []
        for (dr, dc), code in _UPSTREAM.items():
            ni, nj = i + dr, j + dc
            if 0 <= ni < h and 0 <= nj < w and stream[ni, nj] and \
                    flow_dir[ni, nj] == code and (ni, nj) in strahler:
                ups.append(strahler[(ni, nj)])
        if not ups:
            o, inicio = 1, True
        else:
            m = max(ups)
            if ups.count(m) >= 2:
                o, inicio = m + 1, True
            else:
                o, inicio = m, False
        strahler[(i, j)] = o
        if inicio:
            n_por_orden[o] = n_por_orden.get(o, 0) + 1
    max_order = max(strahler.values())
    n_total = sum(n_por_orden.values())
    rbs = []
    for k in range(1, max_order):
        a, b = n_por_orden.get(k, 0), n_por_orden.get(k + 1, 0)
        if b > 0:
            rbs.append(a / b)
    rb = sum(rbs) / len(rbs) if rbs else float("nan")
    long_total_km = stream.sum() * paso_med / 1000.0

    # --- Cauce principal: distancia D8 al exutorio (descendente por upa) ---
    desc = asc[::-1]
    dist = {}
    for k in desc:
        i, j = int(coords[k][0]), int(coords[k][1])
        code = int(flow_dir[i, j])
        paso = diag if code in diag_codes else paso_med
        if code in _D8:
            dr, dc = _D8[code]
            ni, nj = i + dr, j + dc
            d_down = dist.get((ni, nj), 0.0)
        else:
            d_down = 0.0
        dist[(i, j)] = paso + d_down
    # El cauce principal es el de mayor distancia desde una cabecera al exutorio.
    main_celda = max(dist, key=dist.get)
    main_channel_km = dist[main_celda] / 1000.0
    # Distancia recta cabecera→exutorio (para sinuosidad).
    di = (main_celda[0] - i_out) * paso_lat_m
    dj = (main_celda[1] - j_out) * paso_lon_m
    recta_km = math.hypot(di, dj) / 1000.0
    # Sinuosidad = longitud del cauce / distancia recta cabecera→exutorio, con
    # AMBAS longitudes medidas sobre el MISMO trazado D8. NO se acota a ≥ 1.0:
    # el clamp anterior enmascaraba un dato físicamente imposible (un cauce no
    # puede ser más corto que la recta que une sus extremos) y hacía que la
    # sinuosidad publicada no fuera reproducible a partir de Lc y Lr. Si el
    # cociente sale < 1 se reporta tal cual y se marca la inconsistencia para
    # que el informe la declare en vez de ocultarla.
    sinuosidad = main_channel_km / recta_km if recta_km > 0 else float("nan")
    return {
        "n_por_orden": {int(k): int(v) for k, v in n_por_orden.items()},
        "n_total": int(n_total), "max_order": int(max_order),
        "rb": round(rb, 2) if rb == rb else None,
        "long_total_km": round(long_total_km, 3),
        "main_channel_km": round(main_channel_km, 3),
        "recta_km": round(recta_km, 3),
        "sinuosidad": (round(sinuosidad, 3) if sinuosidad == sinuosidad
                       else None),
        "sinuosidad_inconsistente": bool(sinuosidad == sinuosidad
                                          and sinuosidad < 1.0),
    }


def _morfologia_desde_mascara(mask, elv, upa, flow_dir, i_out, j_out, transform):
    """Calcula morfología desde la cuenca y devuelve también los arrays internos.

    Retorna un dict con escalares + los arrays 1D de elevación y pendiente
    DENTRO de la cuenca (para curva hipsométrica y % por banda) más el área
    de píxel, la longitud total de cauces y el análisis de red de drenaje.
    """
    from scipy.ndimage import binary_erosion
    west, north, paso_lon, paso_lat = transform
    lat_centro = north + (mask.shape[0] / 2) * paso_lat
    paso_lon_m = abs(paso_lon) * 111320.0 * math.cos(math.radians(lat_centro))
    paso_lat_m = abs(paso_lat) * 110540.0
    area_pixel_m2 = paso_lon_m * paso_lat_m
    area_km2 = mask.sum() * area_pixel_m2 / 1e6
    # Hmax/Hmin sobre el DEM enmascarado, filtrando valores inválidos
    elv_validos = np.isfinite(elv) & (elv > -1000)
    dentro = mask & elv_validos
    elev_dentro = elv[dentro].astype(np.float64)
    if elev_dentro.size == 0:
        return None
    hmax = float(elev_dentro.max())
    hmin = float(elev_dentro.min())
    desnivel = hmax - hmin
    # Pendiente por píxel desde el gradiente del DEM (en %), recortada a la cuenca.
    gy, gx = np.gradient(elv.astype(np.float64))
    slope_pct = np.sqrt((gx / paso_lon_m) ** 2 + (gy / paso_lat_m) ** 2) * 100.0
    pendiente_dentro = slope_pct[dentro]
    pendiente_dentro = pendiente_dentro[np.isfinite(pendiente_dentro)]
    # Perímetro: píxeles de borde × tamaño promedio de píxel
    borde = mask & ~binary_erosion(mask)
    perimetro_km = borde.sum() * (paso_lon_m + paso_lat_m) / 2 / 1000.0
    # Longitud total de cauces (upa ≥ 1 km²) dentro de la cuenca → Dd.
    cauces = mask & (upa >= 1.0) & elv_validos
    long_cauce_total_km = cauces.sum() * (paso_lon_m + paso_lat_m) / 2 / 1000.0
    # Análisis de red de drenaje (Strahler, Rb, cauce principal real D8).
    red = _analisis_red(flow_dir, upa, mask, i_out, j_out,
                        paso_lon_m, paso_lat_m)
    # Longitud del cauce principal: la real por D8 si está, si no ley de Hack.
    if red and red.get("main_channel_km"):
        long_cauce_km = red["main_channel_km"]
    else:
        long_cauce_km = 1.4 * area_km2 ** 0.6
    pendiente = desnivel / (long_cauce_km * 1000.0) if long_cauce_km else 0.0
    return {
        "area_km2": round(area_km2, 3),
        "perimetro_km": round(perimetro_km, 3),
        "cota_mayor_m": round(hmax, 1),
        "cota_menor_m": round(hmin, 1),
        "desnivel_m": round(desnivel, 1),
        "pendiente_media_mm": round(pendiente, 4),
        "long_cauce_km": round(long_cauce_km, 3),
        "long_cauce_total_km": round(long_cauce_total_km, 3),
        "area_pixel_m2": area_pixel_m2,
        "elev_dentro_m": elev_dentro,
        "pendiente_dentro_pct": pendiente_dentro,
        "red_drenaje": red,
    }


def delinear_cuenca_merit(lat: float, lon: float,
                           radio_grados: float = 0.3,
                           reintentar_borde: bool = True) -> Optional[CuencaDelineada]:
    """API principal: delinea la cuenca real al punto y calcula morfología.

    `radio_grados` controla el tamaño del tile descargado. Si la cuenca toca
    el borde y `reintentar_borde` está activo, se reintenta con el doble de
    radio. Para cuencas muy grandes (Bermejo, Mamoré) conviene pasar
    `reintentar_borde=False` para que el análisis de Strahler sobre la red
    expandida no bloquee al worker.

    Devuelve None si GEE no responde o la cuenca es degenerada.
    """
    radios = [radio_grados, radio_grados * 2] if reintentar_borde else [radio_grados]
    for intento, radio in enumerate(radios, 1):
        resultado = _descargar_tile_merit(lat, lon, radio)
        if resultado is None:
            return None
        flow_dir, elv, upa, transform = resultado
        h, w = flow_dir.shape
        west, north, paso_lon, paso_lat = transform
        j0 = int((lon - west) / paso_lon)
        i0 = int((lat - north) / paso_lat)
        if not (0 <= i0 < h and 0 <= j0 < w):
            _msg(f"punto fuera del tile (i={i0}, j={j0})")
            return None
        i_out, j_out = _snap_a_cauce(upa, i0, j0, ventana=7)
        _msg(f"snap: ({i0},{j0}) → ({i_out},{j_out}), "
             f"upa={upa[i_out, j_out]:.2f} km²")
        mask = _watershed_d8(flow_dir, i_out, j_out)
        n_pix = int(mask.sum())
        _msg(f"watershed → {n_pix} píxeles")
        if n_pix < 5:
            return None
        # Si toca el borde del tile, ampliar radio y reintentar.
        toca_borde = (mask[0, :].any() or mask[-1, :].any() or
                      mask[:, 0].any() or mask[:, -1].any())
        if toca_borde and intento < len(radios):
            _msg("cuenca toca borde del tile, ampliando radio…")
            continue
        if toca_borde:
            _msg("cuenca toca borde (truncada) — se conserva tal cual")
        # Listo: vectorizar y calcular morfología.
        poligono = _mascara_a_poligono(mask, transform)
        if poligono is None or len(poligono) < 4:
            _msg("contorno vacío")
            return None
        morf = _morfologia_desde_mascara(mask, elv, upa, flow_dir,
                                         i_out, j_out, transform)
        if morf is None:
            return None
        lon_snap = west + (j_out + 0.5) * paso_lon
        lat_snap = north + (i_out + 0.5) * paso_lat
        bbox = (poligono[:, 0].min(), poligono[:, 1].min(),
                poligono[:, 0].max(), poligono[:, 1].max())
        _msg(f"delineada OK: A={morf['area_km2']} km², "
             f"P={morf['perimetro_km']} km, "
             f"H={morf['cota_menor_m']}-{morf['cota_mayor_m']} m")
        return CuencaDelineada(
            poligono_latlon=poligono,
            bbox=bbox,
            punto_snap_latlon=(lat_snap, lon_snap),
            truncada=bool(toca_borde),
            **morf,
        )
    return None
