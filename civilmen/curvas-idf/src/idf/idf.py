"""Ajuste del modelo IDF de Sherman:

        i(T, d) = a · T^m / (d + b)^n

donde
    i  : intensidad media máxima [mm/h]
    T  : período de retorno [años]
    d  : duración [minutos]
    a, b, m, n : parámetros a calibrar (b ≥ 0; m, n > 0; a > 0)

Se ajusta por mínimos cuadrados no lineales en log-espacio:

        ln i = ln a + m·ln T − n·ln(d + b)

con b optimizado por búsqueda 1D y a, m, n por regresión lineal multivariada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar


@dataclass
class ModeloIDF:
    """Parámetros calibrados del modelo de Sherman."""

    a: float
    b: float
    m: float
    n: float
    r2: float
    rmse_mm_h: float

    def intensidad(self, T: float, d_min: float) -> float:
        return self.a * (T ** self.m) / ((d_min + self.b) ** self.n)

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"i = {self.a:.3f}·T^{self.m:.4f} / (d + {self.b:.3f})^{self.n:.4f}   "
            f"[R²={self.r2:.4f}, RMSE={self.rmse_mm_h:.3f} mm/h]"
        )


def _ajustar_amn_dado_b(
    T: np.ndarray, d: np.ndarray, i: np.ndarray, b: float
) -> tuple[float, float, float, float]:
    """Regresión lineal en log-espacio para a, m, n con b fijo. Devuelve (a, m, n, sse)."""
    X = np.column_stack(
        [
            np.ones_like(T),
            np.log(T),
            -np.log(d + b),
        ]
    )
    y = np.log(i)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    ln_a, m, n = coef
    pred = X @ coef
    sse = float(np.sum((y - pred) ** 2))
    return float(np.exp(ln_a)), float(m), float(n), sse


def ajustar_sherman(idf_largo: pd.DataFrame) -> ModeloIDF:
    """Ajusta el modelo i = a·T^m / (d+b)^n.

    idf_largo: DataFrame con columnas T_anios, duracion_min, i_mm_h.
    """
    req = {"T_anios", "duracion_min", "i_mm_h"}
    if not req.issubset(idf_largo.columns):
        raise ValueError(f"Faltan columnas requeridas: {req - set(idf_largo.columns)}")
    T = idf_largo["T_anios"].to_numpy(dtype=float)
    d = idf_largo["duracion_min"].to_numpy(dtype=float)
    i = idf_largo["i_mm_h"].to_numpy(dtype=float)
    if np.any(i <= 0) or np.any(T <= 0) or np.any(d <= 0):
        raise ValueError("T, d e i deben ser estrictamente positivos.")

    def sse_de_b(b: float) -> float:
        _, _, _, sse = _ajustar_amn_dado_b(T, d, i, b)
        return sse

    res = minimize_scalar(sse_de_b, bounds=(0.0, max(d) * 5.0), method="bounded")
    b_opt = float(res.x)
    a, m, n, sse = _ajustar_amn_dado_b(T, d, i, b_opt)

    # Refinamiento por MÍNIMOS CUADRADOS NO LINEALES (scipy curve_fit) en el
    # espacio original i = k·T^m/(d+c)^n, tomando el ajuste log-lineal como
    # semilla. Es la forma que exige el Manual ABC (parámetros k, m, n, c).
    # Si curve_fit no converge, se conserva el ajuste log-lineal.
    try:
        from scipy.optimize import curve_fit

        def _modelo_abc(X, k, mm, nn, c):
            TT, dd = X
            return k * (TT ** mm) / ((dd + c) ** nn)

        popt, _ = curve_fit(
            _modelo_abc, (T, d), i, p0=[a, m, n, b_opt],
            bounds=([1e-6, 0.0, 0.0, 0.0], [np.inf, 2.0, 3.0, max(d) * 5.0]),
            maxfev=20000)
        a2, m2, n2, b2 = (float(popt[0]), float(popt[1]), float(popt[2]),
                          float(popt[3]))
        pred2 = a2 * (T ** m2) / ((d + b2) ** n2)
        if np.all(np.isfinite(pred2)):
            a, m, n, b_opt = a2, m2, n2, b2
    except Exception:  # noqa: BLE001
        pass

    # Métricas en el espacio original (mm/h).
    pred = a * (T ** m) / ((d + b_opt) ** n)
    ss_res = float(np.sum((i - pred) ** 2))
    ss_tot = float(np.sum((i - i.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    rmse = float(np.sqrt(ss_res / len(i)))
    return ModeloIDF(a=a, b=b_opt, m=m, n=n, r2=r2, rmse_mm_h=rmse)


def intensidad(modelo: ModeloIDF, T: float, d_min: float) -> float:
    """Helper funcional equivalente a modelo.intensidad(T, d_min)."""
    return modelo.intensidad(T, d_min)
