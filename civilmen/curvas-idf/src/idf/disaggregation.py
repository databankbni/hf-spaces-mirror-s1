"""Desagregación de precipitación máxima 24h a duraciones sub-diarias.

Fórmula de Dyck-Peschke (ampliamente usada en Bolivia para sitios sin registro
pluviográfico):

        P_d = P_24h · (d / 1440)^n_exp        con  d en minutos

El exponente típico es n_exp = 0.25 (Dyck-Peschke clásico). Algunos manuales
SENAMHI y guías ABC usan rangos 0.20–0.30 según la región.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


# 5 segmentos uniformes en 0-60 min (12, 24, 36, 48, 60) + duraciones largas
# hasta 24 h. La resolución fina en sub-hora es útil para tiempos de
# concentración cortos típicos de cuencas urbanas pequeñas (pasarela).
# Duraciones sub-horarias EXIGIDAS por el Manual de Hidrología y Drenaje ABC
# (5, 10, 15, 30 min) + segmentos hasta 60 min. Bajo ~10 min la desagregación
# de Dyck-Peschke es una extrapolación (se advierte en el informe).
DURACIONES_FINAS_HORA_MIN: tuple[int, ...] = (5, 10, 15, 30, 45, 60)
DURACIONES_LARGAS_MIN: tuple[int, ...] = (90, 120, 180, 240, 360, 480, 720, 1440)
DURACIONES_DEFAULT_MIN: tuple[int, ...] = DURACIONES_FINAS_HORA_MIN + DURACIONES_LARGAS_MIN


# Exponente de Dyck-Peschke por región climática de Bolivia. El 0.25 clásico
# es el promedio europeo; el skill «estudio-hidrologico-bolivia» (curvas-idf.md)
# indica que en Bolivia conviene 0.21–0.28 según región, y que Yungas requiere
# 0.28–0.30 (error frecuente: usar 0.25 sin verificar). Un exponente mayor
# concentra más la lluvia en duraciones cortas → mayor intensidad.
EXPONENTE_DYCK_PESCHKE_REGION = {
    "altiplano":     0.22,
    "puna":          0.22,
    "nival":         0.22,
    "valles":        0.25,
    "prepuna":       0.25,
    "yungas":        0.29,
    "tierras_bajas": 0.27,   # llanos amazónicos / chaco
}


def exponente_dyck_peschke(lat: float, lon: float,
                              altitud_m: float | None = None) -> tuple[float, str]:
    """Devuelve (exponente, región) de Dyck-Peschke para el sitio.

    Usa la clasificación de pisos ecológicos de Bolivia. Si no se puede
    clasificar, devuelve el 0.25 clásico.
    """
    try:
        from .pisos_ecologicos import clasificar
        piso = clasificar(lat, lon, altitud_m)
        exp = EXPONENTE_DYCK_PESCHKE_REGION.get(piso.clave, 0.25)
        return exp, piso.nombre
    except Exception:  # noqa: BLE001
        return 0.25, "región no clasificada"


def desagregar_dyck_peschke(
    p24_por_T: pd.DataFrame,
    duraciones_min: Sequence[int] = DURACIONES_DEFAULT_MIN,
    exponente: float = 0.25,
) -> pd.DataFrame:
    """Devuelve un DataFrame en formato largo con columnas:
    T_anios, duracion_min, p_mm, i_mm_h.

    p24_por_T debe contener al menos las columnas 'T_anios' y 'p24_mm'.
    """
    if not (0.0 < exponente < 1.0):
        raise ValueError("Exponente de Dyck-Peschke debe estar en (0, 1).")
    duraciones = np.asarray(duraciones_min, dtype=float)
    filas = []
    for _, row in p24_por_T.iterrows():
        P24 = float(row["p24_mm"])
        T = int(row["T_anios"])
        Pd = P24 * (duraciones / 1440.0) ** exponente
        Id = Pd / (duraciones / 60.0)  # mm/h
        for d, p, i in zip(duraciones, Pd, Id):
            filas.append(
                {
                    "T_anios": T,
                    "duracion_min": int(d),
                    "p_mm": float(p),
                    "i_mm_h": float(i),
                }
            )
    return pd.DataFrame(filas)
