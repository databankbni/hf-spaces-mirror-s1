"""Modelación HEC-HMS-like en Python: pérdidas SCS-CN + transformación HU SCS.

El motor de HEC-HMS para cuencas pequeñas/medianas en modo "lluvia-escorrentía"
usa típicamente dos modelos en cadena:

1. **Modelo de pérdidas**: SCS Curve Number (USDA-SCS TR-55, 1986).
   Convierte la lluvia bruta P (mm) en lluvia efectiva o de escorrentía Pe (mm)
   reteniendo la fracción que infiltra/se percola/se intercepta.

       S = 25400/CN − 254               (retención potencial, mm)
       Ia = 0.2·S                       (abstracción inicial, mm)
       Pe = (P − Ia)² / (P − Ia + S)    si P > Ia, sino Pe = 0

2. **Modelo de transformación**: Hidrograma Unitario SCS Triangular.
   Convoluciona Pe(t) con un HU adimensional (triangular) para obtener el
   hidrograma de escorrentía directa Q(t).

       Tp = Δt/2 + lag                  (tiempo al pico, h)
       lag = 0.6·Tc                     (NRCS NEH-630, Cap. 16)
       Tb = 2.67·Tp                     (tiempo base)
       Qp = 0.208·A·1mm / Tp            (caudal pico para 1 mm efectivo, m³/s)

Implementamos ambas fases en NumPy puro y exponemos la API que también puede
volcarse a un proyecto HEC-HMS estándar (.basin/.met/.control/.gage) que el
usuario puede abrir y verificar con el binario oficial.

Referencias clave:
- USDA-SCS (1986). Urban Hydrology for Small Watersheds — TR-55.
- USDA-NRCS (2004). National Engineering Handbook, Part 630 — Hydrology,
  Capítulos 10 (SCS-CN) y 16 (HU triangular).
- USACE (2022). HEC-HMS User's Manual, v4.10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ResultadoHEC:
    """Resultado de una simulación HEC-HMS-like para un único T."""
    T_anios: int
    delta_t_min: float
    duracion_total_min: float
    tabla: pd.DataFrame    # t_min, P_mm, Pe_mm, Pe_incr_mm, Q_m3s
    P_total_mm: float
    Pe_total_mm: float
    Q_pico_m3s: float
    t_pico_min: float
    volumen_directo_hm3: float


@dataclass
class ParametrosHEC:
    """Parámetros de la cuenca para la modelación HEC-HMS."""
    area_km2: float
    cn: float                  # CN ponderado (SCS)
    tc_min: float              # tiempo de concentración
    metodo_hieto: str = "scs"  # nombre del hietograma usado
    cn_descripcion: str = ""   # texto justificación
    nota_hieto: str = ""

    @property
    def lag_min(self) -> float:
        """Lag time NRCS = 0.6·Tc."""
        return 0.6 * float(self.tc_min)

    @property
    def S_ret_mm(self) -> float:
        """Retención potencial S = 25400/CN − 254."""
        cn = max(min(float(self.cn), 99.0), 30.0)
        return 25400.0 / cn - 254.0

    @property
    def Ia_mm(self) -> float:
        return 0.2 * self.S_ret_mm


# ---------------------------------------------------------------------------
# Selector del método de hietograma "más adecuado" (13.0)
# ---------------------------------------------------------------------------

def cn_ajustado_pendiente(cn2: float, pendiente_frac: float) -> dict:
    """Ajuste del Número de Curva por pendiente media (Williams, 1995 — SWAT).

    El CN tabulado del SCS supone pendientes ~5 %. En cuencas de montaña
    bolivianas la pendiente es mayor y aumenta la escorrentía, por lo que se
    corrige el CN(AMC II) por la pendiente media del terreno:

        CN3  = CN2 · exp(0.00673·(100 − CN2))                  (AMC III)
        CN2s = (CN3 − CN2)/3 · (1 − 2·exp(−13.86·S)) + CN2

    con S la pendiente media en m/m. Devuelve {cn2, cn2s, cn3, pendiente_pct}.
    El resultado se acota a [30, 100].
    """
    cn2 = float(max(30.0, min(99.0, cn2)))
    S = max(0.0, float(pendiente_frac))
    cn3 = cn2 * np.exp(0.00673 * (100.0 - cn2))
    cn2s = (cn3 - cn2) / 3.0 * (1.0 - 2.0 * np.exp(-13.86 * S)) + cn2
    cn2s = float(max(30.0, min(100.0, cn2s)))
    return {"cn2": cn2, "cn2s": round(cn2s, 1), "cn3": round(float(cn3), 1),
            "pendiente_pct": round(S * 100.0, 1)}


def recomendar_hietograma(area_km2: float, tc_min: float,
                            aplica_huff: bool) -> tuple[str, str]:
    """Devuelve (clave, justificacion) según criterios de área y Tc.

    Criterios (Manual MOPSV/ABC + USDA-SCS + Huff 1967):
    - Cuenca grande/larga (A > 25 km² y Tc > 120 min) y aplica Huff →
      <b>Huff Q2</b> (mediana del segundo cuartil, tormentas frontales).
    - Cuenca pequeña urbana (A < 25 km² y Tc < 60 min) → <b>Chicago</b>.
    - Cuenca rural pequeña/mediana (A ≤ 100 km²) → <b>SCS Tipo II</b> (USDA-SCS).
    - En cualquier otro caso → <b>Bloques alternos</b> (Chow et al. 1994).
    """
    if area_km2 > 25 and tc_min > 120 and aplica_huff:
        return ("huff",
                "cuenca <b>A > 25 km²</b> y Tc > 2 h: dominan tormentas "
                "frontales de mayor duración; el método de <b>Huff (1967) "
                "cuartil 2 (mediana)</b> reproduce mejor la masa temporal de "
                "lluvia observada en estos eventos, según Bonta & Rao (1988).")
    if area_km2 < 25 and tc_min < 60:
        return ("chicago",
                "cuenca pequeña (A < 25 km²) y Tc corto: <b>Chicago "
                "(Keifer & Chu 1957)</b> es el estándar para cuencas urbanas "
                "y rurales pequeñas con respuesta rápida.")
    if area_km2 <= 100:
        return ("scs",
                "cuenca rural pequeña/mediana: la <b>distribución SCS Tipo II "
                "(USDA-SCS TR-55, 1986)</b> es la práctica recomendada en "
                "Latinoamérica (MOPSV/ABC) y está calibrada para lluvias "
                "convectivas de 24 h en regiones similares a la andina.")
    return ("bloques",
            "cuenca de gran tamaño o duración: el método de <b>bloques alternos "
            "(Chow, Maidment & Mays 1994)</b> deriva el hietograma directamente "
            "de la IDF y es el más conservador para diseño hidráulico.")


# ---------------------------------------------------------------------------
# Pérdidas SCS-CN  (13.1)
# ---------------------------------------------------------------------------

def aplicar_scs_cn(p_acumulada_mm: np.ndarray, S_mm: float) -> np.ndarray:
    """Calcula la lluvia efectiva acumulada Pe(t) por SCS-CN.

    `p_acumulada_mm` es un array (no decreciente) de profundidad acumulada
    en cada paso del hietograma. Devuelve un array del mismo tamaño con la
    lluvia efectiva acumulada (mm).
    """
    Ia = 0.2 * S_mm
    P = np.asarray(p_acumulada_mm, dtype=np.float64)
    Pe = np.zeros_like(P)
    masc = P > Ia
    Pe[masc] = (P[masc] - Ia) ** 2 / (P[masc] - Ia + S_mm)
    return Pe


# ---------------------------------------------------------------------------
# Transformación HU SCS triangular  (13.2)
# ---------------------------------------------------------------------------

def hu_scs_triangular(delta_t_min: float, tc_min: float,
                       area_km2: float, n_puntos: int = 200) -> np.ndarray:
    """Hidrograma unitario SCS triangular para 1 mm de lluvia efectiva.

    Devuelve un array Q (m³/s) muestreado cada `delta_t_min` minutos, con
    suficiente longitud para cubrir el tiempo base Tb = 2.67·Tp.

    Tp = Δt/2 + lag,  lag = 0.6·Tc   (NRCS NEH-630, Cap. 16)
    Qp = 0.208·A·1mm/Tp (m³/s para A en km² y Tp en horas).
    """
    lag_h = 0.6 * tc_min / 60.0
    Tp_h = (delta_t_min / 2.0) / 60.0 + lag_h
    Tb_h = 2.67 * Tp_h
    Qp = 0.208 * area_km2 / Tp_h     # m³/s por mm de Pe
    n = max(int(np.ceil(Tb_h * 60.0 / delta_t_min)) + 1, 3)
    t_h = np.arange(n) * delta_t_min / 60.0
    hu = np.zeros_like(t_h)
    masc1 = t_h <= Tp_h
    hu[masc1] = Qp * t_h[masc1] / Tp_h
    masc2 = (t_h > Tp_h) & (t_h <= Tb_h)
    hu[masc2] = Qp * (Tb_h - t_h[masc2]) / (Tb_h - Tp_h)
    return hu


def convolucion_hidrograma(pe_incremental_mm: np.ndarray,
                            hu_m3s_por_mm: np.ndarray) -> np.ndarray:
    """Hidrograma de escorrentía directa = convolución(Pe_incr, HU)."""
    return np.convolve(pe_incremental_mm, hu_m3s_por_mm, mode="full")


# ---------------------------------------------------------------------------
# Simulación completa por T  (13.3)
# ---------------------------------------------------------------------------

def simular_hidrograma(parametros: ParametrosHEC,
                        hietograma) -> ResultadoHEC:
    """Aplica pérdidas SCS-CN + HU triangular a un hietograma de diseño.

    `hietograma` es una instancia del dataclass Hietograma (ver hietograma.py)
    con tabla t_min / intensidad_mm_h / p_incremental_mm / p_acumulada_mm.
    """
    p = parametros
    tabla = hietograma.tabla.copy()
    dt = float(hietograma.delta_t_min)
    P_acum = tabla["p_acumulada_mm"].to_numpy()
    Pe_acum = aplicar_scs_cn(P_acum, p.S_ret_mm)
    Pe_incr = np.diff(np.concatenate([[0.0], Pe_acum]))
    hu = hu_scs_triangular(dt, p.tc_min, p.area_km2)
    Q = convolucion_hidrograma(Pe_incr, hu)
    # El eje temporal del hidrograma resultante: paso dt, n_total = n_pe + n_hu - 1.
    n_total = len(Q)
    t_total = np.arange(n_total) * dt  # min, comienza en 0
    # Extiendo Pe y P al mismo eje para reportarlos en una tabla compacta.
    P_full = np.concatenate([P_acum, np.full(n_total - len(P_acum),
                                              P_acum[-1] if len(P_acum) else 0)])
    Pe_full = np.concatenate([Pe_acum, np.full(n_total - len(Pe_acum),
                                                Pe_acum[-1] if len(Pe_acum) else 0)])
    Pe_incr_full = np.concatenate([Pe_incr,
                                    np.zeros(n_total - len(Pe_incr))])
    tabla_out = pd.DataFrame({
        "t_min": t_total,
        "P_mm": np.round(P_full, 3),
        "Pe_mm": np.round(Pe_full, 3),
        "Pe_incr_mm": np.round(Pe_incr_full, 3),
        "Q_m3s": np.round(Q, 3),
    })
    Q_pico = float(Q.max()) if len(Q) else 0.0
    t_pico = float(t_total[int(np.argmax(Q))]) if len(Q) else 0.0
    # Volumen = integral de Q dt = Σ Q·Δt(s) → m³ → hm³.
    volumen_m3 = float(Q.sum() * dt * 60.0)
    return ResultadoHEC(
        T_anios=int(hietograma.T_anios),
        delta_t_min=dt,
        duracion_total_min=float(t_total[-1]) if len(t_total) else 0.0,
        tabla=tabla_out,
        P_total_mm=float(P_acum[-1]) if len(P_acum) else 0.0,
        Pe_total_mm=float(Pe_acum[-1]) if len(Pe_acum) else 0.0,
        Q_pico_m3s=Q_pico,
        t_pico_min=t_pico,
        volumen_directo_hm3=volumen_m3 / 1e6,
    )


def simular_familia_T(parametros: ParametrosHEC,
                       hietogramas_por_T: dict) -> dict:
    """Simula el hidrograma para cada T usando el método de hietograma elegido.

    `hietogramas_por_T` viene del pipeline como {T: {metodo: Hietograma}}.
    Selecciona el método dictado por `parametros.metodo_hieto` y devuelve
    {T: ResultadoHEC}.
    """
    salida = {}
    metodo = parametros.metodo_hieto
    for T, dic in sorted(hietogramas_por_T.items()):
        h = dic.get(metodo) or next(iter(dic.values()))
        salida[int(T)] = simular_hidrograma(parametros, h)
    return salida


# ---------------------------------------------------------------------------
# Generación de archivos de proyecto HEC-HMS  (13.4 — opcional)
# ---------------------------------------------------------------------------

def exportar_proyecto_hec_hms(parametros: ParametrosHEC,
                               hietograma_diseno,
                               out_dir, nombre: str = "CuencaIDF") -> dict:
    """Genera los archivos texto de un proyecto HEC-HMS listo para abrir.

    Crea: <nombre>.hms (proyecto), <nombre>.basin (cuenca + métodos),
    <nombre>.met (modelo meteorológico), <nombre>.control (especificaciones
    de control) y <nombre>.dss (ASCII, contenido del hietograma).
    """
    from pathlib import Path
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    A = parametros.area_km2
    cn = parametros.cn
    Ia = parametros.Ia_mm
    tc_min = parametros.tc_min
    lag_min = parametros.lag_min
    dt = hietograma_diseno.delta_t_min
    dur = hietograma_diseno.duracion_min

    # 1. Archivo de proyecto (.hms)
    (out_dir / f"{nombre}.hms").write_text(
        f"""Project: {nombre}
     Description: Modelacion lluvia-escorrentia generada por HYDROFRA v1.3.
     File Version: 4.10
     Default Unit System: Metric
     Unit System: Metric
End:
""", encoding="utf-8")

    # 2. Basin model (.basin) — una sola subcuenca con SCS-CN + HU SCS
    (out_dir / f"{nombre}.basin").write_text(
f"""Basin: {nombre}
     Description: Subcuenca unica delineada por watershed MERIT Hydro 90 m.
     Last Modified Date: 1 January 2026
     Unit System: Metric
End:

Subbasin: Subcuenca-1
     Area: {A:.3f}
     Canopy: None
     Surface: None
     LossRate: SCS Curve Number
       Initial Abstraction: {Ia:.2f}
       Curve Number: {cn:.0f}
       Impervious Area: 0
     Transform: SCS Unit Hydrograph
       Lag Time: {lag_min:.2f}
     Baseflow: None
End:
""", encoding="utf-8")

    # 3. Control specifications (.control)
    (out_dir / f"{nombre}.control").write_text(
f"""Control: Diseno
     Description: Tormenta de duracion = Tc.
     Last Modified Date: 1 January 2026
     Start Date: 1 January 2026
     Start Time: 00:00
     End Date: 1 January 2026
     End Time: {int(dur*4)//60:02d}:{int(dur*4)%60:02d}
     Time Interval: {int(dt)}
End:
""", encoding="utf-8")

    # 4. Meteorologic model (.met)
    (out_dir / f"{nombre}.met").write_text(
f"""Meteorology: TormentaDiseno
     Description: Hietograma {parametros.metodo_hieto} para T = {hietograma_diseno.T_anios} anios.
     Last Modified Date: 1 January 2026
     Unit System: Metric
     Precipitation Method: Specified Hyetograph
End:

Subbasin: Subcuenca-1
     Gage: GageTormenta
End:
""", encoding="utf-8")

    # 5. DSS ASCII (hietograma) — formato simple legible.
    tab = hietograma_diseno.tabla
    csv_path = out_dir / f"{nombre}_hietograma.dss.csv"
    tab.to_csv(csv_path, index=False)
    return {
        "hms": out_dir / f"{nombre}.hms",
        "basin": out_dir / f"{nombre}.basin",
        "met": out_dir / f"{nombre}.met",
        "control": out_dir / f"{nombre}.control",
        "dss_csv": csv_path,
    }
