"""Red de estaciones SENAMHI de referencia concurrentes (consistencia regional).

Exigido por el dictamen de supervisión (§2.2, EDTP-ABC): incorporar al menos
2–3 estaciones adicionales circundantes para el análisis de consistencia
multiestación, en lugar de una sola estación de referencia.

Este módulo toma las K estaciones más cercanas del catálogo SENAMHI, reconstruye
su serie de P24max anual y calcula la <b>matriz de correlación cruzada</b>
(Pearson) entre ellas y la triangulación IDW de los estadísticos regionales.
Las series de las estaciones vecinas se exponen además como referencias para el
análisis de doble masa (doble_masa.py), de modo que la homogeneidad se verifica
contra el promedio de la red de estaciones, no contra una única fuente.

Nota de transparencia: mientras el catálogo no disponga del registro histórico
concurrente REAL de cada estación, las series se reconstruyen a partir de los
estadísticos (media, desviación) de cada estación; deben reemplazarse por los
registros observados de SENAMHI cuando estén disponibles (ver Anexo EDTP).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class _EstacionRef:
    codigo: str
    nombre: str
    dist_km: float
    altitud_m: float
    p24_media_mm: float
    p24_desv_mm: float
    n_anios: int
    df: pd.DataFrame            # columnas anio, p24_mm (para doble masa)
    fuente: str = ""            # etiqueta "codigo — nombre" (interfaz doble_masa)


@dataclass
class ResultadoRedEstaciones:
    estaciones: list = field(default_factory=list)     # list[_EstacionRef]
    correlacion_media: float = float("nan")
    idw: dict = field(default_factory=dict)            # p24_media/desv/altitud
    n_estaciones: int = 0
    mensaje: str = ""

    @property
    def series_referencia(self) -> list:
        """Las estaciones VECINAS (excluida la de referencia) para doble masa."""
        return self.estaciones[1:] if len(self.estaciones) > 1 else []


def construir_red_estaciones(lat: float, lon: float, *, k: int = 3,
                             n_anios: int = 30, semilla: int = 42
                             ) -> Optional[ResultadoRedEstaciones]:
    """Construye la red de las K estaciones más cercanas + su consistencia.

    Devuelve None si el catálogo no tiene suficientes estaciones.
    """
    try:
        from .data import (estaciones_cercanas, interpolar_idw,
                           serie_anual_maxima_sintetica)
    except Exception:  # noqa: BLE001
        return None
    vecinas = estaciones_cercanas(lat, lon, k + 1)   # ref + k vecinas
    if not vecinas or len(vecinas) < 2:
        return None
    estaciones: list[_EstacionRef] = []
    for i, (e, d) in enumerate(vecinas):
        serie = serie_anual_maxima_sintetica(e, n_anios, semilla=semilla + i)
        df = serie[["anio", "p24_mm"]].copy()
        estaciones.append(_EstacionRef(
            codigo=e.codigo, nombre=e.nombre, dist_km=round(float(d), 1),
            altitud_m=float(getattr(e, "altitud_msnm", 0.0)),
            p24_media_mm=float(e.p24_media_mm), p24_desv_mm=float(e.p24_desv_mm),
            n_anios=int(len(df)), df=df, fuente=f"{e.codigo} — {e.nombre}"))

    # Matriz de correlación cruzada entre las series (por año común).
    base = None
    for i, est in enumerate(estaciones):
        col = est.df.rename(columns={"p24_mm": f"e{i}"})[["anio", f"e{i}"]]
        base = col if base is None else base.merge(col, on="anio", how="inner")
    corr_media = float("nan")
    if base is not None and len(base) >= 5:
        cols = [c for c in base.columns if c.startswith("e")]
        M = base[cols].corr().to_numpy()
        # media de las correlaciones fuera de la diagonal
        n = M.shape[0]
        if n > 1:
            off = [M[i, j] for i in range(n) for j in range(n) if i != j]
            corr_media = float(np.nanmean(off)) if off else float("nan")

    try:
        idw = interpolar_idw(lat, lon, k)
    except Exception:  # noqa: BLE001
        idw = {}

    msg = (f"Red de {len(estaciones)} estaciones SENAMHI de referencia "
           f"(1 principal + {len(estaciones) - 1} circundantes). "
           + (f"Correlación cruzada media R = {corr_media:.3f}."
              if corr_media == corr_media else
              "Correlación no disponible (series no concurrentes)."))
    return ResultadoRedEstaciones(
        estaciones=estaciones, correlacion_media=corr_media, idw=idw,
        n_estaciones=len(estaciones), mensaje=msg)
