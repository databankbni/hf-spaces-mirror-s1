"""Marco normativo aplicable a estudios hidrológicos de agua potable en Bolivia.

Cumple con la especificación de la Sección 1.5 del skill «Memoria de cálculo
de caudales mínimos para agua potable». Cada entrada del marco lleva
instrumento, descripción, organismo emisor, año y la aplicación específica
en el presente estudio (qué decisión hidrológica respalda).

Las normas técnicas IBNORCA (NB 512, NB 689, NB 688) son referenciadas con
su última edición vigente en el ámbito del Ministerio de Medio Ambiente y
Agua (MMAyA) y la Autoridad de Fiscalización y Control Social de Agua
Potable y Saneamiento Básico (AAPS).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormaAplicable:
    """Norma o instrumento aplicable, con justificación de uso."""
    clave: str
    instrumento: str           # Citación corta
    descripcion: str           # Qué regula
    organismo: str             # Quién la emite
    anio: str                  # Año de vigencia
    aplicacion_en_estudio: str # Qué decisión respalda


# ─── Normativa nacional boliviana ─────────────────────────────────────────

NB_512 = NormaAplicable(
    clave="NB_512",
    instrumento="NB 512 — Agua Potable. Requisitos",
    descripcion=("Establece los requisitos físicos, químicos, "
                  "bacteriológicos y radiológicos del agua para consumo "
                  "humano en todo el territorio nacional."),
    organismo="IBNORCA / MMAyA",
    anio="2010 (5ª revisión)",
    aplicacion_en_estudio=(
        "Define la calidad mínima exigible a la fuente y, cuando hay "
        "análisis físico-químico, sustenta la recomendación de tipo de "
        "tratamiento. Es referencia obligatoria para la conclusión "
        "sobre viabilidad de la fuente."),
)

NB_689 = NormaAplicable(
    clave="NB_689",
    instrumento="NB 689 — Diseño de sistemas de agua potable",
    descripcion=("Reglamento técnico para diseño de sistemas de "
                  "abastecimiento de agua potable: dotaciones, períodos "
                  "de diseño, coeficientes de variación, caudales de "
                  "captación, almacenamiento y conducción."),
    organismo="IBNORCA / MMAyA",
    anio="2004 (con actualizaciones)",
    aplicacion_en_estudio=(
        "Define el horizonte de proyección poblacional, los coeficientes "
        "K1 (máximo diario) y K2 (máximo horario), las dotaciones "
        "orientativas por categoría poblacional y el caudal de diseño "
        "de la obra de captación (Sección 6 del informe)."),
)

NB_688 = NormaAplicable(
    clave="NB_688",
    instrumento="NB 688 — Diseño de sistemas de alcantarillado sanitario "
                 "y pluvial",
    descripcion=("Norma boliviana de diseño de redes de alcantarillado "
                  "sanitario y pluvial."),
    organismo="IBNORCA / MMAyA",
    anio="2007",
    aplicacion_en_estudio=(
        "Referencia complementaria cuando el proyecto de agua potable "
        "se integra al balance hídrico del sistema sanitario (retornos, "
        "vertidos, conflictos de uso aguas abajo)."),
)

LEY_1333 = NormaAplicable(
    clave="LEY_1333",
    instrumento="Ley 1333 — Ley del Medio Ambiente",
    descripcion=("Ley marco ambiental boliviana. Establece principios de "
                  "protección y conservación de los recursos hídricos y "
                  "el régimen de evaluación de impacto ambiental."),
    organismo="Estado Plurinacional de Bolivia",
    anio="1992",
    aplicacion_en_estudio=(
        "Sustenta el requerimiento de respetar un caudal ecológico "
        "remanente en la fuente y la obligatoriedad de no comprometer "
        "ecosistemas hídricos por el aprovechamiento."),
)

RMCH = NormaAplicable(
    clave="RMCH",
    instrumento="Reglamento en Materia de Contaminación Hídrica (RMCH)",
    descripcion=("Reglamento de la Ley 1333 que clasifica los cuerpos de "
                  "agua según su aptitud de uso (clases A–D) y fija "
                  "límites permisibles de descarga."),
    organismo="MMAyA",
    anio="1995 (modificado 2007)",
    aplicacion_en_estudio=(
        "Determina la clase de aptitud que debe cumplir la fuente para "
        "destino de consumo humano (clase A: tratamiento simple; "
        "clase B: tratamiento físico-químico)."),
)

AAPS = NormaAplicable(
    clave="AAPS",
    instrumento="Lineamientos AAPS para proyectos de agua potable",
    descripcion=("Reglamentos y guías de la Autoridad de Fiscalización y "
                  "Control Social de Agua Potable y Saneamiento Básico "
                  "para presentación de proyectos sectoriales."),
    organismo="AAPS",
    anio="vigente",
    aplicacion_en_estudio=(
        "Define el formato y contenido mínimo de la memoria técnica "
        "presentada para registro de fuente y licencia de operación."),
)

# ─── Referencias técnicas internacionales ────────────────────────────────

OMM_168 = NormaAplicable(
    clave="OMM_168",
    instrumento="OMM-N° 168 — Guía de Prácticas Hidrológicas (Vol. I y II)",
    descripcion=("Manual oficial de la Organización Meteorológica Mundial "
                  "con prácticas estandarizadas para hidrometría, análisis "
                  "de series, cálculo de estiajes y caudales mínimos en "
                  "cuencas con información escasa."),
    organismo="OMM (WMO)",
    anio="2008 (6ª ed., en español)",
    aplicacion_en_estudio=(
        "Respaldo metodológico para Q95, Q7,10, curva de duración, "
        "balance hídrico de Thornthwaite-Mather y análisis de "
        "consistencia (doble masa, homogeneidad)."),
)

TENNANT = NormaAplicable(
    clave="TENNANT_1976",
    instrumento="Método Tennant (Montana Method) para caudales ambientales",
    descripcion=("Metodología hidrológica de Tennant (1976) que fija "
                  "porcentajes del caudal medio anual como caudal mínimo "
                  "para distintos niveles de protección biológica."),
    organismo="Tennant, D.L. (Montana Dept. Fish & Game)",
    anio="1976",
    aplicacion_en_estudio=(
        "Referencia internacional para el cálculo del caudal ecológico "
        "(Sección 5.5). Se complementa con Tessman (1980), Smakhtin Q90 "
        "y criterio Q7,10 ecológico cuando hay datos."),
)

ISO_748 = NormaAplicable(
    clave="ISO_748",
    instrumento="ISO 748 — Hidrometría. Medición de caudales en canales "
                 "abiertos por método velocidad-área",
    descripcion=("Norma internacional para aforos por molinete, "
                  "vadeo y bote, con tratamiento estadístico de la "
                  "incertidumbre del caudal."),
    organismo="ISO (International Organization for Standardization)",
    anio="2007",
    aplicacion_en_estudio=(
        "Referencia técnica para los aforos directos de la Sección 5.1: "
        "número mínimo de verticales, distribución de puntos en cada "
        "vertical y cálculo del caudal por sección media."),
)

NORMAS_PRIMARIAS = (NB_512, NB_689, NB_688, LEY_1333, RMCH, AAPS,
                       OMM_168, TENNANT, ISO_748)


def tabla_marco_normativo() -> list[list[str]]:
    """Tabla 1 obligatoria (Sección 1.5).

    Devuelve la lista de filas (la primera es la cabecera) lista para
    insertarse en el PDF / HTML del informe.
    """
    cab = ["Instrumento", "Descripción", "Aplicación en el estudio"]
    filas: list[list[str]] = [cab]
    for n in NORMAS_PRIMARIAS:
        filas.append([
            f"{n.instrumento} ({n.organismo}, {n.anio})",
            n.descripcion,
            n.aplicacion_en_estudio,
        ])
    return filas


def bibliografia_apa() -> list[str]:
    """Entradas en formato APA-7 abreviado para la Sección 10 / Bibliografía."""
    return [
        "Instituto Boliviano de Normalización y Calidad (IBNORCA). (2010). "
        "<i>NB 512: Agua potable – Requisitos</i> (5ª rev.). La Paz: "
        "IBNORCA / MMAyA.",
        "Instituto Boliviano de Normalización y Calidad (IBNORCA). (2004). "
        "<i>NB 689: Reglamento técnico de diseño de sistemas de agua "
        "potable</i>. La Paz: IBNORCA / MMAyA.",
        "Instituto Boliviano de Normalización y Calidad (IBNORCA). (2007). "
        "<i>NB 688: Reglamento técnico de diseño de sistemas de "
        "alcantarillado sanitario y pluvial</i>. La Paz: IBNORCA / MMAyA.",
        "Estado Plurinacional de Bolivia. (1992). <i>Ley 1333 – Ley del "
        "Medio Ambiente</i>. Gaceta Oficial de Bolivia.",
        "Ministerio de Medio Ambiente y Agua. (1995/2007). <i>Reglamento "
        "en Materia de Contaminación Hídrica (RMCH)</i>. La Paz: MMAyA.",
        "Autoridad de Fiscalización y Control Social de Agua Potable y "
        "Saneamiento Básico (AAPS). <i>Lineamientos para la presentación "
        "de proyectos de agua potable</i>. La Paz: AAPS.",
        "Organización Meteorológica Mundial (OMM). (2008). <i>Guía de "
        "Prácticas Hidrológicas, OMM-N° 168</i> (6ª ed.). Ginebra: WMO.",
        "Tennant, D. L. (1976). Instream flow regimens for fish, wildlife, "
        "recreation and related environmental resources. <i>Fisheries</i>, "
        "1(4), 6–10.",
        "International Organization for Standardization (ISO). (2007). "
        "<i>ISO 748: Hydrometry – Measurement of liquid flow in open "
        "channels using current-meters or floats</i>. Geneva: ISO.",
    ]
