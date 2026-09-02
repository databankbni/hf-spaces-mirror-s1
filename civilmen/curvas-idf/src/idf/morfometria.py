"""Análisis morfométrico completo de la cuenca a partir del DEM delineado.

Toma un `CuencaDelineada` (MERIT Hydro 90 m, con los arrays de elevación y
pendiente de los píxeles internos) y calcula todas las variables morfológicas
e hidrológicas que se reportan en las secciones 9.10–9.12 del informe:

- Geometría: A, P, longitud de cauce, longitud axial Lb, ancho medio.
- Relieve: Hmax, Hmin, Hmedia, desnivel, pendiente media de cuenca y de cauce.
- Forma: Gravelius (Kc), Horton (Ff), elongación (Re), circularidad (Rc),
  rectángulo equivalente, coeficiente de masividad.
- Drenaje: densidad de drenaje Dd.
- Curva hipsométrica + integral hipsométrica (HI) + estado de la cuenca.
- Bandas de elevación y de pendiente (% de área) para leyendas y tablas.

Todo se deriva del DEM real; nada es sintético.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class BandaElevacion:
    desde_m: float
    hasta_m: float
    area_km2: float
    pct: float
    pct_acum: float  # % de área por ENCIMA del límite inferior (para hipsométrica)


@dataclass
class AnalisisMorfologico:
    # Geometría
    area_km2: float
    perimetro_km: float
    long_cauce_km: float          # cauce principal (Hack)
    long_axial_km: float          # longitud de la cuenca Lb
    ancho_medio_km: float
    # Relieve
    cota_mayor_m: float
    cota_menor_m: float
    cota_media_m: float
    desnivel_m: float
    pendiente_cuenca_pct: float
    pendiente_cauce_pct: float
    # Índices de forma
    kc_gravelius: float
    ff_horton: float
    re_elongacion: float
    rc_circularidad: float
    rect_lado_mayor_km: float
    rect_lado_menor_km: float
    coef_masividad: float
    # Drenaje
    densidad_drenaje_km_km2: float
    pendiente_cuenca_grados: float = 0.0
    long_cauce_principal_km: float = 0.0
    frecuencia_corrientes: float = 0.0     # F = N/A
    textura_drenaje: float = 0.0           # T = N/P
    intensidad_drenaje: float = 0.0        # ID = Dd·F
    numero_rugosidad: float = 0.0          # Rn = Dd·H (Melton)
    orden_max: int = 0                     # orden de Strahler
    relacion_bifurcacion: float = 0.0      # Rb
    sinuosidad: float = 0.0
    # Distancia RECTA cabecera→exutorio medida sobre el mismo trazado D8 con el
    # que se mide el cauce principal. Es el denominador exacto de la sinuosidad
    # (S = Lc/Lr); publicarla permite reproducir S a partir de la tabla.
    long_recta_cauce_km: float = 0.0
    # True si Lc < Lr (cauce más corto que la recta): imposible físicamente,
    # señal de extracción D8 truncada. Se declara en el informe.
    sinuosidad_inconsistente: bool = False
    n_corrientes: int = 0
    n_por_orden: dict = field(default_factory=dict)
    retencion_s_mm: float = 0.0            # S = 25400/CN − 254 (infiltración pot.)
    cn: float = 0.0
    interp_pendiente: str = ""
    interp_tc: str = ""
    interp_dd: str = ""
    # Hipsometría
    integral_hipsometrica: float = 0.0
    estado_cuenca: str = ""
    hipso_area_pct: np.ndarray = field(default=None)   # x de la curva (% área ≥ h)
    hipso_altura_rel: np.ndarray = field(default=None)  # y de la curva (altura rel)
    bandas_elevacion: list = field(default_factory=list)
    bandas_pendiente: list = field(default_factory=list)
    clase_forma: str = ""


def _longitud_axial_km(poligono_lonlat) -> float:
    """Diámetro del polígono (máxima distancia entre vértices) en km."""
    lon = poligono_lonlat[:, 0]
    lat = poligono_lonlat[:, 1]
    lat0 = float(lat.mean())
    x = (lon - lon.mean()) * 111.320 * math.cos(math.radians(lat0))  # km
    y = (lat - lat.mean()) * 110.540
    pts = np.column_stack([x, y])
    # Si hay muchos puntos, submuestrear para que el O(N²) sea barato.
    if len(pts) > 300:
        idx = np.linspace(0, len(pts) - 1, 300).astype(int)
        pts = pts[idx]
    d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2)
    return float(np.sqrt(d2.max()))


def _bandas(valores: np.ndarray, lo: float, hi: float, n: int,
            area_total_km2: float, acumulado_desde_arriba: bool):
    """Divide [lo,hi] en n bandas y calcula área y % por banda."""
    bordes = np.linspace(lo, hi, n + 1)
    total = valores.size
    bandas = []
    acum = 0.0
    # Para hipsométrica el acumulado es "% por encima"; recorremos de arriba abajo.
    rango = range(n - 1, -1, -1) if acumulado_desde_arriba else range(n)
    for k in rango:
        b0, b1 = bordes[k], bordes[k + 1]
        if k == n - 1:
            sel = (valores >= b0) & (valores <= b1)
        else:
            sel = (valores >= b0) & (valores < b1)
        cnt = int(sel.sum())
        pct = 100.0 * cnt / total if total else 0.0
        area = area_total_km2 * cnt / total if total else 0.0
        acum += pct
        bandas.append(BandaElevacion(round(b0, 1), round(b1, 1),
                                     round(area, 3), round(pct, 1),
                                     round(acum, 1)))
    if acumulado_desde_arriba:
        bandas.reverse()
    return bandas


def _interp_dd(dd: float) -> str:
    if dd < 0.5:
        return "drenaje pobre, suelos permeables"
    if dd < 1.5:
        return "drenaje moderado"
    if dd < 2.5:
        return "drenaje alto"
    return "drenaje muy alto, suelos impermeables"


def analizar(cuenca, tc_min: float = None,
             cn_ponderado: float = None) -> AnalisisMorfologico:
    """Calcula el análisis morfológico completo desde la cuenca delineada."""
    A = float(cuenca.area_km2)
    P = float(cuenca.perimetro_km)
    L = float(cuenca.long_cauce_km)
    Lb = _longitud_axial_km(cuenca.poligono_latlon)
    Lb = max(Lb, L * 0.5, 0.1)
    W = A / Lb if Lb else 0.0

    elev = np.asarray(cuenca.elev_dentro_m, dtype=np.float64)
    hmax = float(elev.max())
    hmin = float(elev.min())
    hmean = float(elev.mean())
    desnivel = hmax - hmin

    pend = np.asarray(cuenca.pendiente_dentro_pct, dtype=np.float64)
    pend = pend[np.isfinite(pend)]
    pendiente_cuenca = float(pend.mean()) if pend.size else 0.0
    pendiente_cauce = 100.0 * desnivel / (L * 1000.0) if L else 0.0

    # Índices de forma
    kc = 0.2821 * P / math.sqrt(A) if A else 0.0
    ff = A / (Lb ** 2) if Lb else 0.0
    re = 1.1284 * math.sqrt(A) / Lb if Lb else 0.0
    rc = 4 * math.pi * A / (P ** 2) if P else 0.0
    # Rectángulo equivalente
    if kc >= 1.128:
        raiz = math.sqrt(max(0.0, 1 - (1.128 / kc) ** 2))
        base = kc * math.sqrt(A) / 1.128
        rect_mayor = base * (1 + raiz)
        rect_menor = base * (1 - raiz)
    else:
        rect_mayor = rect_menor = math.sqrt(A)
    coef_masividad = hmean / A if A else 0.0

    Dd = float(cuenca.long_cauce_total_km) / A if A else 0.0

    # Curva hipsométrica: a*(h) = fracción de área con elevación >= h.
    niveles = np.linspace(hmin, hmax, 40)
    area_pct = np.array([100.0 * (elev >= h).sum() / elev.size for h in niveles])
    altura_rel = (niveles - hmin) / desnivel if desnivel else np.zeros_like(niveles)
    # Integral hipsométrica (relación altura-relieve, Pike & Wilson).
    HI = (hmean - hmin) / desnivel if desnivel else 0.0
    if HI > 0.60:
        estado = "Fase de juventud (desequilibrio, fuerte potencial erosivo)"
    elif HI >= 0.35:
        estado = "Fase de madurez (equilibrio entre erosión y sedimentación)"
    else:
        estado = "Fase de vejez (cuenca erosionada, relieve suavizado)"

    bandas_elev = _bandas(elev, hmin, hmax, 6, A, acumulado_desde_arriba=True)
    pend_hi = float(min(pend.max(), 80.0)) if pend.size else 1.0
    bandas_pend = _bandas(pend, 0.0, max(pend_hi, 1.0), 6, A,
                          acumulado_desde_arriba=False)

    # Clase de forma combinando Ff y Kc.
    if ff > 0.5 and kc < 1.25:
        clase = "circular (crecidas rápidas, Tc cortos)"
    elif ff < 0.3 and kc > 1.5:
        clase = "elongada (crecidas atenuadas, Tc largos)"
    else:
        clase = "intermedia (oval-oblonga)"

    # --- Parámetros de red de drenaje (Strahler) e hidrológicos ---
    red = getattr(cuenca, "red_drenaje", None) or {}
    n_total = int(red.get("n_total", 0))
    n_por_orden = red.get("n_por_orden", {}) or {}
    orden_max = int(red.get("max_order", 0))
    rb = float(red.get("rb") or 0.0)
    sinuosidad = float(red.get("sinuosidad") or 0.0)
    long_principal = float(red.get("main_channel_km") or L)
    F = n_total / A if A else 0.0                 # frecuencia de corrientes
    T = n_total / P if P else 0.0                 # textura de drenaje
    ID = Dd * F                                   # intensidad de drenaje
    Rn = Dd * (desnivel / 1000.0)                 # número de rugosidad (Melton)
    pendiente_grados = math.degrees(math.atan(pendiente_cuenca / 100.0))
    cn = float(cn_ponderado) if cn_ponderado else float(getattr(cuenca, "cn", 0) or 0)
    S_ret = (25400.0 / cn - 254.0) if cn else 0.0  # retención potencial (mm)

    # Interpretaciones cualitativas (params 34-36)
    if pendiente_cuenca < 8:
        ip = "baja (terreno suave)"
    elif pendiente_cuenca < 20:
        ip = "media (terreno ondulado)"
    elif pendiente_cuenca < 35:
        ip = "alta (terreno montañoso)"
    else:
        ip = "muy alta (terreno escarpado)"
    if tc_min is None:
        itc = ""
    elif tc_min < 30:
        itc = "respuesta muy rápida (crecidas súbitas)"
    elif tc_min < 90:
        itc = "respuesta rápida"
    elif tc_min < 240:
        itc = "respuesta media"
    else:
        itc = "respuesta lenta (crecidas atenuadas)"
    idd = _interp_dd(Dd)

    return AnalisisMorfologico(
        area_km2=round(A, 3), perimetro_km=round(P, 3),
        long_cauce_km=round(L, 3), long_axial_km=round(Lb, 3),
        ancho_medio_km=round(W, 3),
        cota_mayor_m=round(hmax, 1), cota_menor_m=round(hmin, 1),
        cota_media_m=round(hmean, 1), desnivel_m=round(desnivel, 1),
        pendiente_cuenca_pct=round(pendiente_cuenca, 2),
        pendiente_cauce_pct=round(pendiente_cauce, 2),
        kc_gravelius=round(kc, 3), ff_horton=round(ff, 3),
        re_elongacion=round(re, 3), rc_circularidad=round(rc, 3),
        rect_lado_mayor_km=round(rect_mayor, 3),
        rect_lado_menor_km=round(rect_menor, 3),
        coef_masividad=round(coef_masividad, 3),
        densidad_drenaje_km_km2=round(Dd, 3),
        pendiente_cuenca_grados=round(pendiente_grados, 2),
        long_cauce_principal_km=round(long_principal, 3),
        frecuencia_corrientes=round(F, 3),
        textura_drenaje=round(T, 3),
        intensidad_drenaje=round(ID, 3),
        numero_rugosidad=round(Rn, 3),
        orden_max=orden_max, relacion_bifurcacion=round(rb, 2),
        sinuosidad=round(sinuosidad, 3),
        long_recta_cauce_km=round(float(red.get("recta_km") or 0.0), 3),
        sinuosidad_inconsistente=bool(red.get("sinuosidad_inconsistente")),
        n_corrientes=n_total, n_por_orden=n_por_orden,
        retencion_s_mm=round(S_ret, 1), cn=round(cn, 1),
        interp_pendiente=ip, interp_tc=itc, interp_dd=idd,
        integral_hipsometrica=round(HI, 3), estado_cuenca=estado,
        hipso_area_pct=area_pct, hipso_altura_rel=altura_rel,
        bandas_elevacion=bandas_elev, bandas_pendiente=bandas_pend,
        clase_forma=clase,
    )
