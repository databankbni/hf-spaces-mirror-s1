"""Tipos de obra hidráulica y períodos de retorno de diseño (normativa Bolivia).

Cada tipo de obra define un rango de período de retorno (T) recomendado y la
norma/reglamento de referencia. El valor adoptado por defecto es el extremo
superior conservador del rango (criterio de seguridad), ajustable por el usuario.

Referencias normativas (Bolivia):
- MOPSV / ABC: Manual de Hidrología y Drenaje.
- MMAyA / AAPS: Normas de seguridad de presas; NB 688 (alcantarillado).
- IDIAFI / reglamentos de riego.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TipoObra:
    clave: str
    nombre: str
    t_min: int
    t_max: int
    t_recomendado: int
    norma: str
    # Período de retorno de VERIFICACIÓN estructural (caso pésimo), cuando la
    # norma exige verificar la estructura con un T superior al de diseño.
    # None si no aplica.
    t_verificacion: int | None = None

    @property
    def rango_texto(self) -> str:
        return f"{self.t_min}–{self.t_max} años"

    @property
    def dimensionamiento_texto(self) -> str:
        """Texto contextual del objeto que se dimensionará con el Q diseño.

        Se usa en la conclusión de la Sección 13.4 («…constituye la base para
        el dimensionamiento hidráulico de …») y en el cuadro de resultados.
        """
        return _DIMENSIONAMIENTO.get(
            self.clave,
            "la obra hidráulica seleccionada y sus estructuras de control "
            "del flujo")


_DIMENSIONAMIENTO: dict[str, str] = {
    "carretera_puente":
        "el puente y de sus estructuras de drenaje longitudinal y "
        "transversal asociadas",
    "drenaje_vial_menor":
        "las alcantarillas y obras de drenaje vial menor (caños, "
        "tubulares y badenes)",
    "riego_pequeno":
        "la obra de captación, aducción y distribución del sistema "
        "de riego pequeño–mediano",
    "riego_grande":
        "las obras de captación, presa, conducción y red de "
        "distribución del sistema de riego de gran escala (>10 000 ha)",
    "presa_proyecto":
        "la presa y su vertedero de proyecto (gasto de diseño)",
    "presa_extremo":
        "el vertedero de emergencia y la verificación de seguridad "
        "de la presa frente al Evento Máximo Probable de Seguridad "
        "(EMPS / PMF)",
    "hidro_estructura":
        "las estructuras de operación de la central hidroeléctrica "
        "(toma, desarenador, túneles, cámara de carga)",
    "hidro_vertedero":
        "el vertedero principal de la central hidroeléctrica",
    "ferrocarril":
        "los drenes internos, obras de protección de la vía férrea "
        "y sus alcantarillados de cruce",
    "drenaje_urbano_cc":
        "el sistema de drenaje urbano (colectores, canales y "
        "sumideros) dimensionado bajo criterios de adaptación al "
        "cambio climático",
    "analisis_riesgo_abc":
        "los drenajes mayores (puentes) y sus obras de protección "
        "frente a socavación, dimensionados bajo criterios de riesgo "
        "hidroclimático y adaptación al cambio climático (Manual de la ABC)",
}


TIPOS_OBRA: tuple[TipoObra, ...] = (
    TipoObra("carretera_puente", "Carreteras y puentes (principales)",
             50, 100, 100, "Manual de Hidrología y Drenaje — MOPSV/ABC",
             t_verificacion=500),
    TipoObra("drenaje_vial_menor", "Drenaje vial menor (alcantarillas)",
             10, 25, 25, "Manual de Hidrología y Drenaje — MOPSV/ABC"),
    TipoObra("riego_pequeno", "Riego (pequeño–mediano)",
             5, 25, 25, "Reglamentos de riego / estudios IDIAFI"),
    TipoObra("riego_grande", "Riego grande (>10 000 ha)",
             25, 50, 50, "Reglamentos de riego / estudios IDIAFI"),
    TipoObra("presa_proyecto", "Presas (gasto de proyecto)",
             50, 500, 500, "Normas de seguridad de presas — MMAyA/AAPS"),
    TipoObra("presa_extremo", "Presas (evento extremo EMPS)",
             10000, 10000, 10000, "Normas de seguridad de presas — MMAyA/AAPS"),
    TipoObra("hidro_estructura", "Hidroeléctricas (estructuras de operación)",
             50, 100, 100, "Normas de presas / estudios IDIAFI"),
    TipoObra("hidro_vertedero", "Hidroeléctricas (vertederos)",
             200, 500, 500, "Normas de seguridad de presas"),
    TipoObra("ferrocarril", "Ferrocarriles (drenaje interno)",
             25, 50, 50, "Normas MOPSV/AAPS (por analogía)"),
    TipoObra("drenaje_urbano_cc", "Adaptación al cambio climático (drenaje urbano)",
             50, 100, 100, "NB 688 y estudios I-D-F — MMAyA"),
    TipoObra("analisis_riesgo_abc",
             "Análisis de riesgo para obras viales según Manual de la ABC",
             200, 300, 200,
             "Manual para la Interpretación y Aplicación de los Índices y "
             "Parámetros de Variabilidad Climática — ABC",
             t_verificacion=300),
)

_POR_CLAVE = {o.clave: o for o in TIPOS_OBRA}


def obtener_tipo_obra(clave: str) -> TipoObra:
    """Devuelve el tipo de obra por clave (default: carretera_puente)."""
    return _POR_CLAVE.get(clave, _POR_CLAVE["carretera_puente"])
