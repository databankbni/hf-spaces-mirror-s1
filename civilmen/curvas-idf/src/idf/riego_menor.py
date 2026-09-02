"""Hidráulica fluvial para captación de riego menor.

Dimensiona preliminarmente las obras de una toma de riego a partir del caudal
de captación (demanda) y de los caudales del río (estiaje y crecida) que aporta
el estudio hidrológico:

- **Canal de conducción** — sección de máxima eficiencia (o geometría dada) por
  Manning, con verificación de velocidades (no sedimentación / no erosión).
- **Desarenador** — velocidad de sedimentación de la partícula de diseño
  (ecuación de arrastre con Cd = f(Re)) y dimensiones por el método de Camp.
- **Bocatoma** — se dimensionan las tres alternativas: (a) barraje fijo + toma
  lateral, (b) toma tirolesa (rejilla de fondo) y (c) toma directa sin barraje.
- **Protección de márgenes** — enrocado (Isbash) y gaviones a partir de la
  velocidad del río.

Es un **predimensionamiento**; el diseño definitivo requiere topografía del
sitio, modelación HEC-RAS y estudio de sedimentos.

Referencias
-----------
- Krochin, S. *Diseño Hidráulico* (canales, desarenadores, tomas).
- Rocha, A. *Hidráulica de Tuberías y Canales*.
- MMAyA/VRHR — criterios de obras de riego (Bolivia).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

G = 9.81
_NU = 1.0e-6      # viscosidad cinemática del agua (m²/s, ~20 °C)
_SS = 2.65        # densidad relativa de la arena/roca

# n de Manning por revestimiento del canal.
N_REVESTIMIENTO = {
    "tierra": 0.025,
    "tierra_revestida": 0.020,
    "mamposteria": 0.017,
    "hormigon": 0.014,
    "hormigon_pulido": 0.013,
}
# Velocidades admisibles (m/s): mínima (evita sedimentación) y máxima (evita
# erosión) según revestimiento.
V_ADM = {
    "tierra": (0.40, 0.80),
    "tierra_revestida": (0.45, 1.50),
    "mamposteria": (0.60, 3.00),
    "hormigon": (0.60, 4.00),
    "hormigon_pulido": (0.60, 5.00),
}


# ─────────────────── Velocidad de sedimentación ───────────────────

def velocidad_sedimentacion(d_mm: float) -> float:
    """Velocidad de caída (m/s) de una partícula de diámetro d (mm) en agua,
    resolviendo vs = √(4 g d (Ss−1) / (3 Cd)) con Cd = f(Re) iterado."""
    d = d_mm / 1000.0
    vs = 0.1
    for _ in range(50):
        Re = vs * d / _NU
        Re = max(Re, 1e-6)
        Cd = 24.0 / Re + 3.0 / math.sqrt(Re) + 0.34   # White
        vs_new = math.sqrt(4.0 * G * d * (_SS - 1.0) / (3.0 * Cd))
        if abs(vs_new - vs) < 1e-6:
            vs = vs_new
            break
        vs = vs_new
    return vs


# ─────────────────── Canal de conducción ───────────────────

@dataclass
class Canal:
    forma: str
    Q_m3s: float
    n_manning: float
    So: float
    talud_z: float
    base_b_m: float
    tirante_y_m: float
    area_m2: float
    velocidad_ms: float
    froude: float
    bordo_libre_m: float
    alto_total_m: float
    v_adm_min_ms: float
    v_adm_max_ms: float
    obs: list[str] = field(default_factory=list)


def _y_normal_canal(Q, n, So, z, b):
    """Tirante normal por Manning para sección trapezoidal (z=0 → rectangular)."""
    obj = Q * n / math.sqrt(So)
    lo, hi = 1e-4, 50.0
    for _ in range(80):
        y = 0.5 * (lo + hi)
        A = (b + z * y) * y
        P = b + 2.0 * y * math.sqrt(1.0 + z * z)
        val = A * (A / P) ** (2.0 / 3.0) if P > 0 else 0.0
        if val < obj:
            lo = y
        else:
            hi = y
    return 0.5 * (lo + hi)


def disenar_canal(Q, So_pct, revestimiento="hormigon", forma="trapezoidal",
                  talud_z=1.0, base_b_m=None):
    """Diseña el canal de conducción. Si no se fija la base, usa la sección de
    máxima eficiencia hidráulica."""
    n = N_REVESTIMIENTO.get(revestimiento, 0.014)
    So = max(So_pct / 100.0, 1e-4)
    z = talud_z if forma == "trapezoidal" else 0.0
    if base_b_m and base_b_m > 0:
        b = float(base_b_m)
        y = _y_normal_canal(Q, n, So, z, b)
    else:
        # Sección de máxima eficiencia: b/y = 2(√(1+z²) − z).
        rel = 2.0 * (math.sqrt(1.0 + z * z) - z)
        # Resolver y con b = rel·y.
        obj = Q * n / math.sqrt(So)
        lo, hi = 1e-4, 50.0
        for _ in range(80):
            y = 0.5 * (lo + hi)
            b = rel * y
            A = (b + z * y) * y
            P = b + 2.0 * y * math.sqrt(1.0 + z * z)
            val = A * (A / P) ** (2.0 / 3.0) if P > 0 else 0.0
            if val < obj:
                lo = y
            else:
                hi = y
        y = 0.5 * (lo + hi)
        b = rel * y
    A = (b + z * y) * y
    V = Q / A if A > 0 else 0.0
    T = b + 2.0 * z * y            # ancho superficial
    Dh = A / T if T > 0 else y     # profundidad hidráulica
    Fr = V / math.sqrt(G * Dh) if Dh > 0 else 0.0
    # Bordo libre (criterio práctico): ~ 0.30 m mínimo o 1/3 del tirante.
    bl = max(0.30, y / 3.0)
    vmin, vmax = V_ADM.get(revestimiento, (0.6, 4.0))
    obs = []
    if V < vmin:
        obs.append(f"V = {V:.2f} m/s < mínima {vmin:.2f}: riesgo de "
                   "sedimentación; aumentar pendiente o reducir sección")
    if V > vmax:
        obs.append(f"V = {V:.2f} m/s > máxima {vmax:.2f}: riesgo de erosión; "
                   "reducir pendiente o revestir mejor")
    if Fr > 0.9 and Fr < 1.1:
        obs.append("Flujo cercano al crítico (Fr≈1): inestable, ajustar sección")
    return Canal(
        forma=forma, Q_m3s=float(Q), n_manning=n, So=So, talud_z=z,
        base_b_m=round(b, 3), tirante_y_m=round(y, 3), area_m2=round(A, 3),
        velocidad_ms=round(V, 3), froude=round(Fr, 3),
        bordo_libre_m=round(bl, 2), alto_total_m=round(y + bl, 2),
        v_adm_min_ms=vmin, v_adm_max_ms=vmax, obs=obs)


# ─────────────────── Desarenador ───────────────────

@dataclass
class Desarenador:
    Q_m3s: float
    d_particula_mm: float
    vs_sedim_ms: float
    vh_horizontal_ms: float
    profundidad_m: float
    ancho_m: float
    longitud_m: float
    tiempo_retencion_s: float
    obs: list[str] = field(default_factory=list)


def disenar_desarenador(Q, d_particula_mm=0.20, vh_ms=0.25,
                        profundidad_m=1.5, k_seguridad=1.5):
    """Dimensiona el desarenador (método de Camp): L = k·vh·h/vs."""
    vs = velocidad_sedimentacion(d_particula_mm)
    h = float(profundidad_m)
    vh = float(vh_ms)
    B = Q / (vh * h) if (vh * h) > 0 else 0.0
    L = k_seguridad * vh * h / vs if vs > 0 else 0.0
    t = L / vh if vh > 0 else 0.0
    obs = []
    if vh > 0.5:
        obs.append("Velocidad horizontal alta (>0.5 m/s): puede re-suspender "
                   "el sedimento; reducir vh")
    if B > 0 and L / B < 3:
        obs.append("Relación L/B < 3: alargar la nave para mejor eficiencia")
    return Desarenador(
        Q_m3s=float(Q), d_particula_mm=float(d_particula_mm),
        vs_sedim_ms=round(vs, 4), vh_horizontal_ms=vh,
        profundidad_m=round(h, 2), ancho_m=round(B, 2),
        longitud_m=round(L, 2), tiempo_retencion_s=round(t, 1), obs=obs)


# ─────────────────── Bocatoma (tres alternativas) ───────────────────

@dataclass
class Bocatoma:
    tipo: str
    nombre: str
    parametros: dict
    descripcion: str


def disenar_bocatomas(Q_captacion, Q_crecida, ancho_rio_m,
                      tirante_estiaje_m=0.5, coef_vertedero=2.0):
    """Dimensiona preliminarmente las tres alternativas de captación."""
    Lb = max(ancho_rio_m, 1.0)
    # (a) Barraje fijo + toma lateral.
    H_barraje = (Q_crecida / (coef_vertedero * Lb)) ** (2.0 / 3.0) \
        if Q_crecida > 0 else 0.0
    # Ventana de captación (orificio) para Q_captacion con carga ~ tirante.
    h_carga = max(tirante_estiaje_m, 0.3)
    A_ventana = Q_captacion / (0.60 * math.sqrt(2.0 * G * h_carga))
    b_vent = max(math.sqrt(A_ventana * 2.0), 0.30)   # ~2:1 (ancho:alto)
    h_vent = A_ventana / b_vent if b_vent > 0 else 0.0
    barraje = Bocatoma(
        "barraje_fijo", "Barraje fijo + toma lateral",
        {"long_cresta_m": round(Lb, 2),
         "carga_sobre_cresta_H_m": round(H_barraje, 2),
         "area_ventana_m2": round(A_ventana, 3),
         "ventana_ancho_m": round(b_vent, 2),
         "ventana_alto_m": round(h_vent, 2)},
        "Azud fijo sobre el río con ventana de captación lateral, desripiador "
        "y compuerta de limpia. La carga H es sobre la cresta en la crecida de "
        "diseño.")
    # (b) Tirolesa (rejilla de fondo). Caudal captado por rejilla:
    #     Q = C·μ·b·L·√(2g·k·H), con C·μ≈0.435, k≈0.9, H≈energía sobre rejilla.
    Ce = 0.435
    H_rej = max(tirante_estiaje_m, 0.15)
    b_rej = max(min(Lb * 0.5, 3.0), 0.5)
    L_rej = Q_captacion / (Ce * b_rej * math.sqrt(2.0 * G * 0.9 * H_rej)) \
        if (b_rej > 0) else 0.0
    tirolesa = Bocatoma(
        "tirolesa", "Toma tirolesa (rejilla de fondo)",
        {"ancho_rejilla_b_m": round(b_rej, 2),
         "longitud_rejilla_L_m": round(L_rej, 2),
         "carga_H_m": round(H_rej, 2),
         "area_rejilla_m2": round(b_rej * L_rej, 3)},
        "Captación de fondo con rejilla, para ríos de fuerte pendiente y "
        "acarreo grueso. La rejilla se orienta en el sentido del flujo con "
        "barras espaciadas para retener el material grueso.")
    # (c) Toma directa sin barraje: orificio lateral al tirante de estiaje.
    A_dir = Q_captacion / (0.60 * math.sqrt(2.0 * G * max(h_carga * 0.5, 0.15)))
    b_dir = max(math.sqrt(A_dir * 2.0), 0.30)
    h_dir = A_dir / b_dir if b_dir > 0 else 0.0
    directa = Bocatoma(
        "toma_directa", "Toma directa sin barraje",
        {"area_toma_m2": round(A_dir, 3),
         "ancho_m": round(b_dir, 2), "alto_m": round(h_dir, 2),
         "tirante_estiaje_m": round(tirante_estiaje_m, 2)},
        "Captación lateral directa sin azud; requiere tirante suficiente en "
        "estiaje. Sensible a la variación del nivel del río.")
    return [barraje, tirolesa, directa]


# ─────────────────── Protección de márgenes ───────────────────

def disenar_proteccion_margenes(V_rio_ms, tirante_m=1.0):
    """Enrocado (Isbash) y gaviones a partir de la velocidad del río."""
    if not V_rio_ms or V_rio_ms <= 0:
        return None
    C = 0.86
    d50 = V_rio_ms ** 2 / (C * C * 2.0 * G * (_SS - 1.0))
    espesor = max(2.0 * d50, 0.30)
    # Gaviones: colchón de espesor típico 0.30–0.50 m; se recomienda si el
    # enrocado requerido es muy grande (roca escasa).
    usar_gaviones = d50 > 0.30
    return {
        "velocidad_rio_ms": round(V_rio_ms, 2),
        "d50_enrocado_m": round(d50, 3),
        "d50_enrocado_pulg": round(d50 * 39.37, 1),
        "espesor_enrocado_m": round(espesor, 2),
        "recomendacion": ("Colchón de gaviones (0.30–0.50 m) o enrocado con "
                          "roca de cantera; el D50 requerido es grande."
                          if usar_gaviones else
                          "Enrocado de protección con roca de cantera."),
    }


# ─────────────────── Resultado agregado ───────────────────

@dataclass
class ResultadoRiego:
    q_captacion_m3s: float
    fuente_q: str                 # "directo" | "área×módulo"
    area_ha: float | None
    modulo_ls_ha: float | None
    q_crecida_m3s: float | None
    q_estiaje_m3s: float | None
    cota_captacion: str | None
    canal: Canal | None
    desarenador: Desarenador | None
    bocatomas: list
    proteccion_margenes: dict | None
    # Balance oferta (estiaje del módulo Qmín) vs demanda (captación).
    balance: dict | None = None
    notas: list[str] = field(default_factory=list)


def _balance_oferta_demanda(q_demanda, q_estiaje, frac_ecologico=0.10):
    """Compara la oferta en estiaje (del estudio de caudales mínimos) con la
    demanda de captación, reservando un caudal ecológico."""
    if not q_estiaje or q_estiaje <= 0:
        return None
    q_eco = frac_ecologico * q_estiaje
    q_disponible = max(q_estiaje - q_eco, 0.0)
    cobertura = 100.0 * q_demanda / q_disponible if q_disponible > 0 else 0.0
    deficit = max(q_demanda - q_disponible, 0.0)
    if q_demanda <= q_disponible:
        veredicto = "SUFICIENTE"
        mensaje = ("La oferta en estiaje cubre la demanda de captación tras "
                   "reservar el caudal ecológico.")
    else:
        veredicto = "INSUFICIENTE"
        mensaje = ("La demanda supera la oferta disponible en estiaje: revisar "
                   "el módulo de riego, el área servida o prever regulación "
                   "(almacenamiento) aguas arriba.")
    return {
        "q_estiaje_m3s": round(q_estiaje, 4),
        "q_ecologico_m3s": round(q_eco, 4),
        "q_disponible_m3s": round(q_disponible, 4),
        "q_demanda_m3s": round(q_demanda, 4),
        "cobertura_pct": round(cobertura, 1),
        "deficit_m3s": round(deficit, 4),
        "veredicto": veredicto,
        "mensaje": mensaje,
    }


def disenar_captacion_riego(
    *,
    q_captacion_ls: float | None = None,
    area_ha: float | None = None,
    modulo_ls_ha: float | None = None,
    q_crecida_m3s: float | None = None,
    q_estiaje_m3s: float | None = None,
    q_estiaje_ls: float | None = None,
    ancho_rio_m: float = 8.0,
    cota_captacion: str | None = None,
    canal_so_pct: float = 0.1,
    canal_revestimiento: str = "hormigon",
    canal_forma: str = "trapezoidal",
    canal_talud_z: float = 1.0,
    canal_base_m: float | None = None,
    d_particula_mm: float = 0.20,
) -> ResultadoRiego | None:
    """Dimensiona la captación de riego menor. El caudal de captación se toma
    directo (l/s) o se deriva de área × módulo."""
    fuente_q = "directo"
    Q = None
    if q_captacion_ls and q_captacion_ls > 0:
        Q = q_captacion_ls / 1000.0
    elif area_ha and modulo_ls_ha and area_ha > 0 and modulo_ls_ha > 0:
        Q = (area_ha * modulo_ls_ha) / 1000.0
        fuente_q = "área × módulo"
    if Q is None or Q <= 0:
        return None

    tw_estiaje = None
    canal = disenar_canal(Q, canal_so_pct, canal_revestimiento, canal_forma,
                          canal_talud_z, canal_base_m)
    desar = disenar_desarenador(Q, d_particula_mm)
    # Tirante de estiaje aproximado para las tomas (si no hay dato, usar el del
    # canal como orden de magnitud del nivel disponible).
    tw_estiaje = canal.tirante_y_m if canal else 0.5
    bocatomas = disenar_bocatomas(
        Q, q_crecida_m3s or (Q * 20.0), ancho_rio_m, tw_estiaje)
    # Velocidad del río en crecida (orden de magnitud) para la protección.
    v_rio = None
    if q_crecida_m3s and ancho_rio_m:
        # Estimación gruesa V = Q/(ancho·tirante) con tirante ~ H barraje.
        H = bocatomas[0].parametros.get("carga_sobre_cresta_H_m", 1.0)
        v_rio = q_crecida_m3s / max(ancho_rio_m * max(H, 0.3), 0.1)
    prot = disenar_proteccion_margenes(v_rio or 3.0)

    # Estiaje (oferta): del estudio de caudales mínimos (Q95 / Q7,10).
    q_est = q_estiaje_m3s
    if q_est is None and q_estiaje_ls and q_estiaje_ls > 0:
        q_est = q_estiaje_ls / 1000.0
    balance = _balance_oferta_demanda(Q, q_est) if q_est else None

    notas = [
        "Predimensionamiento: el diseño definitivo requiere topografía del "
        "sitio, modelación HEC-RAS y estudio de sedimentos (curva "
        "granulométrica del acarreo).",
    ]
    if q_est is None:
        notas.append("El caudal de estiaje (disponibilidad) debe verificarse "
                     "con el estudio de caudales mínimos (Q95 / Q7,10) e "
                     "ingresarse para cerrar el balance oferta–demanda.")
    return ResultadoRiego(
        q_captacion_m3s=round(Q, 4), fuente_q=fuente_q,
        area_ha=area_ha, modulo_ls_ha=modulo_ls_ha,
        q_crecida_m3s=q_crecida_m3s, q_estiaje_m3s=q_est,
        cota_captacion=cota_captacion, canal=canal, desarenador=desar,
        bocatomas=bocatomas, proteccion_margenes=prot, balance=balance,
        notas=notas)
