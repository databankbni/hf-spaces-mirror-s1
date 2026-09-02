"""Múltiples modelos de ajuste de curvas IDF.

Todos se calibran sobre la tabla larga (T, duración d [min], intensidad i [mm/h])
obtenida de la desagregación. Cada modelo expone:
  - parametros: dict de parámetros calibrados
  - ecuacion: cadena legible de la ecuación
  - intensidad(T, d): evaluación
  - r2, rmse_mm_h: bondad de ajuste en el espacio original

Modelos (la familia/forma exacta se documenta explícitamente en cada uno):
  1. Sherman                i = a·T^m / (d + b)^n
  2. Chen                   i = a·T^m / d^n                  (potencia, base de Chen)
  3. Chen modificado        i = a·T^m / (d^c + b)            (denominador Kimijima)
  4. Wenzel                 i = a·T^m / (d + b)              (Talbot generalizado)
  5. Témez                  I_t/I_d = (I1/Id)^((28^0.1−t^0.1)/(28^0.1−1))
  6. Témez modificado       igual con exponente p calibrado
  7. Curva promedio adimensional   φ̄(d/d_ref) re-dimensionalizada
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar


@dataclass
class ModeloIDFGenerico:
    nombre: str
    ecuacion: str
    parametros: dict
    r2: float
    rmse_mm_h: float
    _func: Callable[[float, float], float] = field(repr=False, default=None)

    def intensidad(self, T: float, d_min: float) -> float:
        return float(self._func(T, d_min))


def _metricas(T, d, i, func) -> tuple[float, float]:
    pred = np.array([func(t, dd) for t, dd in zip(T, d)])
    ss_res = float(np.sum((i - pred) ** 2))
    ss_tot = float(np.sum((i - i.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    rmse = float(np.sqrt(ss_res / len(i)))
    return r2, rmse


def _arrays(idf_largo: pd.DataFrame):
    T = idf_largo["T_anios"].to_numpy(float)
    d = idf_largo["duracion_min"].to_numpy(float)
    i = idf_largo["i_mm_h"].to_numpy(float)
    return T, d, i


# --- 1. Sherman: a·T^m/(d+b)^n -------------------------------------------------

def _fit_sherman(T, d, i) -> ModeloIDFGenerico:
    def amn_dado_b(b):
        X = np.column_stack([np.ones_like(T), np.log(T), -np.log(d + b)])
        coef, *_ = np.linalg.lstsq(X, np.log(i), rcond=None)
        return coef, float(np.sum((np.log(i) - X @ coef) ** 2))

    res = minimize_scalar(lambda b: amn_dado_b(b)[1], bounds=(0.0, max(d) * 5),
                          method="bounded")
    b = float(res.x)
    (ln_a, m, n), _ = amn_dado_b(b)
    a = float(np.exp(ln_a))
    f = lambda Tt, dd: a * Tt ** m / (dd + b) ** n
    r2, rmse = _metricas(T, d, i, f)
    return ModeloIDFGenerico("Sherman", "i = a·T^m / (d + b)^n",
                             {"a": a, "b": b, "m": m, "n": n}, r2, rmse, f)


# --- 2. Chen (potencia pura): a·T^m/d^n ---------------------------------------

def _fit_chen(T, d, i) -> ModeloIDFGenerico:
    X = np.column_stack([np.ones_like(T), np.log(T), -np.log(d)])
    (ln_a, m, n), *_ = np.linalg.lstsq(X, np.log(i), rcond=None)
    a = float(np.exp(ln_a))
    f = lambda Tt, dd: a * Tt ** m / dd ** n
    r2, rmse = _metricas(T, d, i, f)
    return ModeloIDFGenerico("Chen", "i = a·T^m / d^n",
                             {"a": a, "m": float(m), "n": float(n)}, r2, rmse, f)


# --- 3. Chen modificado: a·T^m/(d^c + b) --------------------------------------

def _fit_chen_mod(T, d, i) -> ModeloIDFGenerico:
    # i = a·T^m / (d^c + b)^p  (Kimijima generalizado: denominador con exponente p)
    lni = np.log(i)
    mejor = None
    for c in np.linspace(0.3, 1.5, 25):
        dc = d ** c
        def amp_dado_b(b):
            # ln i = ln a + m·ln T − p·ln(d^c + b)
            X = np.column_stack([np.ones_like(T), np.log(T), -np.log(dc + b)])
            coef, *_ = np.linalg.lstsq(X, lni, rcond=None)
            return coef, float(np.sum((lni - X @ coef) ** 2))
        res = minimize_scalar(lambda b: amp_dado_b(b)[1],
                              bounds=(1e-3, max(dc) * 5), method="bounded")
        b = float(res.x)
        coef, sse = amp_dado_b(b)
        if mejor is None or sse < mejor[0]:
            mejor = (sse, coef, b, c)
    _, (ln_a, m, p), b, c = mejor
    a = float(np.exp(ln_a))
    f = lambda Tt, dd: a * Tt ** m / (dd ** c + b) ** p
    r2, rmse = _metricas(T, d, i, f)
    return ModeloIDFGenerico("Chen modificado", "i = a·T^m / (d^c + b)^p",
                             {"a": a, "b": b, "c": float(c), "p": float(p),
                              "m": float(m)}, r2, rmse, f)


# --- 4. Wenzel (Talbot generalizado): a·T^m/(d + b) ---------------------------

def _fit_wenzel(T, d, i) -> ModeloIDFGenerico:
    # Wenzel (1982) / Kimijima: i = a·T^m / (d^c + b)  (denominador potencia c, exp 1)
    lni = np.log(i)
    mejor = None
    for c in np.linspace(0.5, 1.3, 17):
        dc = d ** c
        def am_dado_b(b):
            # ln i + ln(d^c+b) = ln a + m·ln T
            y = lni + np.log(dc + b)
            X = np.column_stack([np.ones_like(T), np.log(T)])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            return coef, float(np.sum((y - X @ coef) ** 2))
        res = minimize_scalar(lambda b: am_dado_b(b)[1],
                              bounds=(1e-3, max(dc) * 5), method="bounded")
        b = float(res.x)
        coef, sse = am_dado_b(b)
        if mejor is None or sse < mejor[0]:
            mejor = (sse, coef, b, c)
    _, (ln_a, m), b, c = mejor
    a = float(np.exp(ln_a))
    f = lambda Tt, dd: a * Tt ** m / (dd ** c + b)
    r2, rmse = _metricas(T, d, i, f)
    return ModeloIDFGenerico("Wenzel", "i = a·T^m / (d^c + b)",
                             {"a": a, "b": b, "c": float(c), "m": float(m)}, r2, rmse, f)


# --- 5/6. Témez: I_t/I_d = (I1/Id)^((28^0.1 - t^0.1)/(28^0.1 - 1)) ------------

def _fit_temez(T, d, i, exponente=0.1, nombre="Témez") -> ModeloIDFGenerico:
    # Id(T) = P24(T)/24 [mm/h]; se estima de la propia tabla por T.
    th = d / 60.0  # duración en horas
    base = 28.0 ** exponente
    # Estimar Id(T) e I1/Id por mínimos cuadrados sobre cada T.
    Tunicos = np.unique(T)
    id_por_T = {}
    ratios = []
    for Tt in Tunicos:
        msk = T == Tt
        # Id ≈ i a 24 h (1440 min) si existe; si no, extrapolar con la mediana
        d_T, i_T = d[msk], i[msk]
        # i a 24h
        if np.any(np.isclose(d_T, 1440.0)):
            Id = float(i_T[np.isclose(d_T, 1440.0)][0])
        else:
            Id = float(np.interp(1440.0, d_T, i_T))
        id_por_T[Tt] = Id
        # ratio I1/Id que mejor ajusta esta curva
        th_T = d_T / 60.0
        exp_t = (base - th_T ** exponente) / (base - 1.0)
        # i = Id * R^exp_t  ->  ln(i/Id) = exp_t * ln R
        y = np.log(np.clip(i_T / Id, 1e-6, None))
        lnR = float(np.sum(exp_t * y) / np.sum(exp_t * exp_t))
        ratios.append(np.exp(lnR))
    R = float(np.mean(ratios))

    def f(Tt, dd):
        Id = id_por_T.get(Tt)
        if Id is None:
            Id = float(np.interp(Tt, list(id_por_T.keys()), list(id_por_T.values())))
        th_ = dd / 60.0
        exp_t = (base - th_ ** exponente) / (base - 1.0)
        return Id * R ** exp_t

    r2, rmse = _metricas(T, d, i, f)
    return ModeloIDFGenerico(
        nombre, f"I_t/I_d = (I1/Id)^((28^{exponente:g}−t^{exponente:g})/(28^{exponente:g}−1))",
        {"I1/Id": R, "exponente": exponente}, r2, rmse, f)


def _fit_temez_mod(T, d, i) -> ModeloIDFGenerico:
    # Calibra el exponente p (fijo 0.1 en Témez clásico) maximizando R².
    res = minimize_scalar(
        lambda p: 1.0 - _fit_temez(T, d, i, exponente=p).r2,
        bounds=(0.04, 0.30), method="bounded",
    )
    return _fit_temez(T, d, i, exponente=float(res.x), nombre="Témez modificado")


# --- 7. Curva promedio adimensional -------------------------------------------

def _fit_promedio_adim(T, d, i, d_ref=60.0) -> ModeloIDFGenerico:
    Tunicos = np.unique(T)
    # i(d_ref, T) por T
    iref = {}
    for Tt in Tunicos:
        msk = T == Tt
        iref[Tt] = float(np.interp(d_ref, d[msk], i[msk]))
    # Curva adimensional φ(d) = i(d,T)/i(d_ref,T), promediada sobre T
    duraciones = np.unique(d)
    phi = []
    for dd in duraciones:
        vals = []
        for Tt in Tunicos:
            msk = (T == Tt)
            vals.append(float(np.interp(dd, d[msk], i[msk])) / iref[Tt])
        phi.append(np.mean(vals))
    phi = np.array(phi)
    # Ajustar φ̄(d) = 1/(d/d_ref + b)^n  (forma Sherman adimensional)
    def amn(b):
        X = np.column_stack([np.ones_like(duraciones), -np.log(duraciones / d_ref + b)])
        coef, *_ = np.linalg.lstsq(X, np.log(phi), rcond=None)
        return coef, float(np.sum((np.log(phi) - X @ coef) ** 2))
    res = minimize_scalar(lambda b: amn(b)[1], bounds=(0.01, 50), method="bounded")
    b = float(res.x)
    (ln_k, n), _ = amn(b)
    k = float(np.exp(ln_k))
    # i(d_ref, T) en función de T por ley potencia
    Tarr = np.array(list(iref.keys()))
    iarr = np.array(list(iref.values()))
    (ln_a, m), *_ = np.linalg.lstsq(
        np.column_stack([np.ones_like(Tarr), np.log(Tarr)]), np.log(iarr), rcond=None)
    a_ref = float(np.exp(ln_a))

    def f(Tt, dd):
        iref_T = a_ref * Tt ** m
        phi_d = k / (dd / d_ref + b) ** n
        return iref_T * phi_d

    r2, rmse = _metricas(T, d, i, f)
    return ModeloIDFGenerico(
        "Curva promedio adimensional",
        "i = (a·T^m)·k/(d/d_ref + b)^n",
        {"a_ref": a_ref, "m": float(m), "k": k, "b": b, "n": float(n), "d_ref": d_ref},
        r2, rmse, f)


def ajustar_todos_los_modelos(idf_largo: pd.DataFrame) -> list[ModeloIDFGenerico]:
    """Ajusta los 7 modelos IDF y los devuelve ordenados por R² descendente."""
    T, d, i = _arrays(idf_largo)
    modelos = [
        _fit_sherman(T, d, i),
        _fit_chen(T, d, i),
        _fit_chen_mod(T, d, i),
        _fit_wenzel(T, d, i),
        _fit_temez(T, d, i),
        _fit_temez_mod(T, d, i),
        _fit_promedio_adim(T, d, i),
    ]
    return sorted(modelos, key=lambda m: m.r2, reverse=True)


# Resolución de los datos de lluvia -> modelos IDF recomendados.
# (clave, etiqueta, [modelos preferidos], justificación)
RESOLUCIONES_DATOS: tuple[tuple[str, str, list, str], ...] = (
    ("sub_10min", "Sub-horaria (≤ 10 min)", ["Wenzel"],
     "Datos de alta resolución (≤ 10 min): se recomiendan métodos de alta "
     "resolución como Wenzel."),
    ("horaria", "Horaria", ["Chen", "Chen modificado"],
     "Datos horarios: se recomienda Chen o Chen modificado."),
    ("diaria", "Diaria (P24max) + d > 2 h", ["Témez modificado", "Chen modificado"],
     "Datos diarios y duraciones > 2 h: se recomienda Témez modificado o "
     "Chen modificado."),
    ("altiplano_pocos", "Pocos datos / altiplano",
     ["Sherman", "Curva promedio adimensional"],
     "Sitios con pocos datos o altiplano: Sherman o curva promedio adimensional, "
     "combinados con interpolación espacial (Kriging)."),
)

_RES_MAP = {clave: (pref, just) for clave, _, pref, just in RESOLUCIONES_DATOS}


def recomendar_modelo_por_datos(resolucion: str, modelos: list):
    """Devuelve (modelo_recomendado, justificación, preferidos) según el tipo
    de dato. Entre los modelos preferidos disponibles, elige el de mejor R²."""
    preferidos, just = _RES_MAP.get(resolucion, _RES_MAP["diaria"])
    candidatos = [m for m in modelos if m.nombre in preferidos]
    if not candidatos:
        candidatos = modelos
    elegido = max(candidatos, key=lambda m: m.r2)
    return elegido, just, preferidos
