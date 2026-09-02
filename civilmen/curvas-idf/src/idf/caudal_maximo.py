"""Cálculo de caudal máximo Q(T) por cinco métodos clásicos.

Cada método toma los parámetros morfológicos reales de la cuenca (área, Lc,
pendiente, CN ponderado, C ponderado, Tc) y las precipitaciones P24(T) /
intensidades i(t=Tc, T) calculadas en las secciones 5 y 8 del informe, y
devuelve el caudal máximo Q en m³/s para cada período de retorno T.

Métodos:

1. **Racional** (clásico): Q = C·i·A/3.6, con i = intensidad media de la
   IDF para duración t = Tc (mm/h), C = coef. escorrentía ponderado, A en km².

2. **Racional Modificado (Témez)**: Q = K·C·i·A/3.6 con K = factor de
   uniformidad = 1 + Tc^1.25 / (Tc^1.25 + 14). Tc en horas. Recomendado en
   cuencas medianas (A > 1 km²).

3. **Mac Math**: Q = 0.0091·C·P_d·A^0.58·S^0.42 con P_d = lluvia diaria
   máxima en mm, A en hectáreas, S pendiente media de la cuenca en %.
   Empírico para cuencas rurales pequeñas (común en Bolivia/Perú).

4. **SCS Hidrograma Triangular**: Q_p = 0.208·A·P_e/Tp, con Pe = lluvia
   efectiva por SCS (P-Ia)²/(P-Ia+S_ret), S_ret = 25400/CN−254, Ia = 0.2·S,
   Tp = D/2 + 0.6·Tc (D ≈ Tc). A en km², Pe en mm, Tp en h.

5. **Verni-King modificado** (cuencas andinas, Bolivia/Perú):
   Q = 0.00618·P_d^1.24·A^0.88 (P_d en mm, A en km²). Empírico.

Todos los métodos devuelven Q en m³/s. La tabla final se construye en el
report (§11) con una columna por método y una fila por T.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


PERIODOS_QMAX_DEFAULT = (5, 10, 25, 50, 100, 500, 1000, 5000, 10000)


@dataclass
class EntradaQMax:
    """Parámetros morfológicos e hidrológicos compartidos por todos los métodos."""
    A_km2: float          # área de la cuenca
    L_km: float           # longitud del cauce principal (D8)
    S_pct: float          # pendiente media de la cuenca (%)
    Sc_pct: float         # pendiente del cauce (%)
    Tc_min: float         # tiempo de concentración adoptado (min)
    CN: float             # número de curva ponderado (SCS)
    C: float              # coeficiente de escorrentía racional ponderado

    @property
    def Tc_h(self) -> float:
        return self.Tc_min / 60.0


def _intensidad(modelo, T: float, d_min: float) -> float:
    """Evalúa intensidad i (mm/h) para período T y duración d en minutos."""
    return float(modelo.intensidad(T, d_min))


def q_racional(e: EntradaQMax, i_mm_h: float) -> float:
    """Q = C·i·A/3.6 (m³/s; A en km², i en mm/h)."""
    return e.C * i_mm_h * e.A_km2 / 3.6


def q_racional_modificado(e: EntradaQMax, i_mm_h: float) -> float:
    """Témez: K·C·i·A/3.6 con K = 1 + Tc^1.25/(Tc^1.25+14), Tc en h."""
    K = 1.0 + (e.Tc_h ** 1.25) / ((e.Tc_h ** 1.25) + 14.0)
    return K * e.C * i_mm_h * e.A_km2 / 3.6


def q_mac_math(e: EntradaQMax, P24_mm: float) -> float:
    """Q = 0.0091·C·P_d·A^0.58·S^0.42 (A en HECTÁREAS, S en %)."""
    A_ha = e.A_km2 * 100.0
    S = max(e.S_pct, 0.01)
    return 0.0091 * e.C * P24_mm * (A_ha ** 0.58) * (S ** 0.42)


def q_scs_triangular(e: EntradaQMax, P24_mm: float) -> float:
    """SCS HU triangular: Qp = 0.208·A·Pe/Tp (A km², Pe mm, Tp h)."""
    CN = max(min(e.CN, 99.0), 30.0)
    S_ret = 25400.0 / CN - 254.0       # mm
    Ia = 0.2 * S_ret
    if P24_mm <= Ia:
        return 0.0
    Pe = (P24_mm - Ia) ** 2 / (P24_mm - Ia + S_ret)
    # Duración de la tormenta D ≈ Tc; tiempo al pico Tp = D/2 + 0.6·Tc.
    Tp_h = e.Tc_h / 2.0 + 0.6 * e.Tc_h
    return 0.208 * e.A_km2 * Pe / Tp_h


def q_verni_king(e: EntradaQMax, P24_mm: float) -> float:
    """Verni-King modificado: Q = 0.00618·P_d^1.24·A^0.88 (cuencas andinas)."""
    return 0.00618 * (P24_mm ** 1.24) * (e.A_km2 ** 0.88)


METODOS = [
    ("Racional",                "Q = C·i·A/3.6",                 "intensidad"),
    ("Racional Modificado (Témez)", "K·C·i·A/3.6  ;  K=1+Tc¹·²⁵/(Tc¹·²⁵+14)", "intensidad"),
    ("Mac Math",                "Q = 0.0091·C·Pd·A⁰·⁵⁸·S⁰·⁴²",   "p24"),
    ("SCS HU Triangular",       "Qp = 0.208·A·Pe/Tp",            "p24"),
    ("Verni-King",              "Q = 0.00618·Pd¹·²⁴·A⁰·⁸⁸",      "p24"),
]

# Rango de aplicabilidad por ÁREA de cuenca (km²) de cada método. Fuera de
# este rango el método sobreestima/subestima y NO se incluye en los
# agregados (Q medio / mediana / máx). El Racional clásico y Mac Math son
# para cuencas PEQUEÑAS; aplicarlos a cuencas medianas inflaba el Q hasta
# 4-10 m³/s/km² (caudal específico irreal). Límites de la literatura:
#   - Racional clásico: válido hasta ~25 km² (Chow; muchas guías ≤ 13 km²).
#   - Mac Math: empírico para cuencas rurales pequeñas, ≤ 10 km².
#   - Témez (racional modificado): hasta ~3000 km².
#   - SCS HU triangular: hasta ~250 km².
#   - Verni-King: regional andino, 1–1000 km².
# Límites validados con el skill «estudio-hidrologico-bolivia»
# (references/lluvia-escorrentia.md):
#   - «Método racional SÓLO cuencas pequeñas (A < 5 km²) y homogéneas».
#   - «5 ≤ A < 100 km²: SCS-CN + hidrograma unitario SCS».
#   - «A ≥ 100 km²: HEC-HMS».
#   - Mac Math: empírico rural pequeño (≤ 10 km²).
#   - Témez (racional modificado): hasta cuencas grandes.
#   - Verni-King: regional andino.
APLICABILIDAD_AREA_KM2 = {
    "Q_racional":     (0.0, 5.0),
    "Q_racional_mod": (1.0, 3000.0),
    "Q_mac_math":     (0.0, 10.0),
    "Q_scs":          (0.0, 250.0),
    "Q_verni_king":   (1.0, 1000.0),
}

# Gate ADICIONAL por TIEMPO DE CONCENTRACIÓN (h). El criterio rector de la
# norma 5.2-IC (España) y del manual ABC (Bolivia) para los métodos basados
# en la intensidad de la IDF NO es el área sino el Tc: el método Racional
# evalúa i para duración d = Tc bajo hipótesis de lluvia uniforme durante Tc,
# que deja de ser válida en tormentas largas. 5.2-IC: Racional clásico
# aplicable con Tc ≤ 6 h; Témez (racional modificado) válido para
# 0.25 h ≤ Tc ≤ 24 h. Los métodos basados en P24 (Mac Math, SCS HU,
# Verni-King) no tienen gate normativo de Tc → None.
# Corroboración documental: docs/validacion_metodologica_HYDROFRA.md (Eje 2).
APLICABILIDAD_TC_H = {
    "Q_racional":     (0.0, 6.0),
    "Q_racional_mod": (0.25, 24.0),
    "Q_mac_math":     None,
    "Q_scs":          None,
    "Q_verni_king":   None,
}


def metodos_aplicables(A_km2: float, Tc_h: float | None = None) -> list[str]:
    """Columnas Q_* aplicables para el área (y, si se da, el Tc) de la cuenca.

    Aplica dos compuertas:
      1. Rango de ÁREA de validez de cada método (APLICABILIDAD_AREA_KM2).
      2. Rango de TIEMPO DE CONCENTRACIÓN (APLICABILIDAD_TC_H) — criterio
         rector de la norma 5.2-IC/ABC para los métodos basados en la
         intensidad (Racional/Témez). Solo se aplica si se pasa `Tc_h`.
    Un método se incluye solo si cumple AMBAS.
    """
    out = []
    for k, (lo, hi) in APLICABILIDAD_AREA_KM2.items():
        if not (lo <= A_km2 <= hi):
            continue
        if Tc_h is not None:
            rango_tc = APLICABILIDAD_TC_H.get(k)
            if rango_tc is not None:
                tlo, thi = rango_tc
                if not (tlo <= Tc_h <= thi):
                    continue
        out.append(k)
    return out


def tabla_caudal_maximo(entrada: EntradaQMax, modelo_idf,
                         p24_por_T: dict[int, float],
                         periodos: tuple = PERIODOS_QMAX_DEFAULT) -> pd.DataFrame:
    """Devuelve un DataFrame con columnas T, P24, i_Tc, Q por cada método.

    Los agregados (Q_medio / Q_mediana / Q_max) se calculan SOLO sobre los
    métodos APLICABLES al área de la cuenca (ver APLICABILIDAD_AREA_KM2),
    para no sesgar el caudal de diseño con métodos fuera de su rango de
    validez (p. ej. Mac Math o Racional clásico en cuencas medianas, que
    inflaban el caudal específico a valores irreales).

    `modelo_idf` se evalúa para duración t = Tc; `p24_por_T` ya tiene los
    cuantiles de P24 calculados con el mejor ajuste (estación + satelital).
    El DataFrame lleva en `.attrs` la lista de métodos aplicados y los
    excluidos por área.
    """
    aplic = metodos_aplicables(entrada.A_km2, entrada.Tc_h)
    if not aplic:                      # cuenca fuera de todo rango → usar todos
        aplic = list(APLICABILIDAD_AREA_KM2.keys())
    filas = []
    for T in periodos:
        P = float(p24_por_T[T])
        i = _intensidad(modelo_idf, T, entrada.Tc_min)
        fila = {"T_anios": int(T), "P24_mm": round(P, 2),
                "i_Tc_mm_h": round(i, 2)}
        fila["Q_racional"]      = round(q_racional(entrada, i), 2)
        fila["Q_racional_mod"]  = round(q_racional_modificado(entrada, i), 2)
        fila["Q_mac_math"]      = round(q_mac_math(entrada, P), 2)
        fila["Q_scs"]           = round(q_scs_triangular(entrada, P), 2)
        fila["Q_verni_king"]    = round(q_verni_king(entrada, P), 2)
        # Agregados SOLO sobre métodos aplicables al área.
        q_aplic = [fila[k] for k in aplic]
        fila["Q_medio"]   = round(float(np.mean(q_aplic)), 2)
        fila["Q_mediana"] = round(float(np.median(q_aplic)), 2)
        fila["Q_max"]     = round(float(np.max(q_aplic)), 2)
        filas.append(fila)
    df = pd.DataFrame(filas)
    excluidos = [k for k in APLICABILIDAD_AREA_KM2 if k not in aplic]
    df.attrs["metodos_aplicables"] = aplic
    df.attrs["metodos_excluidos"] = excluidos
    df.attrs["area_km2"] = entrada.A_km2
    df.attrs["tc_h"] = round(entrada.Tc_h, 3)
    # Para trazabilidad en el informe: qué excluyó el área y qué el Tc.
    solo_area = metodos_aplicables(entrada.A_km2)
    df.attrs["excluidos_por_tc"] = [k for k in solo_area if k not in aplic]
    return df
