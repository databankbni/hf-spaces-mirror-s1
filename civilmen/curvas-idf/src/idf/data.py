"""Datos de estaciones SENAMHI Bolivia y generador sintético por coordenadas.

SENAMHI publica precipitación máxima diaria (P24max) por estación. Aquí se
mantiene un catálogo reducido de estaciones representativas con coordenadas
y parámetros climatológicos (media y desviación estándar de P24max anual)
calibrados con valores típicos reportados en estudios IDF para Bolivia.

El catálogo NO sustituye a los datos oficiales de SENAMHI; sirve para localizar
la estación más cercana a una coordenada y, en ausencia de datos reales, generar
una serie sintética coherente con el régimen climático del sitio.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import radians, sin, cos, asin, sqrt
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EstacionSenamhi:
    """Estación pluviométrica del catálogo SENAMHI."""

    codigo: str
    nombre: str
    departamento: str
    latitud: float        # grados decimales (negativo = sur)
    longitud: float       # grados decimales (negativo = oeste)
    altitud_msnm: float
    p24_media_mm: float   # media anual de P24max [mm]
    p24_desv_mm: float    # desviación estándar de P24max [mm]


# Catálogo representativo (valores climatológicos típicos, no son medidas oficiales).
ESTACIONES_SENAMHI: tuple[EstacionSenamhi, ...] = (
    EstacionSenamhi("LPB-01", "El Alto AASANA",          "La Paz",       -16.5133, -68.1925, 4061,  32.0,  9.0),
    EstacionSenamhi("LPB-02", "La Paz Central",          "La Paz",       -16.5000, -68.1500, 3640,  35.0, 10.5),
    EstacionSenamhi("CBB-01", "Cochabamba AASANA",       "Cochabamba",   -17.4214, -66.1747, 2548,  38.0, 11.5),
    EstacionSenamhi("SCZ-01", "Viru-Viru",               "Santa Cruz",   -17.6448, -63.1353,  373,  78.0, 22.0),
    EstacionSenamhi("SCZ-02", "Trompillo",               "Santa Cruz",   -17.8158, -63.1714,  413,  82.0, 24.5),
    EstacionSenamhi("TJA-01", "Tarija AASANA",           "Tarija",       -21.5556, -64.7014, 1854,  46.0, 13.0),
    EstacionSenamhi("ORU-01", "Oruro AASANA",            "Oruro",        -17.9628, -67.0761, 3702,  28.0,  8.5),
    EstacionSenamhi("PTS-01", "Potosí",                  "Potosí",       -19.5836, -65.7531, 3936,  30.0,  9.0),
    EstacionSenamhi("SRE-01", "Sucre AASANA",            "Chuquisaca",   -19.0078, -65.2917, 2904,  42.0, 12.5),
    EstacionSenamhi("BNI-01", "Trinidad AASANA",         "Beni",         -14.8186, -64.9181,  156,  95.0, 28.0),
    EstacionSenamhi("PAN-01", "Cobija AASANA",           "Pando",        -11.0408, -68.7828,  235, 102.0, 30.0),
    EstacionSenamhi("LPB-03", "Copacabana",              "La Paz",       -16.1667, -69.0833, 3841,  30.0,  8.0),
    # --- Cochabamba (región ampliada) ---
    EstacionSenamhi("CBB-02", "Sacabamba",               "Cochabamba",   -17.8000, -65.7833, 2750,  40.0, 12.0),
    EstacionSenamhi("CBB-03", "Sacaba",                  "Cochabamba",   -17.4050, -66.0411, 2680,  39.0, 11.8),
    EstacionSenamhi("CBB-04", "Punata",                  "Cochabamba",   -17.5419, -65.8331, 2730,  41.0, 12.2),
    EstacionSenamhi("CBB-05", "Cliza",                   "Cochabamba",   -17.5928, -65.9333, 2720,  41.5, 12.4),
    EstacionSenamhi("CBB-06", "Tarata",                  "Cochabamba",   -17.6097, -66.0153, 2750,  40.5, 12.1),
    EstacionSenamhi("CBB-07", "Aiquile",                 "Cochabamba",   -18.2000, -65.1833, 2250,  44.0, 13.5),
    EstacionSenamhi("CBB-08", "Mizque",                  "Cochabamba",   -17.9417, -65.3403, 2045,  43.0, 13.0),
    EstacionSenamhi("CBB-09", "Totora",                  "Cochabamba",   -17.7333, -65.1903, 2810,  45.0, 13.8),
    EstacionSenamhi("CBB-10", "Quillacollo",             "Cochabamba",   -17.3931, -66.2792, 2560,  38.5, 11.6),
    EstacionSenamhi("CBB-11", "Tiraque",                 "Cochabamba",   -17.4167, -65.7167, 3300,  47.0, 14.0),
    EstacionSenamhi("CBB-12", "Independencia",           "Cochabamba",   -17.0833, -66.8167, 2860,  46.5, 14.2),
    EstacionSenamhi("CBB-13", "Villa Tunari (Chapare)",  "Cochabamba",   -16.9742, -65.4128,  300, 120.0, 35.0),
    # --- La Paz (ampliada) ---
    EstacionSenamhi("LPB-04", "Patacamaya",              "La Paz",       -17.2417, -67.9211, 3789,  29.0,  8.2),
    EstacionSenamhi("LPB-05", "Coroico",                 "La Paz",       -16.1900, -67.7269, 1525,  85.0, 24.0),
    EstacionSenamhi("LPB-06", "Caranavi",                "La Paz",       -15.8333, -67.5667,  600, 100.0, 29.0),
    EstacionSenamhi("LPB-07", "Charaña",                 "La Paz",       -17.5917, -69.4458, 4057,  22.0,  6.5),
    EstacionSenamhi("LPB-08", "Achacachi",               "La Paz",       -16.0500, -68.6833, 3854,  31.0,  8.4),
    # --- Santa Cruz (ampliada) ---
    EstacionSenamhi("SCZ-03", "Montero",                 "Santa Cruz",   -17.3389, -63.2506,  287,  84.0, 25.0),
    EstacionSenamhi("SCZ-04", "Vallegrande",             "Santa Cruz",   -18.4900, -64.1058, 2030,  50.0, 15.0),
    EstacionSenamhi("SCZ-05", "Camiri",                  "Santa Cruz",   -20.0383, -63.5236,  810,  60.0, 18.0),
    EstacionSenamhi("SCZ-06", "Puerto Suárez",           "Santa Cruz",   -18.9633, -57.8008,  134, 110.0, 32.0),
    EstacionSenamhi("SCZ-07", "San Ignacio de Velasco",  "Santa Cruz",   -16.3719, -60.9525,  413,  95.0, 28.0),
    EstacionSenamhi("SCZ-08", "Concepción",              "Santa Cruz",   -16.1383, -62.0211,  490,  92.0, 27.0),
    # --- Chuquisaca / Tarija / Potosí (ampliada) ---
    EstacionSenamhi("SRE-02", "Monteagudo",              "Chuquisaca",   -19.7989, -63.9569, 1130,  58.0, 17.0),
    EstacionSenamhi("SRE-03", "Camargo",                 "Chuquisaca",   -20.6406, -65.2122, 2410,  38.0, 11.5),
    EstacionSenamhi("TJA-02", "Yacuiba AASANA",          "Tarija",       -21.9608, -63.6519,  644,  70.0, 21.0),
    EstacionSenamhi("TJA-03", "Bermejo",                 "Tarija",       -22.7333, -64.3333,  415,  66.0, 19.5),
    EstacionSenamhi("TJA-04", "Villa Montes AASANA",     "Tarija",       -21.2553, -63.4072,  402,  68.0, 20.0),
    EstacionSenamhi("PTS-02", "Uyuni",                   "Potosí",       -20.4597, -66.8253, 3669,  20.0,  6.0),
    EstacionSenamhi("PTS-03", "Tupiza",                  "Potosí",       -21.4439, -65.7197, 2950,  28.0,  8.5),
    EstacionSenamhi("PTS-04", "Villazón",                "Potosí",       -22.0869, -65.5944, 3443,  26.0,  7.8),
    # --- Oruro / Beni / Pando (ampliada) ---
    EstacionSenamhi("ORU-02", "Huanuni",                 "Oruro",        -18.2719, -66.8369, 3970,  27.0,  8.0),
    EstacionSenamhi("ORU-03", "Sajama",                  "Oruro",        -18.1000, -68.9667, 4220,  24.0,  7.0),
    EstacionSenamhi("BNI-02", "Riberalta AASANA",        "Beni",         -10.9931, -66.0936,  141, 105.0, 31.0),
    EstacionSenamhi("BNI-03", "Rurrenabaque",            "Beni",         -14.4419, -67.5281,  204, 110.0, 32.0),
    EstacionSenamhi("BNI-04", "Guayaramerín",            "Beni",         -10.8258, -65.3608,  130, 104.0, 30.5),
    EstacionSenamhi("BNI-05", "San Borja",               "Beni",         -14.8581, -66.7508,  194, 108.0, 31.5),
    EstacionSenamhi("PAN-02", "Puerto Rico (Pando)",     "Pando",        -11.1050, -67.5519,  180, 100.0, 29.5),
)



def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia ortodrómica en km entre dos coordenadas geográficas."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def estacion_mas_cercana(
    latitud: float,
    longitud: float,
    catalogo: Sequence[EstacionSenamhi] = ESTACIONES_SENAMHI,
) -> tuple[EstacionSenamhi, float]:
    """Devuelve la estación SENAMHI más cercana y la distancia en km."""
    if not catalogo:
        raise ValueError("Catálogo de estaciones vacío.")
    mejor = min(
        catalogo,
        key=lambda e: _haversine_km(latitud, longitud, e.latitud, e.longitud),
    )
    dist = _haversine_km(latitud, longitud, mejor.latitud, mejor.longitud)
    return mejor, dist


def estaciones_cercanas(
    latitud: float,
    longitud: float,
    k: int = 3,
    catalogo: Sequence[EstacionSenamhi] = ESTACIONES_SENAMHI,
) -> list[tuple[EstacionSenamhi, float]]:
    """Devuelve las k estaciones más cercanas con su distancia (km), ordenadas."""
    pares = [
        (e, _haversine_km(latitud, longitud, e.latitud, e.longitud))
        for e in catalogo
    ]
    pares.sort(key=lambda p: p[1])
    return pares[:k]


def interpolar_idw(
    latitud: float,
    longitud: float,
    k: int = 3,
    potencia: float = 2.0,
    catalogo: Sequence[EstacionSenamhi] = ESTACIONES_SENAMHI,
) -> dict[str, float]:
    """Interpolación por distancia inversa (IDW) de las k estaciones más cercanas.

    "Triangulación" práctica: pondera media y desviación de P24max de las k
    estaciones vecinas por 1/d^potencia. Útil cuando el sitio cae entre varias
    estaciones. Devuelve {p24_media_mm, p24_desv_mm, altitud_msnm}.
    """
    vecinas = estaciones_cercanas(latitud, longitud, k, catalogo)
    # Si el sitio coincide con una estación (d≈0), usar esa directamente.
    e0, d0 = vecinas[0]
    if d0 < 1e-6:
        return {
            "p24_media_mm": e0.p24_media_mm,
            "p24_desv_mm": e0.p24_desv_mm,
            "altitud_msnm": e0.altitud_msnm,
        }
    pesos = [1.0 / (d ** potencia) for _, d in vecinas]
    sw = sum(pesos)
    return {
        "p24_media_mm": sum(w * e.p24_media_mm for w, (e, _) in zip(pesos, vecinas)) / sw,
        "p24_desv_mm": sum(w * e.p24_desv_mm for w, (e, _) in zip(pesos, vecinas)) / sw,
        "altitud_msnm": sum(w * e.altitud_msnm for w, (e, _) in zip(pesos, vecinas)) / sw,
    }


def serie_anual_maxima_sintetica(
    estacion: EstacionSenamhi,
    n_anios: int = 30,
    anio_inicio: int | None = None,
    anio_fin: int | None = None,
    semilla: int | None = 42,
) -> pd.DataFrame:
    """Genera una serie sintética de P24max anual (mm) coherente con la estación.

    Se usa una distribución Gumbel (EV-I) que es el modelo más común para
    máximos anuales de precipitación diaria. Los parámetros (β, μ) se derivan
    de la media y desviación reportadas en el catálogo:

        β = σ·√6/π     ;     μ = media − γ·β       (γ ≈ 0.5772)

    Por defecto la serie termina en el **año pasado** (último año completo) y
    cuenta `n_anios` hacia atrás, evitando proyectar al futuro. El usuario
    puede forzar `anio_inicio` y/o `anio_fin` si lo necesita explícitamente.
    """
    if n_anios < 5:
        raise ValueError("Se requieren al menos 5 años para análisis de frecuencias.")
    if anio_inicio is None and anio_fin is None:
        import datetime as _dt
        anio_fin = _dt.date.today().year - 1
        anio_inicio = anio_fin - n_anios + 1
    elif anio_inicio is None:
        anio_inicio = anio_fin - n_anios + 1
    elif anio_fin is None:
        anio_fin = anio_inicio + n_anios - 1
    else:
        # Ambos dados: se respeta el rango aunque difiera de n_anios.
        n_anios = anio_fin - anio_inicio + 1
    rng = np.random.default_rng(semilla)
    beta = estacion.p24_desv_mm * np.sqrt(6.0) / np.pi
    mu = estacion.p24_media_mm - 0.5772 * beta
    muestras = rng.gumbel(loc=mu, scale=beta, size=n_anios)
    muestras = np.clip(muestras, a_min=1.0, a_max=None)  # P24 no puede ser ≤ 0
    return pd.DataFrame(
        {
            "anio": np.arange(anio_inicio, anio_inicio + n_anios),
            "p24_mm": np.round(muestras, 2),
        }
    )
