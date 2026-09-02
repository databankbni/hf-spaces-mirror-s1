"""Análisis de doble masa (doble acumulación) para consistencia de la serie.

Exigido por el dictamen de supervisión (§2.2, Manual de Hidrología y Drenaje
ABC): verifica la homogeneidad y consistencia de la fuente de precipitación
adoptada frente a un patrón regional de referencia.

El método de la curva de doble masa (Searcy & Hardison, 1960; USGS) grafica la
precipitación ANUAL ACUMULADA de la estación/fuente analizada contra la
precipitación anual acumulada del promedio regional de las estaciones/fuentes
vecinas. Si la fuente es consistente, los puntos se alinean sobre una recta; un
quiebre en la pendiente indica un cambio de régimen o una inconsistencia (cambio
de instrumento, reubicación, error sistemático de la fuente).

En HYDROFRA el "promedio regional" se construye con las OTRAS fuentes
independientes disponibles para el sitio (CHIRPS, NASA POWER, ERA5, IMERG,
SENAMHI), que actúan como estaciones de referencia. Se reporta el coeficiente
de correlación de Pearson R, la pendiente de la recta y el mayor quiebre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ResultadoDobleMasa:
    fuente_analizada: str
    fuentes_referencia: list
    anios: list                       # años comunes usados
    acum_analizada: list              # acumulado de la fuente analizada
    acum_referencia: list             # acumulado del promedio regional
    pearson_r: float
    pendiente: float
    n_anios: int
    consistente: bool
    quiebre_anio: Optional[int] = None
    quiebre_desviacion_pct: float = 0.0
    mensaje: str = ""


def analisis_doble_masa(serie_adoptada: pd.DataFrame,
                        series_referencia: list,
                        fuente_adoptada: str = "adoptada"
                        ) -> Optional[ResultadoDobleMasa]:
    """Construye la curva de doble masa de la fuente adoptada vs el promedio
    regional de las series de referencia.

    Parámetros
    ----------
    serie_adoptada : DataFrame con columnas 'anio' y 'p24_mm'.
    series_referencia : lista de objetos con .fuente (str) y .df (DataFrame
        anio/p24_mm) — las OTRAS fuentes disponibles.
    """
    if serie_adoptada is None or "anio" not in serie_adoptada.columns:
        return None
    refs = [s for s in (series_referencia or [])
            if getattr(s, "df", None) is not None and "anio" in s.df.columns]
    if not refs:
        return None

    base = serie_adoptada[["anio", "p24_mm"]].rename(
        columns={"p24_mm": "_adopt"}).copy()
    base["anio"] = base["anio"].astype(int)
    # Promedio regional por año = media de las fuentes de referencia.
    ref_merged = None
    nombres_ref = []
    for i, s in enumerate(refs):
        nombres_ref.append(s.fuente)
        d = s.df[["anio", "p24_mm"]].rename(columns={"p24_mm": f"_r{i}"}).copy()
        d["anio"] = d["anio"].astype(int)
        ref_merged = d if ref_merged is None else ref_merged.merge(
            d, on="anio", how="outer")
    cols_r = [c for c in ref_merged.columns if c.startswith("_r")]
    ref_merged["_ref"] = ref_merged[cols_r].mean(axis=1, skipna=True)
    df = base.merge(ref_merged[["anio", "_ref"]], on="anio", how="inner")
    df = df.dropna(subset=["_adopt", "_ref"]).sort_values("anio")
    if len(df) < 5:
        return None

    acum_a = np.cumsum(df["_adopt"].to_numpy(dtype=float))
    acum_r = np.cumsum(df["_ref"].to_numpy(dtype=float))
    anios = df["anio"].astype(int).tolist()

    # Correlación de Pearson y recta de mejor ajuste (por el origen no forzado).
    if acum_r.std() == 0 or acum_a.std() == 0:
        return None
    r = float(np.corrcoef(acum_a, acum_r)[0, 1])
    pend, inter = np.polyfit(acum_r, acum_a, 1)
    # Mayor quiebre: máxima desviación de la recta ajustada, normalizada por el
    # acumulado TOTAL (no por el running, que infla los primeros años cuando el
    # acumulado es casi cero). Se ignoran los 2 primeros puntos por robustez.
    pred = pend * acum_r + inter
    total = float(acum_a[-1]) or 1.0
    desv = np.abs(acum_a - pred) / total * 100.0
    if len(desv) > 3:
        desv[:2] = 0.0
    i_max = int(np.argmax(desv))
    quiebre_pct = float(desv[i_max])

    consistente = bool(r >= 0.99 and quiebre_pct <= 10.0)
    if consistente:
        msg = (f"La fuente adoptada es CONSISTENTE con el patrón regional: "
               f"R = {r:.4f} y desviación máxima {quiebre_pct:.1f} % "
               f"(≤ 10 %), sin quiebres significativos en la curva de doble "
               f"masa.")
    else:
        msg = (f"La curva de doble masa muestra R = {r:.4f} y una desviación "
               f"máxima de {quiebre_pct:.1f} % hacia el año {anios[i_max]}; "
               f"revisar posible cambio de régimen o inconsistencia de la "
               f"fuente en ese período.")

    return ResultadoDobleMasa(
        fuente_analizada=fuente_adoptada, fuentes_referencia=nombres_ref,
        anios=anios, acum_analizada=[round(v, 1) for v in acum_a.tolist()],
        acum_referencia=[round(v, 1) for v in acum_r.tolist()],
        pearson_r=round(r, 4), pendiente=round(float(pend), 4),
        n_anios=len(df), consistente=consistente,
        quiebre_anio=int(anios[i_max]), quiebre_desviacion_pct=round(quiebre_pct, 1),
        mensaje=msg)
