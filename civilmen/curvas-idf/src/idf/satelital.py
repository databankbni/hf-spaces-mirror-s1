"""Fuentes de datos satelitales/reanálisis de precipitación.

Combinación recomendada:
- CHIRPS      : precipitación histórica espacial (UCSB Climate Hazards Center).
- NASA POWER  : precipitación + variables complementarias (T, radiación).
- Open-Meteo  : reanálisis ERA5 / datos recientes vía API.

De cada fuente se obtiene la serie diaria y se calcula la P24max anual (máximo
anual de la precipitación diaria). Todas las llamadas son tolerantes a fallos:
si la API no responde (sin red, timeout, host bloqueado), se genera una serie
SINTÉTICA claramente etiquetada para que el pipeline nunca se rompa.

Requiere salida a internet (funciona desde el servidor de despliegue). No se
puede verificar en entornos con red restringida.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Timeout por fuente, configurable por entorno. Las consultas de varias décadas
# de datos diarios (NASA POWER, CHIRPS) pueden tardar bastante; con un valor
# muy bajo se corta y cae al fallback sintético aunque haya internet.
_TIMEOUT = int(os.environ.get("IDF_SAT_TIMEOUT", "30"))  # segundos por fuente

# Umbral de depuración: precipitación diaria por encima de este valor (mm) se
# considera un error de la fuente (p. ej. NASA POWER a veces devuelve picos
# espurios) y se descarta antes de calcular el máximo anual. En Bolivia ningún
# día real se acerca a estos valores. Configurable por entorno.
_P24_MAX_DIARIO = float(os.environ.get("IDF_P24_MAX_DIARIO", "500"))  # mm/día


@dataclass
class SerieSatelital:
    fuente: str
    df: pd.DataFrame              # columnas: anio, p24_mm
    exitosa: bool                 # True = API real; False = fallback sintético
    nota: str = ""
    variables_extra: dict = field(default_factory=dict)

    @property
    def n_anios(self) -> int:
        return len(self.df)


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "HYDROFRA/1.3"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _p24max_anual(fechas: list[str], valores: list[float],
                  fmt: str) -> tuple[pd.DataFrame, int]:
    """Convierte serie diaria (fecha, mm) en P24max anual, depurando outliers.

    Descarta valores faltantes (negativos, p. ej. -999 de NASA POWER) y picos
    no físicos (> _P24_MAX_DIARIO). Devuelve (DataFrame anual, n_dias_filtrados).
    """
    s = pd.Series(valores, index=pd.to_datetime(fechas, format=fmt), dtype=float)
    validos = s[s >= 0]                       # quita faltantes negativos
    s = validos[validos <= _P24_MAX_DIARIO]   # quita picos no físicos
    n_filtrados = int(len(validos) - len(s))
    anual = s.groupby(s.index.year).max()
    df = pd.DataFrame({"anio": anual.index.astype(int), "p24_mm": anual.values.round(2)})
    return df, n_filtrados


def _nota_depuracion(n_filtrados: int) -> str:
    if not n_filtrados:
        return ""
    return (f" Se depuraron {n_filtrados} día(s) con valores no físicos "
            f"(> {_P24_MAX_DIARIO:.0f} mm).")


def _fallback_sintetico(fuente: str, lat: float, lon: float,
                        anio_ini: int, anio_fin: int,
                        media: float, desv: float) -> SerieSatelital:
    semilla = abs(hash((fuente, round(lat, 3), round(lon, 3)))) % (2**32)
    rng = np.random.default_rng(semilla)
    n = anio_fin - anio_ini + 1
    beta = desv * np.sqrt(6.0) / np.pi
    mu = media - 0.5772 * beta
    vals = np.clip(rng.gumbel(mu, beta, n), 1.0, None)
    df = pd.DataFrame({"anio": np.arange(anio_ini, anio_fin + 1), "p24_mm": vals.round(2)})
    return SerieSatelital(fuente, df, exitosa=False,
                          nota="Serie SINTÉTICA (API no disponible / sin red).")


# ---------------------------------------------------------------------------
# NASA POWER
# ---------------------------------------------------------------------------

def nasa_power(lat: float, lon: float, anio_ini: int, anio_fin: int,
               media: float, desv: float) -> SerieSatelital:
    base = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {
        "parameters": "PRECTOTCORR,T2M,ALLSKY_SFC_SW_DWN",
        "community": "AG",
        "longitude": f"{lon:.4f}",
        "latitude": f"{lat:.4f}",
        "start": f"{anio_ini}0101",
        "end": f"{anio_fin}1231",
        "format": "JSON",
    }
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        data = _http_get_json(url)
        par = data["properties"]["parameter"]
        prec = par["PRECTOTCORR"]
        fechas = list(prec.keys())
        valores = [float(v) for v in prec.values()]
        df, n_filt = _p24max_anual(fechas, valores, "%Y%m%d")
        t2m = [float(v) for v in par.get("T2M", {}).values() if float(v) > -900]
        rad = [float(v) for v in par.get("ALLSKY_SFC_SW_DWN", {}).values() if float(v) > -900]
        extra = {
            "temp_media_C": round(float(np.mean(t2m)), 2) if t2m else None,
            "radiacion_MJ_m2_dia": round(float(np.mean(rad)), 2) if rad else None,
        }
        return SerieSatelital("NASA POWER", df, exitosa=True,
                              nota="PRECTOTCORR diaria." + _nota_depuracion(n_filt),
                              variables_extra=extra)
    except Exception as e:  # noqa: BLE001
        fb = _fallback_sintetico("NASA POWER", lat, lon, anio_ini, anio_fin, media, desv)
        fb.nota += f" ({type(e).__name__})"
        return fb


# ---------------------------------------------------------------------------
# Open-Meteo (archivo ERA5)
# ---------------------------------------------------------------------------

def open_meteo(lat: float, lon: float, anio_ini: int, anio_fin: int,
               media: float, desv: float) -> SerieSatelital:
    base = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": f"{anio_ini}-01-01",
        "end_date": f"{anio_fin}-12-31",
        "daily": "precipitation_sum",
        "timezone": "auto",
    }
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        data = _http_get_json(url)
        fechas = data["daily"]["time"]
        valores = [float(v) if v is not None else -1.0
                   for v in data["daily"]["precipitation_sum"]]
        df, n_filt = _p24max_anual(fechas, valores, "%Y-%m-%d")
        return SerieSatelital("Open-Meteo (ERA5)", df, exitosa=True,
                              nota="precipitation_sum diaria." + _nota_depuracion(n_filt))
    except Exception as e:  # noqa: BLE001
        fb = _fallback_sintetico("Open-Meteo (ERA5)", lat, lon, anio_ini, anio_fin, media, desv)
        fb.nota += f" ({type(e).__name__})"
        return fb


# ---------------------------------------------------------------------------
# CHIRPS (vía ClimateSERV de SERVIR Global)
# ---------------------------------------------------------------------------

def _chirps_gee(lat: float, lon: float, anio_ini: int,
                  anio_fin: int) -> SerieSatelital | None:
    """CHIRPS Daily 0.05° vía Google Earth Engine (UCSB-CHG/CHIRPS/DAILY).

    Mucho más robusto que ClimateSERV (API síncrona, mismo token GEE que
    los mapas). Para cada año toma el máximo diario de precipitación en
    el píxel del punto → P24max anual. Devuelve None si GEE no responde.
    """
    try:
        from .gee import _intentar_inicializar
        if not _intentar_inicializar():
            return None
        import ee
        punto = ee.Geometry.Point([lon, lat])
        col = (ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
                  .select("precipitation")
                  .filterDate(f"{anio_ini}-01-01", f"{anio_fin}-12-31"))

        def _por_anio(y):
            y = ee.Number(y)
            anual = col.filter(ee.Filter.calendarRange(y, y, "year"))
            pmax = anual.max()   # máximo diario del año (imagen)
            val = pmax.reduceRegion(
                reducer=ee.Reducer.first(), geometry=punto,
                scale=5566, bestEffort=True).get("precipitation")
            return ee.Feature(None, {"anio": y, "p24_mm": val})

        anios = ee.List.sequence(anio_ini, anio_fin)
        fc = ee.FeatureCollection(anios.map(_por_anio))
        datos = fc.getInfo()["features"]
        filas = []
        for f in datos:
            p = f["properties"]
            if p.get("p24_mm") is not None:
                filas.append((int(p["anio"]), round(float(p["p24_mm"]), 2)))
        if len(filas) < 5:
            return None
        df = pd.DataFrame(filas, columns=["anio", "p24_mm"])
        # Depura picos no físicos
        df = df[df["p24_mm"] <= _P24_MAX_DIARIO]
        if len(df) < 5:
            return None
        return SerieSatelital("CHIRPS", df.reset_index(drop=True),
                                exitosa=True,
                                nota="CHIRPS Daily 0.05° vía Google Earth Engine.")
    except Exception:  # noqa: BLE001
        return None


def _imerg_gee(lat: float, lon: float, anio_ini: int,
                 anio_fin: int) -> SerieSatelital | None:
    """IMERG-Final V07 (NASA GPM) — P24max anual vía GEE.

    IMERG es semihorario (precipitation en mm/hr). Para P24max anual:
    por año se suman las medias-horas de cada día (× 0.5 h) y se toma el
    máximo diario. Es el producto satelital que MEJOR representa los
    extremos (vs CHIRPS/ERA5 que los subestiman). Acotado al rango
    disponible (2000-06 → ~2025-09, transición a V08).

    LÍMITE DE CÓMPUTO: la agregación semihoraria→diaria por día es muy
    pesada en GEE. Procesar > ~6 años en un solo `getInfo()` excede el
    presupuesto de cómputo interactivo de GEE (timeout ~30-35 s). Por eso
    IMERG se acota a una **ventana corta reciente (≤ IMERG_MAX_ANIOS años)**
    y se trata como serie de **validación cruzada** del extremo satelital,
    no como fuente primaria de frecuencia (esa la aporta el pluviómetro /
    productos grillados con registro largo). La puerta de adopción en
    `comparacion.py` (≥ 10 años) impide que esta serie corta se adopte como
    fuente de cálculo. Devuelve None si falla o no hay datos.
    """
    IMERG_MAX_ANIOS = 6
    IMERG_MIN_ANIOS = 4
    try:
        from .gee import _intentar_inicializar
        if not _intentar_inicializar():
            return None
        import ee
        # Rango disponible de IMERG-Final V07 (2000-06 → ~2024). Se toma la
        # ventana MÁS RECIENTE de IMERG_MAX_ANIOS años dentro del rango pedido.
        af = min(int(anio_fin), 2024)
        ai = max(int(anio_ini), 2001, af - IMERG_MAX_ANIOS + 1)
        if af - ai + 1 < IMERG_MIN_ANIOS:
            return None
        punto = ee.Geometry.Point([lon, lat])
        # filterBounds primero: GEE solo procesa el píxel del punto.
        col = (ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
                  .select("precipitation")
                  .filterBounds(punto)
                  .filterDate(f"{ai}-01-01", f"{af + 1}-01-01"))

        def _por_anio(y):
            y = ee.Number(y)
            anual = col.filter(ee.Filter.calendarRange(y, y, "year"))
            dias = ee.List.sequence(1, 366)

            def _diario(d):
                # calendarRange(day_of_year) sobre el subconjunto anual ya
                # filtrado: ~3× más rápido que filterDate por día (medido).
                dia = anual.filter(ee.Filter.calendarRange(d, d, "day_of_year"))
                # mm/día = Σ(mm/hr × 0.5 h) sobre las medias-horas del día.
                return dia.sum().multiply(0.5)

            diarios = ee.ImageCollection(dias.map(_diario))
            pmax = diarios.max()
            val = pmax.reduceRegion(
                reducer=ee.Reducer.first(), geometry=punto,
                scale=11132, bestEffort=True, tileScale=4).get("precipitation")
            return ee.Feature(None, {"anio": y, "p24_mm": val})

        anios = ee.List.sequence(ai, af)
        fc = ee.FeatureCollection(anios.map(_por_anio))
        datos = fc.getInfo()["features"]
        filas = []
        for f in datos:
            p = f["properties"]
            if p.get("p24_mm") is not None:
                v = round(float(p["p24_mm"]), 2)
                if 0 < v <= _P24_MAX_DIARIO:
                    filas.append((int(p["anio"]), v))
        if len(filas) < IMERG_MIN_ANIOS:
            return None
        df = pd.DataFrame(filas, columns=["anio", "p24_mm"])
        return SerieSatelital("IMERG V07", df, exitosa=True,
                                nota=(f"IMERG-Final V07 (GPM) — semihorario → "
                                      f"P24max anual vía GEE ({len(filas)} años "
                                      f"recientes); mejor producto satelital "
                                      f"para extremos. Ventana corta → "
                                      f"validación cruzada, no fuente primaria "
                                      f"de frecuencia."))
    except Exception:  # noqa: BLE001
        return None


def imerg(lat: float, lon: float, anio_ini: int, anio_fin: int,
            media: float, desv: float) -> SerieSatelital:
    """IMERG-Final V07 vía GEE; fallback sintético si no responde."""
    g = _imerg_gee(lat, lon, anio_ini, anio_fin)
    if g is not None:
        return g
    fb = _fallback_sintetico("IMERG V07", lat, lon, anio_ini, anio_fin,
                                media, desv)
    fb.nota += " (IMERG GEE no disponible)"
    return fb


def chirps(lat: float, lon: float, anio_ini: int, anio_fin: int,
           media: float, desv: float) -> SerieSatelital:
    # 1) CHIRPS vía GEE (robusto, mismo token que los mapas).
    gee = _chirps_gee(lat, lon, anio_ini, anio_fin)
    if gee is not None:
        return gee
    # 2) Fallback: ClimateSERV (API asíncrona, poco robusta). Si falla →
    #    serie sintética etiquetada.
    base = "https://climateserv.servirglobal.net/api/getDataFromRequest/"
    # Polígono mínimo alrededor del punto (GeoJSON)
    d = 0.05
    geom = json.dumps([[lon - d, lat - d], [lon + d, lat - d],
                       [lon + d, lat + d], [lon - d, lat + d]])
    params = {
        "datatype": "0",  # CHIRPS
        "begintime": f"01/01/{anio_ini}",
        "endtime": f"12/31/{anio_fin}",
        "intervaltype": "0",
        "operationtype": "5",  # max
        "geometry": geom,
    }
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        data = _http_get_json(url)
        registros = data["data"]
        fechas = [r["date"] for r in registros]
        valores = [float(r["value"]["max"]) for r in registros]
        df, n_filt = _p24max_anual(fechas, valores, "%m/%d/%Y")
        if df.empty:
            raise ValueError("CHIRPS sin datos")
        return SerieSatelital("CHIRPS", df, exitosa=True,
                              nota="CHIRPS vía ClimateSERV." + _nota_depuracion(n_filt))
    except Exception as e:  # noqa: BLE001
        fb = _fallback_sintetico("CHIRPS", lat, lon, anio_ini, anio_fin, media, desv)
        fb.nota += f" ({type(e).__name__})"
        return fb


# ---------------------------------------------------------------------------
# NOAA GHCN-Daily (estaciones terrestres reales con código BO)
# ---------------------------------------------------------------------------

def ghcn_daily(lat: float, lon: float, anio_ini: int, anio_fin: int,
                 media: float, desv: float,
                 radio_max_km: float = 80.0) -> SerieSatelital:
    """Serie P24max anual de la estación GHCN-D boliviana más cercana al punto.

    A diferencia de CHIRPS / NASA / ERA5 (productos grillados), GHCN-D entrega
    las OBSERVACIONES TERRESTRES reales de las estaciones SENAMHI que reportan
    al GTS de la OMM (prefijo «BO» en el catálogo NOAA). Si no hay estación a
    menos de `radio_max_km`, devuelve fallback sintético etiquetado.
    """
    try:
        from .conectores_externos import (catalogo_ghcnd_bolivia,
                                             serie_ghcnd)
        from math import asin, cos, radians, sin, sqrt

        def _hav(la1, lo1, la2, lo2):
            R = 6371.0088
            la1, lo1, la2, lo2 = map(radians, (la1, lo1, la2, lo2))
            a = (sin((la2 - la1) / 2) ** 2
                  + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2)
            return 2 * R * asin(sqrt(a))

        catalogo = catalogo_ghcnd_bolivia(timeout=_TIMEOUT)
        if not catalogo:
            raise ValueError("catálogo GHCN-D vacío o inaccesible")
        candidatas = sorted(
            ((e, _hav(lat, lon, e.latitud, e.longitud)) for e in catalogo),
            key=lambda x: x[1])
        mejor, dist = candidatas[0]
        if dist > radio_max_km:
            raise ValueError(f"sin estación GHCN-D a < {radio_max_km:.0f} km "
                              f"(la más cercana: {dist:.0f} km)")
        csv = serie_ghcnd(mejor.id, start=f"{anio_ini}-01-01",
                            end=f"{anio_fin}-12-31",
                            variables=("PRCP",), timeout=_TIMEOUT * 2)
        if not csv:
            raise ValueError("NCEI Access API no devolvió datos")
        # Parsea CSV: columnas STATION,DATE,PRCP (PRCP ya en mm con units=metric)
        import io
        df_raw = pd.read_csv(io.StringIO(csv))
        col_prcp = next((c for c in df_raw.columns
                          if c.strip().upper() == "PRCP"), None)
        col_date = next((c for c in df_raw.columns
                          if c.strip().upper() == "DATE"), None)
        if col_prcp is None or col_date is None:
            raise ValueError("CSV GHCN-D sin columnas PRCP/DATE")
        fechas = df_raw[col_date].astype(str).tolist()
        valores = pd.to_numeric(df_raw[col_prcp],
                                  errors="coerce").fillna(-1).tolist()
        df, n_filt = _p24max_anual(fechas, valores, "%Y-%m-%d")
        if df.empty or len(df) < 5:
            raise ValueError("serie GHCN-D demasiado corta tras depuración")
        nota = (f"Estación GHCN-D «{mejor.nombre}» ({mejor.id}) a "
                f"{dist:.0f} km, {len(df)} años."
                + _nota_depuracion(n_filt))
        return SerieSatelital("NOAA GHCN-D", df, exitosa=True, nota=nota,
                              variables_extra={"estacion_id": mejor.id,
                                                "estacion_nombre": mejor.nombre,
                                                "distancia_km": round(dist, 1)})
    except Exception as e:  # noqa: BLE001
        fb = _fallback_sintetico("NOAA GHCN-D", lat, lon, anio_ini, anio_fin,
                                   media, desv)
        fb.nota += f" ({type(e).__name__}: {str(e)[:60]})"
        return fb


def serie_senamhi_online(lat: float, lon: float, anio_ini: int, anio_fin: int,
                         media: float, desv: float,
                         radio_max_km: float = 120.0,
                         max_intentos: int = 4) -> SerieSatelital:
    """Serie P24max anual de la estación SENAMHI más cercana con registro en línea.

    Recorre el catálogo OFICIAL COMPLETO de SENAMHI (cientos de estaciones,
    `catalogo_senamhi`) ordenado por cercanía y, para cada estación con código
    OMM, intenta traer su serie diaria observada publicada en línea a través de
    NOAA GHCN-D / NCEI (el conducto internacional que republica los datos SENAMHI
    reportados al GTS de la OMM). Adopta la PRIMERA estación SENAMHI que devuelve
    una serie real suficiente, conservando su nombre y distancia oficiales.

    Nota técnica: SENAMHI Bolivia no expone una API pública de series diarias
    (solo boletines PDF y resúmenes mensuales), por lo que la recuperación en
    línea de la observación de estación se hace por este conducto. Si ninguna
    estación cercana tiene registro en línea, devuelve un fallback sintético
    etiquetado (exitosa=False).
    """
    # ── Vía rápida y confiable: la estación de la red SENAMHI reportada al
    # GTS/OMM más cercana (una sola consulta NCEI), relabelada «SENAMHI». ──
    try:
        g = ghcn_daily(lat, lon, anio_ini, anio_fin, media, desv,
                       radio_max_km=min(radio_max_km, 80.0))
        if getattr(g, "exitosa", False) and len(g.df) >= 5:
            nom = g.variables_extra.get("estacion_nombre", "")
            d = g.variables_extra.get("distancia_km", "—")
            g.fuente = "SENAMHI"
            g.nota = (f"Estación SENAMHI «{nom}» (red reportada al GTS/OMM) a "
                      f"{d} km, {len(g.df)} años, recuperada en línea vía NCEI.")
            return g
    except Exception:  # noqa: BLE001
        pass

    # ── Vía secundaria: catálogo oficial SENAMHI por cod_omm (más cobertura,
    # más lento). Se limita a pocos intentos para no colgar el análisis. ──
    try:
        from .catalogo_senamhi import cercanas
        from .conectores_externos import (catalogo_ghcnd_bolivia,
                                          buscar_ghcnd_por_omm, serie_ghcnd)
        import io

        candidatas = cercanas(lat, lon, tope=40, radio_km=radio_max_km)
        if not candidatas:
            raise ValueError(f"sin estación SENAMHI a < {radio_max_km:.0f} km")
        cat_ghcn = catalogo_ghcnd_bolivia(timeout=_TIMEOUT)
        if not cat_ghcn:
            raise ValueError("catálogo SENAMHI/NCEI inaccesible para resolver OMM")

        intentos = 0
        for est, dist in candidatas:
            if intentos >= max_intentos:
                break
            omm = getattr(est, "cod_omm", None)
            if not omm:
                continue
            g = buscar_ghcnd_por_omm(str(omm), cat_ghcn)
            if g is None:
                continue
            intentos += 1
            csv = serie_ghcnd(g.id, start=f"{anio_ini}-01-01",
                              end=f"{anio_fin}-12-31",
                              variables=("PRCP",), timeout=_TIMEOUT * 2)
            if not csv:
                continue
            df_raw = pd.read_csv(io.StringIO(csv))
            col_prcp = next((c for c in df_raw.columns
                             if c.strip().upper() == "PRCP"), None)
            col_date = next((c for c in df_raw.columns
                             if c.strip().upper() == "DATE"), None)
            if col_prcp is None or col_date is None:
                continue
            fechas = df_raw[col_date].astype(str).tolist()
            valores = pd.to_numeric(df_raw[col_prcp],
                                    errors="coerce").fillna(-1).tolist()
            df, n_filt = _p24max_anual(fechas, valores, "%Y-%m-%d")
            if df.empty or len(df) < 5:
                continue
            nota = (f"Estación SENAMHI «{est.estacion}» (OMM {omm}, GHCN {g.id}) "
                    f"a {dist:.0f} km, {len(df)} años, recuperada en línea vía "
                    f"NCEI/GHCN-D." + _nota_depuracion(n_filt))
            return SerieSatelital("SENAMHI", df, exitosa=True, nota=nota,
                                  variables_extra={"estacion_id": g.id,
                                                   "estacion_nombre": est.estacion,
                                                   "cod_omm": str(omm),
                                                   "distancia_km": round(dist, 1)})
        raise ValueError("ninguna estación SENAMHI cercana tiene serie en línea")
    except Exception as e:  # noqa: BLE001
        fb = _fallback_sintetico("SENAMHI", lat, lon, anio_ini, anio_fin,
                                 media, desv)
        fb.nota += f" ({type(e).__name__}: {str(e)[:60]})"
        return fb


def diagnostico_apis(lat: float, lon: float,
                       anio_ini: int = 2015, anio_fin: int = 2020,
                       media_ref: float = 60.0, desv_ref: float = 18.0
                       ) -> dict:
    """Prueba las 4 APIs satelitales en vivo y reporta el estado de cada una.

    Pensado para el endpoint /apis_test del Space — desde un sandbox con
    red restringida todas darán URLError, pero en el runtime del Space
    (red abierta) muestra cuáles responden de verdad, en cuánto tiempo,
    cuántos años devuelven y el error exacto si fallan.
    """
    import time as _t
    fuentes = [
        ("CHIRPS", chirps),
        ("NASA POWER", nasa_power),
        ("Open-Meteo (ERA5)", open_meteo),
        ("NOAA GHCN-D", ghcn_daily),
        ("IMERG V07", imerg),
    ]
    resultados = []
    n_reales = 0
    for nombre, fn in fuentes:
        t0 = _t.time()
        try:
            s = fn(lat, lon, anio_ini, anio_fin, media_ref, desv_ref)
            ms = int((_t.time() - t0) * 1000)
            if s.exitosa:
                n_reales += 1
            resultados.append({
                "fuente": nombre,
                "exitosa": bool(s.exitosa),
                "ms": ms,
                "n_anios": len(s.df),
                "p24_min_mm": (round(float(s.df["p24_mm"].min()), 1)
                                  if len(s.df) else None),
                "p24_max_mm": (round(float(s.df["p24_mm"].max()), 1)
                                  if len(s.df) else None),
                "nota": s.nota[:160],
            })
        except Exception as e:  # noqa: BLE001
            resultados.append({
                "fuente": nombre, "exitosa": False,
                "ms": int((_t.time() - t0) * 1000),
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            })
    return {
        "lat": lat, "lon": lon,
        "rango": f"{anio_ini}-{anio_fin}",
        "timeout_s": _TIMEOUT,
        "n_fuentes_reales": n_reales,
        "analisis_posible_v1_3": n_reales >= 1,
        "resultados": resultados,
        "diagnostico": (
            f"{n_reales}/5 fuentes reales respondieron. "
            + ("El análisis Q máx PUEDE generarse (HYDROFRA v1.3 requiere "
               "≥1 fuente real)." if n_reales >= 1 else
               "⚠️ NINGUNA fuente real respondió — el análisis abortará. "
               "Reintentar en unos minutos (suelen ser fallos transitorios) "
               "o revisar si el Space tiene salida a internet abierta.")),
    }


def obtener_series_satelitales(
    lat: float, lon: float,
    anio_ini: int = 1991, anio_fin: int = 2020,
    media_ref: float = 45.0, desv_ref: float = 13.0,
    incluir_ghcn: bool = False,
    incluir_senamhi: bool = True,
) -> list[SerieSatelital]:
    """Obtiene las series de las tres fuentes en paralelo (con fallback individual).

    Se ejecutan concurrentemente para que el tiempo total sea ~el de la fuente
    más lenta y no la suma de las tres. Cada función ya maneja sus errores y
    devuelve un fallback etiquetado, por lo que esto nunca lanza excepción.
    """
    tareas = [
        (chirps, "CHIRPS"),
        (nasa_power, "NASA POWER"),
        (open_meteo, "Open-Meteo (ERA5)"),
        (imerg, "IMERG V07"),     # mejor producto satelital para extremos
    ]
    if incluir_senamhi:
        # Búsqueda terrestre dirigida por el catálogo oficial COMPLETO de SENAMHI.
        tareas.append((serie_senamhi_online, "SENAMHI"))
    if incluir_ghcn:
        tareas.append((ghcn_daily, "NOAA GHCN-D"))
    args = (lat, lon, anio_ini, anio_fin, media_ref, desv_ref)
    with ThreadPoolExecutor(max_workers=len(tareas)) as ex:
        futuros = [ex.submit(fn, *args) for fn, _ in tareas]
        return [f.result() for f in futuros]
