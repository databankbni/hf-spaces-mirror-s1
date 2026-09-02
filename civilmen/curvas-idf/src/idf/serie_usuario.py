"""Carga de la serie de P24max OBSERVADA aportada por el usuario.

El acceso a la base de datos de SENAMHI (INADHI) NO es libre: no existe API
pública ni descarga masiva; la vía oficial es la solicitud certificada
(presencial, con costo). Por eso el programa no puede traer la serie observada
por sí solo. Este módulo permite que el ingeniero PEGUE o suba su serie ya
obtenida —diaria máxima anual (P24max) por año— para que TODO el análisis de
frecuencia se realice sobre datos observados en lugar de productos satelitales.

Formatos aceptados (uno por línea, separador flexible , ; tab o espacio):
    2001  58.4
    2002, 61.0
    2003;47.2
    ...
También acepta una sola columna de valores (se asume un año por fila, ordenados)
y encabezados de texto (se ignoran filas no numéricas). Devuelve un DataFrame
con columnas anio, p24_mm, o None si no hay al menos 10 años válidos.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

_MIN_ANIOS = 10
_P24_MAX_FISICO = 500.0   # mm/día; por encima es casi seguro error de dato
_SEP = re.compile(r"[,;\t ]+")


def parsear_serie_observada(texto: str,
                            anio_fin_defecto: int = 2020
                            ) -> Optional[pd.DataFrame]:
    """Parsea el texto pegado por el usuario a un DataFrame (anio, p24_mm).

    Robusto ante encabezados, separadores mixtos, comas decimales y líneas
    vacías. Filtra valores no físicos (≤0 o > 500 mm). Devuelve None si no se
    obtienen al menos `_MIN_ANIOS` años válidos.
    """
    if not texto or not texto.strip():
        return None
    filas: list[tuple[int, float]] = []
    solo_valores: list[float] = []
    for linea in texto.strip().splitlines():
        s = linea.strip()
        if not s:
            continue
        # Normaliza coma decimal SOLO cuando no hay separador claro de columnas.
        partes = [p for p in _SEP.split(s) if p != ""]
        nums = []
        for p in partes:
            p2 = p.replace(",", ".") if p.count(",") == 1 and "." not in p else p
            try:
                nums.append(float(p2))
            except ValueError:
                nums = []          # línea con texto (encabezado) → se ignora
                break
        if not nums:
            continue
        if len(nums) >= 2:
            anio = int(round(nums[0]))
            val = float(nums[1])
            if 1900 <= anio <= 2100 and 0 < val <= _P24_MAX_FISICO:
                filas.append((anio, round(val, 2)))
        elif len(nums) == 1:
            v = float(nums[0])
            if 0 < v <= _P24_MAX_FISICO:
                solo_valores.append(round(v, 2))

    # Preferir el formato con año explícito; si no, usar la columna de valores.
    if len(filas) >= _MIN_ANIOS:
        df = pd.DataFrame(filas, columns=["anio", "p24_mm"])
        df = df.drop_duplicates(subset="anio").sort_values("anio")
    elif len(solo_valores) >= _MIN_ANIOS:
        n = len(solo_valores)
        anios = list(range(anio_fin_defecto - n + 1, anio_fin_defecto + 1))
        df = pd.DataFrame({"anio": anios, "p24_mm": solo_valores})
    else:
        return None
    df = df.reset_index(drop=True)
    return df if len(df) >= _MIN_ANIOS else None
