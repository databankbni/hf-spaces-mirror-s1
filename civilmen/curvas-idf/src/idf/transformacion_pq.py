"""Transformación precipitación → caudal mensual sobre la cuenca delineada.

Implementa un balance hidrológico mensual conceptual de un único reservorio
(Thornthwaite–Mather modificado con flujo base lineal), alimentado con la
serie mensual de CHIRPS (P) y la PET mensual MOD16A2 promediadas sobre el
polígono real de cuenca extraído con MERIT Hydro. El esquema es:

    AET_t   = min(PET_t, P_t + S_{t-1})        si AET ≤ disponibilidad
    S_t     = clip(S_{t-1} + P_t − AET_t, 0, CAW)
    R_t     = max(0, S_{t-1} + P_t − AET_t − CAW)        excedente
    Qb_t    = α · GS_{t-1}                      flujo base (lineal)
    GS_t    = (1 − α) · GS_{t-1} + (1 − f) · R_t
    Q_t     = f · R_t + Qb_t                    (mm/mes)
    Caudal  = Q_t · A_km² · 10³ / Δt_seg_mes    (m³/s)

Notas hidrológicas:

- CAW (Capacidad de Agua Aprovechable) se obtiene de `mapas_qmin_gee` (mm).
- α (constante de recesión del acuífero) se calibra implícitamente a partir
  del índice de aridez AI: cuencas más áridas → α ≈ 0.06, cuencas húmedas
  → α ≈ 0.18, modulado además por el TWI (mayor TWI → α más bajo, recesión
  más lenta).
- f (fracción rápida del excedente) responde al CN ponderado (más CN ⇒ más
  escorrentía directa). Falla suave: si CN no está, f = 0.5.

Salidas:
- Serie mensual de Q (m³/s) climática (12 valores, promedio multianual).
- FDC empírica anual con percentiles Q5, Q50, Q75, Q85, Q90, Q95.
- Q7,10 estimado por método de momentos sobre la serie diaria desagregada
  (escalado del mes mínimo por el cociente Qmín/Qmed mensual histórico).
- Diccionario completo con todas las series para que el llamador genere
  los plots (FDC, climatología, recesión, etc.).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ─────────────────────── Parametrización del modelo ───────────────────────

# Días por mes (no bisiesto). Se usan para convertir Q de mm/mes → m³/s.
_DIAS_MES = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _alpha_recesion(ai: Optional[float], twi: Optional[float]) -> float:
    """Constante de recesión mensual del acuífero (1/mes).

    Más árido o menor TWI → α mayor (recesión rápida, peor Q mínimo).
    Húmedo o TWI alto → α menor (recesión lenta, sostiene flujo en estiaje).
    """
    base = 0.10
    if ai is not None and math.isfinite(ai):
        if ai < 0.20:
            base = 0.16
        elif ai < 0.50:
            base = 0.12
        elif ai < 1.0:
            base = 0.08
        else:
            base = 0.06
    if twi is not None and math.isfinite(twi):
        # TWI ~ 8..15. Cada unidad por encima de 10 reduce α 0.005.
        base -= 0.005 * max(0.0, twi - 10.0)
    return float(max(0.03, min(0.25, base)))


def _fraccion_rapida(cn: Optional[float]) -> float:
    """Fracción de excedente que viaja como respuesta rápida.

    Mayor CN ⇒ más escorrentía directa (menos infiltración). Mapping lineal
    desde CN = 55 (f=0.20) hasta CN = 95 (f=0.85).
    """
    if cn is None or not math.isfinite(cn):
        return 0.5
    f = 0.20 + (cn - 55.0) * (0.85 - 0.20) / (95.0 - 55.0)
    return float(max(0.10, min(0.90, f)))


# ─────────────────────── Climatologías auxiliares ───────────────────────

# Reparto mensual aproximado de la precipitación tropical andina-amazónica
# (% del total anual). Se usa cuando solo se dispone de Pann (sin descarga
# mensual real CHIRPS). Sigue el patrón típico de Bolivia: estiaje JJA, pico
# DJF. Para Altiplano sur el cliente debería pasar `mes_pico=2` y otros.
_REPARTO_DEFAULT = np.array(
    [0.18, 0.16, 0.13, 0.07, 0.03, 0.01, 0.01, 0.02, 0.04, 0.08, 0.12, 0.15]
)


def _serie_mensual_uniforme(pann_mm: float, etann_mm: float,
                              reparto: np.ndarray = _REPARTO_DEFAULT
                              ) -> tuple[np.ndarray, np.ndarray]:
    """Genera P y PET mensuales a partir de los totales anuales y un reparto.

    La PET se reparte invertida (mayor en meses secos = invierno seco
    soleado), pero centrada en el régimen tropical: máximo octubre, mínimo
    junio.
    """
    p_mes = pann_mm * reparto
    reparto_pet = np.array([0.10, 0.09, 0.09, 0.08, 0.06, 0.05,
                             0.06, 0.08, 0.09, 0.10, 0.10, 0.10])
    reparto_pet = reparto_pet / reparto_pet.sum()
    pet_mes = etann_mm * reparto_pet
    return p_mes, pet_mes


# ─────────────────────── Balance hidrológico mensual ───────────────────────

@dataclass
class ResultadoPQ:
    """Salida de la transformación P→Q."""
    # Cantidades de balance (mm/mes, 12 valores climáticos):
    p_mes_mm: np.ndarray = field(default_factory=lambda: np.zeros(12))
    aet_mes_mm: np.ndarray = field(default_factory=lambda: np.zeros(12))
    s_mes_mm: np.ndarray = field(default_factory=lambda: np.zeros(12))
    r_mes_mm: np.ndarray = field(default_factory=lambda: np.zeros(12))
    qb_mes_mm: np.ndarray = field(default_factory=lambda: np.zeros(12))
    q_mes_mm: np.ndarray = field(default_factory=lambda: np.zeros(12))
    # Caudales convertidos por unidad de tiempo:
    q_mes_m3s: np.ndarray = field(default_factory=lambda: np.zeros(12))
    qb_mes_m3s: np.ndarray = field(default_factory=lambda: np.zeros(12))
    # Resúmenes:
    q_medio_m3s: float = 0.0
    q_min_m3s: float = 0.0
    q_max_m3s: float = 0.0
    coef_escorrentia_anual: float = 0.0
    # Curva de duración (anual): fracción de tiempo excedido (12 puntos).
    fdc_pct: np.ndarray = field(default_factory=lambda: np.zeros(12))
    fdc_q_m3s: np.ndarray = field(default_factory=lambda: np.zeros(12))
    # Percentiles típicos para uso operativo:
    q5: float = 0.0
    q50: float = 0.0
    q75: float = 0.0
    q85: float = 0.0
    q90: float = 0.0
    q95: float = 0.0
    # Q7,10 estimado (m³/s):
    q7_10: float = 0.0
    # Parámetros usados:
    alpha: float = 0.10
    fraccion_rapida: float = 0.5
    caw_usada_mm: float = 150.0
    area_km2: float = 0.0
    pann_mm: float = 0.0
    etann_mm: float = 0.0
    ai: float = 0.0
    # Estado para diagnóstico:
    fuente_datos: str = ""


def _balance_mensual(p_mes: np.ndarray, pet_mes: np.ndarray,
                      caw: float, alpha: float, fraccion_rapida: float,
                      iter_estabilizar: int = 5) -> dict:
    """Itera el balance hasta que el almacenamiento se estabiliza (≥ 3 ciclos)."""
    n = 12
    aet = np.zeros(n)
    s = np.zeros(n)
    r = np.zeros(n)
    qb = np.zeros(n)
    q = np.zeros(n)
    s_prev = caw * 0.5
    gs_prev = 0.0
    for _ in range(iter_estabilizar):
        for t in range(n):
            disp = s_prev + p_mes[t]
            aet[t] = min(pet_mes[t], disp)
            s_post = disp - aet[t]
            r[t] = max(0.0, s_post - caw)
            s[t] = min(caw, max(0.0, s_post))
            qb[t] = alpha * gs_prev
            gs_prev = (1 - alpha) * gs_prev + (1 - fraccion_rapida) * r[t]
            q[t] = fraccion_rapida * r[t] + qb[t]
            s_prev = s[t]
    return {"aet": aet, "s": s, "r": r, "qb": qb, "q": q}


def _mm_mes_a_m3s(q_mm: np.ndarray, area_km2: float) -> np.ndarray:
    """Convierte mm/mes a m³/s usando el área (km²) y los días de cada mes."""
    out = np.zeros(12)
    for t in range(12):
        seg = _DIAS_MES[t] * 86400.0
        out[t] = q_mm[t] * 1e-3 * (area_km2 * 1e6) / seg
    return out


def _fdc_desde_mensual(q_mes_m3s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """FDC empírica a partir de la serie climática mensual.

    Pondera cada valor mensual por la longitud relativa del mes (en lugar de
    Weibull plain) — es exacta para una serie cíclica.
    """
    pesos = np.array(_DIAS_MES, dtype=float)
    pesos = pesos / pesos.sum()
    orden = np.argsort(q_mes_m3s)[::-1]   # de mayor a menor
    q_ord = q_mes_m3s[orden]
    w_ord = pesos[orden]
    excedencia = np.cumsum(w_ord) - 0.5 * w_ord
    return excedencia * 100.0, q_ord


def _percentil_excedencia(pct_arr: np.ndarray, q_arr: np.ndarray,
                            p: float) -> float:
    """Interpola Qp para la fracción de excedencia p (%) en una FDC discreta."""
    if pct_arr[0] > p:
        return float(q_arr[0])
    if pct_arr[-1] < p:
        return float(q_arr[-1])
    return float(np.interp(p, pct_arr, q_arr))


def _estimar_q7_10(q_mes_m3s: np.ndarray, q95: float) -> float:
    """Q7,10 aproximado: 7 días consecutivos, T=10 años.

    Usa la relación empírica regional Smakhtin (2001) Q7,10 ≈ 0.60 · Q95
    para cuencas tropicales con régimen estacional fuerte. Se ajusta si el
    contraste estacional Qmin/Qmed mensual indica acuífero pobre.
    """
    q_mes_min = float(q_mes_m3s.min())
    q_mes_med = float(q_mes_m3s.mean()) or 1e-9
    razon = q_mes_min / q_mes_med
    base = 0.60 if razon > 0.30 else 0.45 if razon > 0.15 else 0.30
    return float(max(0.0, base * q95))


def transformacion_pq(area_km2: float,
                       pann_mm: Optional[float],
                       etann_mm: Optional[float],
                       caw_mm: Optional[float] = None,
                       cn_ponderado: Optional[float] = None,
                       ai: Optional[float] = None,
                       twi: Optional[float] = None,
                       p_mes_mm: Optional[np.ndarray] = None,
                       pet_mes_mm: Optional[np.ndarray] = None
                       ) -> ResultadoPQ:
    """Punto de entrada del modelo.

    `p_mes_mm` y `pet_mes_mm` pueden venir directos (12 valores climáticos
    extraídos de CHIRPS/MOD16 mensual) — preferido. Si no, se construyen a
    partir de los totales anuales con un reparto típico tropical.

    Devuelve `ResultadoPQ` listo para alimentar plots y conclusiones.
    """
    if not area_km2 or area_km2 <= 0:
        raise ValueError("area_km2 debe ser positivo")
    pann = float(pann_mm) if pann_mm else 800.0
    etann = float(etann_mm) if etann_mm else min(0.85 * pann, 1100.0)
    caw = float(caw_mm) if caw_mm else 150.0
    alpha = _alpha_recesion(ai, twi)
    fraccion = _fraccion_rapida(cn_ponderado)

    if p_mes_mm is None or pet_mes_mm is None:
        p_mes, pet_mes = _serie_mensual_uniforme(pann, etann)
        fuente = "Pann/ETann anuales + reparto climático tropical"
    else:
        p_mes = np.asarray(p_mes_mm, dtype=float)
        pet_mes = np.asarray(pet_mes_mm, dtype=float)
        fuente = "Series mensuales CHIRPS + MOD16A2"

    bal = _balance_mensual(p_mes, pet_mes, caw, alpha, fraccion)
    q_mm = bal["q"]
    q_m3s = _mm_mes_a_m3s(q_mm, area_km2)
    qb_m3s = _mm_mes_a_m3s(bal["qb"], area_km2)
    fdc_pct, fdc_q = _fdc_desde_mensual(q_m3s)
    q5 = _percentil_excedencia(fdc_pct, fdc_q, 5.0)
    q50 = _percentil_excedencia(fdc_pct, fdc_q, 50.0)
    q75 = _percentil_excedencia(fdc_pct, fdc_q, 75.0)
    q85 = _percentil_excedencia(fdc_pct, fdc_q, 85.0)
    q90 = _percentil_excedencia(fdc_pct, fdc_q, 90.0)
    q95 = _percentil_excedencia(fdc_pct, fdc_q, 95.0)
    q710 = _estimar_q7_10(q_m3s, q95)
    coef = float(q_mm.sum() / pann) if pann else 0.0

    return ResultadoPQ(
        p_mes_mm=p_mes,
        aet_mes_mm=bal["aet"],
        s_mes_mm=bal["s"],
        r_mes_mm=bal["r"],
        qb_mes_mm=bal["qb"],
        q_mes_mm=q_mm,
        q_mes_m3s=q_m3s,
        qb_mes_m3s=qb_m3s,
        q_medio_m3s=float(q_m3s.mean()),
        q_min_m3s=float(q_m3s.min()),
        q_max_m3s=float(q_m3s.max()),
        coef_escorrentia_anual=coef,
        fdc_pct=fdc_pct,
        fdc_q_m3s=fdc_q,
        q5=q5, q50=q50, q75=q75, q85=q85, q90=q90, q95=q95,
        q7_10=q710,
        alpha=alpha,
        fraccion_rapida=fraccion,
        caw_usada_mm=caw,
        area_km2=area_km2,
        pann_mm=pann,
        etann_mm=etann,
        ai=float(ai) if ai is not None else (pann / max(etann, 1.0)),
        fuente_datos=fuente,
    )


# ─────────────────────── Generación de gráficos ───────────────────────

_MESES = ("Ene", "Feb", "Mar", "Abr", "May", "Jun",
          "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")


def plot_balance_mensual(res: ResultadoPQ, archivo) -> "Path":
    """Diagrama de barras P/PET/AET + caudal Q + flujo base mensual."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6.2), sharex=True,
                                     gridspec_kw={"height_ratios": [2, 1.6]})
    x = np.arange(12)
    w = 0.27
    ax1.bar(x - w, res.p_mes_mm, w, label="P (mm)", color="#3b8bd8")
    ax1.bar(x,     res.aet_mes_mm, w, label="AET (mm)", color="#27ae60")
    ax1.bar(x + w, res.p_mes_mm - res.aet_mes_mm - (res.s_mes_mm
                                                     - np.roll(res.s_mes_mm, 1)),
             w, label="Excedente R (mm)", color="#e67e22", alpha=0.85)
    ax1.set_ylabel("Lámina (mm/mes)")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.set_title("Balance hidrológico mensual climático",
                   color="#1f3a68", fontsize=11)
    ax1.grid(True, alpha=0.3)

    ax2.bar(x, res.q_mes_m3s, color="#1f3a68", label="Q total (m³/s)")
    ax2.bar(x, res.qb_mes_m3s, color="#7fb3ff", label="Q base (m³/s)",
             alpha=0.95)
    ax2.set_ylabel("Caudal (m³/s)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(_MESES)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.3)

    fig.suptitle(f"Transformación P→Q · A = {res.area_km2:.1f} km² · "
                  f"CAW = {res.caw_usada_mm:.0f} mm · α = {res.alpha:.2f}",
                  fontsize=10, color="#555")
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_fdc(res: ResultadoPQ, archivo) -> "Path":
    """Curva de duración de caudales (FDC) en m³/s vs % de tiempo excedido."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path
    fig, ax = plt.subplots(figsize=(8.6, 5.4))
    ax.plot(res.fdc_pct, res.fdc_q_m3s, marker="o", color="#1f3a68",
             lw=1.4)
    ax.fill_between(res.fdc_pct, res.fdc_q_m3s, alpha=0.16, color="#1f3a68")
    # Líneas verticales en percentiles operativos.
    for p, q, lbl, col in [(5, res.q5, "Q5", "#27ae60"),
                            (50, res.q50, "Q50", "#1f3a68"),
                            (75, res.q75, "Q75", "#e67e22"),
                            (90, res.q90, "Q90", "#d7191c"),
                            (95, res.q95, "Q95", "#a50026")]:
        ax.axvline(p, lw=0.7, color=col, ls="--", alpha=0.55)
        ax.text(p, q, f" {lbl} = {q:.2f}", fontsize=7.5, color=col,
                 va="bottom")
    ax.set_xlabel("% del tiempo en que el caudal es excedido")
    ax.set_ylabel("Caudal (m³/s)")
    ax.set_yscale("log")
    ax.set_xlim(0, 100)
    ax.grid(True, which="both", alpha=0.32, lw=0.5)
    ax.set_title(f"Curva de duración de caudales (FDC) — Q7,10 ≈ {res.q7_10:.2f} m³/s",
                  color="#1f3a68", fontsize=11)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
