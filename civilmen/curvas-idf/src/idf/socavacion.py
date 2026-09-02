"""Socavación en puentes — tercer pilar de la hidráulica fluvial.

A partir del tirante y la velocidad en la sección de cruce (pilar 2, motor de
tirante tipo HEC-RAS) y del caudal de diseño/verificación (pilar 1), estima la
SOCAVACIÓN TOTAL para definir la profundidad de cimentación, que es el criterio
estructural crítico de la fundación (AASHTO LRFD, estado límite de evento
extremo — carga WA).

Componentes (FHWA HEC-18, Arneson et al. 2012, 5.ª ed., FHWA-HIF-12-003;
implementadas igual que en HEC-RAS «Hydraulic Design → Bridge Scour»):

1. Socavación por CONTRACCIÓN (Laursen): agua clara o lecho vivo.
2. Socavación LOCAL en PILAS: ecuación CSU/HEC-18 con factores K1–K4.
3. Socavación LOCAL en ESTRIBOS: Froehlich (L/y1 ≤ 25) o HIRE (L/y1 > 25).
4. Socavación GENERAL: Lischtvan-Lebediev (Maza Álvarez; usada en Latinoamérica).

Socavación total en una pila ≈ socavación general/contracción + socavación
local de pila. La cota de desplante debe quedar por debajo de la socavación
total (con el caudal de verificación) más un resguardo.

Solo numpy/math (coherente con el resto del codebase). Referencias completas en
la sección de socavación del informe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

_G = 9.81

# ─────────────────────────────────────────────────────────────────────────────
# D50 por defecto (mm) por tipo de cauce, cuando no hay estudio granulométrico.
# Referenciales (Chow; práctica fluvial); DEBEN reemplazarse por la granulometría
# real del sitio para el diseño definitivo.
# ─────────────────────────────────────────────────────────────────────────────
D50_POR_CAUCE = {
    "arena_fina": 0.3,
    "arena": 1.0,
    "arena_gruesa": 2.0,
    "grava_fina": 8.0,
    "grava": 25.0,
    "grava_gruesa": 60.0,
    "canto_rodado": 150.0,
}
D50_DEFECTO_MM = 25.0   # grava — cauce de montaña/valle típico en Bolivia


# ─────────────────────────────────────────────────────────────────────────────
# Estructura de resultado
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ResultadoSocavacion:
    Q_m3s: float
    T_anios: int
    y1_m: float                 # tirante de aproximación
    V1_ms: float                # velocidad de aproximación
    Fr1: float                  # Froude de aproximación
    D50_mm: float
    # Componentes (m):
    ys_general_m: float = float("nan")       # Lischtvan-Lebediev (desde superficie)
    ys_contraccion_m: float = float("nan")   # Laursen
    regimen_contraccion: str = ""            # "agua clara" | "lecho vivo"
    ys_pila_m: float = float("nan")          # CSU/HEC-18
    ys_estribo_m: float = float("nan")       # Froehlich/HIRE
    metodo_estribo: str = ""
    # Totales (m, medidos desde el fondo actual):
    socavacion_total_pila_m: float = float("nan")     # general + pila
    socavacion_total_estribo_m: float = float("nan")  # general + estribo
    prof_cimentacion_recomendada_m: float = float("nan")
    # Entradas del puente (para trazabilidad):
    ancho_pila_m: Optional[float] = None
    forma_pila: str = ""
    angulo_ataque_grados: float = 0.0
    long_estribo_m: Optional[float] = None
    resguardo_m: float = 0.0
    factores_pila: dict = field(default_factory=dict)
    advertencias: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Velocidad crítica de arrastre (Laursen / HEC-18)
# ─────────────────────────────────────────────────────────────────────────────
def velocidad_critica(y1: float, D_mm: float, Ku: float = 6.19) -> float:
    """Velocidad crítica de inicio de arrastre Vc = Ku·y1^(1/6)·D^(1/3) [m/s].

    Ku = 6.19 (SI). D en metros dentro de la fórmula; se recibe en mm.
    """
    D_m = max(D_mm, 1e-6) / 1000.0
    return Ku * (max(y1, 1e-6) ** (1.0 / 6.0)) * (D_m ** (1.0 / 3.0))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Socavación por contracción (Laursen — HEC-18 Cap. 6)
# ─────────────────────────────────────────────────────────────────────────────
def socavacion_contraccion(Q2: float, y1: float, V1: float, W1: float,
                           W2: float, D50_mm: float,
                           Q1: Optional[float] = None,
                           S1: float = 0.005) -> dict:
    """Socavación por contracción. Elige régimen agua-clara vs lecho-vivo
    comparando V1 con la velocidad crítica Vc para D50.

    Q2: caudal por la sección contraída (m³/s); y1: tirante aguas arriba (m);
    V1: velocidad aguas arriba (m/s); W1/W2: ancho aguas arriba / contraído (m);
    D50_mm: diámetro medio del lecho (mm); Q1: caudal aguas arriba que transporta
    sedimento (por defecto = Q2); S1: pendiente de energía aguas arriba.
    Devuelve dict con regimen, y2 (tirante tras socavar) y ys (= y2 − y1).
    """
    Q1 = Q2 if Q1 is None else Q1
    Vc = velocidad_critica(y1, D50_mm)
    if V1 > Vc:  # lecho vivo (live-bed)
        Vstar = math.sqrt(_G * max(y1, 1e-6) * max(S1, 1e-5))
        omega = _velocidad_caida(D50_mm)
        r = Vstar / omega if omega > 0 else 1.0
        k1 = 0.59 if r < 0.5 else (0.64 if r <= 2.0 else 0.69)
        y2 = y1 * (Q2 / max(Q1, 1e-6)) ** (6.0 / 7.0) * \
            (W1 / max(W2, 1e-6)) ** k1
        regimen = "lecho vivo"
    else:  # agua clara (clear-water)
        Ku = 0.025  # SI
        Dm = 1.25 * D50_mm / 1000.0  # m
        y2 = (Ku * Q2 ** 2 / (Dm ** (2.0 / 3.0) * max(W2, 1e-6) ** 2)) ** (3.0 / 7.0)
        regimen = "agua clara"
    ys = max(0.0, y2 - y1)
    return {"regimen": regimen, "y2": y2, "ys": ys, "Vc": Vc}


def _velocidad_caida(D50_mm: float) -> float:
    """Velocidad de caída ω (m/s) aproximada de la partícula (Rubey/relación
    simplificada). Suficiente para elegir el exponente k1."""
    d = D50_mm / 1000.0  # m
    # Rango grueso: Stokes para finos, ley cuadrática para gruesos.
    rho_rel = 1.65
    if D50_mm < 1.0:
        return (rho_rel * _G * d ** 2) / (18.0 * 1e-6)  # laminar aprox
    return math.sqrt(4.0 / 3.0 * rho_rel * _G * d / 0.4)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Socavación local en pilas — CSU / HEC-18 (Cap. 7)
# ─────────────────────────────────────────────────────────────────────────────
_K1_FORMA = {
    "cuadrada": 1.1,
    "redonda": 1.0,
    "cilindrica": 1.0,
    "circular": 1.0,
    "grupo_cilindros": 1.0,
    "aguda": 0.9,
    "triangular": 0.9,
}


def k1_forma_pila(forma: str) -> float:
    return _K1_FORMA.get((forma or "redonda").strip().lower(), 1.0)


def k2_angulo_ataque(theta_grados: float, L: float, a: float) -> float:
    """K2 = (cosθ + (L/a)·senθ)^0.65, con L/a acotado a 12."""
    theta = math.radians(abs(theta_grados))
    La = min(L / max(a, 1e-6), 12.0)
    return (math.cos(theta) + La * math.sin(theta)) ** 0.65


def k3_condicion_lecho(condicion: str = "agua_clara",
                       altura_duna_m: float = 0.0) -> float:
    c = (condicion or "").strip().lower()
    if c in ("agua_clara", "plano", "antiduna"):
        return 1.1
    if altura_duna_m >= 9.0:
        return 1.3
    if altura_duna_m >= 3.0:
        return 1.2
    return 1.1


def k4_acorazamiento(y1: float, V1: float, a: float,
                     D50_mm: float, D95_mm: float) -> float:
    """K4 reduce la socavación por acorazamiento. Solo si D50≥2 mm y D95≥20 mm;
    caso contrario 1.0. Mínimo 0.4 (HEC-18 Cap. 7)."""
    if D50_mm < 2.0 or D95_mm < 20.0:
        return 1.0
    Ku = 6.19
    D50 = D50_mm / 1000.0
    D95 = D95_mm / 1000.0
    y16 = max(y1, 1e-6) ** (1.0 / 6.0)
    VcD50 = Ku * y16 * D50 ** (1.0 / 3.0)
    VcD95 = Ku * y16 * D95 ** (1.0 / 3.0)
    VicD50 = 0.645 * (D50 / max(a, 1e-6)) ** 0.053 * VcD50
    VicD95 = 0.645 * (D95 / max(a, 1e-6)) ** 0.053 * VcD95
    denom = VcD50 - VicD95
    if denom <= 0:
        return 1.0
    VR = (V1 - VicD50) / denom
    if VR <= 0:
        return 0.4
    return max(0.4, 0.4 * VR ** 0.15)


def socavacion_pila_csu(y1: float, V1: float, a: float,
                        forma: str = "redonda",
                        theta_grados: float = 0.0,
                        L_pila: Optional[float] = None,
                        condicion_lecho: str = "agua_clara",
                        D50_mm: float = D50_DEFECTO_MM,
                        D95_mm: Optional[float] = None) -> dict:
    """Socavación local en pila (CSU/HEC-18):
        ys = 2.0·K1·K2·K3·K4·(a/y1)^0.65·Fr1^0.43 · y1
    con topes ys ≤ 2.4a (Fr≤0.8) y ys ≤ 3.0a (Fr>0.8).
    """
    Fr1 = V1 / math.sqrt(_G * max(y1, 1e-6))
    L = L_pila if L_pila else 4.0 * a
    K1 = k1_forma_pila(forma)
    if abs(theta_grados) > 5.0:
        K1 = 1.0  # domina K2
    K2 = k2_angulo_ataque(theta_grados, L, a)
    K3 = k3_condicion_lecho(condicion_lecho)
    D95 = D95_mm if D95_mm else max(D50_mm * 2.0, 20.0)
    K4 = k4_acorazamiento(y1, V1, a, D50_mm, D95)
    ys = 2.0 * K1 * K2 * K3 * K4 * (a / max(y1, 1e-6)) ** 0.65 * Fr1 ** 0.43 * y1
    tope = (2.4 if Fr1 <= 0.8 else 3.0) * a
    limitado = ys > tope
    ys = min(ys, tope)
    return {"ys": ys, "Fr1": Fr1, "K1": K1, "K2": K2, "K3": K3, "K4": K4,
            "tope_m": tope, "limitado_por_tope": limitado}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Socavación local en estribos — Froehlich / HIRE (HEC-18 Cap. 8)
# ─────────────────────────────────────────────────────────────────────────────
_K1_ESTRIBO = {
    "vertical": 1.00,
    "vertical_aleros": 0.82,
    "derramado": 0.55,
    "spill_through": 0.55,
}


def socavacion_estribo(y1: float, V1: float, L_estribo: float,
                       forma: str = "derramado",
                       theta_grados: float = 90.0) -> dict:
    """Socavación local en estribo. Froehlich si L/y1 ≤ 25; HIRE si > 25.

    L_estribo: longitud del terraplén/estribo proyectada normal al flujo (m).
    forma: 'vertical' | 'vertical_aleros' | 'derramado' (spill-through).
    theta_grados: ángulo del terraplén (90° perpendicular).
    """
    K1 = _K1_ESTRIBO.get((forma or "derramado").strip().lower(), 0.55)
    K2 = (abs(theta_grados) / 90.0) ** 0.13
    rel = L_estribo / max(y1, 1e-6)
    Fr = V1 / math.sqrt(_G * max(y1, 1e-6))
    if rel <= 25.0:
        ys = (2.27 * K1 * K2 * (L_estribo / max(y1, 1e-6)) ** 0.43 *
              Fr ** 0.61 + 1.0) * y1
        metodo = "Froehlich"
    else:
        ys = 4.0 * y1 * (K1 / 0.55) * K2 * Fr ** 0.33
        metodo = "HIRE"
    return {"ys": ys, "metodo": metodo, "K1": K1, "K2": K2, "Fr": Fr}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Socavación general — Lischtvan-Lebediev (Maza Álvarez)
# ─────────────────────────────────────────────────────────────────────────────
def beta_frecuencia(Tr: float) -> float:
    """Coeficiente de frecuencia β = 0.7929 + 0.0973·log10(Tr)."""
    return 0.7929 + 0.0973 * math.log10(max(Tr, 1.0))


# Tabla de exponente x (Lischtvan-Lebediev), no cohesivos: (dm_mm, x)
_X_NO_COHESIVO = [
    (0.05, 0.43), (0.15, 0.42), (0.50, 0.39), (1.0, 0.38), (1.5, 0.37),
    (2.0, 0.35), (3.0, 0.34), (5.0, 0.33), (10.0, 0.31), (15.0, 0.30),
    (20.0, 0.29), (40.0, 0.28), (60.0, 0.27), (100.0, 0.25), (200.0, 0.22),
]
# Cohesivos: (gamma_d_t_m3, x)
_X_COHESIVO = [
    (0.80, 0.52), (1.00, 0.50), (1.20, 0.45), (1.40, 0.42),
    (1.66, 0.39), (2.00, 0.35),
]


def _interp_tabla(tabla, valor):
    xs = [t[0] for t in tabla]
    ys = [t[1] for t in tabla]
    if valor <= xs[0]:
        return ys[0]
    if valor >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= valor <= xs[i + 1]:
            f = (valor - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + f * (ys[i + 1] - ys[i])
    return ys[-1]


def exponente_x(D50_mm: float, cohesivo: bool = False,
                gamma_d: float = 1.2) -> float:
    if cohesivo:
        return _interp_tabla(_X_COHESIVO, gamma_d)
    dm = 1.25 * D50_mm  # dm ≈ 1.25·D50 (mm)
    return _interp_tabla(_X_NO_COHESIVO, dm)


def socavacion_general_ll(Q: float, y0: float, Hm: float, Be: float, Tr: float,
                          D50_mm: float = D50_DEFECTO_MM,
                          cohesivo: bool = False, gamma_d: float = 1.2,
                          mu: float = 0.97) -> dict:
    """Socavación general por Lischtvan-Lebediev.

    Q: caudal de diseño (m³/s); y0: tirante en la vertical antes de socavar (m);
    Hm: profundidad hidráulica media = A/Be (m); Be: ancho efectivo de la
    superficie libre (m); Tr: período de retorno (años); D50_mm; cohesivo/gamma_d
    para suelos cohesivos; mu: coef. de contracción por pilas (0.95–1.0).
    Devuelve Hs (tirante socavado desde la superficie) y ys (= Hs − y0).
    """
    beta = beta_frecuencia(Tr)
    x = exponente_x(D50_mm, cohesivo, gamma_d)
    alpha = Q / (max(Hm, 1e-6) ** (5.0 / 3.0) * max(Be, 1e-6) * mu)
    if cohesivo:
        denom = 0.60 * beta * gamma_d ** 1.18
    else:
        dm = 1.25 * D50_mm  # mm
        denom = 0.68 * beta * dm ** 0.28
    Hs = (alpha * y0 ** (5.0 / 3.0) / denom) ** (1.0 / (1.0 + x))
    ys = max(0.0, Hs - y0)
    return {"Hs": Hs, "ys": ys, "beta": beta, "x": x, "alpha": alpha}


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador
# ─────────────────────────────────────────────────────────────────────────────
def calcular_socavacion(*, Q: float, T_anios: int, y1: float, V1: float,
                        Be: float, W_contraccion: Optional[float] = None,
                        area_m2: Optional[float] = None,
                        D50_mm: float = D50_DEFECTO_MM,
                        D95_mm: Optional[float] = None,
                        cohesivo: bool = False, gamma_d: float = 1.2,
                        ancho_pila_m: Optional[float] = None,
                        forma_pila: str = "redonda",
                        angulo_ataque_grados: float = 0.0,
                        long_pila_m: Optional[float] = None,
                        long_estribo_m: Optional[float] = None,
                        forma_estribo: str = "derramado",
                        resguardo_m: float = 1.5,
                        S_energia: float = 0.005) -> Optional[ResultadoSocavacion]:
    """Calcula la socavación total y la profundidad de cimentación recomendada.

    Toma el tirante y velocidad de la sección de control (pilar 2). Los
    componentes locales (pila/estribo) solo se calculan si se dan sus geometrías.
    `Be` = ancho de la superficie del agua en la sección de cruce (m).
    """
    if Q is None or Q <= 0 or y1 <= 0 or V1 <= 0:
        return None
    adv: list[str] = []
    Fr1 = V1 / math.sqrt(_G * y1)
    Hm = (area_m2 / Be) if (area_m2 and Be) else y1  # prof. hidráulica media

    r = ResultadoSocavacion(
        Q_m3s=Q, T_anios=T_anios, y1_m=y1, V1_ms=V1, Fr1=Fr1, D50_mm=D50_mm,
        ancho_pila_m=ancho_pila_m, forma_pila=forma_pila,
        angulo_ataque_grados=angulo_ataque_grados,
        long_estribo_m=long_estribo_m, resguardo_m=resguardo_m)

    # 4. General (Lischtvan-Lebediev)
    gen = socavacion_general_ll(Q, y1, Hm, Be, T_anios, D50_mm, cohesivo,
                                gamma_d)
    r.ys_general_m = gen["ys"]

    # 1. Contracción (Laursen) — si se conoce el ancho contraído del puente.
    if W_contraccion and Be:
        con = socavacion_contraccion(Q, y1, V1, Be, W_contraccion, D50_mm,
                                     S1=S_energia)
        r.ys_contraccion_m = con["ys"]
        r.regimen_contraccion = con["regimen"]

    # Socavación "de aproximación" para las locales = la mayor entre general y
    # contracción (ambas describen el descenso generalizado del lecho).
    ys_aprox = max(v for v in (r.ys_general_m, r.ys_contraccion_m)
                   if v == v)  # ignora NaN

    # 2. Pila (CSU) — si hay pila en el cauce.
    if ancho_pila_m and ancho_pila_m > 0:
        pil = socavacion_pila_csu(y1, V1, ancho_pila_m, forma_pila,
                                  angulo_ataque_grados, long_pila_m,
                                  D50_mm=D50_mm, D95_mm=D95_mm)
        r.ys_pila_m = pil["ys"]
        r.factores_pila = {k: pil[k] for k in ("K1", "K2", "K3", "K4",
                                               "tope_m", "limitado_por_tope")}
        if pil["limitado_por_tope"]:
            adv.append("La socavación local de pila se limitó al tope físico "
                       "del foso (HEC-18).")
        r.socavacion_total_pila_m = ys_aprox + r.ys_pila_m

    # 3. Estribo (Froehlich/HIRE) — si se da su longitud.
    if long_estribo_m and long_estribo_m > 0:
        est = socavacion_estribo(y1, V1, long_estribo_m, forma_estribo)
        r.ys_estribo_m = est["ys"]
        r.metodo_estribo = est["metodo"]
        r.socavacion_total_estribo_m = ys_aprox + r.ys_estribo_m

    # Profundidad de cimentación recomendada = mayor socavación total + resguardo.
    totales = [v for v in (r.socavacion_total_pila_m,
                           r.socavacion_total_estribo_m) if v == v]
    if not totales:
        totales = [ys_aprox]  # sin obras locales: solo descenso generalizado
    r.prof_cimentacion_recomendada_m = max(totales) + resguardo_m

    if D50_mm == D50_DEFECTO_MM:
        adv.append(f"Se usó D50 = {D50_mm:.0f} mm por defecto (grava). Para el "
                   f"diseño definitivo, reemplazar por la granulometría real "
                   f"(D50, D95) del estudio de suelos del cauce.")
    # Rango de validez de las ecuaciones respecto del régimen del flujo. La
    # ecuación CSU de pila (HEC-18) se calibró mayoritariamente en laboratorio
    # con flujo subcrítico; su término Fr^0.43 extrapola fuera de ese rango. Si
    # el cauce trabaja en régimen supercrítico hay que declararlo en lugar de
    # publicar la profundidad como si estuviera dentro de calibración.
    if Fr1 == Fr1 and Fr1 > 1.0:
        adv.append(
            f"RÉGIMEN SUPERCRÍTICO en la sección de control (Fr = {Fr1:.2f}). "
            f"Las ecuaciones de socavación local de HEC-18 (CSU para pilas, "
            f"Froehlich/HIRE para estribos) fueron calibradas principalmente "
            f"con flujo subcrítico, por lo que su aplicación aquí constituye "
            f"una EXTRAPOLACIÓN fuera del rango de calibración y tiende a ser "
            f"conservadora. La profundidad resultante debe verificarse con "
            f"modelación hidráulica de detalle y, de ser posible, con ensayo "
            f"o referencia de cauces de montaña comparables antes de fijar la "
            f"cota de fundación.")
    elif Fr1 == Fr1 and Fr1 > 0.8:
        adv.append(
            f"Froude de aproximación alto (Fr = {Fr1:.2f}, cercano al "
            f"crítico): la socavación local es sensible a pequeñas variaciones "
            f"de la velocidad, por lo que conviene contrastar el resultado con "
            f"el análisis de sensibilidad del coeficiente de Manning.")
    r.advertencias = adv
    return r
