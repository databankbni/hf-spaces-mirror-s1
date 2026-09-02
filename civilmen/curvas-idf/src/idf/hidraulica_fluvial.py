"""Motor hidráulico fluvial — cálculo del tirante (calado) tipo HEC-RAS 1D.

A partir del caudal de diseño Q(T) ya calculado por el módulo de caudales
máximos (`caudal_maximo.py`), este motor estima el TIRANTE (calado / profundidad
de la lámina de agua) en el sitio del proyecto. La metodología replica el
enfoque de HEC-RAS 1D en régimen uniforme (tirante normal por sección):

  1. Se traza el thalweg (línea de fondo del cauce) sobre el DEM COP-DEM 12.5 m
     usando hidrología D8 (dirección y acumulación de flujo), 200 m aguas arriba
     y 200 m aguas abajo del punto.
  2. Se cortan secciones transversales PERPENDICULARES al thalweg, con un ancho
     y un espaciado que dependen del área de la cuenca (tabla del proyectista).
  3. En cada sección se resuelve el tirante normal y_n como la cota de la
     superficie del agua (WSE) que satisface la ecuación de Manning:

         Q = (1/n) · A · R^(2/3) · S^(1/2)

     con A = área hidráulica, P = perímetro mojado, R = A/P (radio hidráulico),
     S = pendiente del cauce, n = rugosidad de Manning (derivada de la cobertura
     de suelo MapBiomas vía Google Earth Engine).

El tirante normal se resuelve por bisección (scipy.optimize.brentq) sobre la
cota de agua. Se reportan además la velocidad media (V = Q/A), el ancho de
espejo, el radio hidráulico y el número de Froude (régimen sub/supercrítico).

Restricción de dependencias: SOLO numpy/scipy (todo el codebase evita
shapely/rasterio/geopandas/pyproj — ver copernicus_dem.py y red_drenaje_dem.py).
La geometría se resuelve en NumPy puro; las distancias métricas usan una
aproximación equirectangular local (metros-por-grado en el punto), exacta a
escala de tramo (< pocos km).

Degradación elegante: si GEE/DEM no responden, el motor cae a una geometría
trapezoidal estimada por geometría hidráulica de régimen, dejando constancia en
`ResultadoTirante.advertencias` y `fuente_geometria`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Tabla ancho/espaciado de secciones por área de cuenca (criterio del proyectista)
# ─────────────────────────────────────────────────────────────────────────────
# (área_max_km2 exclusivo, ancho_seccion_m, espaciado_entre_secciones_m)
# El ancho es el ancho TOTAL de la sección transversal (mitad a cada lado del
# thalweg); el espaciado es la distancia entre secciones a lo largo del cauce.
# El tramo 500–1000 km² usa 300 m por continuidad con el tramo anterior
# (decisión confirmada con el usuario).
_TABLA_SECCION: tuple[tuple[float, float, float], ...] = (
    (1.0,           20.0,   5.0),
    (10.0,          40.0,   5.0),
    (50.0,          80.0,  10.0),
    (100.0,        200.0,  10.0),
    (200.0,        250.0,  20.0),
    (500.0,        300.0,  20.0),
    (1000.0,       300.0,  20.0),   # 500–1000 km²: continuidad (300 m)
    (math.inf,    2000.0,  20.0),   # > 1000 km²
)

# Tramo por defecto: 200 m aguas arriba + 200 m aguas abajo del punto.
LONGITUD_TRAMO_DEFECTO_M = 200.0

# Secciones de análisis: 5 aguas arriba + el punto + 5 aguas abajo = 11.
SECCIONES_POR_LADO = 5
N_SECCIONES = 2 * SECCIONES_POR_LADO + 1

# Rugosidad de Manning por defecto (cauce natural limpio, Chow 1959) cuando no
# hay cobertura GEE disponible.
N_MANNING_DEFECTO = 0.035

# Pendiente mínima admisible del cauce (fracción). Evita divisiones por cero y
# tirantes infinitos cuando el DEM entrega una pendiente nula/plana espuria.
_S_MIN = 5e-4  # 0.05 %

_G = 9.81  # gravedad (m/s²)

# Gálibo (revancha / borde libre) normativo por defecto entre el Nivel de Aguas
# Máximas (NAME) de diseño y la cara inferior de la viga del tablero. El Manual
# de Hidrología y Drenaje MOPSV/ABC y la práctica AASHTO recomiendan ≥ 1.5 m en
# cauces limpios y ≥ 2.0–2.5 m en ríos con arrastre de palizada/sedimento
# grueso. Se adopta 2.0 m por defecto (ríos de montaña con material flotante),
# reconfigurable vía params_puente["galibo_m"].
GALIBO_DEFECTO_M = 2.0
# Altura por defecto de la palizada / material flotante (troncos) que se suma al
# NAME para la verificación del gálibo libre en ríos de montaña bolivianos.
PALIZADA_DEFECTO_M = 0.5
# Gálibo libre mínimo normativo (Guía de Diseño de Puentes ABC): 1.5 m en
# cauces limpios, hasta 2.0–2.5 m con arrastre importante. Se adopta 1.5 m.
GALIBO_MIN_ABC_M = 1.5


# ─────────────────────────────────────────────────────────────────────────────
# Estructuras de resultado
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SeccionTransversal:
    """Una sección transversal y su solución de tirante normal."""
    id: int
    estacion_m: float                 # distancia acumulada a lo largo del thalweg
    x_local_m: np.ndarray             # abscisas transversales (0 = margen izquierda)
    z_m: np.ndarray                   # cota de fondo a lo largo de la sección (m)
    centro_lonlat: tuple             # (lon, lat) del punto del thalweg
    # Resultados hidráulicos (tirante normal para el Q de diseño):
    wse_m: float = float("nan")       # cota de la superficie del agua (m)
    tirante_m: float = float("nan")   # calado máximo = WSE − cota mínima de fondo
    area_m2: float = float("nan")     # área hidráulica
    perimetro_m: float = float("nan") # perímetro mojado
    radio_h_m: float = float("nan")   # radio hidráulico R = A/P
    ancho_sup_m: float = float("nan") # ancho del espejo de agua (top width)
    velocidad_ms: float = float("nan")
    froude: float = float("nan")
    regimen: str = ""                 # "subcrítico" | "crítico" | "supercrítico"
    desborda: bool = False            # True si el agua supera el ancho de la sección


@dataclass
class ResultadoTirante:
    """Resultado completo del cálculo de tirante en el sitio del proyecto."""
    Q_m3s: float
    T_diseno: int
    n_manning: float
    n_detalle: dict
    S_cauce: float                    # pendiente adoptada (fracción)
    area_cuenca_km2: float
    ancho_seccion_m: float
    espaciado_m: float
    longitud_tramo_m: float
    secciones: list                   # list[SeccionTransversal]
    tirante_medio_m: float
    tirante_max_m: float
    tirante_control_m: float          # tirante en la sección de control (la del punto)
    velocidad_media_ms: float
    froude_medio: float
    regimen_predominante: str
    fuente_geometria: str             # "DEM COP-DEM 12.5 m" | "estimada (geometría hidráulica)"
    metodo: str = "Tirante normal (Manning) por sección — HEC-RAS 1D"
    advertencias: list = field(default_factory=list)
    # Verificación estructural con un T superior (p. ej. puente 100/500):
    Q_verif_m3s: Optional[float] = None
    T_verif: Optional[int] = None
    tirante_verif_m: Optional[float] = None        # tirante de control (verif)
    tirante_verif_max_m: Optional[float] = None    # tirante máximo del tramo (verif)
    velocidad_verif_ms: Optional[float] = None
    froude_verif: Optional[float] = None
    regimen_verif: Optional[str] = None
    secciones_verif: list = field(default_factory=list)  # secciones resueltas T500
    # Pilar 3 — socavación (socavacion.ResultadoSocavacion) o None.
    # `socavacion` = escenario GOBERNANTE (verif/T500 si existe; si no, diseño):
    # es la base de la fundación (retrocompatibilidad). `socavacion_diseno` y
    # `socavacion_verif` son las socavaciones de cada caudal para el cuadro.
    socavacion: object = None
    socavacion_diseno: object = None
    socavacion_verif: object = None
    # Verificación del gálibo de la viga del puente (concepto de cierre de la
    # hidráulica fluvial): la viga se coloca a `galibo_m` sobre el NAME de
    # diseño (T100) y se verifica que el NAME de verificación (T500) no la toca.
    galibo_m: Optional[float] = None                 # revancha normativa (m)
    cota_viga_sobre_fondo_m: Optional[float] = None  # tirante_control(T100)+gálibo
    holgura_viga_verif_m: Optional[float] = None     # cota viga − tirante(T500)
    verifica_viga_verif: Optional[bool] = None       # gálibo libre ≥ mínimo ABC
    altura_palizada_m: Optional[float] = None        # material flotante sumado
    galibo_min_abc_m: Optional[float] = None         # gálibo libre mínimo exigido
    galibo_efectivo_verif_m: Optional[float] = None  # cota viga − (NAME500+palizada)
    # Perfil de flujo gradualmente variado (standard-step) del caudal de diseño:
    # lista de dicts {estacion_m, z_fondo, wse, tirante, V, E, Sf, Fr, metodo}.
    perfil_gvf: list = field(default_factory=list)
    # Thalweg (cauce principal) como Nx2 [lon, lat] para la vista en planta.
    thalweg_lonlat: object = None
    # Coordenadas (lon, lat) del punto del proyecto (sección de control).
    punto_lonlat: object = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Tabla ancho/espaciado
# ─────────────────────────────────────────────────────────────────────────────
def seccion_ancho_espaciado(area_km2: float) -> tuple[float, float]:
    """Devuelve (ancho_seccion_m, espaciado_m) para un área de cuenca dada.

    Sigue la tabla del proyectista (`_TABLA_SECCION`). El área se compara con
    los umbrales de forma estrictamente creciente: cae en el primer tramo cuyo
    límite superior aún no supera.
    """
    a = float(area_km2) if area_km2 and area_km2 > 0 else 0.0
    for amax, ancho, esp in _TABLA_SECCION:
        if a < amax:
            return float(ancho), float(esp)
    return 2000.0, 20.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Hidráulica de sección + solver de tirante normal (Manning) — NumPy puro
# ─────────────────────────────────────────────────────────────────────────────
def propiedades_hidraulicas(x: np.ndarray, z: np.ndarray, wse: float
                            ) -> tuple[float, float, float]:
    """Área hidráulica, perímetro mojado y ancho de espejo bajo la cota `wse`.

    `x` son las abscisas transversales (monótonas crecientes, en metros) y `z`
    las cotas de fondo correspondientes. Se integra segmento a segmento la
    porción sumergida (agua = wse − z donde sea positiva), resolviendo los
    puntos de corte con la margen del agua. Devuelve (A, P, B).
    """
    x = np.asarray(x, dtype=float)
    z = np.asarray(z, dtype=float)
    area = 0.0
    perim = 0.0
    ancho = 0.0
    for i in range(len(x) - 1):
        x0, x1 = x[i], x[i + 1]
        z0, z1 = z[i], z[i + 1]
        if not (np.isfinite(z0) and np.isfinite(z1)):
            continue
        dx = x1 - x0
        if dx <= 0:
            continue
        d0 = wse - z0
        d1 = wse - z1
        if d0 <= 0 and d1 <= 0:
            continue  # segmento seco
        if d0 > 0 and d1 > 0:
            # Segmento totalmente sumergido: trapecio de calados.
            area += 0.5 * (d0 + d1) * dx
            perim += math.hypot(dx, z1 - z0)
            ancho += dx
        else:
            # Segmento parcialmente sumergido: un extremo seco.
            # Punto de corte donde el agua toca el fondo (calado = 0).
            t = d0 / (d0 - d1)          # fracción de x0 → x1 donde wse = z
            xc = x0 + t * dx
            if d0 > 0:                   # mojado del lado x0
                area += 0.5 * d0 * (xc - x0)
                perim += math.hypot(xc - x0, d0)
                ancho += (xc - x0)
            else:                        # mojado del lado x1
                area += 0.5 * d1 * (x1 - xc)
                perim += math.hypot(x1 - xc, d1)
                ancho += (x1 - xc)
    return area, perim, ancho


def resolver_tirante_normal(x: np.ndarray, z: np.ndarray, Q: float,
                            n: float, S: float, g: float = _G
                            ) -> Optional[dict]:
    """Resuelve el tirante normal en una sección por la ecuación de Manning.

    Encuentra la cota de agua WSE tal que la capacidad de conducción
    (conveyance) iguala el caudal:  (1/n)·A·R^(2/3)·√S = Q.

    Devuelve un dict con wse, tirante (WSE − fondo mínimo), area, perimetro,
    radio_h, ancho_sup, velocidad, froude, regimen y `desborda`. `None` si los
    datos no permiten resolver (Q, n o S no positivos, o sección inválida).
    """
    from scipy.optimize import brentq

    x = np.asarray(x, dtype=float)
    z = np.asarray(z, dtype=float)
    validos = np.isfinite(z)
    if validos.sum() < 3 or Q <= 0 or n <= 0 or S <= 0:
        return None
    z_min = float(np.nanmin(z))
    z_max = float(np.nanmax(z))
    if z_max <= z_min:
        return None

    sqrtS = math.sqrt(S)

    def conveyance(wse: float) -> float:
        A, P, _ = propiedades_hidraulicas(x, z, wse)
        if A <= 0 or P <= 0:
            return 0.0
        R = A / P
        return (1.0 / n) * A * (R ** (2.0 / 3.0)) * sqrtS

    def f(wse: float) -> float:
        return conveyance(wse) - Q

    lo = z_min + 1e-6
    hi = z_max
    desborda = False
    # Si a nivel de banco lleno la conducción aún no alcanza Q, el flujo desborda:
    # extendemos la cota (paredes verticales implícitas en los extremos) hasta
    # contener el caudal, marcando el desborde.
    tramo = max(z_max - z_min, 0.5)
    intentos = 0
    while f(hi) < 0 and intentos < 60:
        hi += tramo
        desborda = True
        intentos += 1
    if f(hi) < 0:
        return None  # no converge ni con paredes altas

    try:
        wse = brentq(f, lo, hi, xtol=1e-4, maxiter=200)
    except Exception:  # noqa: BLE001
        return None

    A, P, B = propiedades_hidraulicas(x, z, wse)
    if A <= 0 or P <= 0 or B <= 0:
        return None
    R = A / P
    V = Q / A
    prof_media = A / B                       # profundidad hidráulica media
    Fr = V / math.sqrt(g * prof_media) if prof_media > 0 else float("nan")
    if not np.isfinite(Fr):
        regimen = ""
    elif Fr < 0.95:
        regimen = "subcrítico"
    elif Fr <= 1.05:
        regimen = "crítico"
    else:
        regimen = "supercrítico"
    return {
        "wse": wse,
        "tirante": wse - z_min,
        "area": A,
        "perimetro": P,
        "radio_h": R,
        "ancho_sup": B,
        "velocidad": V,
        "froude": Fr,
        "regimen": regimen,
        "desborda": desborda,
    }


def _props_wse(x, z, wse, Q, n, g=_G):
    """Propiedades hidráulicas para una cota de agua WSE dada (no resuelve Q)."""
    A, P, B = propiedades_hidraulicas(x, z, wse)
    if A <= 0 or P <= 0 or B <= 0:
        return None
    R = A / P
    V = Q / A
    Sf = (n * Q / (A * R ** (2.0 / 3.0))) ** 2      # pendiente de fricción
    E_total = wse + V * V / (2.0 * g)               # cota de la línea de energía
    Dh = A / B
    Fr = V / math.sqrt(g * Dh) if Dh > 0 else float("nan")
    return {"A": A, "P": P, "B": B, "R": R, "V": V, "Sf": Sf,
            "E": E_total, "Fr": Fr, "wse": wse}


def tirante_critico(x, z, Q: float, g: float = _G) -> Optional[dict]:
    """Tirante CRÍTICO de la sección: mínimo de la energía específica.

    La energía específica E(y) = y + Q²/(2g·A(y)²) tiene forma de U: tiende a
    infinito cuando y→0 (A→0) y crece de nuevo para y grande. Su mínimo define
    el tirante crítico y_c y separa la rama SUPERCRÍTICA (y < y_c, Fr > 1) de la
    SUBCRÍTICA (y > y_c, Fr < 1).

    Conocer y_c es indispensable en el método del paso estándar: la ecuación de
    energía tiene DOS raíces (una por rama) y hay que elegir la que corresponde
    al régimen del tramo. Devuelve {y_c, wse_c, E_c, A_c, V_c} o None.
    """
    from scipy.optimize import minimize_scalar
    x = np.asarray(x, dtype=float)
    z = np.asarray(z, dtype=float)
    if Q <= 0 or not np.isfinite(z).any():
        return None
    z_min = float(np.nanmin(z))
    z_max = float(np.nanmax(z))
    y_max = max(z_max - z_min, 1.0) * 3.0

    def _E(y):
        if y <= 1e-4:
            return 1e12
        A, _P, _B = propiedades_hidraulicas(x, z, z_min + y)
        if A <= 1e-6:
            return 1e12
        return y + (Q * Q) / (2.0 * g * A * A)

    try:
        res = minimize_scalar(_E, bounds=(1e-3, y_max), method="bounded",
                              options={"xatol": 1e-4})
        y_c = float(res.x)
    except Exception:  # noqa: BLE001
        return None
    A_c, _P, _B = propiedades_hidraulicas(x, z, z_min + y_c)
    if A_c <= 0:
        return None
    return {"y_c": y_c, "wse_c": z_min + y_c, "E_c": float(_E(y_c)),
            "A_c": A_c, "V_c": Q / A_c}


def perfil_gradualmente_variado(secciones, Q: float, n: float,
                                g: float = _G,
                                fr_max_admisible: float = 12.0
                                ) -> Optional[list]:
    """Perfil de flujo permanente GRADUALMENTE VARIADO — método del paso estándar.

    Resuelve la ecuación de energía entre secciones consecutivas:

        H_2 = H_1 + hf      con   H = z + y + V²/2g   y   hf = ½(Sf_1+Sf_2)·Δx

    Puntos críticos de la implementación (corrigen el fallo numérico detectado
    en la revisión técnica: velocidades de ~135 m/s y Froude ~66):

    1. **Selección de rama.** E(y) es una función en U con mínimo en el tirante
       crítico y_c. La ecuación de energía tiene DOS raíces: una supercrítica
       (y < y_c) y otra subcrítica (y > y_c). Acotar la búsqueda desde el fondo
       del cauce hacía converger SIEMPRE a la raíz supercrítica espuria (y→0,
       V→∞). Ahora la búsqueda se acota explícitamente a la rama del régimen
       vigente, determinada por el tirante normal frente a y_c.

    2. **Dirección de marcha.** En régimen SUBCRÍTICO el control está aguas
       abajo y el cálculo avanza hacia aguas arriba; en régimen SUPERCRÍTICO el
       control está aguas arriba y avanza hacia aguas abajo. Imponer siempre un
       control aguas abajo es incorrecto para flujo supercrítico.

    3. **Guarda de plausibilidad física.** Toda solución con Froude por encima
       de `fr_max_admisible`, tirante no positivo o energía no finita se
       descarta y se sustituye por el tirante normal de la sección, dejando
       constancia en el campo `metodo`.

    Devuelve una lista ordenada por estación con dicts {estacion_m, z_fondo,
    wse, tirante, V, E, Sf, Fr, y_critico, regimen, metodo}, o None.
    """
    from scipy.optimize import brentq
    secs = [s for s in secciones
            if s.z_m is not None and np.isfinite(s.tirante_m)
            and s.tirante_m > 0]
    if len(secs) < 2 or Q <= 0 or n <= 0:
        return None
    secs = sorted(secs, key=lambda s: s.estacion_m)
    bed = [float(np.nanmin(s.z_m)) for s in secs]

    # Tirante crítico por sección (define la rama admisible).
    crit = [tirante_critico(s.x_local_m, s.z_m, Q, g) for s in secs]
    if any(c is None for c in crit):
        return None

    # Régimen predominante del tramo: se compara el tirante NORMAL con el
    # crítico en cada sección y se adopta la mayoría.
    n_super = sum(1 for s, c in zip(secs, crit) if s.tirante_m < c["y_c"])
    supercritico = n_super > len(secs) / 2.0

    # Sentido de la marcha. El extremo de MENOR cota de fondo es aguas abajo.
    aguas_abajo_al_final = bed[-1] <= bed[0]
    if supercritico:
        # Control aguas ARRIBA → marcha hacia aguas abajo.
        orden = (list(range(len(secs))) if aguas_abajo_al_final
                 else list(range(len(secs) - 1, -1, -1)))
    else:
        # Control aguas ABAJO → marcha hacia aguas arriba.
        orden = (list(range(len(secs) - 1, -1, -1)) if aguas_abajo_al_final
                 else list(range(len(secs))))

    def _registro(i, wse, props, metodo):
        return {"estacion_m": secs[i].estacion_m, "z_fondo": bed[i],
                "wse": wse, "tirante": wse - bed[i],
                "V": props["V"], "E": props["E"], "Sf": props["Sf"],
                "Fr": props["Fr"], "y_critico": crit[i]["y_c"],
                "regimen": ("supercrítico" if props["Fr"] > 1.05
                            else "crítico" if props["Fr"] >= 0.95
                            else "subcrítico"),
                "metodo": metodo}

    perfil = {}
    # Condición de borde en la sección de control: tirante normal.
    i0 = orden[0]
    s0 = secs[i0]
    p0 = _props_wse(s0.x_local_m, s0.z_m, s0.wse_m, Q, n, g)
    if p0 is None:
        return None
    perfil[i0] = _registro(
        i0, s0.wse_m, p0,
        f"control {'aguas arriba' if supercritico else 'aguas abajo'} "
        f"(tirante normal)")

    for k in range(1, len(orden)):
        i_ant, i_act = orden[k - 1], orden[k]
        s_act = secs[i_act]
        H_ant = perfil[i_ant]["E"]
        Sf_ant = perfil[i_ant]["Sf"]
        dx = abs(secs[i_act].estacion_m - secs[i_ant].estacion_m)
        z_act = bed[i_act]
        y_c = crit[i_act]["y_c"]
        # Aguas arriba la energía es MAYOR (subcrítico, marcha hacia arriba);
        # aguas abajo es MENOR (supercrítico, marcha hacia abajo).
        signo = -1.0 if supercritico else +1.0

        def _bal(wse):
            pu = _props_wse(s_act.x_local_m, s_act.z_m, wse, Q, n, g)
            if pu is None:
                return 1e6
            hf = 0.5 * (pu["Sf"] + Sf_ant) * dx
            return pu["E"] - (H_ant + signo * hf)

        # Acotar la búsqueda a la RAMA del régimen vigente. Se deja un margen
        # del 1 % respecto de y_c para no caer sobre el mínimo de energía,
        # donde la función es plana y brentq no cambia de signo.
        if supercritico:
            lo = z_act + max(0.02 * y_c, 1e-3)
            hi = z_act + 0.99 * y_c
        else:
            lo = z_act + 1.01 * y_c
            hi = z_act + max(6.0 * y_c, 3.0 * s_act.tirante_m, y_c + 5.0)

        wse_sol = None
        try:
            f_lo, f_hi = _bal(lo), _bal(hi)
            if np.isfinite(f_lo) and np.isfinite(f_hi) and f_lo * f_hi < 0:
                wse_sol = brentq(_bal, lo, hi, xtol=1e-4, maxiter=200)
        except Exception:  # noqa: BLE001
            wse_sol = None

        metodo = "gradualmente variado"
        pu = (_props_wse(s_act.x_local_m, s_act.z_m, wse_sol, Q, n, g)
              if wse_sol is not None else None)
        # Guarda de plausibilidad física: sin ella, una raíz degenerada
        # (y→0) produce velocidades y energías absurdas.
        plausible = (
            pu is not None and wse_sol is not None
            and (wse_sol - z_act) > 1e-3
            and np.isfinite(pu["Fr"]) and pu["Fr"] <= fr_max_admisible
            and np.isfinite(pu["E"]))
        if not plausible:
            wse_sol = s_act.wse_m
            pu = _props_wse(s_act.x_local_m, s_act.z_m, wse_sol, Q, n, g)
            if pu is None:
                continue
            metodo = "respaldo (tirante normal)"
        perfil[i_act] = _registro(i_act, wse_sol, pu, metodo)

    if not perfil:
        return None
    return [perfil[i] for i in sorted(perfil.keys(),
                                      key=lambda i: secs[i].estacion_m)]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Muestreo del DEM (georreferenciado por bbox lon/lat, origen superior)
# ─────────────────────────────────────────────────────────────────────────────
def _muestrear_dem(array: np.ndarray, bbox: dict, lat: float, lon: float
                   ) -> float:
    """Interpola bilinealmente la cota del DEM en (lat, lon).

    El array está georreferenciado por su bbox lon/lat con la fila 0 = norte
    (origin="upper"), la misma convención que usa el resto del codebase al
    dibujar con `imshow(extent=[oeste, este, sur, norte])`. Devuelve NaN si el
    punto cae fuera del array o sobre celdas NaN.
    """
    H, W = array.shape
    o, e = bbox["oeste"], bbox["este"]
    s, n = bbox["sur"], bbox["norte"]
    if e == o or n == s:
        return float("nan")
    fc = (lon - o) / (e - o) * (W - 1)
    fr = (n - lat) / (n - s) * (H - 1)
    if fc < 0 or fc > W - 1 or fr < 0 or fr > H - 1:
        return float("nan")
    c0 = int(math.floor(fc)); c1 = min(c0 + 1, W - 1)
    r0 = int(math.floor(fr)); r1 = min(r0 + 1, H - 1)
    tc = fc - c0; tr = fr - r0
    v00 = array[r0, c0]; v01 = array[r0, c1]
    v10 = array[r1, c0]; v11 = array[r1, c1]
    vals = np.array([v00, v01, v10, v11], dtype=float)
    if not np.all(np.isfinite(vals)):
        # Bilineal no válido: cae al vecino más cercano válido si existe.
        finite = vals[np.isfinite(vals)]
        return float(finite.mean()) if finite.size else float("nan")
    top = v00 * (1 - tc) + v01 * tc
    bot = v10 * (1 - tc) + v11 * tc
    return float(top * (1 - tr) + bot * tr)


def _metros_por_grado(lat: float) -> tuple[float, float]:
    """(m por grado de longitud, m por grado de latitud) en la latitud dada.

    Aproximación equirectangular local, suficiente a escala de tramo fluvial.
    """
    m_lat = 111132.92 - 559.82 * math.cos(2 * math.radians(lat))
    m_lon = 111412.84 * math.cos(math.radians(lat))
    return m_lon, m_lat


# ─────────────────────────────────────────────────────────────────────────────
# 4. Thalweg desde el DEM (hidrología D8)
# ─────────────────────────────────────────────────────────────────────────────
def _thalweg_desde_dem(dem: dict, lat: float, lon: float,
                       largo_arriba_m: float, largo_abajo_m: float
                       ) -> Optional[np.ndarray]:
    """Traza el thalweg (Nx2 [lon, lat]) que pasa por el punto del proyecto.

    Usa D8 (dirección y acumulación de flujo, `red_drenaje_dem`): fija el punto
    sobre el píxel de mayor acumulación en su entorno (cauce), camina aguas
    abajo siguiendo la dirección de flujo y aguas arriba eligiendo el afluente
    de mayor área aportante, hasta cubrir el largo pedido a cada lado.
    `None` si el DEM es insuficiente.
    """
    from .red_drenaje_dem import (rellenar_depresiones, flow_direction_d8,
                                  flow_accumulation, _D8_OFFSETS)

    arr = np.asarray(dem["array"], dtype=float)
    bbox = dem["bbox"]
    paso = float(dem.get("resolucion_m", 12.5))
    H, W = arr.shape
    if H < 5 or W < 5 or np.all(np.isnan(arr)):
        return None

    dem_fill = rellenar_depresiones(arr)
    fdir = flow_direction_d8(dem_fill, paso_m=paso)
    facc = flow_accumulation(fdir)

    # Píxel del punto del proyecto.
    o, e = bbox["oeste"], bbox["este"]
    s, nb = bbox["sur"], bbox["norte"]
    col = int(round((lon - o) / (e - o) * (W - 1)))
    row = int(round((nb - lat) / (nb - s) * (H - 1)))
    col = min(max(col, 0), W - 1)
    row = min(max(row, 0), H - 1)

    # Snap al cauce: mayor acumulación en una ventana ±rad alrededor del punto.
    rad = max(2, int(round(30.0 / paso)))
    r0, r1 = max(0, row - rad), min(H, row + rad + 1)
    c0, c1 = max(0, col - rad), min(W, col + rad + 1)
    sub = facc[r0:r1, c0:c1]
    if sub.size == 0:
        return None
    idx = np.unravel_index(int(np.argmax(sub)), sub.shape)
    row, col = r0 + idx[0], c0 + idx[1]

    cod_a_offset = {code: (dr, dc) for dr, dc, code in _D8_OFFSETS}

    def a_lonlat(r: int, c: int) -> tuple[float, float]:
        lon_p = o + (c / (W - 1)) * (e - o)
        lat_p = nb - (r / (H - 1)) * (nb - s)
        return lon_p, lat_p

    diag = math.sqrt(2.0) * paso

    # Aguas abajo: seguir la dirección de flujo.
    abajo = []
    r, c = row, col
    dist = 0.0
    visto = {(r, c)}
    while dist < largo_abajo_m:
        code = int(fdir[r, c])
        if code not in cod_a_offset:
            break
        dr, dc = cod_a_offset[code]
        nr, nc = r + dr, c + dc
        if not (0 <= nr < H and 0 <= nc < W) or (nr, nc) in visto:
            break
        dist += diag if (dr != 0 and dc != 0) else paso
        r, c = nr, nc
        visto.add((r, c))
        abajo.append((r, c))

    # Aguas arriba: elegir el vecino que drena hacia la celda actual con mayor
    # acumulación (afluente principal).
    arriba = []
    r, c = row, col
    dist = 0.0
    visto2 = {(row, col)} | set(abajo)
    while dist < largo_arriba_m:
        mejor = None
        mejor_acc = -1.0
        for dr, dc, code in _D8_OFFSETS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < H and 0 <= nc < W) or (nr, nc) in visto2:
                continue
            # ¿(nr,nc) drena hacia (r,c)? Su código apunta al opuesto (-dr,-dc).
            code_vec = int(fdir[nr, nc])
            if code_vec not in cod_a_offset:
                continue
            odr, odc = cod_a_offset[code_vec]
            if (odr, odc) == (-dr, -dc):
                if facc[nr, nc] > mejor_acc:
                    mejor_acc = float(facc[nr, nc])
                    mejor = (nr, nc, dr, dc)
        if mejor is None:
            break
        nr, nc, dr, dc = mejor
        dist += diag if (dr != 0 and dc != 0) else paso
        r, c = nr, nc
        visto2.add((r, c))
        arriba.append((r, c))

    # Orden: aguas arriba (invertido) → punto → aguas abajo.
    pix = list(reversed(arriba)) + [(row, col)] + abajo
    if len(pix) < 3:
        return None
    return np.array([a_lonlat(r, c) for r, c in pix], dtype=float)


def _resamplear(linea: np.ndarray, lat0: float, espaciado_m: float,
                n_pts: Optional[int] = None
                ) -> list[tuple[float, float, float, float]]:
    """Resamplea una polilínea lon/lat a puntos equiespaciados (en metros).

    Devuelve lista de (lon, lat, estacion_m, azimut_rad), donde el azimut es la
    dirección local de la línea en el plano ENU (este-norte) local. Si `n_pts`
    se indica, se generan exactamente esos puntos (equiespaciados sobre la
    longitud total); si no, se derivan del `espaciado_m`.
    """
    m_lon, m_lat = _metros_por_grado(lat0)
    # Coordenadas ENU locales (metros) respecto al primer vértice.
    lon0, la0 = linea[0]
    ex = (linea[:, 0] - lon0) * m_lon
    ny = (linea[:, 1] - la0) * m_lat
    d = np.hypot(np.diff(ex), np.diff(ny))
    s = np.concatenate([[0.0], np.cumsum(d)])
    total = s[-1]
    if total <= 0:
        return []
    if n_pts is None:
        n_pts = max(2, int(round(total / espaciado_m)) + 1)
    estaciones = np.linspace(0, total, n_pts)
    puntos = []
    for est in estaciones:
        ex_i = np.interp(est, s, ex)
        ny_i = np.interp(est, s, ny)
        # Azimut local por diferencias finitas.
        de = np.interp(min(est + 0.5, total), s, ex) - \
            np.interp(max(est - 0.5, 0.0), s, ex)
        dn = np.interp(min(est + 0.5, total), s, ny) - \
            np.interp(max(est - 0.5, 0.0), s, ny)
        az = math.atan2(dn, de)
        lon_i = lon0 + ex_i / m_lon
        lat_i = la0 + ny_i / m_lat
        puntos.append((lon_i, lat_i, float(est), az))
    return puntos


# ─────────────────────────────────────────────────────────────────────────────
# 5. Corte de secciones transversales perpendiculares al thalweg
# ─────────────────────────────────────────────────────────────────────────────
def _cortar_secciones(dem: dict, thalweg: np.ndarray, ancho_m: float,
                      espaciado_m: float, lat0: float,
                      n_secciones: Optional[int] = None
                      ) -> list[SeccionTransversal]:
    """Corta secciones perpendiculares al thalweg y muestrea el DEM en ellas.

    Si `n_secciones` se indica, se generan exactamente esa cantidad
    equiespaciadas sobre el tramo (p. ej. 11 = 5 aguas arriba + punto + 5 aguas
    abajo)."""
    arr = np.asarray(dem["array"], dtype=float)
    bbox = dem["bbox"]
    paso = float(dem.get("resolucion_m", 12.5))
    m_lon, m_lat = _metros_por_grado(lat0)
    # Paso transversal de muestreo ≈ resolución del DEM (mínimo 21 puntos).
    n_lados = max(10, int(round((ancho_m / 2.0) / paso)))
    offsets = np.linspace(-ancho_m / 2.0, ancho_m / 2.0, 2 * n_lados + 1)

    puntos = _resamplear(thalweg, lat0, espaciado_m, n_pts=n_secciones)
    secciones: list[SeccionTransversal] = []
    for k, (lon_c, lat_c, est, az) in enumerate(puntos):
        # Perpendicular al thalweg: az + 90° en el plano ENU.
        perp = az + math.pi / 2.0
        ux, uy = math.cos(perp), math.sin(perp)   # componentes este, norte (m)
        z = np.empty(offsets.size, dtype=float)
        for j, off in enumerate(offsets):
            de = off * ux
            dn = off * uy
            lon_p = lon_c + de / m_lon
            lat_p = lat_c + dn / m_lat
            z[j] = _muestrear_dem(arr, bbox, lat_p, lon_p)
        # Abscisas locales 0 = margen izquierda.
        x_local = offsets - offsets[0]
        if np.isfinite(z).sum() < 3:
            continue
        secciones.append(SeccionTransversal(
            id=k, estacion_m=est, x_local_m=x_local, z_m=z,
            centro_lonlat=(lon_c, lat_c)))
    return secciones


# ─────────────────────────────────────────────────────────────────────────────
# 6. Geometría de respaldo (sin DEM): canal trapezoidal de régimen
# ─────────────────────────────────────────────────────────────────────────────
def _seccion_trapezoidal(Q: float, ancho_m: float, talud: float = 2.0,
                         n_secc: int = 5, espaciado_m: float = 10.0
                         ) -> list[SeccionTransversal]:
    """Genera secciones trapezoidales idénticas cuando no hay DEM.

    Ancho de fondo estimado por geometría hidráulica de régimen
    (b ≈ 2.0·√Q, acotado), taludes 1V:`talud`H, profundizado lo suficiente para
    contener el caudal. Es una aproximación conservadora, claramente señalada.
    """
    b = float(np.clip(2.0 * math.sqrt(max(Q, 0.1)), 1.0, ancho_m * 0.6))
    prof = max(1.5, 0.5 * math.sqrt(max(Q, 0.1)))  # profundidad de banco tentativa
    # Perfil trapezoidal centrado en un ancho total = ancho_m.
    ancho_sup_canal = b + 2 * talud * prof
    margen = max((ancho_m - ancho_sup_canal) / 2.0, ancho_m * 0.1)
    xs = [0.0]
    zs = [prof]                       # llanura izquierda (cota = prof sobre fondo)
    xs.append(margen);               zs.append(prof)
    xs.append(margen + talud * prof); zs.append(0.0)          # pie izquierdo
    xs.append(margen + talud * prof + b); zs.append(0.0)      # pie derecho
    xs.append(margen + 2 * talud * prof + b); zs.append(prof) # coronación derecha
    xs.append(2 * margen + ancho_sup_canal); zs.append(prof)  # llanura derecha
    x_local = np.array(xs, dtype=float)
    z = np.array(zs, dtype=float)
    secciones = []
    for k in range(n_secc):
        secciones.append(SeccionTransversal(
            id=k, estacion_m=k * espaciado_m,
            x_local_m=x_local.copy(), z_m=z.copy(),
            centro_lonlat=(float("nan"), float("nan"))))
    return secciones


# ─────────────────────────────────────────────────────────────────────────────
# 7. n de Manning por cobertura (GEE) con respaldo
# ─────────────────────────────────────────────────────────────────────────────
def n_manning_desde_cobertura(poligono_lonlat) -> tuple[float, dict]:
    """Devuelve (n, detalle) del corredor fluvial vía cobertura MapBiomas (GEE).

    Reutiliza `gee.n_manning_ponderado_desde_poligono`. Si GEE no responde,
    devuelve (N_MANNING_DEFECTO, {"fuente": "valor por defecto ..."}).
    """
    detalle = {"fuente": "cobertura MapBiomas Bolivia (GEE)"}
    if poligono_lonlat is not None:
        try:
            from .gee import n_manning_ponderado_desde_poligono
            n = n_manning_ponderado_desde_poligono(poligono_lonlat)
            if n is not None and 0.010 <= n <= 0.20:
                detalle["n_ponderado"] = float(n)
                return float(n), detalle
        except Exception:  # noqa: BLE001
            pass
    detalle = {"fuente": f"valor por defecto (cauce natural, Chow): "
                         f"{N_MANNING_DEFECTO}"}
    return N_MANNING_DEFECTO, detalle


# ─────────────────────────────────────────────────────────────────────────────
# 8. Descarga del DEM del tramo (rectángulo alrededor del punto)
# ─────────────────────────────────────────────────────────────────────────────
def _dem_del_tramo(lat: float, lon: float, ancho_m: float,
                   largo_tramo_m: float) -> Optional[dict]:
    """Descarga el COP-DEM 12.5 m de un rectángulo que cubre el tramo fluvial.

    El rectángulo se dimensiona para contener el thalweg (± largo_tramo_m) y el
    ancho de las secciones, con un margen. `None` si GEE no responde.
    """
    try:
        from .copernicus_dem import obtener_dem_cuenca
    except Exception:  # noqa: BLE001
        return None
    m_lon, m_lat = _metros_por_grado(lat)
    # Semi-lado: cubre el tramo longitudinal y el ancho transversal, + 30 %.
    semi_m = 1.3 * max(largo_tramo_m + ancho_m, ancho_m * 1.5, 250.0)
    dlon = semi_m / m_lon
    dlat = semi_m / m_lat
    rect = np.array([
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ], dtype=float)
    try:
        return obtener_dem_cuenca(rect, res_target_m=12.5)
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 9. Orquestador
# ─────────────────────────────────────────────────────────────────────────────
def _resolver_flujo(secciones, Q: float, n: float, S: float) -> Optional[dict]:
    """Resuelve el tirante normal en TODAS las secciones para un caudal Q.

    Cada sección se copia (dataclasses.replace) para no pisar la solución de
    otro caudal —así el mismo juego de secciones sirve para Q100 y Q500—.
    Devuelve un dict con la lista resuelta, la sección de control y los
    agregados del tramo (tirante de control/máximo/medio, velocidad media,
    Froude/régimen, desborde), o None si ninguna sección converge.
    """
    if Q is None or Q <= 0:
        return None
    resueltas = []
    for sec in secciones:
        r = resolver_tirante_normal(sec.x_local_m, sec.z_m, Q, n, S)
        if r is None:
            continue
        s2 = replace(sec)
        s2.wse_m = r["wse"]; s2.tirante_m = r["tirante"]
        s2.area_m2 = r["area"]; s2.perimetro_m = r["perimetro"]
        s2.radio_h_m = r["radio_h"]; s2.ancho_sup_m = r["ancho_sup"]
        s2.velocidad_ms = r["velocidad"]; s2.froude = r["froude"]
        s2.regimen = r["regimen"]; s2.desborda = r["desborda"]
        resueltas.append(s2)
    if not resueltas:
        return None
    tirantes = np.array([s.tirante_m for s in resueltas], dtype=float)
    vels = np.array([s.velocidad_ms for s in resueltas], dtype=float)
    froudes = np.array([s.froude for s in resueltas
                        if np.isfinite(s.froude)], dtype=float)
    est_centro = np.median([s.estacion_m for s in resueltas])
    i_ctrl = int(np.argmin([abs(s.estacion_m - est_centro) for s in resueltas]))
    fr_medio = float(np.nanmean(froudes)) if froudes.size else float("nan")
    if not np.isfinite(fr_medio):
        regimen = ""
    elif fr_medio < 0.95:
        regimen = "subcrítico"
    elif fr_medio <= 1.05:
        regimen = "crítico"
    else:
        regimen = "supercrítico"
    return {
        "resueltas": resueltas, "i_ctrl": i_ctrl, "sec_ctrl": resueltas[i_ctrl],
        "tirante_control": float(resueltas[i_ctrl].tirante_m),
        "tirante_max": float(np.nanmax(tirantes)),
        "tirante_medio": float(np.nanmean(tirantes)),
        "velocidad_media": float(np.nanmean(vels)),
        "froude_medio": fr_medio, "regimen": regimen,
        "desborda": any(s.desborda for s in resueltas),
    }


def _socavacion_de_flujo(flujo: dict, Q: float, T: int, S: float,
                         pp: dict):
    """Calcula la socavación (general + contracción + pila + estribo) en la
    sección de control para el caudal `flujo`. Devuelve ResultadoSocavacion o
    None si el módulo de socavación falla."""
    try:
        from .socavacion import calcular_socavacion, D50_DEFECTO_MM
        sc = flujo["sec_ctrl"]
        return calcular_socavacion(
            Q=Q, T_anios=int(T), y1=sc.tirante_m, V1=sc.velocidad_ms,
            Be=sc.ancho_sup_m, area_m2=sc.area_m2,
            W_contraccion=pp.get("ancho_contraccion_m"),
            D50_mm=pp.get("D50_mm", D50_DEFECTO_MM), D95_mm=pp.get("D95_mm"),
            cohesivo=pp.get("cohesivo", False), gamma_d=pp.get("gamma_d", 1.2),
            ancho_pila_m=pp.get("ancho_pila_m"),
            forma_pila=pp.get("forma_pila", "redonda"),
            angulo_ataque_grados=pp.get("angulo_ataque_grados", 0.0),
            long_pila_m=pp.get("long_pila_m"),
            long_estribo_m=pp.get("long_estribo_m"),
            forma_estribo=pp.get("forma_estribo", "derramado"),
            resguardo_m=pp.get("resguardo_m", 1.5), S_energia=S)
    except Exception:  # noqa: BLE001
        return None


def calcular_tirante(*, lat: float, lon: float, Q_diseno: float,
                     T_diseno: int, area_cuenca_km2: float,
                     S_cauce_pct: float,
                     poligono_cuenca=None,
                     dem: Optional[dict] = None,
                     n_manning: Optional[float] = None,
                     Q_verif: Optional[float] = None,
                     T_verif: Optional[int] = None,
                     longitud_tramo_m: float = LONGITUD_TRAMO_DEFECTO_M,
                     intentar_dem: bool = True,
                     params_puente: Optional[dict] = None
                     ) -> Optional[ResultadoTirante]:
    """Calcula el tirante (calado) en el sitio del proyecto — HEC-RAS 1D.

    Parámetros
    ----------
    lat, lon : coordenadas del punto del proyecto (sobre el cauce).
    Q_diseno : caudal de diseño (m³/s) — mediana entre métodos del §11.
    T_diseno : período de retorno de diseño (años).
    area_cuenca_km2 : área de la cuenca aportante (define ancho/espaciado).
    S_cauce_pct : pendiente del cauce en % (del análisis morfológico).
    poligono_cuenca : Nx2 [lon, lat] para derivar n de Manning por cobertura.
    dem : dict de DEM ya descargado (para tests/reuso); si None se descarga.
    n_manning : n forzado; si None se deriva de la cobertura GEE.
    Q_verif, T_verif : caudal/período de verificación estructural (opcional).
    longitud_tramo_m : largo aguas arriba y aguas abajo (defecto 200 m).

    Devuelve un `ResultadoTirante`, o `None` si faltan datos mínimos (Q o S).
    """
    if Q_diseno is None or Q_diseno <= 0:
        return None
    advertencias: list[str] = []

    ancho_m, espaciado_m = seccion_ancho_espaciado(area_cuenca_km2)

    # Pendiente adoptada (fracción), con piso físico.
    S = (S_cauce_pct or 0.0) / 100.0
    if S < _S_MIN:
        advertencias.append(
            f"La pendiente del cauce reportada ({S_cauce_pct:.3f} %) es nula o "
            f"muy baja; se adopta el piso de {_S_MIN * 100:.2f} % para el "
            f"cálculo del tirante normal.")
        S = _S_MIN

    # n de Manning.
    if n_manning is not None:
        n = float(n_manning)
        n_detalle = {"fuente": "valor indicado por el usuario", "n": n}
    else:
        n, n_detalle = n_manning_desde_cobertura(poligono_cuenca)
        if n_detalle.get("fuente", "").startswith("valor por defecto"):
            advertencias.append(
                "No se pudo derivar el n de Manning desde la cobertura GEE; se "
                f"adopta n = {N_MANNING_DEFECTO} (cauce natural limpio, Chow).")

    # Geometría de secciones: DEM real o respaldo trapezoidal.
    fuente_geom = "DEM COP-DEM 12.5 m"
    if dem is None and intentar_dem:
        dem = _dem_del_tramo(lat, lon, ancho_m, longitud_tramo_m)
    secciones: list[SeccionTransversal] = []
    thalweg_out = None
    if dem is not None:
        thalweg = _thalweg_desde_dem(dem, lat, lon,
                                     longitud_tramo_m, longitud_tramo_m)
        if thalweg is not None:
            thalweg_out = thalweg
            secciones = _cortar_secciones(dem, thalweg, ancho_m,
                                          espaciado_m, lat,
                                          n_secciones=N_SECCIONES)
    if not secciones:
        fuente_geom = "estimada (geometría hidráulica de régimen — sin DEM)"
        advertencias.append(
            "No se pudo trazar el thalweg ni cortar secciones sobre el DEM "
            "(GEE no disponible o cauce no detectado); se usa una sección "
            "trapezoidal estimada por geometría hidráulica de régimen.")
        # 11 secciones (5 aguas arriba + punto + 5 aguas abajo), espaciadas
        # sobre el tramo de ±longitud_tramo_m.
        secciones = _seccion_trapezoidal(
            Q_diseno, ancho_m, n_secc=N_SECCIONES,
            espaciado_m=longitud_tramo_m / SECCIONES_POR_LADO)

    # ── Flujo de DISEÑO (T100): solución completa en las 11 secciones. ──
    flujo_d = _resolver_flujo(secciones, Q_diseno, n, S)
    if flujo_d is None:
        advertencias.append(
            "No se pudo resolver el tirante normal en ninguna sección.")
        return ResultadoTirante(
            Q_m3s=Q_diseno, T_diseno=T_diseno, n_manning=n, n_detalle=n_detalle,
            S_cauce=S, area_cuenca_km2=area_cuenca_km2, ancho_seccion_m=ancho_m,
            espaciado_m=espaciado_m, longitud_tramo_m=longitud_tramo_m,
            secciones=[], tirante_medio_m=float("nan"),
            tirante_max_m=float("nan"), tirante_control_m=float("nan"),
            velocidad_media_ms=float("nan"), froude_medio=float("nan"),
            regimen_predominante="", fuente_geometria=fuente_geom,
            advertencias=advertencias)

    resueltas = flujo_d["resueltas"]
    tirante_control = flujo_d["tirante_control"]
    # Perfil de flujo gradualmente variado (standard-step) del caudal de diseño.
    # Solo con geometría REAL del DEM (la sección trapezoidal de respaldo no
    # tiene un perfil de fondo longitudinal representativo para el paso estándar).
    perfil_gvf = []
    if fuente_geom.startswith("DEM"):
        try:
            perfil_gvf = perfil_gradualmente_variado(resueltas, Q_diseno, n) or []
        except Exception:  # noqa: BLE001
            perfil_gvf = []
    if flujo_d["desborda"]:
        advertencias.append(
            "En una o más secciones el caudal de diseño supera el ancho "
            "adoptado (desborde): el tirante se calcula extendiendo la sección "
            "con paredes verticales. Considere ampliar el ancho de la sección.")

    pp = params_puente or {}

    # ── Flujo de VERIFICACIÓN (T500): solución completa para el cuadro final
    #    y para la verificación del gálibo de la viga. ──
    flujo_v = None
    tirante_verif = tirante_verif_max = None
    vel_verif = fr_verif = regimen_verif = None
    if Q_verif and Q_verif > 0:
        flujo_v = _resolver_flujo(secciones, Q_verif, n, S)
        if flujo_v is not None:
            tirante_verif = flujo_v["tirante_control"]
            tirante_verif_max = flujo_v["tirante_max"]
            vel_verif = flujo_v["velocidad_media"]
            fr_verif = flujo_v["froude_medio"]
            regimen_verif = flujo_v["regimen"]
            if flujo_v["desborda"]:
                advertencias.append(
                    "Con el caudal de verificación (T superior) el flujo "
                    "desborda el ancho adoptado en alguna sección.")

    # ── Pilar 3 — Socavación para AMBOS caudales (cuadro de resultados). El
    #    escenario GOBERNANTE (mayor socavación → base de la fundación) es el
    #    de verificación T500 si existe; si no, el de diseño. ──
    socav_diseno = _socavacion_de_flujo(flujo_d, Q_diseno, T_diseno, S, pp)
    socav_verif = (_socavacion_de_flujo(flujo_v, Q_verif, T_verif or T_diseno,
                                        S, pp) if flujo_v is not None else None)
    socav = socav_verif or socav_diseno   # gobernante (retrocompatibilidad)

    # ── Verificación del gálibo de la viga (concepto de cierre, Manual ABC).
    #    La viga se coloca a `galibo` sobre el NAME de diseño (T100). La norma
    #    ABC exige que el gálibo LIBRE entre (NAME de verificación + altura de
    #    palizada/troncos) y la cara inferior de la viga sea ≥ galibo_min
    #    (1.50–2.00 m). Si no cumple → ALERTA ROJA. ──
    galibo = float(pp.get("galibo_m", GALIBO_DEFECTO_M))
    altura_palizada = float(pp.get("altura_palizada_m", PALIZADA_DEFECTO_M))
    galibo_min = float(pp.get("galibo_min_m", GALIBO_MIN_ABC_M))
    cota_viga = tirante_control + galibo
    holgura_verif = verifica_viga = galibo_efectivo = None
    if tirante_verif is not None:
        # Holgura simple (cara de viga − NAME de verificación).
        holgura_verif = cota_viga - tirante_verif
        # Gálibo LIBRE efectivo = cara de viga − (NAME verif + palizada).
        galibo_efectivo = cota_viga - (tirante_verif + altura_palizada)
        verifica_viga = bool(galibo_efectivo >= galibo_min)
        if not verifica_viga:
            advertencias.append(
                f"ALERTA: el gálibo libre efectivo ({galibo_efectivo:.2f} m) "
                f"entre el NAME de verificación (T{T_verif or '?'}: "
                f"{tirante_verif:.2f} m) más la palizada ({altura_palizada:.2f} "
                f"m) y la cara inferior de la viga ({cota_viga:.2f} m sobre el "
                f"fondo) es MENOR que el mínimo normativo ABC "
                f"({galibo_min:.2f} m): elevar la rasante o el gálibo.")

    return ResultadoTirante(
        Q_m3s=Q_diseno, T_diseno=T_diseno, n_manning=n, n_detalle=n_detalle,
        S_cauce=S, area_cuenca_km2=area_cuenca_km2, ancho_seccion_m=ancho_m,
        espaciado_m=espaciado_m, longitud_tramo_m=longitud_tramo_m,
        secciones=resueltas,
        tirante_medio_m=flujo_d["tirante_medio"],
        tirante_max_m=flujo_d["tirante_max"],
        tirante_control_m=float(tirante_control),
        velocidad_media_ms=flujo_d["velocidad_media"],
        froude_medio=flujo_d["froude_medio"],
        regimen_predominante=flujo_d["regimen"],
        fuente_geometria=fuente_geom,
        advertencias=advertencias,
        Q_verif_m3s=Q_verif, T_verif=T_verif, tirante_verif_m=tirante_verif,
        tirante_verif_max_m=tirante_verif_max,
        velocidad_verif_ms=vel_verif, froude_verif=fr_verif,
        regimen_verif=regimen_verif,
        secciones_verif=(flujo_v["resueltas"] if flujo_v is not None else []),
        socavacion=socav, socavacion_diseno=socav_diseno,
        socavacion_verif=socav_verif,
        galibo_m=galibo, cota_viga_sobre_fondo_m=cota_viga,
        holgura_viga_verif_m=holgura_verif, verifica_viga_verif=verifica_viga,
        altura_palizada_m=altura_palizada, galibo_min_abc_m=galibo_min,
        galibo_efectivo_verif_m=galibo_efectivo,
        perfil_gvf=perfil_gvf,
        thalweg_lonlat=thalweg_out, punto_lonlat=(lon, lat))
