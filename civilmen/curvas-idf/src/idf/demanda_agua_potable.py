"""Demanda de agua potable según NB 689 (Bolivia).

Implementa proyección poblacional (geométrico, aritmético, Wappäus) y
caudales de diseño (Q_md, Q_máx_d, Q_máx_h) con los coeficientes K1, K2
recomendados por la NB 689 según la categoría poblacional. También calcula
el caudal de captación adoptado según el período de diseño de la NB 689.

Las dotaciones orientativas (Tabla 11 del informe) están en
`pisos_ecologicos.PisoEcologico.dotacion_l_hab_dia_sugerida` y se cruzan
con el nivel de servicio (pileta pública / domiciliaria básica / plena).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ─── Constantes NB 689 ────────────────────────────────────────────────────

# Coeficientes K1 (máximo diario / medio diario) y K2 (máximo horario /
# máximo diario) recomendados por la NB 689 según categoría poblacional.
# Rangos típicos del reglamento; se adopta el valor recomendado para diseño.
K1_NB689 = 1.5    # Máximo diario
K2_NB689 = 2.2    # Máximo horario

# Período de diseño por categoría (NB 689). Categorías por población final:
# A: < 2 000 hab → 20 años; B: 2 000–10 000 → 20 años;
# C: 10 000–100 000 → 25 años; D: > 100 000 → 30 años.
HORIZONTE_NB689 = {
    "A": 20, "B": 20, "C": 25, "D": 30,
}


def categoria_nb689(poblacion_diseno: int) -> str:
    """Devuelve la categoría poblacional NB 689 (A/B/C/D)."""
    if poblacion_diseno < 2000:
        return "A"
    if poblacion_diseno < 10000:
        return "B"
    if poblacion_diseno < 100000:
        return "C"
    return "D"


# Ajuste de dotación por nivel de servicio. Se aplica sobre el rango
# sugerido por piso ecológico (mín/máx) para obtener el valor final.
AJUSTE_NIVEL_SERVICIO = {
    "pileta_publica":  0.55,   # 55 % del valor central del rango
    "domiciliaria_basica": 0.80,
    "domiciliaria_plena":  1.00,
}

NIVELES_SERVICIO_NB689 = {
    "pileta_publica": "Pileta pública (sin conexión domiciliaria)",
    "domiciliaria_basica": "Conexión domiciliaria con servicio básico",
    "domiciliaria_plena": "Conexión domiciliaria con servicio pleno",
}


# ─── Proyección poblacional ──────────────────────────────────────────────

MetodoProyeccion = Literal["geometrico", "aritmetico", "wappaus"]


@dataclass(frozen=True)
class ProyeccionPoblacional:
    poblacion_actual: int
    anio_base: int
    horizonte_anios: int
    tasa_crecimiento_pct: float
    metodo: MetodoProyeccion
    poblacion_diseno: int
    categoria_nb689: str


def proyectar_poblacion(poblacion_actual: int,
                          anio_base: int,
                          horizonte_anios: int,
                          tasa_crecimiento_pct: float,
                          metodo: MetodoProyeccion = "geometrico"
                          ) -> ProyeccionPoblacional:
    """Proyecta población por método clásico.

    - **Geométrico**: P_f = P_0 · (1 + r)^t (compuesto anual).
    - **Aritmético**: P_f = P_0 · (1 + r · t) (lineal).
    - **Wappäus**: P_f = P_0 · (200 + r·t) / (200 − r·t) (saturación
       asintótica). El r aquí se expresa en %/año.
    """
    t = int(horizonte_anios)
    r_pct = float(tasa_crecimiento_pct)
    if metodo == "geometrico":
        r = r_pct / 100.0
        pob = poblacion_actual * ((1 + r) ** t)
    elif metodo == "aritmetico":
        r = r_pct / 100.0
        pob = poblacion_actual * (1 + r * t)
    elif metodo == "wappaus":
        # Wappäus diverge si r·t ≥ 200; protegemos con cap suave.
        denom = max(200.0 - r_pct * t, 1.0)
        pob = poblacion_actual * (200.0 + r_pct * t) / denom
    else:
        raise ValueError(f"Método desconocido: {metodo}")
    pob = max(int(round(pob)), poblacion_actual)
    return ProyeccionPoblacional(
        poblacion_actual=int(poblacion_actual),
        anio_base=int(anio_base),
        horizonte_anios=t,
        tasa_crecimiento_pct=r_pct,
        metodo=metodo,
        poblacion_diseno=pob,
        categoria_nb689=categoria_nb689(pob),
    )


# ─── Dotación adoptada ───────────────────────────────────────────────────

@dataclass(frozen=True)
class DotacionAdoptada:
    dotacion_l_hab_dia: float
    nivel_servicio: str
    nivel_servicio_descripcion: str
    rango_piso_l_hab_dia: tuple[int, int]
    justificacion: str


def dotacion_adoptada(rango_piso: tuple[int, int],
                        nivel_servicio: str,
                        dotacion_usuario_l_hab_dia: float | None = None
                        ) -> DotacionAdoptada:
    """Devuelve la dotación a adoptar.

    Si el usuario provee un valor explícito (`dotacion_usuario_l_hab_dia`)
    se respeta. Si no, se interpola dentro del rango del piso ecológico
    según el nivel de servicio (factor de la tabla
    `AJUSTE_NIVEL_SERVICIO`).
    """
    descripcion = NIVELES_SERVICIO_NB689.get(nivel_servicio, nivel_servicio)
    if dotacion_usuario_l_hab_dia is not None:
        return DotacionAdoptada(
            dotacion_l_hab_dia=float(dotacion_usuario_l_hab_dia),
            nivel_servicio=nivel_servicio,
            nivel_servicio_descripcion=descripcion,
            rango_piso_l_hab_dia=rango_piso,
            justificacion=("Valor declarado por el proyectista, dentro del "
                            "rango orientativo del piso ecológico."),
        )
    factor = AJUSTE_NIVEL_SERVICIO.get(nivel_servicio, 1.0)
    valor = rango_piso[0] + factor * (rango_piso[1] - rango_piso[0])
    return DotacionAdoptada(
        dotacion_l_hab_dia=round(valor, 1),
        nivel_servicio=nivel_servicio,
        nivel_servicio_descripcion=descripcion,
        rango_piso_l_hab_dia=rango_piso,
        justificacion=(f"Adoptada por interpolación en el rango del piso "
                        f"ecológico ({rango_piso[0]}–{rango_piso[1]} L/hab/día) "
                        f"con factor {factor:.2f} correspondiente al nivel "
                        f"«{descripcion.lower()}»."),
    )


# ─── Caudales de diseño ──────────────────────────────────────────────────

@dataclass
class CaudalesDemanda:
    proyeccion: ProyeccionPoblacional
    dotacion: DotacionAdoptada
    k1: float
    k2: float
    q_md_l_s: float          # Caudal medio diario
    q_max_d_l_s: float       # Caudal máximo diario
    q_max_h_l_s: float       # Caudal máximo horario
    q_captacion_l_s: float   # Caudal de diseño de la obra de captación

    # Conversión auxiliar
    @property
    def q_md_m3s(self) -> float:
        return self.q_md_l_s / 1000.0

    @property
    def q_max_d_m3s(self) -> float:
        return self.q_max_d_l_s / 1000.0

    @property
    def q_max_h_m3s(self) -> float:
        return self.q_max_h_l_s / 1000.0


def caudales_diseno(proyeccion: ProyeccionPoblacional,
                     dotacion: DotacionAdoptada,
                     k1: float = K1_NB689,
                     k2: float = K2_NB689) -> CaudalesDemanda:
    """Calcula Q_md, Q_máx_d, Q_máx_h y el Q de captación según NB 689.

    Q_md = Pob_f · Dot / 86 400  [L/s]
    Q_máx_d = K1 · Q_md
    Q_máx_h = K2 · Q_máx_d   (algunas guías usan K2·Q_md; adoptamos NB 689)
    Q_captación = Q_máx_d (criterio conservador NB 689 para captación
        sin regulación intermedia).
    """
    q_md = proyeccion.poblacion_diseno * dotacion.dotacion_l_hab_dia / 86400.0
    q_max_d = k1 * q_md
    q_max_h = k2 * q_max_d
    q_capt = q_max_d
    return CaudalesDemanda(
        proyeccion=proyeccion, dotacion=dotacion, k1=k1, k2=k2,
        q_md_l_s=round(q_md, 4),
        q_max_d_l_s=round(q_max_d, 4),
        q_max_h_l_s=round(q_max_h, 4),
        q_captacion_l_s=round(q_capt, 4),
    )


# ─── Helpers para el informe ─────────────────────────────────────────────

def tabla_demanda(c: CaudalesDemanda) -> list[list[str]]:
    """Tabla 12 del informe — Caudales de diseño."""
    p = c.proyeccion
    d = c.dotacion
    return [
        ["Parámetro", "Valor", "Unidad", "Notas"],
        ["Población actual", f"{p.poblacion_actual:,}".replace(",", " "),
            "hab", f"Año base {p.anio_base}"],
        ["Horizonte de diseño", f"{p.horizonte_anios}", "años",
            f"Categoría NB 689: {p.categoria_nb689}"],
        ["Tasa de crecimiento adoptada", f"{p.tasa_crecimiento_pct:.2f}",
            "%/año", f"Método: {p.metodo}"],
        ["Población de diseño",
            f"{p.poblacion_diseno:,}".replace(",", " "), "hab", "—"],
        ["Nivel de servicio", d.nivel_servicio_descripcion, "—",
            f"Rango piso: {d.rango_piso_l_hab_dia[0]}–"
            f"{d.rango_piso_l_hab_dia[1]} L/hab/día"],
        ["Dotación adoptada", f"{d.dotacion_l_hab_dia:.1f}", "L/hab/día",
            d.justificacion],
        ["Q_md — caudal medio diario", f"{c.q_md_l_s:.3f}", "L/s",
            "Pob · Dot / 86 400"],
        ["K₁ (máx. diario / medio)", f"{c.k1:.2f}", "—",
            "NB 689 (sugerido 1.20–1.50)"],
        ["Q_máx_d — caudal máximo diario", f"{c.q_max_d_l_s:.3f}", "L/s",
            "K₁ · Q_md"],
        ["K₂ (máx. horario / máx. diario)", f"{c.k2:.2f}", "—",
            "NB 689 (sugerido 1.50–2.20)"],
        ["Q_máx_h — caudal máximo horario", f"{c.q_max_h_l_s:.3f}", "L/s",
            "K₂ · Q_máx_d"],
        ["Q_captación adoptado", f"{c.q_captacion_l_s:.3f}", "L/s",
            "Sin regulación intermedia → Q_máx_d"],
    ]
