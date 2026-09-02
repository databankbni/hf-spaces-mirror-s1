"""Diseño hidráulico de alcantarillas de drenaje vial menor (FHWA HDS-5).

Dimensiona la alcantarilla a partir del caudal de diseño calculado en el
estudio hidrológico (Q para T de diseño) y verifica con un caudal de crecida
superior (T de verificación).

Metodología
-----------
Para cada tamaño candidato se calcula la carga a la entrada HW como el máximo
entre el **control de entrada** y el **control de salida** (FHWA HDS-5,
*Hydraulic Design of Highway Culverts*), que es la práctica adoptada por el
Manual de Hidrología y Drenaje del MOPSV/ABC (Bolivia):

- **Control de entrada** — ecuaciones de regresión del HDS-5 (formas no
  sumergida y sumergida) con los coeficientes (K, M, c, Y) por tipo de obra y
  borde de entrada.
- **Control de salida** — ecuación de energía a tubo lleno:
  ``H = [1 + Ke + (2g·n²·L)/R^(4/3)]·V²/(2g)`` y
  ``HW = H + ho − L·So``, con ``ho = max(TW, (dc+D)/2)``.

Se sube por la lista de tamaños comerciales hasta cumplir ``HW/D ≤`` criterio
(por defecto 1.2, ABC) y se comparan los tres tipos, recomendando el de menor
área hidráulica (proxy de costo) que cumple.

Referencias
-----------
- FHWA (2012). *Hydraulic Design of Highway Culverts* (HDS-5, 3.ª ed.).
- MOPSV/ABC. *Manual de Hidrología y Drenaje*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

G = 9.81
_2G = 2.0 * G
KU = 1.811  # factor de unidades SI en el término de flujo del HDS-5


# ─────────────────── Coeficientes por tipo de obra ───────────────────
# (K, M, c, Y) del control de entrada + Ke (pérdida de entrada, control de
# salida) + n de Manning + rugosidad textual. Bordes representativos:
#   circular HºAº → campana con muro cabezal (groove end w/ headwall)
#   cajón HºAº    → aletas 30–75° (wingwall flare)
#   ARMCO         → muro cabezal (headwall)
@dataclass(frozen=True)
class _TipoCulvert:
    clave: str
    nombre: str
    forma: str          # "circular" | "cajon"
    K: float
    M: float
    c: float
    Y: float
    Ke: float
    n: float
    borde: str


TIPOS: dict[str, _TipoCulvert] = {
    "circular_hoao": _TipoCulvert(
        "circular_hoao", "Circular de HºAº", "circular",
        0.0018, 2.0, 0.0292, 0.74, 0.2, 0.013,
        "campana con muro cabezal"),
    "cajon_hoao": _TipoCulvert(
        "cajon_hoao", "Cajón de HºAº", "cajon",
        0.026, 1.0, 0.0385, 0.81, 0.4, 0.013,
        "aletas 30–75°"),
    "armco": _TipoCulvert(
        "armco", "Metálica corrugada (ARMCO)", "circular",
        0.0078, 2.0, 0.0379, 0.69, 0.5, 0.024,
        "muro cabezal"),
}

# Diámetros comerciales de tubería (m).
DIAM_COMERCIALES = (0.60, 0.80, 1.00, 1.20, 1.50, 1.80, 2.00)
# Cajones comerciales (ancho B × alto H, m).
CAJON_COMERCIALES = (
    (1.0, 1.0), (1.5, 1.0), (1.5, 1.5), (2.0, 1.5), (2.0, 2.0),
    (2.5, 2.0), (3.0, 2.0), (3.0, 2.5), (3.0, 3.0),
)


# ─────────────────── Geometría e hidráulica auxiliar ───────────────────

def _area_barril(t: _TipoCulvert, D: float, B: float, H: float) -> float:
    if t.forma == "circular":
        return math.pi * D * D / 4.0
    return B * H


def _radio_hidraulico_lleno(t: _TipoCulvert, D: float, B: float,
                            H: float) -> float:
    if t.forma == "circular":
        return D / 4.0
    return (B * H) / (2.0 * (B + H))


def _tirante_critico_circular(Q: float, D: float) -> float:
    """dc en tubería circular: resuelve Q²/g = A³/T por bisección."""
    obj = Q * Q / G
    lo, hi = 1e-4, D * 0.999
    for _ in range(60):
        y = 0.5 * (lo + hi)
        theta = 2.0 * math.acos(1.0 - 2.0 * y / D)
        A = (D * D / 8.0) * (theta - math.sin(theta))
        T = D * math.sin(theta / 2.0)
        if T <= 1e-9:
            lo = y
            continue
        if A ** 3 / T < obj:
            lo = y
        else:
            hi = y
    return 0.5 * (lo + hi)


def _tirante_critico(t: _TipoCulvert, Q: float, D: float, B: float,
                     H: float) -> float:
    if t.forma == "cajon":
        q = Q / B
        return (q * q / G) ** (1.0 / 3.0)
    return _tirante_critico_circular(Q, D)


def _area_perim(t: _TipoCulvert, y: float, D: float, B: float,
                H: float) -> tuple[float, float]:
    """Área y perímetro mojado a tirante y (m)."""
    if t.forma == "cajon":
        return B * y, B + 2.0 * y
    y = min(y, D)
    theta = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * y / D)))
    A = (D * D / 8.0) * (theta - math.sin(theta))
    P = D * theta / 2.0
    return A, P


def _tirante_normal(t: _TipoCulvert, Q_cel: float, D: float, B: float,
                    H: float, So: float) -> float:
    """Tirante normal (régimen uniforme) por Manning, acotado al alto del
    barril. Si el flujo llena la sección devuelve el alto."""
    alto = H if t.forma == "cajon" else D
    lo, hi = 1e-4, alto * 0.999
    obj = Q_cel * t.n / math.sqrt(So)   # = A·R^(2/3)
    for _ in range(60):
        y = 0.5 * (lo + hi)
        A, P = _area_perim(t, y, D, B, H)
        if P <= 1e-9:
            lo = y
            continue
        if A * (A / P) ** (2.0 / 3.0) < obj:
            lo = y
        else:
            hi = y
    return 0.5 * (lo + hi)


def _velocidad_salida(t: _TipoCulvert, Q_cel: float, D: float, B: float,
                      H: float, So: float, control: str,
                      A_full: float) -> float:
    """Velocidad de salida. En control de entrada el barril fluye parcialmente
    lleno (supercrítico): se usa el tirante normal. En control de salida (tubo
    lleno) se usa el área plena."""
    if control != "entrada":
        return Q_cel / A_full
    alto = H if t.forma == "cajon" else D
    yn = _tirante_normal(t, Q_cel, D, B, H, So)
    if yn >= alto * 0.99:
        return Q_cel / A_full
    A, _ = _area_perim(t, yn, D, B, H)
    return Q_cel / A if A > 1e-9 else Q_cel / A_full


# ─────────────────── Control de entrada / salida ───────────────────

def _hw_control_salida(t: _TipoCulvert, Q: float, A_full: float, R: float,
                       D: float, L: float, So: float, dc: float,
                       TW: float) -> tuple[float, float]:
    """(HW, V) por control de salida a tubo lleno."""
    V = Q / A_full
    H = (1.0 + t.Ke + (_2G * t.n * t.n * L) / (R ** (4.0 / 3.0))) * V * V / _2G
    ho = max(TW, (min(dc, D) + D) / 2.0)
    HW = H + ho - L * So
    return HW, V


# ─────────────────── Resultado ───────────────────

@dataclass
class Candidata:
    tipo: str
    nombre: str
    forma: str
    n_celdas: int
    D_m: float | None          # diámetro / alto de celda (control)
    B_m: float | None          # ancho de celda (cajón)
    H_m: float | None          # alto de celda (cajón)
    area_total_m2: float
    Q_m3s: float
    HW_m: float
    HW_D: float
    control: str               # "entrada" | "salida"
    V_ms: float
    dc_m: float
    cumple: bool
    obs: list[str] = field(default_factory=list)

    @property
    def designacion(self) -> str:
        if self.forma == "circular":
            base = f"Ø{self.D_m:.2f} m"
        else:
            base = f"{self.B_m:.1f}×{self.H_m:.1f} m"
        return f"{self.n_celdas}×{base}" if self.n_celdas > 1 else base


@dataclass
class ResultadoAlcantarilla:
    Q_diseno_m3s: float
    T_diseno: int
    Q_verif_m3s: float | None
    T_verif: int | None
    criterio_hw_d: float
    v_admisible_ms: float
    long_m: float
    pendiente_pct: float
    tw_m: float
    por_tipo: list[Candidata]              # recomendada de cada tipo (diseño)
    recomendada: Candidata | None
    verificacion: Candidata | None         # recomendada evaluada a Q_verif
    modo: str = "auto"                      # "auto" | "fijo" (sección del usuario)
    notas: list[str] = field(default_factory=list)
    # Procedencia de los datos de entrada.
    fuente_q: str = "interno (HEC-HMS)"    # o "HEC-RAS (modelo del usuario)"
    fuente_tw: str = "por defecto"         # "manual" | "HEC-RAS" | "por defecto"
    # Contraste con el modelo HEC-RAS, si se aportó (WSE/velocidad reales).
    contraste_hecras: dict | None = None
    # Modelo hidráulico de la obra adoptada (perfil de remanso, curva de
    # funcionamiento y protección de salida).
    perfil: dict | None = None
    curva_funcionamiento: list | None = None
    proteccion_salida: dict | None = None


# ─────────────────── Evaluación y dimensionamiento ───────────────────

def _evaluar(t: _TipoCulvert, Q: float, n_celdas: int, D: float, B: float,
             H: float, L: float, So: float, TW: float,
             criterio_hw_d: float, v_adm: float) -> Candidata:
    Q_cel = Q / n_celdas
    A = _area_barril(t, D, B, H)
    Dc_altura = D if t.forma == "circular" else H
    R = _radio_hidraulico_lleno(t, D, B, H)
    dc = _tirante_critico(t, Q_cel, D, B, H)

    # Control de entrada — energía específica crítica Hc = dc + Vc²/2g.
    if t.forma == "cajon":
        Ac = B * dc
    else:
        theta = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * dc / D)))
        Ac = (D * D / 8.0) * (theta - math.sin(theta))
    Vc = Q_cel / Ac if Ac > 1e-9 else 0.0
    Hc = dc + Vc * Vc / _2G
    flujo = KU * Q_cel / (A * math.sqrt(Dc_altura))
    hw_d_unsub = Hc / Dc_altura + t.K * (flujo ** t.M) - 0.5 * So
    hw_d_sub = t.c * (flujo ** 2) + t.Y - 0.5 * So
    if flujo <= 3.5:
        hw_d_ent = hw_d_unsub
    elif flujo >= 4.0:
        hw_d_ent = hw_d_sub
    else:
        w = (flujo - 3.5) / 0.5
        hw_d_ent = (1 - w) * hw_d_unsub + w * hw_d_sub
    HW_entrada = max(hw_d_ent, 0.0) * Dc_altura

    # Control de salida.
    HW_salida, _V_full = _hw_control_salida(t, Q_cel, A, R, Dc_altura, L, So,
                                            dc, TW)

    if HW_entrada >= HW_salida:
        HW, control = HW_entrada, "entrada"
    else:
        HW, control = HW_salida, "salida"

    # Velocidad de salida coherente con el control (parcial vs. lleno).
    V = _velocidad_salida(t, Q_cel, D, B, H, So, control, A)

    hw_d = HW / Dc_altura
    obs: list[str] = []
    cumple = hw_d <= criterio_hw_d + 1e-6
    if V > v_adm:
        obs.append(f"velocidad {V:.1f} m/s > admisible {v_adm:.1f} m/s: "
                   "prever disipador/enrocado a la salida")
    return Candidata(
        tipo=t.clave, nombre=t.nombre, forma=t.forma, n_celdas=n_celdas,
        D_m=(D if t.forma == "circular" else None),
        B_m=(B if t.forma == "cajon" else None),
        H_m=(H if t.forma == "cajon" else None),
        area_total_m2=A * n_celdas, Q_m3s=Q, HW_m=HW, HW_D=hw_d,
        control=control, V_ms=V, dc_m=dc, cumple=cumple, obs=obs)


def _dimensionar_tipo(t: _TipoCulvert, Q: float, L: float, So: float,
                      TW: float, criterio_hw_d: float,
                      v_adm: float) -> Candidata:
    """Sube por tamaños/celdas hasta cumplir HW/D; devuelve la mínima que
    cumple (o la mayor evaluada si ninguna cumple)."""
    tamanos = (DIAM_COMERCIALES if t.forma == "circular"
               else CAJON_COMERCIALES)
    ultima: Candidata | None = None
    for n_cel in (1, 2, 3):
        for tam in tamanos:
            if t.forma == "circular":
                D, B, H = float(tam), 0.0, float(tam)
            else:
                B, H = float(tam[0]), float(tam[1])
                D = H
            cand = _evaluar(t, Q, n_cel, D, B, H, L, So, TW,
                            criterio_hw_d, v_adm)
            ultima = cand
            if cand.cumple:
                return cand
    # Ninguna cumplió: devuelve la mayor evaluada, marcada como no conforme.
    if ultima is not None:
        ultima.obs.insert(0, "ningún tamaño comercial cumple HW/D; "
                          "revisar tipo de obra (¿puente/badén?) o T")
    return ultima  # type: ignore[return-value]


def _geom_cand(cand: Candidata):
    """(TipoCulvert, D, B, H, alto) de una candidata."""
    t = TIPOS[cand.tipo]
    if t.forma == "circular":
        D = cand.D_m or 1.0
        return t, D, 0.0, D, D
    B = cand.B_m or 1.0
    H = cand.H_m or 1.0
    return t, H, B, H, H


def perfil_hidraulico(cand: Candidata, Q: float, So: float, long_m: float,
                      tw_m: float) -> dict:
    """Perfil (curva de remanso) de la alcantarilla: tirantes en los puntos de
    control — aguas arriba (pozo), a la entrada, en el barril y a la salida —
    más el nivel aguas abajo (TW). Enfoque FHWA HDS-5."""
    t, D, B, H, alto = _geom_cand(cand)
    Q_cel = Q / max(1, cand.n_celdas)
    dc = _tirante_critico(t, Q_cel, D, B, H)
    yn = _tirante_normal(t, Q_cel, D, B, H, So)
    lleno = yn >= alto * 0.99
    hw = cand.HW_m
    control = cand.control
    if control == "entrada":
        # Régimen supercrítico en el barril: entra por ~crítico y va a normal.
        y_entrada = min(dc, alto)
        y_barril = min(yn, alto)
        y_salida = min(yn, alto)
    else:
        # Control de salida: barril lleno o subcrítico.
        y_entrada = alto if lleno else max(dc, tw_m)
        y_barril = alto if lleno else max(dc, tw_m)
        y_salida = alto if lleno else max(dc, tw_m)
    caida = long_m * So
    return {
        "control": control,
        "hw_pozo_m": round(hw, 3),          # tirante ANTES (pozo aguas arriba)
        "y_entrada_m": round(y_entrada, 3),  # tirante A LA ENTRADA del barril
        "y_barril_m": round(y_barril, 3),    # tirante en el barril (normal)
        "y_salida_m": round(y_salida, 3),    # tirante A LA SALIDA
        "tw_m": round(tw_m, 3),              # tirante AGUAS ABAJO
        "dc_m": round(dc, 3),
        "yn_m": round(yn, 3),
        "seccion_llena": lleno,
        "caida_invert_m": round(caida, 3),
        "salto_hidraulico": bool(control == "entrada" and tw_m > dc * 1.05),
    }


def curva_funcionamiento(cand: Candidata, So: float, long_m: float,
                         tw_m: float, criterio_hw_d: float, v_adm: float,
                         Q_max: float, n_puntos: int = 12) -> list:
    """Curva de funcionamiento (rating curve) de la obra adoptada: HW, HW/D,
    control y velocidad de salida para caudales crecientes hasta Q_max. Sirve
    para ver el comportamiento ante crecidas mayores a la de diseño."""
    t, D, B, H, alto = _geom_cand(cand)
    filas = []
    q0 = max(Q_max / n_puntos, 0.1)
    for i in range(1, n_puntos + 1):
        Q = q0 * i
        c = _evaluar(t, Q, cand.n_celdas, D, B, H, long_m, So, tw_m,
                     criterio_hw_d, v_adm)
        filas.append({
            "Q_m3s": round(Q, 2), "HW_m": round(c.HW_m, 3),
            "HW_D": round(c.HW_D, 3), "control": c.control,
            "V_ms": round(c.V_ms, 2),
            "desborda": bool(c.HW_D > 1.5),
        })
    return filas


def proteccion_salida(cand: Candidata, tw_m: float,
                      ss_roca: float = 2.65) -> dict:
    """Recomendación de socavación local y protección (enrocado) a la salida.

    Estima el enrocado por Isbash a partir de la velocidad de salida y una
    longitud de delantal según HEC-14 (≈ función del alto y del régimen)."""
    V = cand.V_ms
    alto = cand.H_m or cand.D_m or 1.0
    # Enrocado por Isbash: D50 = V² / (C²·2g·(Ss−1)), C≈0.86.
    C = 0.86
    d50_m = V * V / (C * C * _2G * (ss_roca - 1.0))
    # Longitud del delantal de protección (HEC-14, orientativo): mayor cuanto
    # más rápido el flujo respecto de la sección.
    fr_salida = V / math.sqrt(G * max(cand.dc_m, 0.05))
    factor = 3.0 if fr_salida <= 1.0 else min(3.0 + 1.5 * (fr_salida - 1.0), 8.0)
    long_delantal_m = factor * alto
    espesor_m = max(2.0 * d50_m, 0.30)
    requiere_disipador = V > 4.5 or fr_salida > 1.7
    return {
        "velocidad_salida_ms": round(V, 2),
        "froude_salida": round(fr_salida, 2),
        "d50_enrocado_m": round(d50_m, 3),
        "d50_enrocado_pulg": round(d50_m * 39.37, 1),
        "espesor_capa_m": round(espesor_m, 2),
        "long_delantal_m": round(long_delantal_m, 2),
        "requiere_disipador": bool(requiere_disipador),
        "nota": ("Velocidad/Froude altos: prever cuenco disipador o dentellón "
                 "además del enrocado." if requiere_disipador else
                 "Enrocado de protección (delantal) suficiente como medida "
                 "preliminar."),
    }


def _enriquecer(res: "ResultadoAlcantarilla", So: float, long_m: float,
                tw_m: float, criterio: float, v_adm: float) -> None:
    """Adjunta perfil de remanso, curva de funcionamiento y protección de
    salida a la obra recomendada."""
    c = res.recomendada
    if c is None:
        return
    try:
        res.perfil = perfil_hidraulico(c, res.Q_diseno_m3s, So, long_m, tw_m)
    except Exception:  # noqa: BLE001
        res.perfil = None
    try:
        q_max = max((res.Q_verif_m3s or 0.0), res.Q_diseno_m3s * 2.0)
        res.curva_funcionamiento = curva_funcionamiento(
            c, So, long_m, tw_m, criterio, v_adm, q_max)
    except Exception:  # noqa: BLE001
        res.curva_funcionamiento = None
    try:
        res.proteccion_salida = proteccion_salida(c, tw_m)
    except Exception:  # noqa: BLE001
        res.proteccion_salida = None


def disenar_alcantarilla(
    Q_diseno: float,
    T_diseno: int,
    S_cauce_pct: float,
    *,
    Q_verif: float | None = None,
    T_verif: int | None = None,
    long_m: float = 12.0,
    tw_m: float = 0.0,
    criterio_hw_d: float = 1.2,
    v_admisible_ms: float = 4.5,
    tipo_fijo: str | None = None,
    n_celdas_fijo: int = 1,
    D_fijo: float | None = None,
    B_fijo: float | None = None,
    H_fijo: float | None = None,
) -> ResultadoAlcantarilla | None:
    """Dimensiona alcantarilla (circular HºAº, cajón HºAº y ARMCO) para el
    caudal de diseño y verifica la recomendada con el caudal de crecida.

    Parameters
    ----------
    Q_diseno, Q_verif : caudales (m³/s) para T de diseño y de verificación.
    S_cauce_pct : pendiente del cauce/obra (%). Se acota a un mínimo de 0.5 %
        (auto-limpieza) para el diseño.
    long_m : longitud de la alcantarilla (ancho de plataforma + taludes). Valor
        por defecto provisional; ajustar con la geometría vial real.
    tw_m : tirante aguas abajo (tailwater). 0 = descarga libre.
    criterio_hw_d : carga máxima admisible a la entrada HW/D (ABC = 1.2).
    """
    if not Q_diseno or Q_diseno <= 0:
        return None
    So = max(S_cauce_pct / 100.0, 0.005)
    notas = [
        f"So de diseño = {So*100:.2f} % (mín. 0.5 % por auto-limpieza).",
        f"Longitud L = {long_m:.1f} m (provisional; depende de la plataforma "
        "y taludes del terraplén).",
        ("Descarga libre (TW = 0)." if tw_m <= 0 else
         f"Tirante aguas abajo TW = {tw_m:.2f} m."),
        "HW/D por control de entrada y de salida (máximo), método FHWA HDS-5.",
    ]

    # ── Modo FIJO: el usuario indicó tipo + sección + celdas; se verifica esa
    #    obra en vez de comparar/auto-dimensionar. ──
    if tipo_fijo in TIPOS:
        t = TIPOS[tipo_fijo]
        n_cel = max(1, int(n_celdas_fijo or 1))
        dims_ok = True
        if t.forma == "circular":
            D = float(D_fijo) if D_fijo else 0.0
            B, H = 0.0, D
            dims_ok = D > 0
        else:
            B = float(B_fijo) if B_fijo else 0.0
            H = float(H_fijo) if H_fijo else 0.0
            D = H
            dims_ok = B > 0 and H > 0
        if dims_ok:
            cand = _evaluar(t, Q_diseno, n_cel, D, B, H, long_m, So, tw_m,
                            criterio_hw_d, v_admisible_ms)
            cand.obs.insert(0, "sección adoptada por el proyectista (verificación)")
            verif = None
            if Q_verif and Q_verif > 0:
                verif = _evaluar(t, Q_verif, n_cel, D, B, H, long_m, So, tw_m,
                                 criterio_hw_d, v_admisible_ms)
                _dv = ("no desborda" if verif.HW_D <= 1.5
                       else "revisar cota de rasante — posible desborde")
                notas.append(f"Verificación T={T_verif}: HW/D = "
                             f"{verif.HW_D:.2f} ({_dv}).")
            if not cand.cumple:
                notas.append("La sección indicada NO cumple HW/D ≤ "
                             f"{criterio_hw_d:.1f}: aumentar diámetro/celdas.")
            _res = ResultadoAlcantarilla(
                Q_diseno_m3s=float(Q_diseno), T_diseno=int(T_diseno),
                Q_verif_m3s=(float(Q_verif) if Q_verif else None),
                T_verif=(int(T_verif) if T_verif else None),
                criterio_hw_d=criterio_hw_d, v_admisible_ms=v_admisible_ms,
                long_m=long_m, pendiente_pct=So * 100.0, tw_m=tw_m,
                por_tipo=[cand], recomendada=cand, verificacion=verif,
                modo="fijo", notas=notas)
            _enriquecer(_res, So, long_m, tw_m, criterio_hw_d,
                        v_admisible_ms)
            return _res
        notas.append("Faltan dimensiones para el diseño fijo; se comparó "
                     "automáticamente.")

    por_tipo: list[Candidata] = []
    for t in TIPOS.values():
        por_tipo.append(_dimensionar_tipo(
            t, Q_diseno, long_m, So, tw_m, criterio_hw_d, v_admisible_ms))

    # Recomendada: la de MENOR área que cumple; si ninguna cumple, la de menor
    # HW/D. Desempate: preferir circular de HºAº (más económica/común).
    orden = {"circular_hoao": 0, "cajon_hoao": 1, "armco": 2}
    cumplen = [c for c in por_tipo if c.cumple]
    if cumplen:
        recomendada = min(cumplen,
                          key=lambda c: (round(c.area_total_m2, 3),
                                         orden.get(c.tipo, 9)))
    else:
        recomendada = min(por_tipo, key=lambda c: c.HW_D) if por_tipo else None

    # Verificación de la recomendada con Q_verif (mismo tamaño).
    verificacion: Candidata | None = None
    if recomendada is not None and Q_verif and Q_verif > 0:
        t = TIPOS[recomendada.tipo]
        D = recomendada.D_m or recomendada.H_m or 1.0
        B = recomendada.B_m or 0.0
        H = recomendada.H_m or D
        verificacion = _evaluar(
            t, Q_verif, recomendada.n_celdas, D, B, H, long_m, So, tw_m,
            criterio_hw_d, v_admisible_ms)
        _dictamen_verif = ("no desborda" if verificacion.HW_D <= 1.5
                           else "revisar cota de rasante — posible desborde")
        notas.append(
            f"Verificación T={T_verif}: HW/D = {verificacion.HW_D:.2f} "
            f"({_dictamen_verif}).")

    _res = ResultadoAlcantarilla(
        Q_diseno_m3s=float(Q_diseno), T_diseno=int(T_diseno),
        Q_verif_m3s=(float(Q_verif) if Q_verif else None),
        T_verif=(int(T_verif) if T_verif else None),
        criterio_hw_d=criterio_hw_d, v_admisible_ms=v_admisible_ms,
        long_m=long_m, pendiente_pct=So * 100.0, tw_m=tw_m,
        por_tipo=por_tipo, recomendada=recomendada,
        verificacion=verificacion, notas=notas)
    _enriquecer(_res, So, long_m, tw_m, criterio_hw_d, v_admisible_ms)
    return _res
