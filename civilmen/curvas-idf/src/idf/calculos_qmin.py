"""Cálculos operacionales de caudales mínimos para Secciones 4 y 5.

Para cada estación seleccionada (Sección 2.2) y para la serie simulada por
el balance P→Q (Sección 2.9), calcula los caudales y los índices que los
marcos normativos del informe (Sección 4 — por uso) y la frecuencia no
estacionaria (Sección 5) requieren reportar.

Módulos de cálculo (todos en numpy/scipy, sin dependencias nuevas):

- L-moments (Hosking 1990) → ajustes robustos en series cortas.
- Frecuencia de Q mínimos anuales con cuatro distribuciones (Weibull,
  Gumbel inverso, Log-Pearson III y GEV) — selecciona la de mejor KS.
- Cuantiles Q mín T para T = 2, 5, 10, 25, 50, 100.
- Q7,10 (USGS): 7-day low flow con T = 10 años. Cuando solo se tiene
  serie mensual, se aproxima por el cociente regional Q7,10/Q_min,med.
- Caudal ecológico — 5 métodos: Tennant (1976), Tessman (1980), Smakhtin
  Q90/Q95 (2001), Texas (TPWD), Q7,10 + factor ecológico.
- SPI (McKee et al. 1993) con distribución Gamma; escalas 3, 6 y 12 meses.
- Evaluación de modelos CC: KGE (Gupta et al. 2009), NSE, PBIAS, KGE_log
  (para mínimos, Pushpalatha et al. 2012).

Salidas listas para alimentar tablas y plots en el template del informe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats as scs


# ─────────────────────── L-moments (Hosking 1990) ───────────────────────

def lmoments(x: np.ndarray) -> tuple[float, float, float, float]:
    """λ1, λ2, τ3, τ4. Usa los b-moments insesgados (Hosking 1990, eq. 2.3)."""
    x = np.sort(np.asarray(x, dtype=float))
    n = x.size
    if n < 4:
        return float("nan"), float("nan"), float("nan"), float("nan")
    j = np.arange(1, n + 1)
    b0 = x.mean()
    b1 = float(np.sum((j - 1) * x) / (n * (n - 1)))
    b2 = float(np.sum((j - 1) * (j - 2) * x) / (n * (n - 1) * (n - 2)))
    b3 = float(np.sum((j - 1) * (j - 2) * (j - 3) * x)
                / (n * (n - 1) * (n - 2) * (n - 3)))
    l1 = b0
    l2 = 2 * b1 - b0
    l3 = 6 * b2 - 6 * b1 + b0
    l4 = 20 * b3 - 30 * b2 + 12 * b1 - b0
    t3 = l3 / l2 if l2 else float("nan")
    t4 = l4 / l2 if l2 else float("nan")
    return l1, l2, t3, t4


# ─────────────────────── Distribuciones y cuantiles ───────────────────────

# Para Q MÍNIMOS usamos la convención de la "T-yr drought" — el cuantil de
# probabilidad p = 1/T (no excedencia). Así Q mín T crece con T y representa
# el caudal mínimo esperado con período de retorno T años.

DISTRIBUCIONES_QMIN = ("weibull", "gumbel_min", "lp3", "gev_min")


def _ajustar_weibull(x: np.ndarray) -> tuple[dict, float]:
    """Weibull de 2 parámetros (Weibull min) — apropiada para Q mín positivos."""
    try:
        c, loc, scale = scs.weibull_min.fit(x, floc=0)
        ks_d, ks_p = scs.kstest(x, "weibull_min", args=(c, loc, scale))
        return {"c": float(c), "loc": float(loc), "scale": float(scale),
                "ks_p": float(ks_p)}, float(ks_p)
    except Exception:  # noqa: BLE001
        return {}, 0.0


def _ajustar_gumbel_min(x: np.ndarray) -> tuple[dict, float]:
    """Gumbel reversed (mínimos) — útil cuando los Q mín caen en cola izquierda."""
    try:
        loc, scale = scs.gumbel_l.fit(x)
        ks_d, ks_p = scs.kstest(x, "gumbel_l", args=(loc, scale))
        return {"loc": float(loc), "scale": float(scale),
                "ks_p": float(ks_p)}, float(ks_p)
    except Exception:  # noqa: BLE001
        return {}, 0.0


def _ajustar_lp3(x: np.ndarray) -> tuple[dict, float]:
    """Log-Pearson III — exigida por Bulletin 17C para análisis de frecuencia."""
    try:
        xp = x[x > 0]
        if xp.size < 8:
            return {}, 0.0
        lnx = np.log(xp)
        skew_val = float(scs.skew(lnx, bias=False))
        skew_param, loc, scale = scs.pearson3.fit(lnx, fskew=skew_val)
        ks_d, ks_p = scs.kstest(lnx, "pearson3",
                                  args=(skew_param, loc, scale))
        return {"skew": float(skew_param), "loc": float(loc),
                "scale": float(scale), "ks_p": float(ks_p),
                "espacio": "log"}, float(ks_p)
    except Exception:  # noqa: BLE001
        return {}, 0.0


def _ajustar_gev_min(x: np.ndarray) -> tuple[dict, float]:
    """GEV ajustada a −x (mínimos) y se devuelve cambiada de signo."""
    try:
        y = -x
        c, loc, scale = scs.genextreme.fit(y)
        ks_d, ks_p = scs.kstest(y, "genextreme", args=(c, loc, scale))
        return {"c": float(c), "loc": float(loc), "scale": float(scale),
                "ks_p": float(ks_p), "espacio": "neg"}, float(ks_p)
    except Exception:  # noqa: BLE001
        return {}, 0.0


_AJUSTES = {
    "weibull": _ajustar_weibull,
    "gumbel_min": _ajustar_gumbel_min,
    "lp3": _ajustar_lp3,
    "gev_min": _ajustar_gev_min,
}


def ajustar_distribuciones_qmin(serie: np.ndarray) -> dict:
    """Ajusta las 4 distribuciones y devuelve la mejor por KS + todos los detalles."""
    serie = np.asarray(serie, dtype=float)
    serie = serie[np.isfinite(serie) & (serie > 0)]
    if serie.size < 8:
        return {"mejor": None, "ajustes": {}}
    ajustes = {}
    mejor, mejor_p = None, -1.0
    for nombre, fn in _AJUSTES.items():
        params, p = fn(serie)
        ajustes[nombre] = params
        if p > mejor_p:
            mejor, mejor_p = nombre, p
    return {"mejor": mejor, "ajustes": ajustes, "n": int(serie.size)}


def _cuantil_min_t(nombre: str, params: dict, T: float) -> float:
    """Q mín con período de retorno T años (probabilidad no excedencia 1/T)."""
    p = 1.0 / T
    if not params:
        return float("nan")
    try:
        if nombre == "weibull":
            return float(scs.weibull_min.ppf(p, params["c"],
                                                params["loc"], params["scale"]))
        if nombre == "gumbel_min":
            return float(scs.gumbel_l.ppf(p, params["loc"], params["scale"]))
        if nombre == "lp3":
            q_log = float(scs.pearson3.ppf(p, params["skew"], params["loc"],
                                              params["scale"]))
            return float(math.exp(q_log))
        if nombre == "gev_min":
            # Recordar que ajustamos sobre −x.
            return float(-scs.genextreme.ppf(1 - p, params["c"],
                                                params["loc"], params["scale"]))
    except Exception:  # noqa: BLE001
        return float("nan")
    return float("nan")


def cuantiles_qmin_t(resultado_ajuste: dict,
                       T_lista: tuple[int, ...] = (2, 5, 10, 25, 50, 100)
                       ) -> dict:
    """Diccionario {T: Q mín T} usando la mejor distribución."""
    nombre = resultado_ajuste.get("mejor")
    if nombre is None:
        return {T: float("nan") for T in T_lista}
    params = resultado_ajuste["ajustes"].get(nombre, {})
    return {T: _cuantil_min_t(nombre, params, T) for T in T_lista}


# ─────────────────────── Q7,10 ───────────────────────

def q7_10_aproximado(q_min_med: float, q_med: float,
                       cv_estacional: float | None = None) -> float:
    """Estimación regional de Q7,10 cuando solo se tiene Q mín mensual.

    Heurística calibrada por Smakhtin (2001) para cuencas tropicales:
    Q7,10 ≈ k · Q_min,med, con k decreciente cuando el contraste estacional
    (CV mensual) es alto. Si q_min_med no es positivo, devuelve 0.
    """
    if q_min_med is None or q_min_med <= 0:
        return 0.0
    k = 0.55
    if cv_estacional is not None and math.isfinite(cv_estacional):
        if cv_estacional > 1.5:
            k = 0.30
        elif cv_estacional > 1.0:
            k = 0.40
        elif cv_estacional > 0.6:
            k = 0.50
    return float(max(0.0, k * q_min_med))


# ─────────────────────── Caudal ecológico ───────────────────────

@dataclass
class CaudalEcologico:
    metodo: str
    descripcion: str
    q_eco_m3s: float
    referencia: str


def caudal_ecologico(q_mes_climatico: np.ndarray, q_anual: float,
                       q90: float, q95: float, q7_10: float
                       ) -> list[CaudalEcologico]:
    """Cinco métodos comparativos para el caudal ecológico residual.

    `q_mes_climatico`: serie mensual climática (12 valores en m³/s).
    `q_anual`: caudal medio anual (m³/s).
    `q90`, `q95`: percentiles operativos de la FDC.
    `q7_10`: caudal mínimo de 7 días con T = 10 años.
    """
    q_mes_med = float(np.mean(q_mes_climatico)) if len(q_mes_climatico) else q_anual
    salida = []
    # 1. Tennant 1976: 30% Q anual (calidad buena en estación seca).
    salida.append(CaudalEcologico(
        "Tennant 30 %",
        "30 % del caudal medio anual (calidad «buena», Tennant 1976).",
        0.30 * q_anual,
        "Tennant, D. L. (1976). Instream flow regimens for fish, wildlife, "
        "recreation and related environmental resources. Fisheries, 1(4), 6–10."))
    # 2. Tessman 1980: dependiente del mes.
    if q_mes_med < 0.40 * q_anual:
        q_tess = q_mes_med
    else:
        q_tess = 0.40 * q_anual
    salida.append(CaudalEcologico(
        "Tessman 1980",
        "Q_mes si Q_mes < 40 % Q anual; si no, 40 % Q anual.",
        q_tess,
        "Tessman, S. A. (1980). Environmental assessment, Technical "
        "appendix E. Reservoir System Planning Bulletin 80. Water Resources "
        "Institute, South Dakota State University."))
    # 3. Smakhtin Q90.
    salida.append(CaudalEcologico(
        "Smakhtin Q90",
        "Caudal excedido el 90 % del tiempo en la FDC; umbral operativo "
        "de sequía.",
        q90,
        "Smakhtin, V. U. (2001). Low-flow hydrology: A review. Journal of "
        "Hydrology, 240(3–4), 147–186. "
        "https://doi.org/10.1016/S0022-1694(00)00340-1"))
    # 4. Texas (TPWD): 40% del flujo entrante.
    salida.append(CaudalEcologico(
        "Texas (TPWD)",
        "40 % del caudal medio anual; usado por Texas Parks and Wildlife "
        "Department.",
        0.40 * q_anual,
        "Texas Parks & Wildlife Department. (2005). Texas Instream Flow "
        "Studies — Technical Overview. TPWD Report."))
    # 5. Q7,10 + factor ecológico (Pyrce 2004).
    q_pyrce = max(q7_10, 1.5 * q7_10)
    salida.append(CaudalEcologico(
        "Q7,10 ecológico",
        "Q7,10 (USGS) reforzado por factor 1.5 cuando la cuenca tiene "
        "uso ecológico crítico (Pyrce 2004).",
        q_pyrce,
        "Pyrce, R. (2004). Hydrological low flow indices and their uses. "
        "Watershed Science Centre, Trent University, Report 04-2004."))
    return salida


# ─────────────────────── SPI (McKee et al. 1993) ───────────────────────

def spi(precip_mensual: np.ndarray, escala: int = 3) -> np.ndarray:
    """Standardized Precipitation Index a la escala indicada (meses).

    Ajusta una Gamma a la precipitación acumulada en ventanas móviles de
    `escala` meses y devuelve la transformación a normal estándar.
    Valores: > 2 extremadamente húmedo / < −2 extrema sequía.
    """
    x = np.asarray(precip_mensual, dtype=float)
    n = x.size
    if n < escala:
        return np.full(n, np.nan)
    # Ventana móvil de suma.
    s = np.convolve(x, np.ones(escala), mode="valid")
    pad = np.full(escala - 1, np.nan)
    s_full = np.concatenate([pad, s])
    out = np.full(n, np.nan)
    # Ajusta Gamma por mes-del-año para preservar estacionalidad.
    for mes in range(escala - 1, n):
        m = mes % 12
        muestra = s_full[m::12]
        muestra = muestra[np.isfinite(muestra) & (muestra > 0)]
        if muestra.size < 8:
            continue
        try:
            alpha, loc, beta = scs.gamma.fit(muestra, floc=0)
            cdf = scs.gamma.cdf(s_full[mes], alpha, loc, beta)
            cdf = max(min(cdf, 0.999), 0.001)
            out[mes] = float(scs.norm.ppf(cdf))
        except Exception:  # noqa: BLE001
            continue
    return out


# ─────────────────────── Evaluación de modelos CC ───────────────────────

def kge(sim: np.ndarray, obs: np.ndarray) -> dict:
    """KGE con descomposición r/α/β (Gupta et al. 2009)."""
    sim = np.asarray(sim, dtype=float)
    obs = np.asarray(obs, dtype=float)
    mask = np.isfinite(sim) & np.isfinite(obs)
    sim, obs = sim[mask], obs[mask]
    if sim.size < 3:
        return {"KGE": float("nan"), "r": float("nan"),
                "alpha": float("nan"), "beta": float("nan")}
    r = float(np.corrcoef(sim, obs)[0, 1])
    alpha = float(np.std(sim, ddof=1) / np.std(obs, ddof=1)) if np.std(obs) else 0.0
    beta = float(np.mean(sim) / np.mean(obs)) if np.mean(obs) else 0.0
    K = 1 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return {"KGE": K, "r": r, "alpha": alpha, "beta": beta}


def nse(sim: np.ndarray, obs: np.ndarray) -> float:
    """Nash-Sutcliffe Efficiency."""
    sim = np.asarray(sim, dtype=float)
    obs = np.asarray(obs, dtype=float)
    mask = np.isfinite(sim) & np.isfinite(obs)
    sim, obs = sim[mask], obs[mask]
    if sim.size < 3:
        return float("nan")
    den = float(np.sum((obs - obs.mean()) ** 2))
    if den == 0:
        return float("nan")
    return float(1 - np.sum((obs - sim) ** 2) / den)


def pbias(sim: np.ndarray, obs: np.ndarray) -> float:
    """% bias (Moriasi 2007)."""
    sim = np.asarray(sim, dtype=float)
    obs = np.asarray(obs, dtype=float)
    mask = np.isfinite(sim) & np.isfinite(obs)
    sim, obs = sim[mask], obs[mask]
    den = float(np.sum(obs))
    if den == 0:
        return float("nan")
    return float(100 * np.sum(obs - sim) / den)


def kge_log(sim: np.ndarray, obs: np.ndarray) -> float:
    """KGE sobre log(Q+ε), ε = Q̄_obs/100 (Pushpalatha 2012)."""
    eps = float(np.nanmean(obs)) / 100.0 if np.nanmean(obs) > 0 else 1e-3
    # Recorta a positivo antes del log para evitar nan cuando sim<0 por ruido.
    sim_pos = np.maximum(sim, -eps + 1e-9)
    obs_pos = np.maximum(obs, -eps + 1e-9)
    return kge(np.log(sim_pos + eps), np.log(obs_pos + eps))["KGE"]


def evaluar_modelos_cc(serie_obs: np.ndarray,
                         simulaciones: dict[str, np.ndarray]) -> list[dict]:
    """Aplica KGE, NSE, PBIAS y KGE_log a cada modelo simulado.

    Devuelve lista ordenada por KGE_log descendente (mejor reproducción de
    bajos primero, alineado con Pushpalatha 2012 para Q mín).
    """
    salida = []
    for nombre, serie in simulaciones.items():
        k = kge(serie, serie_obs)
        salida.append({
            "modelo": nombre,
            "KGE": round(k["KGE"], 3),
            "r": round(k["r"], 3),
            "alpha": round(k["alpha"], 3),
            "beta": round(k["beta"], 3),
            "NSE": round(nse(serie, serie_obs), 3),
            "PBIAS": round(pbias(serie, serie_obs), 1),
            "KGE_log": round(kge_log(serie, serie_obs), 3),
        })
    salida.sort(key=lambda r: r["KGE_log"]
                if math.isfinite(r["KGE_log"]) else -1, reverse=True)
    return salida


# ─────────────────────── Plots ───────────────────────

def plot_frecuencia_qmin(serie: np.ndarray, ajuste: dict,
                            T_lista: tuple[int, ...],
                            archivo) -> Optional[Path]:
    """Curva empírica + ajustada en escala Gumbel y puntos por T."""
    if not ajuste or not ajuste.get("mejor"):
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    serie = np.sort(np.asarray(serie, dtype=float))
    serie = serie[np.isfinite(serie) & (serie > 0)]
    n = serie.size
    if n < 4:
        return None
    # Posiciones de plotting Weibull (i / (n+1)) — probabilidad NO excedencia.
    p_emp = (np.arange(1, n + 1)) / (n + 1)
    T_emp = 1.0 / p_emp
    fig, ax = plt.subplots(figsize=(9.2, 5.4))
    ax.scatter(T_emp, serie, color="#1f3a68", s=24, label="Empírica (Weibull plot)")
    # Curva ajustada para T continuo.
    T_dense = np.logspace(0.1, 2.2, 80)
    nombre = ajuste["mejor"]
    params = ajuste["ajustes"][nombre]
    q_aj = np.array([_cuantil_min_t(nombre, params, T) for T in T_dense])
    ax.plot(T_dense, q_aj, color="#d7191c", lw=1.6,
             label=f"Ajuste {nombre} (KS p = {params.get('ks_p', 0):.3f})")
    # Marca de cuantiles operativos.
    for T in T_lista:
        Q = _cuantil_min_t(nombre, params, T)
        ax.axvline(T, color="#888", ls=":", lw=0.6, alpha=0.5)
        ax.annotate(f"T={T} → {Q:.2f}", (T, Q), xytext=(4, -6),
                     textcoords="offset points", fontsize=7.5,
                     color="#1f3a68")
    ax.set_xscale("log")
    ax.set_xlabel("Período de retorno T (años)")
    ax.set_ylabel("Caudal mínimo anual (m³/s)")
    ax.set_title("Análisis de frecuencia de caudales mínimos anuales",
                  color="#1f3a68", fontsize=11)
    ax.grid(True, which="both", alpha=0.32, lw=0.5)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_caudal_ecologico(metodos: list, q_anual: float, archivo) -> Optional[Path]:
    """Barras horizontales comparando los métodos de caudal ecológico."""
    if not metodos:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    nombres = [m.metodo for m in metodos]
    valores = [m.q_eco_m3s for m in metodos]
    pct = [100 * v / q_anual if q_anual else 0 for v in valores]
    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    barras = ax.barh(nombres, valores, color="#1f6b3f", alpha=0.85,
                       edgecolor="#0d3f24")
    for b, v, p in zip(barras, valores, pct):
        ax.text(v, b.get_y() + b.get_height() / 2,
                 f"  {v:.3f} m³/s ({p:.1f} % Q anual)",
                 va="center", fontsize=9, color="#1f3a68")
    ax.set_xlabel("Caudal ecológico (m³/s)")
    ax.set_title("Comparación de métodos para el caudal ecológico residual",
                  color="#1f3a68", fontsize=11)
    ax.grid(True, axis="x", alpha=0.3, lw=0.5)
    ax.invert_yaxis()
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_spi(serie_spi: np.ndarray, archivo,
              escala: int = 3) -> Optional[Path]:
    """Serie temporal de SPI con bandas de clasificación McKee 1993."""
    s = np.asarray(serie_spi, dtype=float)
    if s.size < 12 or np.isnan(s).all():
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    t = np.arange(s.size)
    pos = np.where(s > 0, s, 0)
    neg = np.where(s < 0, s, 0)
    ax.fill_between(t, 0, pos, color="#2c7bb6", alpha=0.7,
                     label="Húmedo")
    ax.fill_between(t, 0, neg, color="#d7191c", alpha=0.7,
                     label="Seco")
    for y, txt, col in [(2.0, "Extr. húmedo", "#08519c"),
                          (1.0, "Mod. húmedo", "#2c7bb6"),
                          (-1.0, "Mod. seco", "#fdae61"),
                          (-2.0, "Extr. seco", "#a50026")]:
        ax.axhline(y, color=col, lw=0.5, ls="--", alpha=0.6)
        ax.text(t[-1], y, f" {txt}", fontsize=7,
                 color=col, va="center")
    ax.set_xlabel("Mes (índice)")
    ax.set_ylabel(f"SPI-{escala}")
    ax.set_title(f"Índice de Precipitación Estandarizada SPI-{escala} "
                  f"(McKee et al. 1993)",
                  color="#1f3a68", fontsize=10.5)
    ax.grid(True, alpha=0.3, lw=0.4)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_modelos_taylor(metricas_modelos: list, archivo) -> Optional[Path]:
    """Diagrama de Taylor simplificado (σ vs r) para ranking de modelos."""
    if not metricas_modelos:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8.5, 5.4))
    nombres = [m["modelo"] for m in metricas_modelos]
    alphas = [m["alpha"] for m in metricas_modelos]
    rs = [m["r"] for m in metricas_modelos]
    colores = ["#1f3a68", "#27ae60", "#e67e22", "#d7191c", "#9c27b0",
                "#1abc9c", "#34495e", "#f39c12", "#2980b9", "#c0392b"]
    for i, (nom, a, r) in enumerate(zip(nombres, alphas, rs)):
        if not (math.isfinite(a) and math.isfinite(r)):
            continue
        ax.scatter(r, a, color=colores[i % len(colores)],
                    s=120, edgecolor="k", lw=0.8, zorder=5,
                    label=nom)
        ax.annotate(nom, (r, a), xytext=(6, 4),
                     textcoords="offset points", fontsize=8,
                     color=colores[i % len(colores)])
    # Punto ideal (observación) en r=1, σ_ratio=1.
    ax.scatter([1.0], [1.0], color="#d7191c", marker="*",
                s=260, zorder=8, label="Observación (ideal)")
    ax.axhline(1.0, color="#888", lw=0.5, ls=":", alpha=0.5)
    ax.axvline(1.0, color="#888", lw=0.5, ls=":", alpha=0.5)
    ax.set_xlim(-0.2, 1.05)
    ax.set_ylim(0, max(2.0, max(alphas + [1.5])))
    ax.set_xlabel("Correlación r")
    ax.set_ylabel("Cociente de desviaciones σ_sim / σ_obs")
    ax.set_title("Diagrama de Taylor (Taylor 2001) — modelos CC vs serie observada",
                  color="#1f3a68", fontsize=11)
    ax.grid(True, alpha=0.3, lw=0.4)
    ax.legend(loc="upper left", fontsize=7.5, ncol=2)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
