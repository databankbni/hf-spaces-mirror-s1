"""Análisis de sensibilidad del caudal de diseño al cambio climático.

Aplica el **método de deltas** (IPCC/CMIP6) sobre la precipitación de diseño y
propaga el cambio al caudal pico mediante la ecuación de escorrentía SCS-CN, que
es la base del cálculo hidrológico del informe. Como la relación P→Q es no
lineal (elasticidad > 1), un incremento porcentual de la lluvia produce un
incremento mayor del caudal; esta sección lo cuantifica.

Los factores de cambio (Δ) son **representativos y ajustables**: reflejan el
orden de magnitud del aumento de la precipitación extrema proyectado para los
Andes/Bolivia hacia mediados de siglo bajo distintos forzamientos, y deben
sustituirse por un downscaling regional (CMIP6, quantile mapping) cuando se
disponga de él.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Escenarios de sensibilidad: (nombre, Δ precipitación). Proxies de CMIP6.
ESCENARIOS_CC = (
    ("Sensibilidad moderada (proxy SSP2-4.5, ~2050)", 0.10),
    ("Sensibilidad intermedia (proxy SSP3-7.0, ~2050)", 0.20),
    ("Sensibilidad severa (proxy SSP5-8.5, ~2050)", 0.30),
)


@dataclass
class FilaSensibilidadCC:
    escenario: str
    delta_p_pct: float
    p24_cc_mm: float
    q_cc_m3s: float
    delta_q_pct: float


@dataclass
class ResultadoSensibilidadCC:
    p24_base_mm: float
    q_base_m3s: float
    cn: float
    elasticidad: float          # (ΔQ/Q)/(ΔP/P) en el primer escenario
    filas: list[FilaSensibilidadCC] = field(default_factory=list)
    nota: str = ""


def _escorrentia_scs(P_mm: float, S_mm: float) -> float:
    """Lámina de escorrentía SCS-CN (mm): Q=(P−0.2S)²/(P+0.8S), 0 si P≤0.2S."""
    ia = 0.2 * S_mm
    if P_mm <= ia:
        return 0.0
    return (P_mm - ia) ** 2 / (P_mm + 0.8 * S_mm)


def analisis_sensibilidad_cc(p24_base_mm: float, q_base_m3s: float,
                             cn: float) -> ResultadoSensibilidadCC | None:
    """Sensibilidad del caudal de diseño a deltas de precipitación por CC.

    Propaga ΔP → ΔQ con la razón de escorrentías SCS-CN (misma CN de diseño),
    asumiendo que la forma del hidrograma se conserva (Q_pico ∝ escorrentía)."""
    if not p24_base_mm or p24_base_mm <= 0 or not q_base_m3s or q_base_m3s <= 0:
        return None
    cn = float(cn) if cn else 75.0
    cn = min(max(cn, 30.0), 98.0)
    S = 25400.0 / cn - 254.0
    q_esc_base = _escorrentia_scs(p24_base_mm, S)
    if q_esc_base <= 0:
        return None
    filas = []
    elasticidad = 0.0
    for nombre, d in ESCENARIOS_CC:
        p_cc = p24_base_mm * (1.0 + d)
        q_esc_cc = _escorrentia_scs(p_cc, S)
        ratio = q_esc_cc / q_esc_base if q_esc_base > 0 else 1.0
        dq = (ratio - 1.0) * 100.0
        filas.append(FilaSensibilidadCC(
            escenario=nombre, delta_p_pct=d * 100.0,
            p24_cc_mm=round(p_cc, 1), q_cc_m3s=round(q_base_m3s * ratio, 2),
            delta_q_pct=round(dq, 1)))
        if abs(d) > 0 and elasticidad == 0.0:
            elasticidad = round((ratio - 1.0) / d, 2)
    nota = (
        "La elasticidad Q–P supera la unidad: el caudal crece "
        "proporcionalmente más que la lluvia (efecto de la abstracción "
        "inicial SCS). Se recomienda adoptar un margen de seguridad o "
        "verificar las obras con el escenario severo, especialmente en obras "
        "de larga vida útil.")
    return ResultadoSensibilidadCC(
        p24_base_mm=round(p24_base_mm, 1), q_base_m3s=round(q_base_m3s, 2),
        cn=cn, elasticidad=elasticidad, filas=filas, nota=nota)
