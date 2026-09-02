"""Comparación y correlación entre la estación de referencia y datos satelitales.

Alinea las series anuales por año común, calcula métricas (Pearson r, R², RMSE,
sesgo, Nash-Sutcliffe) de cada fuente satelital respecto a la estación, y decide
la fuente a adoptar para el análisis de frecuencias siguiendo criterios de la
bibliografía de hidrología y cambio climático:

- La estación terrestre es la "verdad de campo": si tiene registro suficiente
  (n ≥ 20 años) y buena correlación con el satélite, se adopta la estación.
- Si el registro terrestre es corto/escaso, se adopta la fuente satelital con
  mejor desempeño (CHIRPS tiene prioridad para precipitación por su resolución
  y validación en regiones andinas — Funk et al., 2015).
- Se reporta la tendencia (cambio climático) para alertar no-estacionariedad.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sst


@dataclass
class MetricasComparacion:
    fuente: str
    n_comun: int
    pearson_r: float
    r2: float
    rmse_mm: float
    sesgo_mm: float          # media(satelital) − media(estación)
    nash_sutcliffe: float
    tendencia_mm_anio: float  # pendiente de regresión lineal (satelital)


@dataclass
class DecisionFuente:
    fuente_adoptada: str      # nombre de la fuente satelital/terrestre REAL adoptada
    serie_adoptada: pd.DataFrame
    justificacion: str
    metricas: list[MetricasComparacion]
    mejor_satelital: str
    # HYDROFRA v1.3: el análisis solo se realiza con datos REALES. Si ninguna
    # fuente real (GHCN-D / CHIRPS / NASA POWER / Open-Meteo) respondió,
    # tiene_dato_real=False y el pipeline aborta con un mensaje claro en lugar
    # de usar la serie sintética de la estación de referencia.
    tiene_dato_real: bool = True


def _metricas(nombre: str, est: pd.DataFrame, sat: pd.DataFrame) -> MetricasComparacion | None:
    m = pd.merge(est, sat, on="anio", suffixes=("_est", "_sat"))
    if len(m) < 3:
        return None
    x = m["p24_mm_est"].to_numpy(float)
    y = m["p24_mm_sat"].to_numpy(float)
    r = float(np.corrcoef(x, y)[0, 1])
    rmse = float(np.sqrt(np.mean((y - x) ** 2)))
    sesgo = float(np.mean(y) - np.mean(x))
    ss_res = float(np.sum((x - y) ** 2))
    ss_tot = float(np.sum((x - np.mean(x)) ** 2))
    nse = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    pend = float(sst.linregress(sat["anio"].to_numpy(float),
                                sat["p24_mm"].to_numpy(float)).slope)
    return MetricasComparacion(
        fuente=nombre, n_comun=len(m), pearson_r=round(r, 3),
        r2=round(r * r, 3), rmse_mm=round(rmse, 2), sesgo_mm=round(sesgo, 2),
        nash_sutcliffe=round(nse, 3), tendencia_mm_anio=round(pend, 3),
    )


# Fuentes terrestres in-situ (pluviómetro): la estación SENAMHI recuperada en
# línea por el catálogo oficial SENAMHI (observación in-situ de la red nacional).
_FUENTES_TERRESTRES = ("SENAMHI",)


def _dist_terrestre(s):
    """Distancia (km) de una serie terrestre, o infinito si no está definida."""
    try:
        d = (getattr(s, "variables_extra", {}) or {}).get("distancia_km")
        return float(d) if d is not None else float("inf")
    except (TypeError, ValueError):
        return float("inf")


def _diagnostico_terrestre(series_satelitales: list,
                           dist_max_km: float, min_anios: int) -> str:
    """Explica, según criterio técnico, por qué NO se adoptó el pluviómetro
    terrestre (estación SENAMHI / NOAA GHCN-D). Devuelve una frase lista para
    incrustar en la justificación cuando se adopta una fuente grillada."""
    terrestres = [s for s in series_satelitales
                  if s.fuente in _FUENTES_TERRESTRES
                  and getattr(s, "exitosa", False)]
    if not terrestres:
        return ("no se obtuvo respuesta de una estación SENAMHI en línea para "
                "el punto y la ventana temporal solicitados")
    s = min(terrestres, key=_dist_terrestre)
    extra = getattr(s, "variables_extra", {}) or {}
    nom = extra.get("estacion_nombre", s.fuente)
    d = _dist_terrestre(s)
    n = len(s.df)
    partes = []
    if d != float("inf") and d > dist_max_km:
        partes.append(f"la estación terrestre más cercana con registro ({nom}) "
                      f"está a {d:.0f} km, más allá del radio de "
                      f"representatividad adoptado de {dist_max_km:.0f} km")
    if n < min_anios:
        partes.append(f"su registro útil ({n} años) es menor al mínimo de "
                      f"{min_anios} años exigido para un ajuste de frecuencia "
                      f"confiable")
    if not partes:
        partes.append("no cumple los criterios de proximidad y longitud de "
                      "registro adoptados")
    return "; ".join(partes)


def comparar_y_decidir(
    serie_estacion: pd.DataFrame,
    series_satelitales: list,
) -> DecisionFuente:
    """Compara la estación con cada serie satelital y decide la fuente a adoptar."""
    metricas: list[MetricasComparacion] = []
    for s in series_satelitales:
        m = _metricas(s.fuente, serie_estacion, s.df)
        if m is not None:
            metricas.append(m)

    # Mejor satelital por |r| (correlación con la estación)
    mejor_sat_nombre = max(metricas, key=lambda m: m.pearson_r).fuente if metricas else "—"
    mejor_sat_serie = next(
        (s for s in series_satelitales if s.fuente == mejor_sat_nombre), None
    )

    n_est = len(serie_estacion)
    r_mejor = max((m.pearson_r for m in metricas), default=0.0)

    # Prioridad máxima: si NOAA GHCN-D devolvió una serie REAL (no sintética)
    # es la observación terrestre verdadera de la estación SENAMHI más
    # cercana — supera a la serie sintética de la estación de referencia y a
    # los productos grillados.
    #
    # Criterio reforzado para ANÁLISIS DE EXTREMOS (decisión del hidrólogo,
    # v2.0): los productos grillados (CHIRPS, ERA5, NASA POWER) promedian la
    # tormenta sobre el píxel (5–11 km) y SUBESTIMAN sistemáticamente la cola
    # alta — en este sitio CHIRPS dio P24max ≈ 33 mm vs 211 mm del pluviómetro
    # a 19 km (×6). Para frecuencia de extremos el gauge in-situ es la verdad
    # de campo, por lo que se prioriza cuando está a distancia razonable
    # (≤ GHCN_DIST_MAX_KM) con registro suficiente (≥ GHCN_MIN_ANIOS años),
    # bajando el umbral antes exigido (15 → 10 años). La correlación de
    # Pearson NO mide el sesgo de cola, así que no se usa como filtro aquí.
    GHCN_MIN_ANIOS = 10
    GHCN_DIST_MAX_KM = 30.0

    def _terrestre_apto(s) -> bool:
        if s.fuente not in _FUENTES_TERRESTRES or not getattr(s, "exitosa", False):
            return False
        if len(s.df) < GHCN_MIN_ANIOS:
            return False
        return _dist_terrestre(s) <= GHCN_DIST_MAX_KM

    # De haber estación terrestre apta (SENAMHI en línea o NOAA GHCN-D), se
    # adopta la MÁS CERCANA — es la medición in-situ real (verdad de campo).
    aptas = [s for s in series_satelitales if _terrestre_apto(s)]
    if aptas:
        terr = min(aptas, key=_dist_terrestre)
        extra = getattr(terr, "variables_extra", {}) or {}
        dist = extra.get("distancia_km", "—")
        nom = extra.get("estacion_nombre", terr.fuente)
        origen = "recuperada en línea del catálogo oficial SENAMHI"
        return DecisionFuente(
            fuente_adoptada=terr.fuente,
            serie_adoptada=terr.df,
            justificacion=(
                f"Se adopta la serie observada de la estación terrestre "
                f"«{nom}» ({origen}; a {dist} km, n = {len(terr.df)} años), que "
                f"constituye la medición in-situ real. Para el análisis de "
                f"frecuencia de EXTREMOS el pluviómetro es la verdad de campo: "
                f"los productos grillados (CHIRPS / ERA5 / NASA POWER) promedian "
                f"la tormenta sobre el píxel y subestiman la cola alta, por lo "
                f"que se reservan para validación cruzada. Criterio: WMO-168, "
                f"jerarquía de fuentes in-situ > satelital."),
            metricas=metricas, mejor_satelital=mejor_sat_nombre,
        )

    # HYDROFRA v1.3 — solo datos REALES. La serie sintética de la estación de
    # referencia (ruido Gumbel de la climatología SENAMHI) NO se adopta —
    # solo sirvió arriba para correlación.
    def _r_de(s):
        return next((m.pearson_r for m in metricas
                      if m.fuente == s.fuente), -1.0)
    reales = [s for s in series_satelitales
                if getattr(s, "exitosa", False) and len(s.df) >= 10]
    # Más allá del radio in-situ (30 km) se prioriza el producto GRILLADO, cuya
    # representatividad no depende de la distancia a un gauge; el pluviómetro
    # lejano solo se usa si ninguna fuente grillada respondió.
    grilladas = [s for s in reales if s.fuente not in _FUENTES_TERRESTRES]
    if grilladas:
        mejor = max(grilladas, key=lambda s: (_r_de(s), len(s.df)))
        r_m = _r_de(mejor)
        adoptada = mejor.fuente
        serie = mejor.df
        motivo = _diagnostico_terrestre(series_satelitales,
                                        GHCN_DIST_MAX_KM, GHCN_MIN_ANIOS)
        # Justificación por criterio técnico del uso de la fuente grillada:
        # (1) jerarquía de fuentes WMO-168 (in-situ > grillada) y por qué el
        # gauge quedó descartado en este sitio; (2) validez del producto
        # adoptado; (3) advertencia de sesgo de cola y su tratamiento.
        _val = {
            "CHIRPS": ("CHIRPS v2.0 combina la banda IR de fría de nubes con "
                       "estaciones in-situ a 0.05° (~5 km) y está validado en "
                       "los Andes tropicales (Funk et al., 2015)"),
            "NASA POWER": ("NASA POWER deriva de reanálisis MERRA-2/GEOS y está "
                           "validado para aplicaciones hidro-agrícolas (Stackhouse "
                           "et al.)"),
            "Open-Meteo ERA5": ("ERA5 es el reanálisis global de ECMWF a ~9–31 km "
                                "asimilando observaciones, de calidad documentada "
                                "(Hersbach et al., 2020)"),
        }.get(adoptada, f"{adoptada} es un producto grillado validado en la región")
        just = (
            f"Se adopta la fuente grillada de mejor desempeño ({adoptada}, "
            f"n = {len(serie)} años, r = {r_m:.2f} frente a la climatología "
            f"SENAMHI de referencia). Criterio técnico: la jerarquía de fuentes "
            f"de la OMM (WMO-No. 168) prioriza el pluviómetro in-situ como verdad "
            f"de campo, pero en este sitio {motivo}; por lo tanto, y dado que "
            f"HYDROFRA v1.3 trabaja únicamente con datos reales (la serie "
            f"sintética de la estación de referencia se descarta como fuente de "
            f"cálculo), se recurre a la mejor fuente grillada disponible. "
            f"Justificación del producto: {_val}. "
            f"Limitación reconocida: los productos grillados promedian la "
            f"tormenta sobre el píxel y tienden a subestimar la cola alta de "
            f"precipitación extrema; por ello el análisis aplica la corrección "
            f"de Hershfield (intervalo fijo) y se recomienda validación cruzada "
            f"con un pluviómetro cercano cuando exista registro suficiente."
        )
        return DecisionFuente(
            fuente_adoptada=adoptada, serie_adoptada=serie,
            justificacion=just, metricas=metricas,
            mejor_satelital=mejor_sat_nombre, tiene_dato_real=True,
        )

    # Solo respondió un pluviómetro terrestre fuera del radio de 30 km: se
    # adopta como mejor dato real disponible (preferible a no tener nada),
    # dejando constancia de que su representatividad del sitio es limitada.
    if reales:
        terr = min(reales, key=_dist_terrestre)
        extra = getattr(terr, "variables_extra", {}) or {}
        dist = extra.get("distancia_km", "—")
        nom = extra.get("estacion_nombre", terr.fuente)
        return DecisionFuente(
            fuente_adoptada=terr.fuente, serie_adoptada=terr.df,
            justificacion=(
                f"Ninguna fuente grillada respondió; se adopta la estación "
                f"terrestre «{nom}» ({terr.fuente}, a {dist} km, "
                f"n = {len(terr.df)} años) como mejor dato real disponible. "
                f"Nota: se encuentra más allá del radio in-situ ideal de "
                f"{GHCN_DIST_MAX_KM:.0f} km, por lo que su representatividad "
                f"del sitio es limitada; conviene validar con un pluviómetro "
                f"más cercano cuando exista registro."),
            metricas=metricas, mejor_satelital=mejor_sat_nombre,
            tiene_dato_real=True,
        )

    # Ninguna fuente real respondió → señalamos para que el pipeline aborte.
    return DecisionFuente(
        fuente_adoptada="SIN_DATOS_REALES",
        serie_adoptada=serie_estacion,   # placeholder, no se usará
        justificacion=("Ninguna fuente de precipitación real (CHIRPS, NASA "
                         "POWER, Open-Meteo, SENAMHI) respondió para este "
                         "sitio. HYDROFRA v1.3 no genera análisis con series "
                         "sintéticas — reintentar en unos minutos."),
        metricas=metricas, mejor_satelital=mejor_sat_nombre,
        tiene_dato_real=False,
    )
