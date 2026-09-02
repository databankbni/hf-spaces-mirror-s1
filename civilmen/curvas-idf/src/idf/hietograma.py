"""Hietograma de diseño por el método de bloques alternos (Alternating Block).

Dado el modelo IDF, un período de retorno T y una duración total D (igual al
tiempo de concentración), se discretiza D en bloques de Δt y se construye el
hietograma reordenando las profundidades incrementales de modo que el bloque
máximo quede al centro y los demás se alternen a izquierda y derecha en orden
decreciente (Chow, Maidment & Mays, 1994).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .idf import ModeloIDF


def _delta_t_automatico(duracion_min: float) -> float:
    """Δt ≈ D/10 redondeado al múltiplo de 5 min más cercano (mínimo 5)."""
    bruto = duracion_min / 10.0
    dt = round(bruto / 5.0) * 5.0
    return max(dt, 5.0)


@dataclass
class Hietograma:
    T_anios: int
    duracion_min: float
    delta_t_min: float
    n_bloques: int
    tabla: pd.DataFrame   # columnas: t_min, intensidad_mm_h, p_incremental_mm, p_acumulada_mm
    p_total_mm: float
    i_pico_mm_h: float


def bloques_alternos(
    modelo: ModeloIDF,
    T_anios: int,
    duracion_min: float,
    delta_t_min: float | None = None,
) -> Hietograma:
    """Construye el hietograma de bloques alternos.

    modelo: modelo IDF de Sherman ajustado.
    T_anios: período de retorno de diseño.
    duracion_min: duración total (= tiempo de concentración).
    delta_t_min: intervalo; si None, se usa D/10 redondeado a 5 min.
    """
    if duracion_min <= 0:
        raise ValueError("La duración debe ser positiva.")
    dt = float(delta_t_min) if delta_t_min else _delta_t_automatico(duracion_min)
    n = max(int(round(duracion_min / dt)), 1)

    # 1) Intensidades y profundidades acumuladas para d = dt, 2dt, ..., n·dt
    duraciones = np.arange(1, n + 1) * dt          # min
    intensidades = np.array([modelo.intensidad(T_anios, d) for d in duraciones])  # mm/h
    p_acum = intensidades * duraciones / 60.0      # mm

    # 2) Profundidades incrementales
    incrementos = np.diff(np.concatenate([[0.0], p_acum]))  # length n

    # 3) Reordenamiento de bloques alternos: máximo al centro, alternando.
    orden_desc = np.sort(incrementos)[::-1]        # incrementos en orden decreciente
    posiciones = np.empty(n, dtype=int)
    centro = (n - 1) // 2
    izquierda, derecha = centro - 1, centro + 1
    posiciones[centro] = 0  # el mayor (índice 0 de orden_desc) va al centro
    siguiente = 1
    poner_derecha = True
    while siguiente < n:
        if poner_derecha and derecha < n:
            posiciones[derecha] = siguiente
            derecha += 1
            siguiente += 1
        elif not poner_derecha and izquierda >= 0:
            posiciones[izquierda] = siguiente
            izquierda -= 1
            siguiente += 1
        elif derecha < n:
            posiciones[derecha] = siguiente
            derecha += 1
            siguiente += 1
        elif izquierda >= 0:
            posiciones[izquierda] = siguiente
            izquierda -= 1
            siguiente += 1
        poner_derecha = not poner_derecha

    bloques = orden_desc[posiciones]               # profundidad incremental por bloque (mm)
    tiempos = np.arange(1, n + 1) * dt             # extremo derecho de cada bloque (min)
    intens_bloque = bloques / (dt / 60.0)          # mm/h por bloque
    p_acumulada_hieto = np.cumsum(bloques)

    tabla = pd.DataFrame(
        {
            "t_min": tiempos.astype(float),
            "intensidad_mm_h": np.round(intens_bloque, 3),
            "p_incremental_mm": np.round(bloques, 3),
            "p_acumulada_mm": np.round(p_acumulada_hieto, 3),
        }
    )
    return Hietograma(
        T_anios=int(T_anios),
        duracion_min=float(duracion_min),
        delta_t_min=float(dt),
        n_bloques=n,
        tabla=tabla,
        p_total_mm=float(np.sum(bloques)),
        i_pico_mm_h=float(np.max(intens_bloque)),
    )


# Distribución temporal SCS 24 h adimensional, Tipo II (la más usada).
# Fracción de P acumulada vs fracción de tiempo (Pt/P24 en t/24).
_SCS_T2_T = np.array([0.0, 0.1, 0.2, 0.3, 0.35, 0.4, 0.45, 0.48, 0.5,
                      0.52, 0.55, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0])
_SCS_T2_P = np.array([0.0, 0.022, 0.048, 0.080, 0.098, 0.120, 0.147, 0.181, 0.500,
                      0.702, 0.760, 0.823, 0.870, 0.903, 0.952, 0.980, 1.0])


def scs_tipo2(
    modelo,
    T_anios: int,
    duracion_min: float,
    delta_t_min: float | None = None,
) -> Hietograma:
    """Hietograma por la distribución temporal SCS Tipo II (adimensional).

    La profundidad total se toma de la IDF para la duración dada y se reparte
    según la curva acumulada SCS Tipo II reescalada a la duración.
    """
    dt = float(delta_t_min) if delta_t_min else _delta_t_automatico(duracion_min)
    n = max(int(round(duracion_min / dt)), 1)
    p_total = modelo.intensidad(T_anios, duracion_min) * duracion_min / 60.0

    tiempos = np.arange(1, n + 1) * dt
    frac_t = tiempos / duracion_min
    p_acum = np.interp(frac_t, _SCS_T2_T, _SCS_T2_P) * p_total
    incr = np.diff(np.concatenate([[0.0], p_acum]))
    intens = incr / (dt / 60.0)
    tabla = pd.DataFrame({
        "t_min": tiempos.astype(float),
        "intensidad_mm_h": np.round(intens, 3),
        "p_incremental_mm": np.round(incr, 3),
        "p_acumulada_mm": np.round(p_acum, 3),
    })
    return Hietograma(int(T_anios), float(duracion_min), float(dt), n, tabla,
                      float(p_acum[-1]), float(np.max(intens)))


def chicago(
    modelo,
    T_anios: int,
    duracion_min: float,
    delta_t_min: float | None = None,
    r: float = 0.4,
) -> Hietograma:
    """Hietograma de Chicago (Keifer & Chu, 1957) a partir del modelo IDF.

    Usa la forma Sherman i = a·T^m/(d+b)^n del modelo (si está disponible) para
    derivar la intensidad instantánea antes/después del pico:
        antes:   i(t_b) = a'·((1−n)·t_b/r + b) / (t_b/r + b)^(n+1)
        después: i(t_a) = a'·((1−n)·t_a/(1−r) + b) / (t_a/(1−r) + b)^(n+1)
    con a' = a·T^m. r = coeficiente de avance de la tormenta (posición del pico).
    """
    a = getattr(modelo, "a", None)
    b = getattr(modelo, "b", None)
    n = getattr(modelo, "n", None)
    m = getattr(modelo, "m", None)
    if a is None or b is None or n is None or m is None:
        # Si el modelo no es Sherman, caer a bloques alternos.
        return bloques_alternos(modelo, T_anios, duracion_min, delta_t_min)

    dt = float(delta_t_min) if delta_t_min else _delta_t_automatico(duracion_min)
    nb = max(int(round(duracion_min / dt)), 1)
    a_prima = a * T_anios ** m
    t_pico = r * duracion_min

    centros = (np.arange(nb) + 0.5) * dt
    intens = np.empty(nb)
    for k, tc in enumerate(centros):
        if tc <= t_pico:
            tb = (t_pico - tc) / r
            intens[k] = a_prima * ((1 - n) * tb + b) / (tb + b) ** (n + 1)
        else:
            ta = (tc - t_pico) / (1 - r)
            intens[k] = a_prima * ((1 - n) * ta + b) / (ta + b) ** (n + 1)
    intens = np.clip(intens, 0.0, None)
    incr = intens * (dt / 60.0)
    p_acum = np.cumsum(incr)
    tiempos = np.arange(1, nb + 1) * dt
    tabla = pd.DataFrame({
        "t_min": tiempos.astype(float),
        "intensidad_mm_h": np.round(intens, 3),
        "p_incremental_mm": np.round(incr, 3),
        "p_acumulada_mm": np.round(p_acum, 3),
    })
    return Hietograma(int(T_anios), float(duracion_min), float(dt), nb, tabla,
                      float(p_acum[-1]), float(np.max(intens)))


# ---------------------------------------------------------------------------
# Método de Huff (1967) — distribución empírica adimensional por cuartiles.
# Referencia: Huff, F.A. (1967). "Time distribution of rainfall in heavy
# storms." Water Resources Research, 3(4), 1007-1019.
#
# Para cada cuartil (1..4) se da la masa acumulada mediana (P/P_tot) vs el
# tiempo adimensional (t/D). El cuartil indica en qué cuarto de la duración
# total ocurre la mayor intensidad: Q1 tormentas convectivas (pico temprano),
# Q2 frontales (pico al medio, recomendado para cuencas medianas), Q3 estrato-
# frontales (pico tardío-medio), Q4 estratiformes largas (pico tardío).
# Para A > 25 km² (tormentas más largas) se prefiere Q2.
# ---------------------------------------------------------------------------
_HUFF_T = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
_HUFF_MEDIANA = {
    1: np.array([0.00, 0.16, 0.33, 0.43, 0.52, 0.62, 0.71, 0.79, 0.86, 0.93, 1.00]),
    2: np.array([0.00, 0.03, 0.08, 0.12, 0.25, 0.50, 0.75, 0.86, 0.92, 0.96, 1.00]),
    3: np.array([0.00, 0.03, 0.08, 0.15, 0.21, 0.30, 0.46, 0.71, 0.86, 0.95, 1.00]),
    4: np.array([0.00, 0.02, 0.05, 0.08, 0.14, 0.20, 0.28, 0.42, 0.64, 0.84, 1.00]),
}


def huff(modelo, T_anios: int, duracion_min: float,
         delta_t_min: float | None = None,
         cuartil: int = 2) -> Hietograma:
    """Hietograma por la curva mediana de Huff (1967) para el cuartil dado.

    cuartil = 1, 2, 3 o 4. Default = 2 (tormentas frontales, recomendado para
    cuencas medianas y grandes A > 25 km²).
    """
    if cuartil not in _HUFF_MEDIANA:
        raise ValueError(f"Cuartil de Huff inválido: {cuartil} (use 1..4)")
    dt = float(delta_t_min) if delta_t_min else _delta_t_automatico(duracion_min)
    n = max(int(round(duracion_min / dt)), 1)
    p_total = modelo.intensidad(T_anios, duracion_min) * duracion_min / 60.0
    tiempos = np.arange(1, n + 1) * dt
    frac_t = tiempos / duracion_min
    p_acum = np.interp(frac_t, _HUFF_T, _HUFF_MEDIANA[cuartil]) * p_total
    incr = np.diff(np.concatenate([[0.0], p_acum]))
    intens = incr / (dt / 60.0)
    tabla = pd.DataFrame({
        "t_min": tiempos.astype(float),
        "intensidad_mm_h": np.round(intens, 3),
        "p_incremental_mm": np.round(incr, 3),
        "p_acumulada_mm": np.round(p_acum, 3),
    })
    return Hietograma(int(T_anios), float(duracion_min), float(dt), n, tabla,
                      float(p_acum[-1]), float(np.max(intens)))
