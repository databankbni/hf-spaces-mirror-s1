"""Análisis de consistencia de la serie anual máxima.

Pruebas estadísticas recomendadas por la OMM (WMO-No. 168, "Guide to
Hydrological Practices", Vol. II) y el Bulletin 17C (USGS, 2018) antes de
realizar el análisis de frecuencias:

  • Outliers           — Grubbs-Beck (modificado) para detectar valores
                          atípicos altos/bajos.
  • Independencia      — Wald-Wolfowitz (rachas) y autocorrelación de lag-1.
  • Tendencia          — Mann-Kendall no paramétrico (S, Z, p-valor).
  • Homogeneidad       — Pettitt para detectar punto de cambio.

Cada prueba devuelve un dataclass con estadístico, p-valor y veredicto al
nivel de significancia α = 0.05 (configurable).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy import stats


@dataclass
class ResultadoPrueba:
    nombre: str
    estadistico: float
    valor_critico: float | None
    p_valor: float | None
    alfa: float
    conclusion: str
    pasa: bool


# ---------------------------------------------------------------------------
# Outliers — Grubbs-Beck modificado (umbral 10% para alto/bajo)
# ---------------------------------------------------------------------------

def grubbs_beck(serie: Sequence[float], alfa: float = 0.10) -> ResultadoPrueba:
    """Detección de outliers altos y bajos en log-espacio.

    Estadístico K_N tabulado (Stedinger et al., 1993) — aprox. polinomial
    de Pilon & Harvey (1992). Se calcula sobre ln(x).
    """
    x = np.sort(np.asarray(serie, dtype=float))
    n = x.size
    y = np.log(x)
    y_mean = y.mean()
    y_std = y.std(ddof=1)

    # Aproximación polinomial Pilon-Harvey (válida 10 ≤ n ≤ 150)
    n_lim = max(min(n, 150), 10)
    K = (
        -3.62201
        + 6.28446 * n_lim ** 0.25
        - 2.49835 * n_lim ** 0.5
        + 0.491436 * n_lim ** 0.75
        - 0.037911 * n_lim
    )
    y_alto = y_mean + K * y_std
    y_bajo = y_mean - K * y_std
    n_alto = int(np.sum(y > y_alto))
    n_bajo = int(np.sum(y < y_bajo))
    pasa = (n_alto == 0) and (n_bajo == 0)
    return ResultadoPrueba(
        nombre="Grubbs-Beck (outliers)",
        estadistico=float(K),
        valor_critico=None,
        p_valor=None,
        alfa=alfa,
        conclusion=(
            f"Outliers altos detectados: {n_alto}; outliers bajos: {n_bajo}. "
            f"Umbrales en log-espacio: [{y_bajo:.3f}, {y_alto:.3f}] "
            f"⇒ [{np.exp(y_bajo):.2f}, {np.exp(y_alto):.2f}] mm."
        ),
        pasa=pasa,
    )


# ---------------------------------------------------------------------------
# Independencia — autocorrelación lag-1 y Wald-Wolfowitz (rachas)
# ---------------------------------------------------------------------------

def autocorrelacion_lag1(serie: Sequence[float], alfa: float = 0.05) -> ResultadoPrueba:
    """Test del coeficiente de autocorrelación de lag-1.

    Bajo H0 de independencia, r1 ~ N(-1/(n-1), 1/n) aprox.
    Se rechaza H0 si |r1 - μ| > z_{α/2} · σ.
    """
    x = np.asarray(serie, dtype=float)
    n = x.size
    media = x.mean()
    num = np.sum((x[:-1] - media) * (x[1:] - media))
    den = np.sum((x - media) ** 2)
    r1 = float(num / den) if den > 0 else 0.0
    mu = -1.0 / (n - 1)
    sigma = 1.0 / np.sqrt(n)
    z_crit = stats.norm.ppf(1 - alfa / 2)
    pasa = abs(r1 - mu) <= z_crit * sigma
    p = 2 * (1 - stats.norm.cdf(abs(r1 - mu) / sigma))
    return ResultadoPrueba(
        nombre="Autocorrelación lag-1",
        estadistico=r1,
        valor_critico=float(mu + z_crit * sigma),
        p_valor=float(p),
        alfa=alfa,
        conclusion=(
            f"r₁ = {r1:.4f}; intervalo de confianza al {(1-alfa)*100:.0f}%: "
            f"[{mu - z_crit*sigma:.4f}, {mu + z_crit*sigma:.4f}]."
        ),
        pasa=pasa,
    )


def wald_wolfowitz_rachas(serie: Sequence[float], alfa: float = 0.05) -> ResultadoPrueba:
    """Test de rachas (Wald-Wolfowitz) sobre la mediana.

    Bajo H0 de aleatoriedad, número de rachas R ~ N(μ_R, σ_R²) con
        μ_R = 2 n1 n2 / n + 1
        σ_R² = 2 n1 n2 (2 n1 n2 - n) / (n² (n-1))
    """
    x = np.asarray(serie, dtype=float)
    n = x.size
    mediana = np.median(x)
    s = np.where(x >= mediana, 1, 0)
    n1, n2 = int(np.sum(s == 1)), int(np.sum(s == 0))
    R = 1 + int(np.sum(np.diff(s) != 0))
    if n1 == 0 or n2 == 0:
        return ResultadoPrueba(
            nombre="Wald-Wolfowitz (rachas)",
            estadistico=float(R),
            valor_critico=None,
            p_valor=None,
            alfa=alfa,
            conclusion="Serie constante o degenerada, prueba no aplicable.",
            pasa=True,
        )
    mu_R = 2 * n1 * n2 / n + 1
    var_R = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n ** 2 * (n - 1))
    Z = (R - mu_R) / np.sqrt(var_R) if var_R > 0 else 0.0
    p = 2 * (1 - stats.norm.cdf(abs(Z)))
    pasa = p >= alfa
    return ResultadoPrueba(
        nombre="Wald-Wolfowitz (rachas)",
        estadistico=float(R),
        valor_critico=float(mu_R),
        p_valor=float(p),
        alfa=alfa,
        conclusion=(
            f"Rachas observadas R = {R}; esperadas μ_R = {mu_R:.2f}; Z = {Z:.3f}."
        ),
        pasa=pasa,
    )


# ---------------------------------------------------------------------------
# Tendencia — Mann-Kendall
# ---------------------------------------------------------------------------

def mann_kendall(serie: Sequence[float], alfa: float = 0.05) -> ResultadoPrueba:
    """Test de Mann-Kendall para detectar tendencia monótona."""
    x = np.asarray(serie, dtype=float)
    n = x.size
    s = 0
    for i in range(n - 1):
        s += int(np.sum(np.sign(x[i + 1 :] - x[i])))
    # Corrección por empates
    vals, counts = np.unique(x, return_counts=True)
    ties = counts[counts > 1]
    var_s = (n * (n - 1) * (2 * n + 5) - np.sum(ties * (ties - 1) * (2 * ties + 5))) / 18.0
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    pasa = p >= alfa
    direccion = "creciente" if s > 0 else ("decreciente" if s < 0 else "sin tendencia")
    return ResultadoPrueba(
        nombre="Mann-Kendall (tendencia)",
        estadistico=float(s),
        valor_critico=float(stats.norm.ppf(1 - alfa / 2)),
        p_valor=float(p),
        alfa=alfa,
        conclusion=f"S = {s}; Z = {z:.3f}; dirección: {direccion}.",
        pasa=pasa,
    )


# ---------------------------------------------------------------------------
# Homogeneidad — Pettitt
# ---------------------------------------------------------------------------

def pettitt(serie: Sequence[float], alfa: float = 0.05) -> ResultadoPrueba:
    """Test no paramétrico de Pettitt para punto de cambio."""
    x = np.asarray(serie, dtype=float)
    n = x.size
    U = np.zeros(n)
    for t in range(n):
        s = 0
        for i in range(t + 1):
            for j in range(t + 1, n):
                s += np.sign(x[i] - x[j])
        U[t] = s
    K = float(np.max(np.abs(U)))
    t_cambio = int(np.argmax(np.abs(U)))
    p = 2.0 * np.exp(-6.0 * K ** 2 / (n ** 3 + n ** 2))
    p = min(p, 1.0)
    pasa = p >= alfa
    return ResultadoPrueba(
        nombre="Pettitt (homogeneidad)",
        estadistico=float(K),
        valor_critico=None,
        p_valor=float(p),
        alfa=alfa,
        conclusion=(
            f"K = {K:.0f}; posible punto de cambio en posición t = {t_cambio + 1} "
            f"(de {n})."
        ),
        pasa=pasa,
    )


def correr_todas(serie: Sequence[float], alfa: float = 0.05) -> list[ResultadoPrueba]:
    """Ejecuta el panel completo de pruebas de consistencia."""
    return [
        grubbs_beck(serie, alfa=0.10),
        autocorrelacion_lag1(serie, alfa=alfa),
        wald_wolfowitz_rachas(serie, alfa=alfa),
        mann_kendall(serie, alfa=alfa),
        pettitt(serie, alfa=alfa),
    ]
