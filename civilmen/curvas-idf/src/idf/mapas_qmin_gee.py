"""Mapas temáticos GEE específicos para el análisis de caudales mínimos.

Complementan los 6 mapas hidrológicos clásicos (red de drenaje, uso de suelo,
cobertura, CN, pendientes, C) con las variables que controlan el régimen de
mínimos: oferta de agua, demanda atmosférica, capacidad de almacenamiento de
los suelos y conectividad subterránea. Sobre la cuenca delineada por MERIT
Hydro genera 6 PNG decorados con grilla UTM, leyenda con % por clase, escala,
proyección y autor.

Mapas (numeración 2.3.1 a 2.3.6 en el informe):
- 2.3.1 Precipitación media anual (mm/año) — CHIRPS Daily 1981–presente.
- 2.3.2 Evapotranspiración media anual (mm/año) — MOD16A2 / MODIS 500 m.
- 2.3.3 Índice de aridez Pann/PETann (UNEP) — CHIRPS / MOD16A2.
- 2.3.4 Capacidad de retención de agua del suelo (CAW, mm) — OpenLandMap.
- 2.3.5 Productividad de acuíferos (proxy de aporte base) — WHYMAP/IGRAC + topografía.
- 2.3.6 Recarga potencial media anual (mm/año) — WaterGAP / GLDAS-Noah.

Si una capa falla individualmente (timeout o asset no disponible) el llamador
omite ese mapa; los que sí salen se devuelven con su path y un dict de
estadísticas ponderadas sobre la cuenca para alimentar la transformación
precipitación → caudal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .gee import (
    _decorar_mapa_cartografico,
    _intentar_inicializar,
    _msg,
    descargar_con_timeout,
    epsg_utm,
)
from .mapas_gee import (
    _contorno_cuenca,
    _frecuencia,
    _geometria_y_bounds,
    _indice_por_bordes,
    _leyenda_desde_frec,
)


def _thumb(salida, bounds, bbox, out_path: Path, autor: str,
            titulo: str, entradas_leyenda=None, resumen: str = "",
            dimensions: int = 700, timeout: float = 60.0) -> Path:
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
    _decorar_mapa_cartografico(out_path, bbox, autor, titulo=titulo,
                                entradas_leyenda=entradas_leyenda,
                                resumen=resumen)
    return out_path


def _media_sobre_cuenca(img, geom, scale: float) -> Optional[float]:
    """Media espacial de `img` sobre la geometría de la cuenca."""
    try:
        import ee
        d = img.reduceRegion(ee.Reducer.mean(), geom, scale=scale,
                              maxPixels=1e9, bestEffort=True).getInfo()
        if not d:
            return None
        v = next(iter(d.values()))
        return float(v) if v is not None else None
    except Exception as e:  # noqa: BLE001
        _msg(f"_media_sobre_cuenca falló: {type(e).__name__}: {e}")
        return None


# ─────────── 2.3.1 Precipitación media anual (CHIRPS) ───────────
_P_BORDES = [0, 200, 400, 600, 800, 1200, 1800, 10000]
_P_NOMBRE = {0: "P < 200 (árido)", 1: "200–400", 2: "400–600",
             3: "600–800", 4: "800–1200", 5: "1200–1800",
             6: "P ≥ 1800 (muy húmedo)"}
_P_COLOR = {0: "#d73027", 1: "#fdae61", 2: "#fee08b", 3: "#ffffbf",
            4: "#abd9e9", 5: "#4575b4", 6: "#313695"}


def mapa_precipitacion_anual_gee(lat, lon, poligono, out_path,
                                   autor: str = "",
                                   anio_inicio: int = 2001,
                                   anio_fin: int = 2023) -> Optional[dict]:
    """Pann media multianual CHIRPS sobre la cuenca (mm/año)."""
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        col = (ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
                 .filterDate(f"{anio_inicio}-01-01", f"{anio_fin}-12-31"))
        # Suma anual por año y promedio sobre todos los años (mm/año).
        anios = ee.List.sequence(anio_inicio, anio_fin)
        def _suma_anual(y):
            y = ee.Number(y).toInt()
            d_ini = ee.Date.fromYMD(y, 1, 1)
            d_fin = d_ini.advance(1, "year")
            return col.filterDate(d_ini, d_fin).sum().rename("p").set("year", y)
        anuales = ee.ImageCollection.fromImages(anios.map(_suma_anual))
        p_med = anuales.mean()
        vis = p_med.visualize(min=100, max=2000, palette=[
            "d73027", "fdae61", "fee08b", "ffffbf",
            "abd9e9", "74add1", "4575b4", "313695"])
        composite = vis.blend(_contorno_cuenca(geom))
        pann = _media_sobre_cuenca(p_med, geom, 5566)  # CHIRPS ~5.5 km
        idx = _indice_por_bordes(p_med, _P_BORDES)
        frec = _frecuencia(idx, geom, 5566)
        leyenda = [{"etiqueta": _P_NOMBRE[k], "color": _P_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(7)
                   if frec.get(k, 0.0) >= 0.5]
        resumen = f"Pann ≈ {pann:.0f} mm/año" if pann else ""
        path = _thumb(composite, bounds, bbox, out_path, autor,
                       titulo=f"2.3.1 Precipitación media anual ({anio_inicio}–{anio_fin}) — CHIRPS",
                       entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "pann_mm": pann}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_precipitacion_anual_gee falló: {type(e).__name__}: {e}")
        return None


# ─────────── 2.3.2 Evapotranspiración media anual (MOD16A2) ───────────
_ET_BORDES = [0, 200, 400, 600, 800, 1000, 1200, 5000]
_ET_NOMBRE = {0: "ET < 200", 1: "200–400", 2: "400–600", 3: "600–800",
              4: "800–1000", 5: "1000–1200", 6: "ET ≥ 1200"}
_ET_COLOR = {0: "#ffffd9", 1: "#edf8b1", 2: "#c7e9b4", 3: "#7fcdbb",
             4: "#41b6c4", 5: "#1d91c0", 6: "#225ea8"}


def _et_mod16(geom, anio_inicio, anio_fin):
    """ETa media anual MOD16A2 v061 (mm/año). Fallback de PML. → ee.Image."""
    import ee
    col = (ee.ImageCollection("MODIS/061/MOD16A2GF")
             .filterDate(f"{anio_inicio}-01-01", f"{anio_fin}-12-31")
             .select("ET"))
    anios = ee.List.sequence(anio_inicio, anio_fin)
    def _suma_anual(y):
        y = ee.Number(y).toInt()
        d_ini = ee.Date.fromYMD(y, 1, 1)
        d_fin = d_ini.advance(1, "year")
        return (col.filterDate(d_ini, d_fin).sum()
                   .multiply(0.1).rename("eta").set("year", y))
    return ee.ImageCollection.fromImages(anios.map(_suma_anual)).mean()


def mapa_evapotranspiracion_gee(lat, lon, poligono, out_path,
                                  autor: str = "",
                                  anio_inicio: int = 2001,
                                  anio_fin: int = 2022) -> Optional[dict]:
    """ETa media anual sobre la cuenca (mm/año).

    Fuente principal: PML_V2.2a (Zhang & Gan; CC-BY 4.0; NSE > 0.60,
    sesgo < 5 %; balance hídrico de cuenca NSE 0.89–0.91). Particiona ET
    en transpiración (Ec) + evaporación de suelo (Es) + intercepción
    (Ei) → mejor cierre del balance para Q mínimos. Fallback a MOD16A2.
    """
    if not _intentar_inicializar() or poligono is None:
        return None
    import ee
    geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
    fuente_et = "PML_V2.2a (Ec+Es+Ei)"
    try:
        # PML_V2.2a: Ec/Es/Ei en mm/d (compuestos de 8 días). ET diaria =
        # Ec+Es+Ei; ET anual ≈ media diaria × 365.
        col = (ee.ImageCollection(
                    "projects/pml_evapotranspiration/PML/OUTPUT/PML_V2_2a")
                  .filterDate(f"{anio_inicio}-01-01", f"{anio_fin}-12-31")
                  .select(["Ec", "Es", "Ei"]))
        n = col.size().getInfo()
        if not n or n < 10:
            raise ValueError("PML_V2.2a sin imágenes suficientes")
        et_daily = col.map(
            lambda img: img.reduce(ee.Reducer.sum()).rename("et"))
        eta = et_daily.mean().multiply(365.0)
    except Exception as e:  # noqa: BLE001
        _msg(f"ET PML_V2.2a falló ({type(e).__name__}: {e}), cae a MOD16")
        try:
            eta = _et_mod16(geom, anio_inicio, anio_fin)
            fuente_et = "MOD16A2 (PML no disponible)"
        except Exception as e2:  # noqa: BLE001
            _msg(f"ET MOD16 también falló: {type(e2).__name__}: {e2}")
            return None
    try:
        vis = eta.visualize(min=100, max=1400, palette=[
            "ffffd9", "edf8b1", "c7e9b4", "7fcdbb",
            "41b6c4", "1d91c0", "225ea8", "0c2c84"])
        composite = vis.blend(_contorno_cuenca(geom))
        eta_med = _media_sobre_cuenca(eta, geom, 500)
        idx = _indice_por_bordes(eta, _ET_BORDES)
        frec = _frecuencia(idx, geom, 500)
        leyenda = [{"etiqueta": _ET_NOMBRE[k], "color": _ET_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(7)
                   if frec.get(k, 0.0) >= 0.5]
        resumen = (f"ETa ≈ {eta_med:.0f} mm/año ({fuente_et})"
                     if eta_med else "")
        path = _thumb(composite, bounds, bbox, out_path, autor,
                       titulo=("2.3.2 Evapotranspiración real (mm/año) — "
                                  + fuente_et.split(" ")[0]),
                       entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "eta_mm": eta_med, "fuente_et": fuente_et}
    except Exception as e:  # noqa: BLE001
        _msg(f"render ET falló: {type(e).__name__}: {e}")
        return None


# ─────────── 2.3.3 Índice de aridez Pann/PETann (UNEP) ───────────
_AI_BORDES = [0.0, 0.05, 0.20, 0.50, 0.65, 1.00, 10.0]
_AI_NOMBRE = {0: "Hiperárido (AI<0.05)", 1: "Árido (0.05–0.20)",
              2: "Semiárido (0.20–0.50)", 3: "Subhúmedo seco (0.50–0.65)",
              4: "Subhúmedo (0.65–1.0)", 5: "Húmedo (AI≥1.0)"}
_AI_COLOR = {0: "#a50026", 1: "#d73027", 2: "#fdae61", 3: "#fee08b",
             4: "#abd9e9", 5: "#2c7bb6"}


def mapa_indice_aridez_gee(lat, lon, poligono, out_path,
                             autor: str = "",
                             anio_inicio: int = 2001,
                             anio_fin: int = 2022) -> Optional[dict]:
    """AI = Pann/PETann clasificado por UNEP usando CHIRPS + MOD16A2."""
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        chirps = (ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
                    .filterDate(f"{anio_inicio}-01-01", f"{anio_fin}-12-31"))
        et_col = (ee.ImageCollection("MODIS/061/MOD16A2GF")
                    .filterDate(f"{anio_inicio}-01-01", f"{anio_fin}-12-31")
                    .select("PET"))
        anios = ee.List.sequence(anio_inicio, anio_fin)
        def _pp_anual(y):
            y = ee.Number(y).toInt()
            d = ee.Date.fromYMD(y, 1, 1)
            return chirps.filterDate(d, d.advance(1, "year")).sum().rename("p")
        def _pet_anual(y):
            y = ee.Number(y).toInt()
            d = ee.Date.fromYMD(y, 1, 1)
            return (et_col.filterDate(d, d.advance(1, "year")).sum()
                       .multiply(0.1).rename("pet"))
        p = ee.ImageCollection.fromImages(anios.map(_pp_anual)).mean()
        pet = ee.ImageCollection.fromImages(anios.map(_pet_anual)).mean()
        ai = p.divide(pet.max(1)).rename("ai")
        vis = ai.visualize(min=0.0, max=1.5, palette=[
            "a50026", "d73027", "fdae61", "fee08b",
            "ffffbf", "abd9e9", "2c7bb6", "313695"])
        composite = vis.blend(_contorno_cuenca(geom))
        ai_med = _media_sobre_cuenca(ai, geom, 500)
        idx = _indice_por_bordes(ai, _AI_BORDES)
        frec = _frecuencia(idx, geom, 500)
        leyenda = [{"etiqueta": _AI_NOMBRE[k], "color": _AI_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(6)
                   if frec.get(k, 0.0) >= 0.5]
        resumen = f"AI medio ≈ {ai_med:.2f}" if ai_med else ""
        path = _thumb(composite, bounds, bbox, out_path, autor,
                       titulo="2.3.3 Índice de aridez P/PET (UNEP) — CHIRPS·MOD16",
                       entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "ai": ai_med}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_indice_aridez_gee falló: {type(e).__name__}: {e}")
        return None


# ─────────── 2.3.4 Capacidad de retención de agua del suelo (CAW) ───────────
_CAW_BORDES = [0, 50, 100, 150, 200, 300, 1000]
_CAW_NOMBRE = {0: "CAW < 50 (muy baja)", 1: "50–100", 2: "100–150",
               3: "150–200", 4: "200–300", 5: "CAW ≥ 300 (alta)"}
_CAW_COLOR = {0: "#f7fcb9", 1: "#d9f0a3", 2: "#addd8e", 3: "#78c679",
              4: "#41ab5d", 5: "#006837"}


def mapa_capacidad_retencion_gee(lat, lon, poligono, out_path,
                                   autor: str = "") -> Optional[dict]:
    """CAW = (fc - pwp) × profundidad_radical, mm, sobre la cuenca.

    Usa contenido volumétrico a -10 kPa y -1500 kPa de OpenLandMap (ISRIC)
    promediados a 0–100 cm. CAW alta amortigua el estiaje (mayor caudal base).
    """
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        # 6 profundidades 0/10/30/60/100/200 cm — usamos las primeras 5 (0..100).
        fc = (ee.Image("OpenLandMap/SOL/SOL_WATERCONTENT-33KPA_USDA-4B1C_M/v01")
                .select(["b0", "b10", "b30", "b60", "b100"])
                .reduce(ee.Reducer.mean())
                .divide(100.0))  # % → fracción
        pwp = (ee.Image("OpenLandMap/SOL/SOL_WATERCONTENT-1500KPA_USDA-3C2A1A_M/v01")
                 .select(["b0", "b10", "b30", "b60", "b100"])
                 .reduce(ee.Reducer.mean())
                 .divide(100.0))
        # CAW = (θfc − θwp) × 1000 mm/m × 1.0 m (zona radical promedio).
        caw = fc.subtract(pwp).multiply(1000).max(0).rename("caw")
        vis = caw.visualize(min=20, max=350, palette=[
            "f7fcb9", "d9f0a3", "addd8e", "78c679",
            "41ab5d", "238443", "006837", "004529"])
        composite = vis.blend(_contorno_cuenca(geom))
        caw_med = _media_sobre_cuenca(caw, geom, 250)
        idx = _indice_por_bordes(caw, _CAW_BORDES)
        frec = _frecuencia(idx, geom, 250)
        leyenda = [{"etiqueta": _CAW_NOMBRE[k], "color": _CAW_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(6)
                   if frec.get(k, 0.0) >= 0.5]
        resumen = f"CAW ≈ {caw_med:.0f} mm" if caw_med else ""
        path = _thumb(composite, bounds, bbox, out_path, autor,
                       titulo="2.3.4 Capacidad de retención de agua del suelo (mm) — OpenLandMap",
                       entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "caw_mm": caw_med}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_capacidad_retencion_gee falló: {type(e).__name__}: {e}")
        return None


# ─────────── 2.3.5 Topographic Wetness Index (proxy de aporte base) ───────────
_TWI_BORDES = [-5, 5, 8, 10, 12, 15, 30]
_TWI_NOMBRE = {0: "TWI < 5 (drenaje libre)", 1: "5–8", 2: "8–10",
               3: "10–12", 4: "12–15", 5: "TWI ≥ 15 (saturación)"}
_TWI_COLOR = {0: "#f7fbff", 1: "#deebf7", 2: "#9ecae1", 3: "#4292c6",
              4: "#2171b5", 5: "#08306b"}


def mapa_twi_gee(lat, lon, poligono, out_path,
                  autor: str = "") -> Optional[dict]:
    """TWI = ln(área_drenada / tan β). Proxy de zonas que mantienen flujo base."""
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        import math
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"]))
        slope_rad = ee.Terrain.slope(dem).multiply(math.pi / 180)
        tan_b = slope_rad.tan().max(0.001)
        upa_m2 = (ee.Image("MERIT/Hydro/v1_0_1").select("upa")
                    .multiply(1e6).max(1))  # km² → m²
        twi = upa_m2.divide(tan_b).log().rename("twi")
        vis = twi.visualize(min=2, max=20, palette=[
            "f7fbff", "deebf7", "9ecae1", "6baed6",
            "4292c6", "2171b5", "08519c", "08306b"])
        composite = vis.blend(_contorno_cuenca(geom))
        twi_med = _media_sobre_cuenca(twi, geom, 90)
        idx = _indice_por_bordes(twi, _TWI_BORDES)
        frec = _frecuencia(idx, geom, 90)
        leyenda = [{"etiqueta": _TWI_NOMBRE[k], "color": _TWI_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(6)
                   if frec.get(k, 0.0) >= 0.5]
        resumen = f"TWI medio ≈ {twi_med:.1f}" if twi_med else ""
        path = _thumb(composite, bounds, bbox, out_path, autor,
                       titulo="2.3.5 Topographic Wetness Index (TWI) — MERIT·SRTM",
                       entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "twi": twi_med}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_twi_gee falló: {type(e).__name__}: {e}")
        return None


# ─────────── 2.3.6 Humedad de suelo media anual (SMAP) ───────────
_SM_BORDES = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 1.0]
_SM_NOMBRE = {0: "θ < 0.10 (seco)", 1: "0.10–0.20", 2: "0.20–0.30",
              3: "0.30–0.40", 4: "0.40–0.50", 5: "θ ≥ 0.50 (saturado)"}
_SM_COLOR = {0: "#ffffcc", 1: "#a1dab4", 2: "#41b6c4", 3: "#2c7fb8",
             4: "#253494", 5: "#081d58"}


def mapa_humedad_suelo_gee(lat, lon, poligono, out_path,
                             autor: str = "",
                             anio_inicio: int = 2016,
                             anio_fin: int = 2023) -> Optional[dict]:
    """Humedad volumétrica media de zona radical (NASA SMAP L4)."""
    if not _intentar_inicializar() or poligono is None:
        return None
    try:
        import ee
        geom, bounds, bbox = _geometria_y_bounds(poligono, buffer_frac=0.05)
        sm = (ee.ImageCollection("NASA/SMAP/SPL4SMGP/007")
                .filterDate(f"{anio_inicio}-01-01", f"{anio_fin}-12-31")
                .select("sm_rootzone")
                .mean())
        vis = sm.visualize(min=0.05, max=0.55, palette=[
            "ffffcc", "c7e9b4", "7fcdbb", "41b6c4",
            "2c7fb8", "253494", "081d58"])
        composite = vis.blend(_contorno_cuenca(geom))
        sm_med = _media_sobre_cuenca(sm, geom, 10000)
        idx = _indice_por_bordes(sm, _SM_BORDES)
        frec = _frecuencia(idx, geom, 10000)
        leyenda = [{"etiqueta": _SM_NOMBRE[k], "color": _SM_COLOR[k],
                    "pct": frec.get(k, 0.0)} for k in range(6)
                   if frec.get(k, 0.0) >= 0.5]
        resumen = f"θ raíz ≈ {sm_med:.2f}" if sm_med else ""
        path = _thumb(composite, bounds, bbox, out_path, autor,
                       titulo=f"2.3.6 Humedad de suelo zona radical ({anio_inicio}–{anio_fin}) — NASA SMAP L4",
                       entradas_leyenda=leyenda or None, resumen=resumen)
        return {"path": path, "sm_rootzone": sm_med}
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_humedad_suelo_gee falló: {type(e).__name__}: {e}")
        return None


def generar_mapas_qmin(lat: float, lon: float, poligono,
                        out_dir: Path, autor: str = "") -> dict:
    """Genera en paralelo los 6 mapas temáticos del análisis de caudales mínimos.

    Devuelve {clave: path, ..., "_stats": {pann_mm, eta_mm, ai, caw_mm,
    twi, sm_rootzone}}. Los mapas que fallan se omiten silenciosamente.
    """
    if poligono is None:
        return {}
    out_dir = Path(out_dir)
    candidatos = {
        "mapa_precipitacion":  (mapa_precipitacion_anual_gee,   "qmin_02_3_1_pann.png"),
        "mapa_et":             (mapa_evapotranspiracion_gee,    "qmin_02_3_2_eta.png"),
        "mapa_aridez":         (mapa_indice_aridez_gee,         "qmin_02_3_3_aridez.png"),
        "mapa_caw":            (mapa_capacidad_retencion_gee,   "qmin_02_3_4_caw.png"),
        "mapa_twi":            (mapa_twi_gee,                   "qmin_02_3_5_twi.png"),
        "mapa_humedad":        (mapa_humedad_suelo_gee,         "qmin_02_3_6_sm.png"),
    }
    from concurrent.futures import ThreadPoolExecutor, as_completed
    salida: dict = {}
    stats: dict = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futuros = {
            ex.submit(fn, lat, lon, poligono, out_dir / nombre, autor): clave
            for clave, (fn, nombre) in candidatos.items()
        }
        for fut in as_completed(futuros, timeout=150):
            clave = futuros[fut]
            try:
                resultado = fut.result()
            except Exception as e:  # noqa: BLE001
                _msg(f"{clave} thread falló: {type(e).__name__}: {e}")
                continue
            if resultado is not None:
                salida[clave] = resultado["path"]
                for k, v in resultado.items():
                    if k != "path" and v is not None:
                        stats[k] = v
    if salida:
        _msg(f"mapas_qmin OK: {sorted(salida.keys())}")
    if stats:
        salida["_stats"] = stats
    return salida
