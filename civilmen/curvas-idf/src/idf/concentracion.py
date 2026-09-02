"""Tiempo de concentración por múltiples fórmulas empíricas.

Cada fórmula devuelve el tiempo de concentración (Tc) en minutos. Los parámetros
provienen de la morfología de la cuenca:
    A : área [km²]
    L : longitud del cauce principal [km]
    S : pendiente media del cauce [m/m]
    H : desnivel total [m]

El Tc adoptado se obtiene como promedio de las fórmulas, descartando valores
atípicos por el criterio de Tukey (rango intercuartil, IQR).

Referencias: Chow et al. (1994); Témez (1978); SCS; Villón (2002).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .morfologia import MorfologiaCuenca


@dataclass
class ResultadoTc:
    nombre: str
    tc_min: float
    formula: str
    aplicable: bool = True
    nota: str = ""
    clave: str = ""

    @property
    def tc_horas(self) -> float:
        return self.tc_min / 60.0


# --- Fórmulas (cada una devuelve Tc en minutos) -----------------------------

def _kirpich(A, L, S, H, CN=None) -> float:
    # Tc(min) = 0.0195 · L_m^0.77 · S^-0.385   (L en metros, S en m/m)
    L_m = L * 1000.0
    return 0.0195 * L_m ** 0.77 * S ** (-0.385)


def _temez(A, L, S, H, CN=None) -> float:
    # Tc(h) = 0.3 · (L / S^0.25)^0.76   (L en km, S en m/m)
    return 0.3 * (L / S ** 0.25) ** 0.76 * 60.0


def _california(A, L, S, H, CN=None) -> float:
    # California Culverts Practice: Tc(h) = 0.95 · (L³ / H)^0.385  (L en km, H en m)
    return 0.95 * (L ** 3 / H) ** 0.385 * 60.0


def _giandotti(A, L, S, H, CN=None) -> float:
    # Tc(h) = (4·√A + 1.5·L) / (0.8·√H)   (A en km², L en km, H en m)
    return (4.0 * np.sqrt(A) + 1.5 * L) / (0.8 * np.sqrt(H)) * 60.0


def _ventura(A, L, S, H, CN=None) -> float:
    # Tc(h) = 0.127 · √(A / S)   (A en km², S en m/m)
    return 0.127 * np.sqrt(A / S) * 60.0


def _passini(A, L, S, H, CN=None) -> float:
    # Tc(h) = 0.108 · (A·L)^(1/3) / √S   (A en km², L en km, S en m/m)
    return 0.108 * (A * L) ** (1.0 / 3.0) / np.sqrt(S) * 60.0


def _bransby_williams(A, L, S, H, CN=None) -> float:
    # Tc(h) = 0.2426 · L · A^-0.1 · S^-0.2   (L en km, A en km², S en m/m)
    return 0.2426 * L * A ** (-0.1) * S ** (-0.2) * 60.0


def _scs_lag(A, L, S, H, CN) -> float:
    # SCS (Mockus): Tc = Lag/0.6; Lag(h)=L_ft^0.8·(Sret+1)^0.7/(1900·Y^0.5)
    # con Sret = 1000/CN − 10, Y = pendiente en %.
    if CN is None or CN <= 0:
        raise ValueError("SCS requiere CN")
    L_ft = L * 3280.84
    Sret = 1000.0 / CN - 10.0
    Y = S * 100.0  # pendiente en %
    lag_h = (L_ft ** 0.8) * ((Sret + 1.0) ** 0.7) / (1900.0 * Y ** 0.5)
    return (lag_h / 0.6) * 60.0


# (nombre, clave, expresión, función, usa_CN)
_FORMULAS: tuple[tuple[str, str, str, Callable, bool], ...] = (
    ("Kirpich (1940)",        "kirpich",   "0.0195·L_m^0.77·S^-0.385",  _kirpich, False),
    ("Témez (1978)",          "temez",     "0.3·(L/S^0.25)^0.76",       _temez, False),
    ("California C.P. (1942)", "california","0.95·(L³/H)^0.385",         _california, False),
    ("Giandotti (1934)",      "giandotti", "(4√A+1.5L)/(0.8√H)",        _giandotti, False),
    ("Ventura-Heras",         "ventura",   "0.127·√(A/S)",              _ventura, False),
    ("Passini",               "passini",   "0.108·(A·L)^(1/3)/√S",      _passini, False),
    ("Bransby-Williams",      "bransby",   "0.2426·L·A^-0.1·S^-0.2",    _bransby_williams, False),
    ("SCS Lag (Mockus)",      "scs",       "Lag/0.6; Lag=L^0.8(Sret+1)^0.7/(1900√Y)", _scs_lag, True),
)


def calcular_todas(morf: MorfologiaCuenca) -> list[ResultadoTc]:
    """Calcula Tc con todas las fórmulas para la morfología dada."""
    A, L, S, H, CN = (morf.area_km2, morf.long_cauce_km, morf.pendiente_media_mm,
                      morf.desnivel_m, morf.cn)
    resultados: list[ResultadoTc] = []
    for nombre, clave, expr, fn, usa_cn in _FORMULAS:
        try:
            tc = float(fn(A, L, S, H, CN))
            if not np.isfinite(tc) or tc <= 0:
                resultados.append(ResultadoTc(nombre, float("nan"), expr, False, "No aplicable", clave))
            else:
                resultados.append(ResultadoTc(nombre, round(tc, 2), expr, True, "", clave))
        except Exception as e:  # pragma: no cover
            resultados.append(ResultadoTc(nombre, float("nan"), expr, False, str(e), clave))
    return resultados


@dataclass
class TcAdoptado:
    tc_min: float
    tc_horas: float
    metodo: str
    usadas: list[str]
    descartadas: list[str]
    n_usadas: int
    # Diagnóstico del procedimiento por pasos
    clase_area: str = ""
    clase_pendiente: str = ""
    cn_disponible: bool = False
    cv_pct: float = 0.0
    regla_cv: str = ""
    ff_horton: float = 0.0
    kc_gravelius: float = 0.0
    clase_forma: str = ""
    regla_forma: str = ""
    regla_conservadorismo: str = ""
    # Frase única que nombra el criterio que produjo tc_min, para que el
    # informe no pueda describirlo de dos maneras distintas.
    criterio_final: str = ""
    tc_min_val: float = 0.0
    tc_promedio: float = 0.0
    tc_mediana: float = 0.0
    tc_max_val: float = 0.0


# Métodos recomendados por clase de área y de pendiente (claves de _FORMULAS).
def _metodos_por_area(A: float) -> tuple[str, set]:
    if A < 100:
        return ("Microcuenca (A < 100 km²)",
                {"kirpich", "california", "scs", "temez", "passini"})
    if A < 700:
        return ("Subcuenca (100–700 km²)",
                {"temez", "passini", "giandotti", "scs"})
    return "Cuenca (A > 700 km²)", {"giandotti", "temez"}


def _metodos_por_pendiente(S_pct: float) -> tuple[str, set]:
    if S_pct > 10:
        return "Torrencial/andina (S > 10%)", {"kirpich", "california"}
    if S_pct >= 3:
        return "Moderada (3–10%)", {"temez", "kirpich", "scs"}
    return "Suave/llanura (S < 3%)", {"bransby", "giandotti", "passini"}


_CONSERVADORISMO = {
    # tipo de obra -> (regla, criterio)  criterio ∈ {"min","prom","max"}
    "drenaje_vial_menor": ("Alcantarillas/cunetas → Tc mínimo (hidrograma más agresivo)", "min"),
    "carretera_puente":   ("Carreteras/puentes → Tc representativo (paso 4)", "prom"),
    "presa_proyecto":     ("Presas/embalses → Tc promedio o mediano", "prom"),
    "presa_extremo":      ("Presas/embalses → Tc promedio o mediano", "prom"),
    "drenaje_urbano_cc":  ("Inundación/planificación → Tc máximo (escenario conservador)", "max"),
}


def adoptar_tc(resultados, morfologia, tipo_obra_clave: str = "carretera_puente",
               cn_disponible: bool = False) -> TcAdoptado:
    """Adopta Tc por procedimiento de 5 pasos (área, pendiente, CN, CV, obra)
    con validación de forma (Horton Ff, Gravelius Kc)."""
    A = morfologia.area_km2
    S_pct = morfologia.pendiente_pct

    # Paso 1 y 2: métodos por área y por pendiente
    clase_area, met_area = _metodos_por_area(A)
    clase_pend, met_pend = _metodos_por_pendiente(S_pct)
    aplicables = set(met_area) | set(met_pend)

    # Paso 3: CN. Si no hay CN verificado, descartar SCS.
    if not cn_disponible:
        aplicables.discard("scs")

    por_clave = {r.clave: r for r in resultados if r.aplicable and np.isfinite(r.tc_min)}
    seleccion = {k: por_clave[k] for k in aplicables if k in por_clave}
    if not seleccion:  # respaldo: usar todas las aplicables
        seleccion = por_clave

    # Validación de forma (Horton/Gravelius): descartar sobre/subestimaciones.
    ff, kc, clase_forma = morfologia.ff_horton, morfologia.kc_gravelius, morfologia.clase_forma
    regla_forma = "Sin descarte por forma (cuenca intermedia)."
    if seleccion and ("circular" in clase_forma):
        # circular -> Tc cortos: descartar el método que más sobreestima (máx)
        peor = max(seleccion.values(), key=lambda r: r.tc_min)
        if len(seleccion) > 1:
            del seleccion[peor.clave]
            regla_forma = f"Cuenca circular: se descarta {peor.nombre} (sobreestima Tc)."
    elif seleccion and ("elongada" in clase_forma):
        peor = min(seleccion.values(), key=lambda r: r.tc_min)
        if len(seleccion) > 1:
            del seleccion[peor.clave]
            regla_forma = f"Cuenca elongada: se descarta {peor.nombre} (subestima Tc)."

    valores = np.array([r.tc_min for r in seleccion.values()], dtype=float)
    usadas = [r.nombre for r in seleccion.values()]
    descartadas = [r.nombre for r in resultados
                   if r.aplicable and r.nombre not in usadas]

    tc_prom = float(np.mean(valores))
    tc_med = float(np.median(valores))
    tc_minv = float(np.min(valores))
    tc_maxv = float(np.max(valores))
    cv = float(np.std(valores, ddof=1) / tc_prom * 100.0) if len(valores) > 1 and tc_prom else 0.0

    # Paso 4: criterio según CV.
    # IMPORTANTE: el método "regional" de respaldo debe buscarse SOLO entre los
    # que siguen en `seleccion`. Antes se tomaba de `por_clave` (todos los
    # aplicables), de modo que un método ya descartado por la regla de forma
    # podía volver a entrar como criterio de adopción: el informe llegaba a
    # descartar Témez por la forma de la cuenca y, dos líneas después,
    # adoptarlo como método regional. Esa contradicción queda eliminada.
    temez = seleccion.get("temez")
    giandotti = seleccion.get("giandotti")
    regional = temez or giandotti
    if cv < 20:
        tc_base = tc_prom
        regla_cv = f"CV = {cv:.1f}% < 20% → se adopta el promedio aritmético."
    elif cv <= 40:
        tc_base = regional.tc_min if regional else tc_prom
        regla_cv = (f"CV = {cv:.1f}% (20–40%) → mejor ajuste regional altoandino "
                    f"({regional.nombre if regional else 'promedio'}; USFX-PUCP recomiendan Témez).")
    else:
        tc_base = regional.tc_min if regional else tc_med
        regla_cv = (f"CV = {cv:.1f}% > 40% → revisar morfología/DEM. Se adopta el método "
                    f"regional ({regional.nombre if regional else 'mediana'}) provisionalmente.")

    # Paso 5: conservadorismo según tipo de obra.
    regla_cons, criterio = _CONSERVADORISMO.get(
        tipo_obra_clave, ("Tc representativo (paso 4)", "prom"))
    if criterio == "min":
        tc_final = tc_minv
        criterio_final = (f"mínimo del conjunto depurado "
                          f"({tc_minv:.1f} min), por el tipo de obra")
    elif criterio == "max":
        tc_final = tc_maxv
        criterio_final = (f"máximo del conjunto depurado "
                          f"({tc_maxv:.1f} min), escenario conservador por el "
                          f"tipo de obra")
    else:
        tc_final = tc_base
        # `tc_base` puede ser el promedio, la mediana o un método regional
        # concreto, según el CV. Se nombra el que efectivamente se usó para que
        # el informe no pueda describir el criterio de dos maneras distintas.
        if abs(tc_base - tc_prom) < 1e-6:
            criterio_final = (f"promedio aritmético de las {len(usadas)} "
                              f"fórmulas depuradas ({tc_prom:.1f} min)")
        elif abs(tc_base - tc_med) < 1e-6:
            criterio_final = (f"mediana de las {len(usadas)} fórmulas "
                              f"depuradas ({tc_med:.1f} min)")
        elif regional is not None and abs(tc_base - regional.tc_min) < 1e-6:
            criterio_final = (f"método regional {regional.nombre} "
                              f"({regional.tc_min:.1f} min), por dispersión "
                              f"entre fórmulas (CV = {cv:.1f} %)")
        else:
            criterio_final = f"valor representativo del paso 4 ({tc_base:.1f} min)"

    return TcAdoptado(
        tc_min=round(tc_final, 2), tc_horas=round(tc_final / 60.0, 3),
        metodo="Procedimiento de 5 pasos (área, pendiente, CN, CV, tipo de obra)",
        usadas=usadas, descartadas=descartadas, n_usadas=len(usadas),
        clase_area=clase_area, clase_pendiente=clase_pend, cn_disponible=cn_disponible,
        cv_pct=round(cv, 1), regla_cv=regla_cv,
        ff_horton=round(ff, 3), kc_gravelius=round(kc, 3), clase_forma=clase_forma,
        regla_forma=regla_forma, regla_conservadorismo=regla_cons,
        tc_min_val=round(tc_minv, 1), tc_promedio=round(tc_prom, 1),
        tc_mediana=round(tc_med, 1), tc_max_val=round(tc_maxv, 1),
        criterio_final=criterio_final,
    )
