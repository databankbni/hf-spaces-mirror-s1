"""Mapas temáticos reales de la cuenca generados con Google Earth Engine.

Para cada uno de los 6 mapas 9.2-9.7 consulta el dataset correspondiente,
recorta al polígono de cuenca delineado por MERIT Hydro y genera un PNG con
marco cartográfico profesional: grilla UTM cada 2500 m, leyenda con el % de
área de cada clase, barra de escala graduada, proyección (zona UTM) y autor.

Si GEE no responde o el polígono falta, el llamador (pipeline.py) cae al
mapa esquemático equivalente de `mapas.py`.

Datasets usados:
- 9.2 Red de drenaje:    MERIT/Hydro/v1_0_1 banda `upa` (3 umbrales).
- 9.3 Uso de suelo:      FROM-GLC10 10 m (Gong et al. 2019); MapBiomas Bolivia
                         30 m como fallback.
- 9.4 Cobertura vegetal: ESA/WorldCover/v200 (10 m, paleta ESA oficial).
- 9.5 CN SCS:            MapBiomas remapeado por _CN_POR_COBERTURA (60-100).
- 9.6 Pendientes:        Terrain.slope(SRTM) en % (clases geotécnicas).
- 9.7 Coef. escorrentía: racional (uso de suelo × pendiente).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from .gee import (
    _CN_POR_COBERTURA,
    _N_MANNING_POR_COBERTURA,
    _decorar_mapa_cartografico,
    _intentar_inicializar,
    _msg,
    descargar_con_timeout,
)


# ---------------------------------------------------------------------------
# Geometría, descarga y leyendas
# ---------------------------------------------------------------------------

def _geometria_y_bounds(poligono_lonlat, buffer_frac: float = 0.08):
    """Convierte polígono Nx2 lon/lat → (ee.Geometry, bounds_buffered, bbox_dict)."""
    import ee
    coords = [[float(c[0]), float(c[1])] for c in poligono_lonlat]
    geom = ee.Geometry.Polygon([coords])
    bounds = geom.bounds(maxError=1).buffer(
        ee.Number(geom.area(maxError=1)).sqrt().multiply(buffer_frac)
    )
    bbox_coords = bounds.bounds(maxError=1).coordinates().getInfo()[0]
    xs = [c[0] for c in bbox_coords]
    ys = [c[1] for c in bbox_coords]
    bbox = {"oeste": min(xs), "este": max(xs),
            "sur": min(ys), "norte": max(ys)}
    return geom, bounds, bbox


def _escala_adaptativa(bbox, dimensions: int = 700, px_min_m: float = 30.0,
                        sobremuestreo: float = 2.0) -> float:
    """Escala (m/píxel) para reproyectar sin reventar el thumbnail.

    En cuencas grandes, `.reproject(scale=30)` fija el cómputo a 30 m sobre
    TODA la cuenca antes de reducir el thumbnail a `dimensions` px — miles de
    millones de píxeles → timeout/límite de memoria en GEE. Esta escala se
    ajusta al tamaño de la cuenca: ~`sobremuestreo` píxeles de cómputo por
    píxel de salida, con piso en `px_min_m` (30 m nativo COP-DEM) para que las
    cuencas pequeñas sigan usando resolución fina. Para clasificar 1–5 en un
    thumbnail de 700 px, una cuenca de 500 km sale a ~360 m/píxel sin pérdida
    visible, y el render pasa de minutos a segundos.
    """
    lat_c = (bbox["sur"] + bbox["norte"]) / 2.0
    ancho_m = (abs(bbox["este"] - bbox["oeste"]) * 111320.0
               * max(0.1, math.cos(math.radians(lat_c))))
    alto_m = abs(bbox["norte"] - bbox["sur"]) * 110540.0
    lado_m = max(ancho_m, alto_m)
    return max(px_min_m, lado_m / (max(1, dimensions) * max(0.5, sobremuestreo)))


def _thumb_decorado(salida, bounds, bbox, out_path: Path, autor: str,
                     dimensions: int = 700, timeout: float = 75.0,
                     titulo: str = "", entradas_leyenda=None,
                     resumen: str = "") -> Path:
    from .gee import epsg_utm
    # Render en UTM (zona del centro de la cuenca) para que la grilla métrica
    # cada 2500 m sea rectilínea y exacta en el PNG.
    lat_c = (bbox["sur"] + bbox["norte"]) / 2
    lon_c = (bbox["oeste"] + bbox["este"]) / 2
    crs = epsg_utm(lat_c, lon_c)
    url = salida.getThumbURL({
        "region": bounds,
        "dimensions": str(dimensions),
        "crs": crs,
        "format": "png",
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _msg(f"descargando {out_path.name} ({crs})…")
    descargar_con_timeout(url, out_path, timeout=timeout)
    _decorar_mapa_cartografico(out_path, bbox, autor, entradas_leyenda=entradas_leyenda,
                                resumen=resumen, titulo=titulo)
    return out_path


def _contorno_cuenca(geom):
    """Pinta el contorno de la cuenca en rojo grueso sobre cualquier mapa."""
    import ee
    return ee.Image().byte().paint(
        featureCollection=ee.FeatureCollection([ee.Feature(geom)]),
        color=1, width=3,
    ).visualize(palette=["#e53935"])


def _frecuencia(img_clase, geom, scale: float) -> dict:
    """frequencyHistogram de una imagen de clases (enteros) sobre la cuenca.

    Devuelve {clase_int: porcentaje} normalizado a 100. {} si falla.
    """
    import ee
    try:
        d = img_clase.rename("c").reduceRegion(
            ee.Reducer.frequencyHistogram(), geom, scale=scale,
            maxPixels=1e9, bestEffort=True).getInfo()
        hist = (d or {}).get("c") or {}
        total = sum(float(v) for v in hist.values()) or 1.0
        return {int(float(k)): 100.0 * float(v) / total for k, v in hist.items()}
    except Exception as e:  # noqa: BLE001
        _msg(f"_frecuencia falló: {type(e).__name__}: {e}")
        return {}


def _indice_por_bordes(img, bordes):
    """Imagen de índice de clase 0..n-1 según los bordes interiores (gte acumulado)."""
    import ee
    idx = ee.Image(0)
    for b in bordes[1:-1]:
        idx = idx.add(img.gte(b))
    return idx


def _leyenda_desde_frec(frec: dict, nombres: dict, colores: dict,
                         tope: int = 8) -> list:
    """Construye entradas de leyenda (etiqueta, color, pct) ordenadas por % desc."""
    items = sorted(frec.items(), key=lambda kv: kv[1], reverse=True)
    entradas = []
    otros = 0.0
    for i, (clase, pct) in enumerate(items):
        if i >= tope or pct < 0.5:
            otros += pct
            continue
        entradas.append({
            "etiqueta": nombres.get(clase, f"Clase {clase}"),
            "color": colores.get(clase, "#cccccc"),
            "pct": pct,
        })
    if otros >= 0.5:
        entradas.append({"etiqueta": "Otros", "color": "#dddddd", "pct": otros})
    return entradas


# ---------------------------------------------------------------------------
# Nomenclatura y paletas
# ---------------------------------------------------------------------------

# MapBiomas Bolivia (subset principal) — colores oficiales aproximados.
_PALETA_MAPBIOMAS = {
    1:  "#1f8d49", 3:  "#1f8d49", 4:  "#7dc975",
    6:  "#1c89a3", 10: "#d6bc74", 11: "#519799",
    12: "#d6bc74", 13: "#cebd9c",
    14: "#ffefc3", 15: "#edde8e", 18: "#e974ed",
    21: "#ffefc3", 22: "#d4271e",
    23: "#ffa07a", 24: "#af2a2a", 25: "#9c0027",
    26: "#2532e4", 27: "#cccccc", 29: "#807a40",
    30: "#9b3b06", 31: "#02bcbe",
    33: "#0066ff", 34: "#ffffff", 39: "#f3b4f1",
    61: "#dfdfa9", 66: "#d1aa83", 68: "#9c8463",
    72: "#ff69b4", 81: "#a89968", 82: "#7e9c98",
}

_NOMBRE_MAPBIOMAS = {
    1: "Bosque", 3: "Bosque", 4: "Bosque abierto", 6: "Bosque inundable",
    10: "Pastizal/herbazal", 11: "Herbazal inundable", 12: "Pastizal",
    13: "Otra form. natural", 14: "Cultivo", 15: "Pastura",
    18: "Agricultura", 21: "Mosaico de usos", 22: "Área sin vegetación",
    23: "Playa/duna", 24: "Urbano", 25: "Otra área antrópica",
    26: "Agua", 27: "No observado", 29: "Afloramiento rocoso",
    30: "Minería", 31: "Acuicultura", 33: "Río/lago", 34: "Glaciar",
    39: "Soya", 61: "Salar", 66: "Matorral", 68: "Otra área natural",
    72: "Otros cultivos", 81: "Pajonal andino", 82: "Bofedal",
}

# ESA WorldCover v200 (11 clases globales).
_ESA_CODIGOS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
_ESA_COLOR = {10: "#006400", 20: "#ffbb22", 30: "#ffff4c", 40: "#f096ff",
              50: "#fa0000", 60: "#b4b4b4", 70: "#f0f0f0", 80: "#0064c8",
              90: "#0096a0", 95: "#00cf75", 100: "#fae6a0"}
_ESA_NOMBRE = {10: "Árboles", 20: "Arbustos", 30: "Pradera", 40: "Cultivos",
               50: "Construido", 60: "Suelo desnudo", 70: "Nieve/hielo",
               80: "Agua", 90: "Humedal", 95: "Manglar", 100: "Musgo/liquen"}

# Coeficiente de escorrentía racional: (C_llano, C_empinado) por grupo de uso.
# C crece con la pendiente; el grupo se deriva de la clase MapBiomas.
_C_POR_USO = {
    "bosque":      (0.10, 0.35),
    "pasto":       (0.15, 0.45),
    "agricola":    (0.20, 0.50),
    "desnudo":     (0.45, 0.75),
    "urbano":      (0.70, 0.90),
    "agua":        (0.95, 1.00),
}
_GRUPO_USO = {
    1: "bosque", 3: "bosque", 4: "bosque", 6: "bosque", 66: "bosque", 81: "bosque",
    10: "pasto", 11: "pasto", 12: "pasto", 13: "pasto", 15: "pasto", 82: "pasto",
    14: "agricola", 18: "agricola", 21: "agricola", 39: "agricola", 72: "agricola",
    22: "desnudo", 25: "desnudo", 29: "desnudo", 30: "desnudo", 61: "desnudo", 68: "desnudo",
    24: "urbano",
    26: "agua", 31: "agua", 33: "agua", 34: "agua",
}


# ---------------------------------------------------------------------------
# 9.2 Red de drenaje
# ---------------------------------------------------------------------------
def mapa_red_drenaje_gee(lat, lon, poligono, out_path, autor: str = "") -> Optional[dict]:
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.08)
        # COP-DEM GLO-30 (Copernicus): cobertura global completa sin huecos,
        # mejor calidad que SRTM. Single-band float32 en metros sobre WGS84.
        # `select` y `rename` con lista por consistencia API (string también
        # funciona pero la lista es la firma estable documentada).
        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"]))
        hill = ee.Terrain.hillshade(dem).visualize(min=0, max=255,
                                                    palette=["#bbbbbb", "#ffffff"])
        upa = ee.Image("MERIT/Hydro/v1_0_1").select("upa")
        capilar = upa.gte(0.5).And(upa.lt(5)).selfMask().visualize(palette=["#9ed1ff"])
        secundario = upa.gte(5).And(upa.lt(50)).selfMask().visualize(palette=["#3b8bd8"])
        principal = upa.gte(50).selfMask().visualize(palette=["#0a4f9e"])
        composite = (hill.blend(capilar).blend(secundario).blend(principal)
                     .blend(_contorno_cuenca(geom)))
        # % de cada clase de cauce (sobre celdas con upa ≥ 0.5).
        cls = (upa.gte(0.5).add(upa.gte(5)).add(upa.gte(50))
               .updateMask(upa.gte(0.5)))
        frec = _frecuencia(cls, geom, 90)
        nombres = {1: "Cauce capilar (0.5–5 km²)", 2: "Cauce secundario (5–50 km²)",
                   3: "Cauce principal (≥50 km²)"}
        colores = {1: "#9ed1ff", 2: "#3b8bd8", 3: "#0a4f9e"}
        leyenda = [{"etiqueta": nombres[k], "color": colores[k],
                    "pct": frec.get(k, 0.0)} for k in (3, 2, 1) if frec.get(k, 0.0) > 0]
        path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                               titulo="9.2 Red de drenaje (MERIT Hydro)",
                               entradas_leyenda=leyenda or None)
        return {"path": path}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_red_drenaje_gee falló: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# 9.3 Uso de suelo — FROM-GLC10 (Tsinghua, Gong et al. 2019), 10 m global.
# Diez clases (10..100). Asset community-catalog sat-io (licencia abierta).
# 10 m → 9× más píxeles que MapBiomas 30 m; cobertura global (no solo
# Bolivia) y la usamos también como 4ª fuente en la triangulación de
# cobertura (concordancia_cobertura) → mejor estimación del CN.
# ---------------------------------------------------------------------------
_FROMGLC_ASSET = "projects/sat-io/open-datasets/FROM-GLC10"
_FROMGLC_NOMBRE = {
    10: "Cultivos", 20: "Bosque", 30: "Pastizal", 40: "Matorral",
    50: "Humedal", 60: "Agua", 70: "Tundra", 80: "Área construida",
    90: "Suelo desnudo", 100: "Nieve/Hielo",
}
_FROMGLC_COLOR = {
    10: "#FFC85C", 20: "#1A7A2E", 30: "#A4D65E", 40: "#C6AD8D",
    50: "#5DB8B0", 60: "#1A5BAB", 70: "#B59FCC", 80: "#ED022A",
    90: "#D9D2C5", 100: "#F2FAFF",
}
# Super-clase para la triangulación (1=agua, 2=veg densa, 3=veg rala/cultivo,
# 4=suelo/urbano), coherente con _WC_SUPER / _DW_SUPER / _ESRI_SUPER.
_FROMGLC_SUPER = {10: 3, 20: 2, 30: 3, 40: 3, 50: 2, 60: 1, 70: 3,
                  80: 4, 90: 4, 100: 4}
# FROM-GLC10 → grupo de uso para el coeficiente de escorrentía C (9.7),
# usando los mismos rangos de _C_POR_USO.
_GRUPO_USO_FROMGLC = {
    10: "agricola", 20: "bosque", 30: "pasto", 40: "pasto", 50: "pasto",
    60: "agua", 70: "pasto", 80: "urbano", 90: "desnudo", 100: "desnudo",
}


def _mapa_uso_suelo_mapbiomas(geom, bounds, bbox, out_path, autor):
    """Fallback 9.3: MapBiomas Bolivia 30 m (solo Bolivia)."""
    import ee
    wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
            .sort("year", False).first().select(0))
    clases = sorted(_PALETA_MAPBIOMAS.keys())
    paleta = [_PALETA_MAPBIOMAS[c] for c in clases]
    vis = wc.remap(clases, list(range(len(clases))), len(clases)).visualize(
        min=0, max=len(clases) - 1, palette=paleta + ["#ffffff"])
    composite = vis.blend(_contorno_cuenca(geom))
    frec = _frecuencia(wc, geom, 30)
    leyenda = _leyenda_desde_frec(frec, _NOMBRE_MAPBIOMAS, _PALETA_MAPBIOMAS)
    path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                           titulo="9.3 Uso de suelo (MapBiomas Bolivia 30 m)",
                           entradas_leyenda=leyenda or None)
    return {"path": path}


def mapa_uso_suelo_gee(lat, lon, poligono, out_path, autor: str = "") -> Optional[dict]:
    if not _intentar_inicializar() or poligono is None:
        return None
    geom = bounds = bbox = None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        # FROM-GLC10: ImageCollection global → mosaico recortado a la cuenca.
        glc = (ee.ImageCollection(_FROMGLC_ASSET).filterBounds(geom)
                  .mosaic().select([0]).clip(geom))
        clases = sorted(_FROMGLC_NOMBRE.keys())
        paleta = [_FROMGLC_COLOR[c] for c in clases]
        vis = glc.remap(clases, list(range(len(clases))), len(clases)).visualize(
            min=0, max=len(clases) - 1, palette=paleta + ["#ffffff"])
        composite = vis.blend(_contorno_cuenca(geom))
        frec = _frecuencia(glc, geom, 10)
        leyenda = _leyenda_desde_frec(frec, _FROMGLC_NOMBRE, _FROMGLC_COLOR)
        if not leyenda:
            # Sin píxeles FROM-GLC sobre la cuenca → fallback MapBiomas.
            raise ValueError("FROM-GLC10 sin cobertura sobre la cuenca")
        path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                               titulo="9.3 Uso de suelo (FROM-GLC10 10 m)",
                               entradas_leyenda=leyenda or None)
        return {"path": path}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_uso_suelo_gee (FROM-GLC10) falló: {type(e).__name__}: {e}"
             f" — fallback MapBiomas")
        try:
            if geom is None:
                geom, bounds, bbox = _geometria_y_bounds(poligono,
                                                          buffer_frac=0.05)
            return _mapa_uso_suelo_mapbiomas(geom, bounds, bbox, out_path, autor)
        except Exception as e2:  # noqa: BLE001
            _msg(f"fallback MapBiomas también falló: {type(e2).__name__}: {e2}")
            return None


# ---------------------------------------------------------------------------
# 9.4 Cobertura del suelo — ESRI Global LULC 10 m Time Series
# (Impact Observatory / ESRI / Microsoft). Clases NO consecutivas:
# 1,2,4,5,7,8,9,10,11 (faltan 3 y 6). Paleta oficial Impact Observatory.
# ---------------------------------------------------------------------------
_ESRI_ASSET = "projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS"
_ESRI_NOMBRE = {
    1: "Agua", 2: "Árboles", 4: "Vegetación inundable", 5: "Cultivos",
    7: "Área construida", 8: "Suelo desnudo", 9: "Nieve/Hielo",
    10: "Nubes", 11: "Pastizal/Matorral",
}
_ESRI_COLOR = {
    1: "#1A5BAB", 2: "#358221", 4: "#87D19E", 5: "#FFDB5C",
    7: "#ED022A", 8: "#EDE9E4", 9: "#F2FAFF", 10: "#C8C8C8",
    11: "#C6AD8D",
}
# Paleta para visualize() min=1..max=11 (índices 3 y 6 sin uso → gris).
_ESRI_PALETA = ["1A5BAB", "358221", "999999", "87D19E", "FFDB5C",
                "999999", "ED022A", "EDE9E4", "F2FAFF", "C8C8C8", "C6AD8D"]


# Triangulación de cobertura: reclasificación a 4 super-clases comunes
# (1=agua, 2=veg densa/árboles, 3=veg rala/pasto/cultivo, 4=suelo/urbano)
# para medir concordancia entre fuentes independientes → incertidumbre real
# del CN. Donde coinciden, el CN es robusto; donde divergen, se reporta.
_SUPER = {1: "agua", 2: "veg. densa", 3: "veg. rala/cultivo", 4: "suelo/urbano"}
_ESRI_SUPER = {1: 1, 2: 2, 4: 2, 5: 3, 7: 4, 8: 4, 9: 4, 10: 4, 11: 3}
_WC_SUPER = {10: 2, 20: 3, 30: 3, 40: 3, 50: 4, 60: 4, 70: 4, 80: 1,
             90: 2, 95: 2, 100: 3}
_DW_SUPER = {0: 1, 1: 2, 2: 3, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4, 8: 4}


def _clase_dominante(img_super, geom):
    """Super-clase (1-4) dominante de una imagen reclasificada, o None."""
    import ee
    try:
        h = (img_super.rename("s").reduceRegion(
            ee.Reducer.frequencyHistogram(), geom, scale=30,
            maxPixels=1e9, bestEffort=True).getInfo() or {}).get("s") or {}
        if not h:
            return None
        return int(float(max(h.items(), key=lambda kv: float(kv[1]))[0]))
    except Exception:  # noqa: BLE001
        return None


def concordancia_cobertura(geom) -> dict | None:
    """Compara la super-clase dominante de ESRI, WorldCover, Dynamic World y
    FROM-GLC10.

    Devuelve {fuentes: {...}, concordancia: alta/media/baja, mensaje} o None.
    Cuatro fuentes independientes: donde coinciden el CN es robusto.
    """
    try:
        import ee
        dom = {}
        # ESRI (último año)
        try:
            esri = (ee.ImageCollection(_ESRI_ASSET).filterBounds(geom)
                       .sort("system:time_start", False).first()
                       .select([0]).clip(geom))
            esri_s = esri.remap(list(_ESRI_SUPER), list(_ESRI_SUPER.values()), 0)
            dom["ESRI"] = _clase_dominante(esri_s, geom)
        except Exception:  # noqa: BLE001
            dom["ESRI"] = None
        # FROM-GLC10 (10 m, Tsinghua)
        try:
            glc = (ee.ImageCollection(_FROMGLC_ASSET).filterBounds(geom)
                      .mosaic().select([0]).clip(geom))
            glc_s = glc.remap(list(_FROMGLC_SUPER), list(_FROMGLC_SUPER.values()), 0)
            dom["FROM-GLC10"] = _clase_dominante(glc_s, geom)
        except Exception:  # noqa: BLE001
            dom["FROM-GLC10"] = None
        # ESA WorldCover
        try:
            wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map").clip(geom)
            wc_s = wc.remap(list(_WC_SUPER), list(_WC_SUPER.values()), 0)
            dom["WorldCover"] = _clase_dominante(wc_s, geom)
        except Exception:  # noqa: BLE001
            dom["WorldCover"] = None
        # Dynamic World (año reciente, moda de label)
        try:
            dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(geom)
                     .filterDate("2023-01-01", "2024-12-31")
                     .select("label").mode().clip(geom))
            dw_s = dw.remap(list(_DW_SUPER), list(_DW_SUPER.values()), 0)
            dom["DynamicWorld"] = _clase_dominante(dw_s, geom)
        except Exception:  # noqa: BLE001
            dom["DynamicWorld"] = None

        vals = [v for v in dom.values() if v]
        if len(vals) < 2:
            return None
        n_coinc = max(vals.count(v) for v in set(vals))
        if n_coinc == len(vals):
            conc, msg = "alta", ("las fuentes de cobertura coinciden → CN "
                                   "robusto")
        elif n_coinc >= 2:
            conc, msg = "media", ("mayoría de fuentes coinciden; revisar la "
                                    "divergente")
        else:
            conc, msg = "baja", ("las fuentes divergen → incertidumbre alta "
                                   "en el CN, reportar y verificar en campo")
        return {
            "fuentes": {k: _SUPER.get(v, "—") for k, v in dom.items()},
            "concordancia": conc,
            "mensaje": (f"Triangulación de cobertura ({len(vals)} fuentes): "
                          f"concordancia {conc.upper()} — {msg}."),
        }
    except Exception:  # noqa: BLE001
        return None


def mapa_cobertura_gee(lat, lon, poligono, out_path, autor: str = "") -> Optional[dict]:
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        # ESRI Global LULC 10 m Time Series: una imagen por año. Tomamos el
        # año MÁS RECIENTE disponible sobre la cuenca y lo mosaicamos.
        col = ee.ImageCollection(_ESRI_ASSET).filterBounds(geom)
        ultimo = ee.Image(col.sort("system:time_start", False).first())
        anio = ee.Date(ultimo.get("system:time_start")).get("year")
        lulc = (col.filter(ee.Filter.calendarRange(anio, anio, "year"))
                   .mosaic().select([0]).clip(geom))
        try:
            anio_int = int(anio.getInfo())
        except Exception:  # noqa: BLE001
            anio_int = None
        vis = lulc.visualize(min=1, max=11, palette=_ESRI_PALETA)
        composite = vis.blend(_contorno_cuenca(geom))
        frec = _frecuencia(lulc, geom, 10)
        leyenda = _leyenda_desde_frec(frec, _ESRI_NOMBRE, _ESRI_COLOR)
        titulo = ("9.4 Cobertura del suelo (ESRI Global LULC 10 m"
                    + (f", {anio_int}" if anio_int else "") + ")")
        # Triangulación con WorldCover + Dynamic World (incertidumbre del CN).
        conc = concordancia_cobertura(geom)
        resumen = (conc["mensaje"] if conc else "")
        path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                               titulo=titulo,
                               entradas_leyenda=leyenda or None,
                               resumen=resumen)
        return {"path": path, "concordancia_cobertura": conc}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_cobertura_gee (ESRI LULC) falló: {type(e).__name__}: {e}")
        # Fallback a ESA WorldCover si ESRI no responde
        try:
            import ee
            geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
            wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
            vis = wc.visualize(min=10, max=100,
                               palette=[_ESA_COLOR[c].lstrip("#") for c in _ESA_CODIGOS])
            composite = vis.blend(_contorno_cuenca(geom))
            frec = _frecuencia(wc, geom, 10)
            leyenda = _leyenda_desde_frec(frec, _ESA_NOMBRE, _ESA_COLOR)
            path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                                   titulo="9.4 Cobertura del suelo (ESA WorldCover 10 m)",
                                   entradas_leyenda=leyenda or None)
            return {"path": path}
        except Exception as e2:  # noqa: BLE001
            _msg(f"fallback ESA WorldCover también falló: {type(e2).__name__}: {e2}")
            return None


# ---------------------------------------------------------------------------
# 9.5 Número de curva CN (SCS)
# ---------------------------------------------------------------------------
_CN_BORDES = [0, 60, 70, 78, 85, 92, 101]
_CN_NOMBRE = {0: "CN < 60 (alta infiltr.)", 1: "CN 60–70", 2: "CN 70–78",
              3: "CN 78–85", 4: "CN 85–92", 5: "CN ≥ 92 (impermeable)"}
_CN_COLOR = {0: "#1a9850", 1: "#a6d96a", 2: "#d9ef8b", 3: "#fee08b",
             4: "#f46d43", 5: "#a50026"}


# Datasets v2.0 (community catalog sat-io, licencia abierta comercial-OK):
_GCN250_AVG = "projects/sat-io/open-datasets/GCN250/GCN250Average"
_GCN250_DRY = "projects/sat-io/open-datasets/GCN250/GCN250Dry"
_GCN250_WET = "projects/sat-io/open-datasets/GCN250/GCN250Wet"
_HYSOGS = "projects/sat-io/open-datasets/HYSOGs250m"
# HYSOGs: 1=A 2=B 3=C 4=D 11=A/D 12=B/D 13=C/D 14=D (dual drenado/no).
_HSG_NOMBRE = {1: "A (alta infiltr.)", 2: "B", 3: "C", 4: "D (baja infiltr.)",
               11: "A/D", 12: "B/D", 13: "C/D", 14: "D"}


def _grupo_hsg_dominante(geom):
    """Grupo hidrológico dominante (HYSOGs250m) sobre la cuenca, o None."""
    try:
        import ee
        hsg = ee.Image(_HYSOGS).select([0])
        hist = (hsg.rename("g").reduceRegion(
            ee.Reducer.frequencyHistogram(), geom, scale=250,
            maxPixels=1e9, bestEffort=True).getInfo() or {}).get("g") or {}
        if not hist:
            return None
        dom = max(hist.items(), key=lambda kv: float(kv[1]))[0]
        return int(float(dom))
    except Exception:  # noqa: BLE001
        return None


def mapa_cn_gee(lat, lon, poligono, out_path, autor: str = "") -> Optional[dict]:
    if not _intentar_inicializar() or poligono is None:
        return None
    import ee
    geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
    # ── CN v2.0: GCN250 (Jaafar et al. 2019, revisado por pares) que combina
    # cobertura × grupo hidrológico REAL (de HYSOGs250m) + condición de
    # humedad. Reemplaza el supuesto «grupo B» del método anterior. Reporta
    # también el rango seco/medio/húmedo (AMC I/II/III) y el HSG dominante.
    try:
        cn_avg = ee.Image(_GCN250_AVG).select([0]).clip(geom).toFloat()
        cn_dry = ee.Image(_GCN250_DRY).select([0]).clip(geom).toFloat()
        cn_wet = ee.Image(_GCN250_WET).select([0]).clip(geom).toFloat()
        vis = cn_avg.visualize(min=55, max=100, palette=[
            "1a9850", "66bd63", "a6d96a", "d9ef8b", "ffffbf",
            "fee08b", "fdae61", "f46d43", "d73027", "a50026"])
        composite = vis.blend(_contorno_cuenca(geom))

        def _media(img):
            d = img.reduceRegion(ee.Reducer.mean(), geom, scale=250,
                                   maxPixels=1e9, bestEffort=True).getInfo()
            return float(list((d or {}).values())[0]) if d else None
        cn_pond = _media(cn_avg)
        cn_seco = _media(cn_dry)
        cn_humedo = _media(cn_wet)
        if cn_pond is None or cn_pond <= 0:
            raise ValueError("GCN250 sin datos sobre la cuenca")
        hsg_dom = _grupo_hsg_dominante(geom)
        idx = _indice_por_bordes(cn_avg, _CN_BORDES)
        frec = _frecuencia(idx, geom, 250)
        leyenda = [{"etiqueta": _CN_NOMBRE[k], "color": _CN_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(6) if frec.get(k, 0.0) >= 0.5]
        resumen = (f"CN ponderado (AMC II) = {cn_pond:.0f}  ·  "
                     f"rango AMC I–III: {cn_seco:.0f}–{cn_humedo:.0f}"
                     + (f"  ·  HSG dominante: {_HSG_NOMBRE.get(hsg_dom, '?')}"
                        if hsg_dom else ""))
        path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                               titulo="9.5 Número de curva CN (GCN250 · HSG real)",
                               entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "cn_ponderado": cn_pond,
                "cn_seco": cn_seco, "cn_humedo": cn_humedo,
                "hsg_dominante": _HSG_NOMBRE.get(hsg_dom) if hsg_dom else None,
                "fuente_cn": "GCN250 (cobertura × HSG real HYSOGs250m)"}
    except Exception as e:  # noqa: BLE001
        _msg(f"CN GCN250 falló ({type(e).__name__}: {e}), cae a MapBiomas×CN_B")
        # Fallback: MapBiomas remapeado a CN asumiendo grupo B (método previo).
        try:
            wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
                    .sort("year", False).first().select(0))
            clases = sorted(_CN_POR_COBERTURA.keys())
            valores_cn = [int(_CN_POR_COBERTURA[c]) for c in clases]
            cn_img = wc.remap(clases, valores_cn, 75).toFloat()
            vis = cn_img.visualize(min=55, max=100, palette=[
                "1a9850", "66bd63", "a6d96a", "d9ef8b", "ffffbf",
                "fee08b", "fdae61", "f46d43", "d73027", "a50026"])
            composite = vis.blend(_contorno_cuenca(geom))
            cn_med = cn_img.reduceRegion(ee.Reducer.mean(), geom, scale=30,
                                         maxPixels=1e9, bestEffort=True).getInfo()
            cn_pond = float(list((cn_med or {}).values())[0]) if cn_med else None
            idx = _indice_por_bordes(cn_img, _CN_BORDES)
            frec = _frecuencia(idx, geom, 30)
            leyenda = [{"etiqueta": _CN_NOMBRE[k], "color": _CN_COLOR[k],
                        "pct": frec.get(k, 0.0)} for k in range(6) if frec.get(k, 0.0) >= 0.5]
            resumen = (f"CN ponderado = {cn_pond:.0f} (MapBiomas, grupo B "
                         f"asumido — GCN250 no respondió)" if cn_pond else "")
            path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                                   titulo="9.5 Número de curva CN (SCS, MapBiomas)",
                                   entradas_leyenda=leyenda or None, resumen=resumen)
            return {"path": path, "cn_ponderado": cn_pond,
                    "fuente_cn": "MapBiomas × CN(grupo B asumido)"}
        except Exception as e2:  # noqa: BLE001
            _msg(f"fallback CN MapBiomas también falló: {type(e2).__name__}: {e2}")
            return None


# ---------------------------------------------------------------------------
# 9.8 Coeficiente de rugosidad de Manning (n) — espacial por cobertura MapBiomas
# ---------------------------------------------------------------------------
# Clases de n para la leyenda (rangos típicos de Chow, 1959).
_N_BORDES = [0.0, 0.030, 0.040, 0.055, 0.080, 0.200]
_N_NOMBRE = {0: "n ≤ 0.030 (cauce liso / urbano)",
             1: "0.030–0.040 (cauce natural / cultivo)",
             2: "0.040–0.055 (pastos / matorral)",
             3: "0.055–0.080 (vegetación densa)",
             4: "n > 0.080 (bosque / planicie arbolada)"}
_N_COLOR = {0: "#2c7fb8", 1: "#7fcdbb", 2: "#c7e9b4", 3: "#fdae61", 4: "#d7301f"}


def mapa_manning_gee(lat, lon, poligono, out_path, autor: str = "") -> Optional[dict]:
    """Mapa 9.8 del coeficiente de Manning n: remapea la cobertura MapBiomas a
    n (tablas de Chow) y lo colorea sobre la cuenca. Devuelve dict con path y n
    ponderado, o None si GEE no responde."""
    if not _intentar_inicializar() or poligono is None:
        return None
    import ee
    geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
    try:
        wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
                .sort("year", False).first().select(0))
        clases = sorted(_N_MANNING_POR_COBERTURA.keys())
        # n×1000 como entero para el remap (0.035 → 35).
        valores_n = [int(round(_N_MANNING_POR_COBERTURA[c] * 1000)) for c in clases]
        n_img = wc.remap(clases, valores_n, 35).toFloat()          # n×1000
        vis = n_img.visualize(min=15, max=120, palette=[
            "2c7fb8", "41b6c4", "7fcdbb", "c7e9b4", "ffffcc",
            "fed976", "fdae61", "f46d43", "d7301f", "7f0000"])
        composite = vis.blend(_contorno_cuenca(geom))
        d = n_img.reduceRegion(ee.Reducer.mean(), geom, scale=30,
                               maxPixels=1e9, bestEffort=True).getInfo()
        n_pond = (float(list(d.values())[0]) / 1000.0) if d else None
        # Leyenda por clases de n (n×1000 → bordes ×1000).
        bordes_ke = [b * 1000 for b in _N_BORDES]
        idx = _indice_por_bordes(n_img, bordes_ke)
        frec = _frecuencia(idx, geom, 30)
        leyenda = [{"etiqueta": _N_NOMBRE[k], "color": _N_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(5)
                   if frec.get(k, 0.0) >= 0.5]
        resumen = (f"n de Manning ponderado por área = {n_pond:.3f}"
                   if n_pond else "")
        path = _thumb_decorado(
            composite, bounds, bbox, out_path, autor,
            titulo="9.8 Coeficiente de rugosidad de Manning (n · MapBiomas)",
            entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "n_ponderado": n_pond,
                "fuente_n": "MapBiomas × n de Manning (Chow, 1959)"}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa Manning 9.8 falló: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# 9.9 Mapa de riesgo (susceptibilidad) de inundación — HAND + agua permanente
# ---------------------------------------------------------------------------
# Índice HAND (Height Above Nearest Drainage, Rennó et al. 2008; Nobre et al.
# 2011): altura vertical de cada píxel sobre el cauce más cercano al que drena.
# Es el descriptor topográfico estándar de susceptibilidad a la inundación —
# cuanto más bajo el HAND, más cerca del nivel del cauce y más propenso a
# anegarse. Se toma de la banda `hnd` de MERIT Hydro (Yamazaki et al. 2019),
# el mismo dataset con que se deriva la red de drenaje (mapa 9.2), y se
# refuerza con la ocurrencia de agua superficial permanente del JRC Global
# Surface Water (Pekel et al. 2016): donde el agua está presente ≥50 % del
# tiempo, la susceptibilidad es máxima por definición.
_INUND_NOMBRE = {
    5: "Muy alta — HAND ≤ 2 m / agua permanente",
    4: "Alta — HAND 2–5 m",
    3: "Media — HAND 5–15 m",
    2: "Baja — HAND 15–30 m",
    1: "Muy baja — HAND > 30 m",
}
_INUND_COLOR = {1: "#deebf7", 2: "#9ecae1", 3: "#6baed6",
                4: "#3182bd", 5: "#08519c"}
_INUND_PALETA = ["deebf7", "9ecae1", "6baed6", "3182bd", "08519c"]


def mapa_riesgo_inundacion_gee(lat, lon, poligono, out_path,
                                autor: str = "") -> Optional[dict]:
    """Mapa 9.9 de susceptibilidad a la inundación.

    Clasifica 1–5 el índice HAND (banda `hnd` de MERIT Hydro): HAND ≤ 2 m →
    muy alta, 2–5 m → alta, 5–15 m → media, 15–30 m → baja, > 30 m → muy baja.
    Los píxeles con agua superficial permanente (JRC GSW occurrence ≥ 50 %) se
    fuerzan a la clase máxima. Devuelve {path, area_alta_pct, hand_medio} o
    None si GEE no responde.
    """
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        # HAND en metros (MERIT Hydro 90 m). unmask(0) evita huecos en píxeles
        # de cauce donde HAND = 0 podría venir enmascarado.
        hnd = (ee.Image("MERIT/Hydro/v1_0_1").select(["hnd"])
                  .unmask(0).clip(geom))
        # Agua superficial permanente/frecuente (occurrence 0–100 %).
        occ = (ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select(["occurrence"])
                  .unmask(0).clip(geom))
        clase = hnd.expression(
            "(h<=2)?5:(h<=5)?4:(h<=15)?3:(h<=30)?2:1", {"h": hnd})
        clase = clase.where(occ.gte(50), 5).toInt().rename("c")
        vis = clase.visualize(min=1, max=5, palette=_INUND_PALETA)
        composite = vis.blend(_contorno_cuenca(geom))
        # Frecuencia por clase (susceptibilidad) sobre la cuenca.
        frec = _frecuencia(clase, geom, 90)
        leyenda = [{"etiqueta": _INUND_NOMBRE[k], "color": _INUND_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(5, 0, -1)
                   if frec.get(k, 0.0) >= 0.5]
        area_alta = frec.get(4, 0.0) + frec.get(5, 0.0)
        # HAND medio de la cuenca (indicador de encajamiento del valle).
        hand_medio = None
        try:
            d = hnd.reduceRegion(ee.Reducer.mean(), geom, scale=90,
                                 maxPixels=1e9, bestEffort=True).getInfo()
            hand_medio = float(list((d or {}).values())[0]) if d else None
        except Exception:  # noqa: BLE001
            pass
        resumen = (f"Área con susceptibilidad alta/muy alta = {area_alta:.1f} % "
                     f"de la cuenca"
                     + (f"  ·  HAND medio = {hand_medio:.1f} m" if hand_medio
                        else ""))
        path = _thumb_decorado(
            composite, bounds, bbox, out_path, autor,
            titulo=("9.9 Riesgo de inundación (HAND · MERIT Hydro + "
                       "agua permanente JRC)"),
            entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "area_alta_pct": area_alta,
                "hand_medio": hand_medio,
                "fuente_inundacion": ("HAND MERIT Hydro (Yamazaki 2019) + "
                                        "JRC GSW occurrence (Pekel 2016)")}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa riesgo inundación 9.9 falló: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# 9.6 Pendientes (clases geotécnicas, %)
# ---------------------------------------------------------------------------
_SLOPE_BORDES = [0, 3, 8, 15, 30, 50, 1000]
_SLOPE_NOMBRE = {0: "0–3 % (plano)", 1: "3–8 % (suave)", 2: "8–15 % (moderado)",
                 3: "15–30 % (fuerte)", 4: "30–50 % (escarpado)", 5: "> 50 % (muy escarpado)"}
_SLOPE_COLOR = {0: "#edf8e9", 1: "#bae4b3", 2: "#74c476", 3: "#fdae61",
                4: "#f46d43", 5: "#a50026"}


def mapa_pendientes_gee(lat, lon, poligono, out_path, autor: str = "") -> Optional[dict]:
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.08)
        # COP-DEM GLO-30 (Copernicus): cobertura global completa sin huecos,
        # mejor calidad que SRTM. Single-band float32 en metros sobre WGS84.
        # `select` y `rename` con lista por consistencia API (string también
        # funciona pero la lista es la firma estable documentada).
        from .gee import epsg_utm
        crs_utm = epsg_utm(lat, lon)
        # CRÍTICO: reproyectar el DEM a UTM MÉTRICA antes de Terrain.slope.
        # Sobre EPSG:4326 (grados) la pendiente sale inflada porque mezcla
        # grados (horizontal) con metros (vertical) — es lo que daba
        # pendientes irreales (44-60 %). En UTM ambos ejes están en metros.
        # CLIP a la cuenca (buffer del bounds): acota la reproyección UTM al
        # área del proyecto. Sin esto, en cuencas grandes GEE materializa el
        # DEM reproyectado sobre un tile enorme → timeout/límite de memoria en
        # el thumbnail o el reduceRegion, y el mapa 9.6 caía a NO DISPONIBLE.
        escala = _escala_adaptativa(bbox)
        escala_stats = max(30.0, escala)
        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"])
                  .reproject(crs=crs_utm, scale=escala).clip(geom))
        slope_deg = ee.Terrain.slope(dem)            # algoritmo de Horn (grados)
        slope_pct = (slope_deg.multiply(math.pi / 180).tan().multiply(100)
                       .clip(geom))
        vis = slope_pct.visualize(min=0, max=60, palette=[
            "edf8e9", "bae4b3", "74c476", "31a354", "fdae61",
            "f46d43", "d73027", "a50026"])
        composite = vis.blend(_contorno_cuenca(geom))
        # Estadísticos (media % y frecuencia por clase): OPCIONALES. Si el
        # reduceRegion falla (cuenca grande), el mapa igual se genera; solo
        # queda sin leyenda de % y sin la media. tileScale evita saturar memoria.
        s_pond = None
        leyenda = None
        try:
            idx = _indice_por_bordes(slope_pct, _SLOPE_BORDES)
            frec = (idx.rename("s").reduceRegion(
                ee.Reducer.frequencyHistogram(), geom, scale=escala_stats,
                maxPixels=1e9, bestEffort=True, tileScale=4).getInfo() or {}
            ).get("s") or {}
            tot = sum(float(v) for v in frec.values()) or 1.0
            frec = {int(float(k)): float(v) / tot * 100.0 for k, v in frec.items()}
            s_med = slope_pct.reduceRegion(
                ee.Reducer.mean(), geom, scale=escala_stats, maxPixels=1e9,
                bestEffort=True, tileScale=4).getInfo()
            s_pond = float(list((s_med or {}).values())[0]) if s_med else None
            leyenda = [{"etiqueta": _SLOPE_NOMBRE[k], "color": _SLOPE_COLOR[k],
                        "pct": frec.get(k, 0.0)} for k in range(6)
                       if frec.get(k, 0.0) >= 0.5]
        except Exception as e:  # noqa: BLE001
            _msg(f"9.6 estadísticos fallaron (mapa igual se genera): "
                 f"{type(e).__name__}: {e}")
        resumen = (f"Pendiente media = {s_pond:.1f} %  "
                     f"(COP-DEM GLO-30, Terrain.slope en UTM)"
                     if s_pond else "")
        path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                               titulo=("9.6 Pendientes del terreno "
                                          "(COP-DEM GLO-30, algoritmo de Horn)"),
                               entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "pendiente_media_pct": s_pond}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_pendientes_gee falló: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# 9.7 Coeficiente de escorrentía C (racional: uso de suelo × pendiente)
# ---------------------------------------------------------------------------
_C_BORDES = [0.0, 0.20, 0.35, 0.50, 0.65, 0.80, 1.01]
_C_NOMBRE = {0: "C < 0.20 (muy bajo)", 1: "C 0.20–0.35 (bajo)",
             2: "C 0.35–0.50 (medio)", 3: "C 0.50–0.65 (alto)",
             4: "C 0.65–0.80 (muy alto)", 5: "C ≥ 0.80 (extremo)"}
_C_COLOR = {0: "#2c7bb6", 1: "#abd9e9", 2: "#ffffbf", 3: "#fdae61",
            4: "#f46d43", 5: "#d7191c"}


def mapa_coef_escorrentia_gee(lat, lon, poligono, out_path,
                               autor: str = "") -> Optional[dict]:
    """C por píxel = Cmin(uso) + (Cmax-Cmin)·factor_pendiente. Método racional."""
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        # Uso de suelo: FROM-GLC10 10 m (preferente, global) → MapBiomas 30 m
        # (fallback si el asset sat-io no respondiera).
        try:
            wc = (ee.ImageCollection(_FROMGLC_ASSET).filterBounds(geom)
                    .mosaic().select([0]).clip(geom))
            grupo = _GRUPO_USO_FROMGLC
            fuente_uso = "FROM-GLC10 10 m"
        except Exception:  # noqa: BLE001
            wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
                    .sort("year", False).first().select(0))
            grupo = _GRUPO_USO
            fuente_uso = "MapBiomas 30 m"
        clases = sorted(grupo.keys())
        cmin = [int(round(_C_POR_USO[grupo[c]][0] * 1000)) for c in clases]
        cmax = [int(round(_C_POR_USO[grupo[c]][1] * 1000)) for c in clases]
        cmin_img = wc.remap(clases, cmin, 200).toFloat().divide(1000)
        cmax_img = wc.remap(clases, cmax, 500).toFloat().divide(1000)
        # COP-DEM GLO-30 (Copernicus): cobertura global completa sin huecos,
        # mejor calidad que SRTM. Single-band float32 en metros sobre WGS84.
        # `select` y `rename` con lista por consistencia API (string también
        # funciona pero la lista es la firma estable documentada).
        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"]))
        slope_pct = ee.Terrain.slope(dem).multiply(math.pi / 180).tan().multiply(100)
        # factor pendiente 0..1 saturando en 30 %.
        fpend = slope_pct.divide(30).clamp(0, 1)
        c_img = cmin_img.add(cmax_img.subtract(cmin_img).multiply(fpend)).clamp(0, 1)
        vis = c_img.visualize(min=0.1, max=0.9, palette=[
            "2c7bb6", "abd9e9", "ffffbf", "fdae61", "f46d43", "d7191c"])
        composite = vis.blend(_contorno_cuenca(geom))
        c_med = c_img.reduceRegion(ee.Reducer.mean(), geom, scale=30,
                                   maxPixels=1e9, bestEffort=True).getInfo()
        c_pond = float(list((c_med or {}).values())[0]) if c_med else None
        idx = _indice_por_bordes(c_img, _C_BORDES)
        frec = _frecuencia(idx, geom, 30)
        leyenda = [{"etiqueta": _C_NOMBRE[k], "color": _C_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(6) if frec.get(k, 0.0) >= 0.5]
        resumen = f"C ponderado = {c_pond:.2f}" if c_pond else ""
        path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                               titulo=("9.7 Coeficiente de escorrentía C "
                                       f"(racional · {fuente_uso})"),
                               entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "c_ponderado": c_pond}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_coef_escorrentia_gee falló: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# 14.x Mapa de vulnerabilidad y riesgo hidroclimático (Manual ABC 480/21)
# R = V × A. La VULNERABILIDAD (V) se construye con Álgebra de Mapas sobre las
# 7 variables del Manual reclasificadas 1–5 y sumadas con sus pesos (Tabla 5.1).
# Las variables espaciales se derivan de nuestros datasets GEE; clima, capa de
# rodadura y fisiografía se toman del tramo RVF (constantes por tramo, como en
# el Manual). El color es el código de riesgo de la Tabla 6.2 (verde→rojo).
# ---------------------------------------------------------------------------
_RIESGO_PALETA = ["1a9850", "a6d96a", "fee08b", "fdae61", "d73027"]
_RIESGO_NOMBRE = {1: "Mínimo", 2: "Leve", 3: "Medio", 4: "Apreciable",
                  5: "Considerable"}
_RIESGO_COLOR = {1: "#1a9850", 2: "#a6d96a", 3: "#fee08b", 4: "#fdae61",
                 5: "#d73027"}


def mapa_riesgo_abc_gee(lat, lon, poligono, fis, clima, rod,
                        out_path, autor: str = "") -> Optional[dict]:
    """Mapa de vulnerabilidad/riesgo hidroclimático (metodología ABC) vía GEE.

    Reclasifica 1–5 las 7 variables del Manual y las combina con pesos:
      V = 0.10·Fisiografía + 0.10·Clima + 0.20·Pendiente + 0.20·Conservación
          + 0.20·Inundación + 0.10·CN + 0.10·Rodadura
    Variables espaciales (GEE): Pendiente (COP-DEM GLO-30 en UTM), Conservación
    (Global Human Modification), Inundación (JRC Global Surface Water) y CN
    (GCN250). Clima, Rodadura y Fisiografía se toman del tramo RVF (constantes
    por tramo, como en el Manual). Devuelve {path, v_media} o None.
    """
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        from .gee import epsg_utm
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        crs_utm = epsg_utm(lat, lon)
        # Escala adaptativa: en cuencas grandes reproyectar a 30 m revienta el
        # thumbnail (era la causa de que el mapa 14.6 no se generara). Se ajusta
        # al tamaño de la cuenca, con piso en 30 m para las pequeñas.
        escala = _escala_adaptativa(bbox)
        escala_stats = max(90.0, escala)

        # --- Variables espaciales reclasificadas 1–5 (Álgebra de Mapas) ---
        # Pendiente (%) sobre COP-DEM reproyectado a UTM (Horn). Clip a la cuenca.
        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30").select(["DEM"])
                  .mosaic().reproject(crs=crs_utm, scale=escala).clip(geom))
        pend_pct = (ee.Terrain.slope(dem).multiply(math.pi / 180).tan()
                       .multiply(100))
        pend = pend_pct.expression(
            "(b<1)?1:(b<8)?2:(b<15)?3:(b<45)?4:5", {"b": pend_pct})
        # Aptitud a la escorrentía — Número de Curva (GCN250 Average).
        cn = ee.Image(_GCN250_AVG).select([0]).clip(geom)
        cn_r = cn.expression("(b<50)?1:(b<60)?2:(b<70)?3:(b<80)?4:5", {"b": cn})
        # Conservación ambiental (intervención antrópica) — Global Human
        # Modification (Kennedy et al. 2019), gHM 0–1.
        ghm = (ee.ImageCollection("CSP/HM/GlobalHumanModification").first()
                  .select(["gHM"]).clip(geom))
        cons = ghm.expression("(b<0.1)?2:(b<0.2)?3:(b<0.4)?4:5", {"b": ghm})
        # Potencial de inundación — JRC Global Surface Water occurrence (0–100).
        occ = (ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select(["occurrence"])
                  .unmask(0).clip(geom))
        inund = occ.expression(
            "(b>=50)?5:(b>=20)?4:(b>=5)?3:(b>=1)?2:1", {"b": occ})
        # Constantes por tramo (Manual): fisiografía, clima, rodadura (1–5).
        c_fis = ee.Image.constant(float(fis))
        c_cli = ee.Image.constant(float(clima))
        c_rod = ee.Image.constant(float(rod))

        # --- Vulnerabilidad total parametrizada (suma ponderada) ---
        V = (c_fis.multiply(0.10).add(c_cli.multiply(0.10))
             .add(pend.multiply(0.20)).add(cons.multiply(0.20))
             .add(inund.multiply(0.20)).add(cn_r.multiply(0.10))
             .add(c_rod.multiply(0.10))).clip(geom).rename("V")

        vis = V.visualize(min=1, max=5, palette=_RIESGO_PALETA)
        composite = vis.blend(_contorno_cuenca(geom))

        # Estadísticos opcionales (media y % por clase de riesgo).
        v_media = None
        leyenda = None
        try:
            v_cls = V.round().clamp(1, 5).toInt()
            hist = (v_cls.rename("s").reduceRegion(
                ee.Reducer.frequencyHistogram(), geom, scale=escala_stats,
                maxPixels=1e9, bestEffort=True, tileScale=4).getInfo() or {}
            ).get("s") or {}
            tot = sum(float(x) for x in hist.values()) or 1.0
            frec = {int(float(k)): float(v) / tot * 100.0 for k, v in hist.items()}
            vm = V.reduceRegion(ee.Reducer.mean(), geom, scale=escala_stats,
                                maxPixels=1e9, bestEffort=True,
                                tileScale=4).getInfo()
            v_media = float(list((vm or {}).values())[0]) if vm else None
            leyenda = [{"etiqueta": f"{k} — {_RIESGO_NOMBRE[k]}",
                        "color": _RIESGO_COLOR[k], "pct": frec.get(k, 0.0)}
                       for k in range(1, 6) if frec.get(k, 0.0) >= 0.5]
        except Exception as e:  # noqa: BLE001
            _msg(f"14.x riesgo ABC estadísticos fallaron: {type(e).__name__}: {e}")
        resumen = (f"Vulnerabilidad media V = {v_media:.2f} / 5  (R = V × A; "
                     f"riesgo por escenario en la Sección 14.3)"
                     if v_media else "R = V × A (ver Sección 14.3)")
        path = _thumb_decorado(composite, bounds, bbox, out_path, autor,
                               titulo=("14 · Vulnerabilidad y riesgo "
                                          "hidroclimático (Manual ABC)"),
                               entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "v_media": v_media}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_riesgo_abc_gee falló: {type(e).__name__}: {e}")
        return None


def generar_todos_los_mapas_gee(lat: float, lon: float, poligono,
                                  out_dir: Path, autor: str = "") -> dict:
    """Genera los 6 mapas temáticos reales (9.2-9.7) en paralelo.

    Devuelve {clave: path, ..., "_stats": {cn_ponderado, c_ponderado}}.
    Los mapas que fallan individualmente se omiten (el llamador los rellena
    con esquemáticos).
    """
    if poligono is None:
        return {}
    out_dir = Path(out_dir)
    # 9.2 — red de drenaje: PRIMERO intentamos derivarla del COP-DEM
    # 12.5 m con algoritmo D8 + flow-accumulation (NumPy puro, sin GEE).
    # 9.6 — pendientes: IDEM, calculadas en Python sobre COP-DEM 12.5 m
    # con np.gradient (vs Terrain.slope server-side sobre 30 m nativo).
    # Ambos garantizan formato cartográfico estándar HYDROFRA + valores
    # consistentes con el mismo DEM que alimenta la morfometría. Si
    # alguno falla, fallback transparente al GEE legacy.
    salida_predef: dict = {}
    stats_dem: dict = {}
    try:
        from .red_drenaje_dem import generar_mapa_9_2
        r92 = generar_mapa_9_2(poligono, out_dir / "mapa_02_drenaje_dem.png",
                                 autor=autor, res_target_m=12.5)
        if r92 is not None and r92.get("path"):
            salida_predef["mapa_red_drenaje"] = r92["path"]
            _msg(f"9.2 vía D8 sobre COP-DEM: cap={r92['n_pixels_capilar']} "
                   f"px, sec={r92['n_pixels_secundario']} px, "
                   f"pri={r92['n_pixels_principal']} px, "
                   f"long≈{r92['longitud_total_aprox_km']} km")
    except Exception as e:  # noqa: BLE001
        _msg(f"9.2 vía D8 falló, cae a MERIT GEE: {type(e).__name__}: {e}")
    # 9.6 — pendientes: el cálculo Python (np.gradient sobre el DEM
    # descargado) daba valores inflados por ruido de remuestreo. Usamos
    # ee.Terrain.slope (algoritmo de Horn) sobre COP-DEM reproyectado a
    # UTM — método SIG estándar y robusto. mapa_pendientes_gee entra al
    # pool más abajo (no acá), pero su resultado incluye
    # pendiente_media_pct que recogemos del pool para la morfología.
    candidatos = {
        # Solo metemos al pool los que no quedaron predefinidos arriba.
        **({} if "mapa_red_drenaje" in salida_predef else {
            "mapa_red_drenaje": (mapa_red_drenaje_gee,
                                    "mapa_02_drenaje_gee.png")}),
        "mapa_uso_suelo":        (mapa_uso_suelo_gee,        "mapa_03_uso_suelo_gee.png"),
        "mapa_cobertura":        (mapa_cobertura_gee,        "mapa_04_cobertura_gee.png"),
        "mapa_cn":               (mapa_cn_gee,               "mapa_05_cn_gee.png"),
        **({} if "mapa_pendientes" in salida_predef else {
            "mapa_pendientes": (mapa_pendientes_gee,
                                   "mapa_06_pendientes_gee.png")}),
        "mapa_coef_escorrentia": (mapa_coef_escorrentia_gee, "mapa_07_coef_c_gee.png"),
        "mapa_manning":          (mapa_manning_gee,          "mapa_08_manning_gee.png"),
        "mapa_riesgo_inundacion": (mapa_riesgo_inundacion_gee,
                                     "mapa_09_inundacion_gee.png"),
    }
    from concurrent.futures import (ThreadPoolExecutor, as_completed,
                                     TimeoutError as _FutTimeout)
    salida = dict(salida_predef)   # incluye 9.2 y/o 9.6 si entraron vía DEM
    stats = dict(stats_dem)        # pendiente_media_pct si vino del 9.6
    # IMPORTANTE: NO usar `with ThreadPoolExecutor(...)`. Su __exit__ hace
    # shutdown(wait=True), que ESPERA a los threads colgados (p. ej. un mapa
    # cuyo getThumbURL de GEE no responde) → colgaría el worker y la página
    # indefinidamente. En su lugar, acotamos con timeout y abandonamos los
    # threads pendientes con shutdown(wait=False).
    # REINTENTOS: cada ronda corre los mapas que aún faltan con un timeout
    # acotado; los que fallan o exceden el tiempo se REGENERAN en la ronda
    # siguiente (los timeouts de GEE suelen ser transitorios). Así esperamos a
    # que el mapa se genere, sin colgar el worker (cada intento está acotado y
    # los threads colgados se abandonan con shutdown(wait=False)).
    import os as _os
    MAX_INTENTOS = int(_os.environ.get("HYDROFRA_MAPAS_REINTENTOS", "3"))
    TIMEOUT_RONDA = int(_os.environ.get("HYDROFRA_MAPAS_TIMEOUT", "180"))
    pendientes = dict(candidatos)   # clave → (fn, nombre)
    for intento in range(1, MAX_INTENTOS + 1):
        if not pendientes:
            break
        ex = ThreadPoolExecutor(max_workers=min(6, len(pendientes)))
        try:
            futuros = {
                ex.submit(fn, lat, lon, poligono, out_dir / nombre, autor): clave
                for clave, (fn, nombre) in pendientes.items()
            }
            try:
                for fut in as_completed(futuros, timeout=TIMEOUT_RONDA):
                    clave = futuros[fut]
                    try:
                        resultado = fut.result()
                    except Exception as e:  # noqa: BLE001
                        _msg(f"{clave} thread falló (intento {intento}): "
                             f"{type(e).__name__}: {e}")
                        continue
                    if resultado is not None and resultado.get("path"):
                        salida[clave] = resultado["path"]
                        if resultado.get("cn_ponderado"):
                            stats["cn_ponderado"] = resultado["cn_ponderado"]
                        if resultado.get("c_ponderado"):
                            stats["c_ponderado"] = resultado["c_ponderado"]
                        if resultado.get("pendiente_media_pct") is not None:
                            stats["pendiente_media_pct"] = \
                                resultado["pendiente_media_pct"]
                        if resultado.get("area_alta_pct") is not None:
                            stats["inund_area_alta_pct"] = \
                                resultado["area_alta_pct"]
                        if resultado.get("hand_medio") is not None:
                            stats["hand_medio_m"] = resultado["hand_medio"]
            except _FutTimeout:
                _msg(f"mapas_gee: timeout {TIMEOUT_RONDA} s en la ronda "
                     f"{intento}; se reintentan los que faltan")
        finally:
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except TypeError:   # cancel_futures no existe en Python < 3.9
                ex.shutdown(wait=False)
        # Los que ya se generaron salen de la lista de pendientes.
        pendientes = {c: v for c, v in pendientes.items() if c not in salida}
        if pendientes and intento < MAX_INTENTOS:
            _msg(f"mapas_gee: regenerando (intento {intento + 1}/"
                 f"{MAX_INTENTOS}) los mapas que faltan: {list(pendientes)}")
    if pendientes:
        _msg(f"mapas_gee: tras {MAX_INTENTOS} intentos no se generaron: "
             f"{list(pendientes)} (quedan esquemáticos)")
    if salida:
        _msg(f"mapas_gee OK: {sorted(salida.keys())}")
    if stats:
        salida["_stats"] = stats
    return salida
