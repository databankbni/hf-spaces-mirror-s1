"""Análisis de sensibilidad de los parámetros hidrológico-hidráulicos.

Exigido por el dictamen de supervisión (nivel EDTP, Manual de Hidrología y
Drenaje ABC): cuantifica cómo varían el CAUDAL máximo de diseño y el TIRANTE
hidráulico ante variaciones de ±20 % en los tres parámetros de mayor
incertidumbre del estudio:

  • CN  — número de curva (SCS): controla las pérdidas y por tanto el volumen
          de escorrentía y el caudal pico del hidrograma HEC-HMS.
  • Tc  — tiempo de concentración: controla el lag del hidrograma unitario y,
          por ende, la forma y el pico del hidrograma.
  • n   — coeficiente de rugosidad de Manning: controla el tirante normal
          (a mayor n, mayor calado para el mismo caudal).

El caudal se reevalúa con el mismo motor HEC-HMS del §13 (tormenta de 24 h,
SCS-CN + HU SCS) perturbando CN y Tc; el tirante se reevalúa con la ecuación de
Manning en la sección de control perturbando n y propagando el cambio de
caudal. Todo reutiliza los objetos ya calculados: no requiere GEE ni recomputar
la cuenca. Devuelve una estructura tabular lista para el informe.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np


@dataclass
class FilaSensibilidad:
    """Sensibilidad de Q y/o y a ±20 % de un parámetro."""
    parametro: str            # "CN", "Tc" o "n"
    unidad: str
    valor_base: float
    valor_menos: float        # −20 %
    valor_mas: float          # +20 %
    # Caudal (m³/s) resultante (None si el parámetro no afecta a Q, p. ej. n):
    q_menos: Optional[float] = None
    q_base: Optional[float] = None
    q_mas: Optional[float] = None
    # Tirante de control (m) resultante:
    y_menos: Optional[float] = None
    y_base: Optional[float] = None
    y_mas: Optional[float] = None

    @staticmethod
    def _var(a, b):
        if a is None or b is None or b == 0:
            return None
        return 100.0 * (a - b) / b

    @property
    def q_var_pct(self):
        """Máxima variación relativa de Q (%) entre los extremos y la base."""
        vs = [abs(v) for v in (self._var(self.q_menos, self.q_base),
                               self._var(self.q_mas, self.q_base)) if v is not None]
        return max(vs) if vs else None

    @property
    def y_var_pct(self):
        vs = [abs(v) for v in (self._var(self.y_menos, self.y_base),
                               self._var(self.y_mas, self.y_base)) if v is not None]
        return max(vs) if vs else None


@dataclass
class ResultadoSensibilidad:
    T_diseno: int
    filas: list = field(default_factory=list)   # list[FilaSensibilidad]
    variacion: float = 0.20                       # ±20 %
    parametro_mas_sensible_q: str = ""
    parametro_mas_sensible_y: str = ""
    nota: str = ""


def _q_hec(hec_params, hietograma, cn=None, tc=None) -> Optional[float]:
    """Q pico (m³/s) del hidrograma HEC-HMS con CN/Tc opcionalmente perturbados."""
    try:
        from .hec_hms_sim import simular_hidrograma
        p = hec_params
        if cn is not None or tc is not None:
            p = replace(hec_params,
                        cn=float(cn) if cn is not None else hec_params.cn,
                        tc_min=float(tc) if tc is not None else hec_params.tc_min)
        return float(simular_hidrograma(p, hietograma).Q_pico_m3s)
    except Exception:  # noqa: BLE001
        return None


def _seccion_control(tirante):
    """Devuelve la sección de control (más próxima al centro del tramo)."""
    secs = getattr(tirante, "secciones", None) or []
    if not secs:
        return None
    est = [s.estacion_m for s in secs]
    centro = float(np.median(est))
    i = int(np.argmin([abs(e - centro) for e in est]))
    return secs[i]


def _y_control(seccion, Q, n, S) -> Optional[float]:
    """Tirante de control (m) para un caudal, n y pendiente dados."""
    if seccion is None or Q is None or Q <= 0:
        return None
    try:
        from .hidraulica_fluvial import resolver_tirante_normal
        r = resolver_tirante_normal(seccion.x_local_m, seccion.z_m,
                                    float(Q), float(n), float(S))
        return float(r["tirante"]) if r else None
    except Exception:  # noqa: BLE001
        return None


@dataclass
class FilaSensibilidadHidraulica:
    """Respuesta de tirante/velocidad/socavación/gálibo a ±var de un parámetro."""
    parametro: str            # "Q", "n", "S" o "D50"
    variacion_pct: float      # +20, -20, +40, -40, 0 (base)
    valor: float              # valor perturbado del parámetro
    tirante_m: Optional[float] = None
    velocidad_ms: Optional[float] = None
    socavacion_m: Optional[float] = None
    cota_viga_m: Optional[float] = None    # tirante + gálibo (altura de viga)


@dataclass
class ResultadoSensibilidadHidraulica:
    filas: list = field(default_factory=list)   # list[FilaSensibilidadHidraulica]
    variaciones: tuple = (0.20, 0.40)
    galibo_m: float = 2.0
    base: dict = field(default_factory=dict)    # {tirante, V, socavacion, cota_viga}
    nota: str = ""


def _soc_total(soc) -> Optional[float]:
    """Socavación total gobernante (mayor local total, o general) de un
    ResultadoSocavacion; None si no hay."""
    if soc is None:
        return None
    cands = [v for v in (getattr(soc, "socavacion_total_pila_m", float("nan")),
                         getattr(soc, "socavacion_total_estribo_m", float("nan")))
             if v == v]
    if cands:
        return max(cands)
    g = getattr(soc, "ys_general_m", float("nan"))
    return g if g == g else None


def sensibilidad_hidraulica(*, tirante, params_puente: Optional[dict],
                            Q_base: float, T_base: int,
                            variaciones: tuple = (0.20, 0.40)
                            ) -> Optional[ResultadoSensibilidadHidraulica]:
    """Sensibilidad del DISEÑO hidráulico a ±variaciones de Q, n, S y D50.

    Para cada parámetro perturbado se recalcula, en la sección de control, el
    tirante normal (Manning), la velocidad, la socavación total (HEC-18) y la
    cota inferior de la viga requerida (tirante + gálibo). Es el análisis que
    exige la plantilla de informe definitivo (n, Q, S, D50 → y, V, ys, gálibo)
    a ±20 % y ±40 %, complementario a la sensibilidad hidrológica (CN, Tc, n).
    """
    sec = _seccion_control(tirante)
    if sec is None or not Q_base or Q_base <= 0:
        return None
    from .hidraulica_fluvial import (resolver_tirante_normal,
                                     GALIBO_DEFECTO_M)
    from .socavacion import calcular_socavacion, D50_DEFECTO_MM
    pp = dict(params_puente or {})
    n0 = float(tirante.n_manning)
    S0 = float(tirante.S_cauce)
    D0 = float(pp.get("D50_mm", D50_DEFECTO_MM))
    galibo = float(pp.get("galibo_m", getattr(tirante, "galibo_m", None)
                          or GALIBO_DEFECTO_M))

    def _evaluar(Q, n, S, D50):
        r = resolver_tirante_normal(sec.x_local_m, sec.z_m, float(Q),
                                    float(n), float(S))
        if r is None:
            return None
        soc = calcular_socavacion(
            Q=float(Q), T_anios=int(T_base), y1=r["tirante"],
            V1=r["velocidad"], Be=r["ancho_sup"], area_m2=r["area"],
            W_contraccion=pp.get("ancho_contraccion_m"),
            D50_mm=float(D50), D95_mm=pp.get("D95_mm"),
            cohesivo=pp.get("cohesivo", False), gamma_d=pp.get("gamma_d", 1.2),
            ancho_pila_m=pp.get("ancho_pila_m"),
            forma_pila=pp.get("forma_pila", "redonda"),
            angulo_ataque_grados=pp.get("angulo_ataque_grados", 0.0),
            long_pila_m=pp.get("long_pila_m"),
            long_estribo_m=pp.get("long_estribo_m"),
            forma_estribo=pp.get("forma_estribo", "derramado"),
            resguardo_m=pp.get("resguardo_m", 1.5), S_energia=float(S))
        return {"tirante": float(r["tirante"]),
                "V": float(r["velocidad"]),
                "socavacion": _soc_total(soc),
                "cota_viga": float(r["tirante"]) + galibo}

    base = _evaluar(Q_base, n0, S0, D0)
    if base is None:
        return None
    filas = [FilaSensibilidadHidraulica(
        "Base", 0.0, Q_base, base["tirante"], base["V"],
        base["socavacion"], base["cota_viga"])]

    # (nombre, valor_base, función que arma los 4 argumentos con el factor)
    _params = [
        ("Q", Q_base, lambda f: (Q_base * f, n0, S0, D0)),
        ("n", n0, lambda f: (Q_base, n0 * f, S0, D0)),
        ("S", S0 * 100.0, lambda f: (Q_base, n0, S0 * f, D0)),   # se muestra en %
        ("D50", D0, lambda f: (Q_base, n0, S0, D0 * f)),
    ]
    for nombre, vbase, arma in _params:
        for var in sorted(set(variaciones)):
            for signo in (-1.0, +1.0):
                f = 1.0 + signo * var
                Q, n, S, D50 = arma(f)
                r = _evaluar(Q, n, S, D50)
                if r is None:
                    continue
                filas.append(FilaSensibilidadHidraulica(
                    parametro=nombre, variacion_pct=signo * var * 100.0,
                    valor=vbase * f,
                    tirante_m=r["tirante"], velocidad_ms=r["V"],
                    socavacion_m=r["socavacion"], cota_viga_m=r["cota_viga"]))

    return ResultadoSensibilidadHidraulica(
        filas=filas, variaciones=tuple(sorted(set(variaciones))),
        galibo_m=galibo, base=base,
        nota=("Sensibilidad hidráulica-socavación evaluada en la sección de "
              "control reevaluando el tirante normal (Manning) y la socavación "
              "total (HEC-18) para cada parámetro perturbado."))


def analisis_sensibilidad(*, hec_params, hietograma_diseno, tirante,
                          Q_base: float, T_diseno: int,
                          variacion: float = 0.20
                          ) -> Optional[ResultadoSensibilidad]:
    """Construye el análisis de sensibilidad ±`variacion` de CN, Tc y n.

    Parámetros
    ----------
    hec_params : ParametrosHEC del §13 (cn, tc_min, área, método).
    hietograma_diseno : Hietograma de 24 h (SCS Tipo II) para T_diseno.
    tirante : ResultadoTirante del §14 (geometría de la sección de control).
    Q_base : caudal pico HEC-HMS base para T_diseno (m³/s).
    T_diseno : período de retorno de diseño.
    """
    if hec_params is None or hietograma_diseno is None or tirante is None:
        return None
    sec = _seccion_control(tirante)
    if sec is None:
        return None
    n_base = float(tirante.n_manning)
    S = float(tirante.S_cauce)
    cn_base = float(hec_params.cn)
    tc_base = float(hec_params.tc_min)
    lo, hi = 1.0 - variacion, 1.0 + variacion

    # Base de tirante coherente con el motor (resuelto sobre la misma sección).
    y_base = _y_control(sec, Q_base, n_base, S) or tirante.tirante_control_m

    filas: list[FilaSensibilidad] = []

    # ── CN: afecta Q (HEC-HMS) y, vía Q, el tirante. CN acotado a [30, 98]. ──
    cn_lo = max(30.0, cn_base * lo)
    cn_hi = min(98.0, cn_base * hi)
    q_cn_lo = _q_hec(hec_params, hietograma_diseno, cn=cn_lo)
    q_cn_hi = _q_hec(hec_params, hietograma_diseno, cn=cn_hi)
    filas.append(FilaSensibilidad(
        "CN", "—", cn_base, cn_lo, cn_hi,
        q_menos=q_cn_lo, q_base=Q_base, q_mas=q_cn_hi,
        y_menos=_y_control(sec, q_cn_lo, n_base, S), y_base=y_base,
        y_mas=_y_control(sec, q_cn_hi, n_base, S)))

    # ── Tc: afecta Q (lag del HU) y, vía Q, el tirante. ──
    tc_lo, tc_hi = tc_base * lo, tc_base * hi
    q_tc_lo = _q_hec(hec_params, hietograma_diseno, tc=tc_lo)
    q_tc_hi = _q_hec(hec_params, hietograma_diseno, tc=tc_hi)
    filas.append(FilaSensibilidad(
        "Tc", "min", tc_base, tc_lo, tc_hi,
        q_menos=q_tc_lo, q_base=Q_base, q_mas=q_tc_hi,
        y_menos=_y_control(sec, q_tc_lo, n_base, S), y_base=y_base,
        y_mas=_y_control(sec, q_tc_hi, n_base, S)))

    # ── n: NO afecta Q; afecta solo el tirante (Manning). ──
    n_lo, n_hi = n_base * lo, n_base * hi
    filas.append(FilaSensibilidad(
        "n", "—", n_base, n_lo, n_hi,
        q_menos=None, q_base=None, q_mas=None,
        y_menos=_y_control(sec, Q_base, n_lo, S), y_base=y_base,
        y_mas=_y_control(sec, Q_base, n_hi, S)))

    # Parámetro más sensible para Q y para y.
    def _mas_sensible(key):
        cand = [(f.parametro, getattr(f, key)) for f in filas
                if getattr(f, key) is not None]
        return max(cand, key=lambda kv: kv[1])[0] if cand else ""

    return ResultadoSensibilidad(
        T_diseno=int(T_diseno), filas=filas, variacion=variacion,
        parametro_mas_sensible_q=_mas_sensible("q_var_pct"),
        parametro_mas_sensible_y=_mas_sensible("y_var_pct"),
        nota=("Sensibilidad evaluada reevaluando el caudal con el motor "
              "HEC-HMS (CN, Tc) y el tirante con la ecuación de Manning en la "
              "sección de control (n, y propagando el cambio de Q)."))
