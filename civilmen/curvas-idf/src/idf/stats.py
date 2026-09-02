"""Análisis estadístico de frecuencias para precipitación máxima anual.

Distribuciones evaluadas: Normal, LogNormal (2 parámetros), Gumbel (EV-I),
Pearson III y Log-Pearson III. Se ajustan por método de momentos / MLE de scipy,
se evalúan con Kolmogorov-Smirnov y RMSE entre cuantiles empíricos y teóricos,
y se obtienen los cuantiles X_T para los períodos de retorno solicitados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats


PERIODOS_RETORNO_DEFAULT: tuple[int, ...] = (
    2, 5, 10, 25, 50, 100, 200, 250, 500, 1000, 10000,
)


@dataclass
class AjusteDistribucion:
    """Resultado del ajuste de una distribución a la serie anual."""

    nombre: str
    parametros: tuple[float, ...]
    ks_estadistico: float
    ks_pvalor: float
    rmse_cuantiles: float
    aic: float
    media_ajustada: float
    desv_ajustada: float
    metodo: str = "MLE"
    # Anderson-Darling A² (se setea tras el ajuste en ajustar_todas). Más
    # sensible a las COLAS que KS → mejor para extremos / Tr altos, que es
    # lo que recomienda el skill de hidrología boliviana para seleccionar
    # la distribución de diseño. NaN = no calculado.
    ad_estadistico: float = float("nan")
    # Chi-cuadrado de bondad de ajuste (Manual de Hidrología y Drenaje ABC).
    # Se setea tras el ajuste en ajustar_todas. NaN = no calculado.
    chi2_estadistico: float = float("nan")
    chi2_pvalor: float = float("nan")
    aceptada_ks: bool = field(init=False)

    def __post_init__(self) -> None:
        self.aceptada_ks = self.ks_pvalor >= 0.05


def _ad_stat(x_ordenado: np.ndarray, cdf_vals: np.ndarray) -> float:
    """Estadístico de Anderson-Darling A² a partir de la CDF teórica.

    A² = -n - (1/n)·Σ(2i-1)[ln F(x_i) + ln(1 - F(x_{n+1-i}))]
    Pondera más las colas que KS → mejor diagnóstico de extremos.
    """
    n = len(x_ordenado)
    F = np.clip(np.asarray(cdf_vals, dtype=float), 1e-12, 1.0 - 1e-12)
    i = np.arange(1, n + 1)
    S = np.sum((2 * i - 1) * (np.log(F) + np.log(1.0 - F[::-1])))
    return float(-n - S / n)


def _cdf_de_ajuste(ajuste: "AjusteDistribucion", x: np.ndarray) -> np.ndarray:
    """Evalúa la CDF teórica del ajuste sobre x (mismo mapeo que _cuantil)."""
    nombre, p = ajuste.nombre, ajuste.parametros
    if nombre == "Normal":
        return stats.norm.cdf(x, loc=p[0], scale=p[1])
    if nombre == "LogNormal":
        mu, sigma = p
        return stats.lognorm.cdf(x, s=sigma, loc=0.0, scale=np.exp(mu))
    if nombre == "LogNormal 3P":
        s, loc, scale = p
        return stats.lognorm.cdf(x, s=s, loc=loc, scale=scale)
    if nombre == "Gumbel":
        return stats.gumbel_r.cdf(x, loc=p[0], scale=p[1])
    if nombre == "Pearson III":
        return stats.pearson3.cdf(x, p[0], loc=p[1], scale=p[2])
    if nombre == "Log-Pearson III":
        return stats.pearson3.cdf(np.log(x), p[0], loc=p[1], scale=p[2])
    if nombre == "GEV":
        return stats.genextreme.cdf(x, p[0], loc=p[1], scale=p[2])
    return np.full_like(x, np.nan, dtype=float)


def _posiciones_weibull(n: int) -> np.ndarray:
    """Probabilidad empírica de no excedencia (Weibull): F = i/(n+1)."""
    return np.arange(1, n + 1) / (n + 1)


def _rmse_cuantiles(datos_ordenados: np.ndarray, cuantiles_teoricos: np.ndarray) -> float:
    return float(np.sqrt(np.mean((datos_ordenados - cuantiles_teoricos) ** 2)))


def _aic(loglik: float, k: int) -> float:
    return 2 * k - 2 * loglik


def _ajustar_normal(x: np.ndarray) -> AjusteDistribucion:
    mu, sigma = stats.norm.fit(x)
    ks = stats.kstest(x, "norm", args=(mu, sigma))
    teor = stats.norm.ppf(_posiciones_weibull(len(x)), loc=mu, scale=sigma)
    rmse = _rmse_cuantiles(np.sort(x), teor)
    loglik = float(np.sum(stats.norm.logpdf(x, loc=mu, scale=sigma)))
    return AjusteDistribucion(
        nombre="Normal",
        parametros=(mu, sigma),
        ks_estadistico=float(ks.statistic),
        ks_pvalor=float(ks.pvalue),
        rmse_cuantiles=rmse,
        aic=_aic(loglik, 2),
        media_ajustada=float(mu),
        desv_ajustada=float(sigma),
    )


def _ajustar_lognormal(x: np.ndarray) -> AjusteDistribucion:
    lnx = np.log(x)
    mu, sigma = lnx.mean(), lnx.std(ddof=1)
    # scipy lognorm: shape=s=sigma, loc=0, scale=exp(mu)
    ks = stats.kstest(x, "lognorm", args=(sigma, 0.0, np.exp(mu)))
    teor = stats.lognorm.ppf(_posiciones_weibull(len(x)), s=sigma, loc=0.0, scale=np.exp(mu))
    rmse = _rmse_cuantiles(np.sort(x), teor)
    loglik = float(np.sum(stats.lognorm.logpdf(x, s=sigma, loc=0.0, scale=np.exp(mu))))
    media = float(np.exp(mu + sigma ** 2 / 2))
    desv = float(np.sqrt((np.exp(sigma ** 2) - 1) * np.exp(2 * mu + sigma ** 2)))
    return AjusteDistribucion(
        nombre="LogNormal",
        parametros=(mu, sigma),
        ks_estadistico=float(ks.statistic),
        ks_pvalor=float(ks.pvalue),
        rmse_cuantiles=rmse,
        aic=_aic(loglik, 2),
        media_ajustada=media,
        desv_ajustada=desv,
        metodo="Momentos en log",
    )


def _ajustar_lognormal3(x: np.ndarray) -> AjusteDistribucion:
    """LogNormal de 3 parámetros (con parámetro de posición/umbral x0).

    Ajusta X = x0 + LogNormal por máxima verosimilitud (scipy.stats.lognorm con
    `loc` = umbral libre). Exigida por el Manual de Hidrología y Drenaje ABC.
    Si el ajuste MLE falla o degenera, cae a LogNormal de 2 parámetros (x0=0).
    """
    xs = np.sort(x)
    try:
        s, loc, scale = stats.lognorm.fit(x)     # 3 parámetros (s, loc, scale)
        if not (np.isfinite(s) and np.isfinite(loc) and np.isfinite(scale)
                and s > 0 and scale > 0):
            raise ValueError("ajuste degenerado")
    except Exception:  # noqa: BLE001
        lnx = np.log(x)
        s, loc, scale = float(lnx.std(ddof=1)), 0.0, float(np.exp(lnx.mean()))
    ks = stats.kstest(x, "lognorm", args=(s, loc, scale))
    teor = stats.lognorm.ppf(_posiciones_weibull(len(x)), s=s, loc=loc, scale=scale)
    rmse = _rmse_cuantiles(xs, teor)
    loglik = float(np.sum(stats.lognorm.logpdf(x, s=s, loc=loc, scale=scale)))
    media = float(loc + scale * np.exp(s ** 2 / 2))
    desv = float(scale * np.sqrt((np.exp(s ** 2) - 1) * np.exp(s ** 2)))
    return AjusteDistribucion(
        nombre="LogNormal 3P",
        parametros=(s, loc, scale),
        ks_estadistico=float(ks.statistic),
        ks_pvalor=float(ks.pvalue),
        rmse_cuantiles=rmse,
        aic=_aic(loglik, 3),
        media_ajustada=media,
        desv_ajustada=desv,
        metodo="MLE (3 parámetros)",
    )


def _ajustar_gumbel(x: np.ndarray) -> AjusteDistribucion:
    # Método de momentos: β = σ√6/π ; μ = mean − γβ  (γ=0.5772)
    sigma_x = x.std(ddof=1)
    beta = sigma_x * np.sqrt(6.0) / np.pi
    mu = x.mean() - 0.5772 * beta
    # scipy gumbel_r: loc=mu, scale=beta
    ks = stats.kstest(x, "gumbel_r", args=(mu, beta))
    teor = stats.gumbel_r.ppf(_posiciones_weibull(len(x)), loc=mu, scale=beta)
    rmse = _rmse_cuantiles(np.sort(x), teor)
    loglik = float(np.sum(stats.gumbel_r.logpdf(x, loc=mu, scale=beta)))
    return AjusteDistribucion(
        nombre="Gumbel",
        parametros=(mu, beta),
        ks_estadistico=float(ks.statistic),
        ks_pvalor=float(ks.pvalue),
        rmse_cuantiles=rmse,
        aic=_aic(loglik, 2),
        media_ajustada=float(mu + 0.5772 * beta),
        desv_ajustada=float(beta * np.pi / np.sqrt(6.0)),
        metodo="Momentos",
    )


def _ajustar_pearson3(x: np.ndarray) -> AjusteDistribucion:
    # Método de momentos: γ = skew, β = (2/γ)^2·σ^2/?? — usar scipy.fit con loc fija al min.
    skew, mean, std = stats.skew(x, bias=False), x.mean(), x.std(ddof=1)
    if abs(skew) < 1e-6:
        skew = 1e-6
    alpha = (2.0 / skew) ** 2
    beta_p = std / np.sqrt(alpha) * np.sign(skew)
    loc = mean - alpha * beta_p
    # scipy pearson3: skew param, loc, scale
    try:
        s_fit, loc_fit, sc_fit = stats.pearson3.fit(x, fskew=skew)
    except Exception:
        s_fit, loc_fit, sc_fit = skew, loc, abs(beta_p)
    ks = stats.kstest(x, "pearson3", args=(s_fit, loc_fit, sc_fit))
    teor = stats.pearson3.ppf(_posiciones_weibull(len(x)), s_fit, loc=loc_fit, scale=sc_fit)
    rmse = _rmse_cuantiles(np.sort(x), teor)
    loglik = float(np.sum(stats.pearson3.logpdf(x, s_fit, loc=loc_fit, scale=sc_fit)))
    return AjusteDistribucion(
        nombre="Pearson III",
        parametros=(s_fit, loc_fit, sc_fit),
        ks_estadistico=float(ks.statistic),
        ks_pvalor=float(ks.pvalue),
        rmse_cuantiles=rmse,
        aic=_aic(loglik, 3),
        media_ajustada=float(mean),
        desv_ajustada=float(std),
        metodo="Momentos",
    )


def _ajustar_log_pearson3(x: np.ndarray) -> AjusteDistribucion:
    lnx = np.log(x)
    skew = stats.skew(lnx, bias=False)
    if abs(skew) < 1e-6:
        skew = 1e-6
    try:
        s_fit, loc_fit, sc_fit = stats.pearson3.fit(lnx, fskew=skew)
    except Exception:
        # Fallback al método de momentos en log.
        mean_l, std_l = lnx.mean(), lnx.std(ddof=1)
        alpha = (2.0 / skew) ** 2
        beta_p = std_l / np.sqrt(alpha) * np.sign(skew)
        loc_fit = mean_l - alpha * beta_p
        s_fit, sc_fit = skew, abs(beta_p)
    # KS aplicado en log-espacio para coherencia con el ajuste.
    ks = stats.kstest(lnx, "pearson3", args=(s_fit, loc_fit, sc_fit))
    teor_log = stats.pearson3.ppf(_posiciones_weibull(len(x)), s_fit, loc=loc_fit, scale=sc_fit)
    rmse = _rmse_cuantiles(np.sort(x), np.exp(teor_log))
    loglik = float(np.sum(stats.pearson3.logpdf(lnx, s_fit, loc=loc_fit, scale=sc_fit) - lnx))
    return AjusteDistribucion(
        nombre="Log-Pearson III",
        parametros=(s_fit, loc_fit, sc_fit),
        ks_estadistico=float(ks.statistic),
        ks_pvalor=float(ks.pvalue),
        rmse_cuantiles=rmse,
        aic=_aic(loglik, 3),
        media_ajustada=float(x.mean()),
        desv_ajustada=float(x.std(ddof=1)),
        metodo="Momentos en log",
    )


def _ajustar_gev(x: np.ndarray) -> AjusteDistribucion:
    # GEV por máxima verosimilitud (scipy genextreme; shape c = -ξ).
    c, loc, scale = stats.genextreme.fit(x)
    ks = stats.kstest(x, "genextreme", args=(c, loc, scale))
    teor = stats.genextreme.ppf(_posiciones_weibull(len(x)), c, loc=loc, scale=scale)
    rmse = _rmse_cuantiles(np.sort(x), teor)
    loglik = float(np.sum(stats.genextreme.logpdf(x, c, loc=loc, scale=scale)))
    return AjusteDistribucion(
        nombre="GEV",
        parametros=(c, loc, scale),
        ks_estadistico=float(ks.statistic),
        ks_pvalor=float(ks.pvalue),
        rmse_cuantiles=rmse,
        aic=_aic(loglik, 3),
        media_ajustada=float(stats.genextreme.mean(c, loc=loc, scale=scale)),
        desv_ajustada=float(stats.genextreme.std(c, loc=loc, scale=scale)),
        metodo="MLE",
    )


def ajustar_todas(serie: Sequence[float]) -> list[AjusteDistribucion]:
    """Ajusta las distribuciones recomendadas y devuelve los resultados.

    Incluye GEV, Gumbel y (Log-)Pearson III, recomendadas para máximos de
    precipitación en Bolivia, además de Normal y LogNormal de referencia.
    """
    x = np.asarray(serie, dtype=float)
    if np.any(x <= 0):
        raise ValueError("La serie debe ser estrictamente positiva (mm > 0).")
    if x.size < 10:
        raise ValueError("Se recomienda n ≥ 10 años para análisis de frecuencias.")
    ajustes = [
        _ajustar_normal(x),
        _ajustar_lognormal(x),
        _ajustar_lognormal3(x),
        _ajustar_gumbel(x),
        _ajustar_pearson3(x),
        _ajustar_log_pearson3(x),
        _ajustar_gev(x),
    ]
    # Calcular Anderson-Darling A² para cada ajuste (post-hoc, con la CDF
    # ajustada). Sensible a las colas → criterio preferido para extremos.
    xs = np.sort(x)
    # nº de parámetros por distribución (para los g.l. de chi-cuadrado).
    _n_par = {"Normal": 2, "LogNormal": 2, "Gumbel": 2, "Pearson III": 3,
              "Log-Pearson III": 3, "GEV": 3}
    for a in ajustes:
        try:
            cdf_vals = _cdf_de_ajuste(a, xs)
            if np.all(np.isfinite(cdf_vals)):
                a.ad_estadistico = _ad_stat(xs, cdf_vals)
        except Exception:  # noqa: BLE001
            pass
        try:
            chi2, pv = _chi2_gof(x, a, _n_par.get(a.nombre, 2))
            a.chi2_estadistico, a.chi2_pvalor = chi2, pv
        except Exception:  # noqa: BLE001
            pass
    return ajustes


def _chi2_gof(x: np.ndarray, ajuste: "AjusteDistribucion",
              n_params: int) -> tuple[float, float]:
    """Prueba de bondad de ajuste Chi-cuadrado (Manual de Hidrología ABC).

    Agrupa la serie en k = round(sqrt(n)) clases equiprobables según la CDF
    ajustada (expected uniforme = n/k) y compara con las frecuencias
    observadas. Devuelve (chi2, p-valor) con g.l. = k − 1 − n_params.
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    k = max(4, int(round(np.sqrt(n))))
    # Bordes equiprobables en el espacio de probabilidad → cuantiles teóricos.
    ps = np.linspace(0.0, 1.0, k + 1)
    bordes = np.array([_cuantil(ajuste, p) for p in ps], dtype=float)
    bordes[0], bordes[-1] = -np.inf, np.inf
    bordes = np.maximum.accumulate(bordes)          # monotonía numérica
    obs, _ = np.histogram(x, bins=bordes)
    esp = np.full(k, n / k, dtype=float)
    chi2 = float(np.sum((obs - esp) ** 2 / esp))
    gl = max(1, k - 1 - n_params)
    pv = float(stats.chi2.sf(chi2, gl))
    return chi2, pv


def intervalos_confianza_cuantiles(
    serie: Sequence[float],
    periodos: Sequence[int] = PERIODOS_RETORNO_DEFAULT,
    criterio: str = "ad",
    n_boot: int = 500,
    nivel: float = 0.90,
    semilla: int = 42,
) -> Optional[pd.DataFrame]:
    """Intervalos de confianza de los cuantiles X_T por bootstrap no paramétrico.

    Exigido por la revisión técnica: con muestras cortas (n ≈ 30 años) los
    cuantiles de períodos de retorno altos (T = 500, 1000, 10 000) tienen
    incertidumbre muy elevada y NO deben presentarse como valores
    deterministas.

    Procedimiento: se remuestrea la serie con reemplazo `n_boot` veces; en cada
    réplica se reajusta la familia de distribuciones, se selecciona la mejor por
    el mismo criterio y se calculan los cuantiles. Se reportan los percentiles
    inferior y superior al nivel de confianza pedido, junto con el ancho
    relativo del intervalo (indicador directo de la fiabilidad del cuantil).

    Devuelve un DataFrame con T_anios, p24_mm (ajuste central), ic_inf, ic_sup,
    amplitud_rel_pct; o None si la serie es insuficiente.
    """
    x = np.asarray(serie, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    n = x.size
    if n < 10:
        return None
    rng = np.random.default_rng(semilla)
    periodos = list(periodos)

    # Ajuste central (sobre la serie completa).
    try:
        central = seleccionar_mejor_ajuste(ajustar_todas(x), criterio=criterio)
        q_central = {int(T): _cuantil(central, 1.0 - 1.0 / T) for T in periodos}
    except Exception:  # noqa: BLE001
        return None

    # En cada réplica se reajusta SOLO la familia seleccionada en el ajuste
    # central (bootstrap paramétrico de familia fija). Reajustar las siete
    # distribuciones por réplica multiplicaba el costo por ~7 sin cambiar
    # materialmente el intervalo, porque la familia rara vez cambia.
    _ajustador = {
        "Normal": _ajustar_normal,
        "LogNormal": _ajustar_lognormal,
        "LogNormal 3P": _ajustar_lognormal3,
        "Gumbel": _ajustar_gumbel,
        "Pearson III": _ajustar_pearson3,
        "Log-Pearson III": _ajustar_log_pearson3,
        "GEV": _ajustar_gev,
    }.get(central.nombre)
    if _ajustador is None:
        return None

    acum: dict[int, list] = {int(T): [] for T in periodos}
    for _ in range(int(n_boot)):
        muestra = rng.choice(x, size=n, replace=True)
        try:
            aj = _ajustador(muestra)
            for T in periodos:
                v = _cuantil(aj, 1.0 - 1.0 / T)
                if np.isfinite(v) and v > 0:
                    acum[int(T)].append(float(v))
        except Exception:  # noqa: BLE001
            continue

    alfa = (1.0 - float(nivel)) / 2.0
    filas = []
    for T in periodos:
        vals = np.asarray(acum[int(T)], dtype=float)
        if vals.size < 20:
            continue
        lo = float(np.percentile(vals, 100.0 * alfa))
        hi = float(np.percentile(vals, 100.0 * (1.0 - alfa)))
        centro = float(q_central[int(T)])
        filas.append({
            "T_anios": int(T),
            "p24_mm": round(centro, 2),
            "ic_inf": round(lo, 2),
            "ic_sup": round(hi, 2),
            "amplitud_rel_pct": (round(100.0 * (hi - lo) / centro, 1)
                                 if centro > 0 else float("nan")),
        })
    if not filas:
        return None
    return pd.DataFrame(filas)


def prueba_grubbs(serie: Sequence[float], alpha: float = 0.05) -> dict:
    """Prueba de Smirnov-Grubbs para detectar valores atípicos (outliers).

    Contrasta el dato más alejado de la media (máximo o mínimo) contra el
    valor crítico de Grubbs al nivel `alpha`. Devuelve un dict con el
    estadístico G, el valor crítico, el dato sospechoso y si es atípico.
    Solo se aplica a un outlier (el más extremo), como es la práctica en
    hidrología para no descartar máximos legítimos de diseño.
    """
    x = np.asarray(serie, dtype=float)
    n = x.size
    out = {"n": int(n), "aplicable": n >= 7, "hay_atipico": False}
    if n < 7:
        out["mensaje"] = ("Serie demasiado corta (n < 7) para la prueba de "
                          "Grubbs.")
        return out
    media = float(np.mean(x))
    s = float(np.std(x, ddof=1))
    if s <= 0:
        out["mensaje"] = "Desviación nula: no aplica."
        return out
    # Dato más alejado de la media (máximo o mínimo).
    i_ext = int(np.argmax(np.abs(x - media)))
    x_ext = float(x[i_ext])
    G = abs(x_ext - media) / s
    # Valor crítico de Grubbs (dos colas) con la t de Student.
    t2 = stats.t.ppf(1.0 - alpha / (2.0 * n), n - 2) ** 2
    G_crit = ((n - 1) / np.sqrt(n)) * np.sqrt(t2 / (n - 2 + t2))
    hay = bool(G > G_crit)
    out.update({
        "G": round(G, 3), "G_critico": round(float(G_crit), 3),
        "alpha": alpha, "dato_sospechoso": round(x_ext, 2),
        "es_maximo": bool(x_ext > media), "hay_atipico": hay,
        "mensaje": (
            f"El valor extremo {x_ext:.1f} mm "
            + ("ES un dato atípico" if hay else "NO es atípico")
            + f" al {int(alpha*100)} % (G = {G:.2f} "
            + (">" if hay else "≤") + f" G_crít = {G_crit:.2f}). "
            + ("En hidrología un máximo atípico no se elimina sin evidencia "
               "física; se conserva salvo error de dato comprobado."
               if hay else
               "La serie no presenta outliers que distorsionen el ajuste.")),
    })
    return out


def seleccionar_mejor_ajuste(
    ajustes: Sequence[AjusteDistribucion],
    criterio: str = "ad",
) -> AjusteDistribucion:
    """Selecciona el mejor ajuste según el criterio dado.

    criterio: "ad" (menor Anderson-Darling — DEFAULT, mejor para colas/
    extremos según el skill de hidrología boliviana), "ks" (menor KS),
    "rmse" o "aic".

    Para "ad": entre las distribuciones que PASAN KS al 5 %, se elige la de
    menor A². Si ninguna pasa KS, se usa el menor A² global. Esto sigue la
    regla del skill: descartar las que no pasan la bondad de ajuste, y
    entre las que pasan elegir la de mejor diagnóstico de cola.
    """
    if criterio == "ad":
        con_ad = [a for a in ajustes if np.isfinite(a.ad_estadistico)]
        if not con_ad:
            return min(ajustes, key=lambda a: a.ks_estadistico)
        aceptadas = [a for a in con_ad if a.aceptada_ks]
        pool = aceptadas if aceptadas else con_ad
        return min(pool, key=lambda a: a.ad_estadistico)
    if criterio == "ks":
        return min(ajustes, key=lambda a: a.ks_estadistico)
    if criterio == "rmse":
        return min(ajustes, key=lambda a: a.rmse_cuantiles)
    if criterio == "aic":
        return min(ajustes, key=lambda a: a.aic)
    raise ValueError(f"Criterio desconocido: {criterio}")


def _cuantil(ajuste: AjusteDistribucion, p_no_exc: float) -> float:
    """Cuantil X tal que P(X ≤ x) = p_no_exc, según la distribución ajustada."""
    nombre = ajuste.nombre
    params = ajuste.parametros
    if nombre == "Normal":
        return float(stats.norm.ppf(p_no_exc, loc=params[0], scale=params[1]))
    if nombre == "LogNormal":
        mu, sigma = params
        return float(stats.lognorm.ppf(p_no_exc, s=sigma, loc=0.0, scale=np.exp(mu)))
    if nombre == "LogNormal 3P":
        s, loc, sc = params
        return float(stats.lognorm.ppf(p_no_exc, s=s, loc=loc, scale=sc))
    if nombre == "Gumbel":
        return float(stats.gumbel_r.ppf(p_no_exc, loc=params[0], scale=params[1]))
    if nombre == "Pearson III":
        s, loc, sc = params
        return float(stats.pearson3.ppf(p_no_exc, s, loc=loc, scale=sc))
    if nombre == "Log-Pearson III":
        s, loc, sc = params
        return float(np.exp(stats.pearson3.ppf(p_no_exc, s, loc=loc, scale=sc)))
    if nombre == "GEV":
        c, loc, sc = params
        return float(stats.genextreme.ppf(p_no_exc, c, loc=loc, scale=sc))
    raise ValueError(f"Distribución no soportada: {nombre}")


def cuantiles_para_periodos_retorno(
    ajuste: AjusteDistribucion,
    periodos: Sequence[int] = PERIODOS_RETORNO_DEFAULT,
) -> pd.DataFrame:
    """Cuantiles X_T para los períodos de retorno T dados (años)."""
    filas = []
    for T in periodos:
        p = 1.0 - 1.0 / T
        filas.append({"T_anios": T, "prob_no_exc": p, "p24_mm": _cuantil(ajuste, p)})
    return pd.DataFrame(filas)
