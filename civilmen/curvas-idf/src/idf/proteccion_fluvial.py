"""Dimensionamiento preliminar de obras de protección fluvial.

Exigido por el dictamen de supervisión (§3.4, nivel EDTP): definición
conceptual y dimensionamiento PRELIMINAR de las obras de encauzamiento y
protección (enrocado de estribos, gaviones, espigones, diques defensivos)
necesarias para evitar la excentricidad del flujo y la falla de los accesos.

Todo se deriva de la hidráulica ya calculada en la Sección 14 (velocidad,
tirante, NAME de diseño/verificación y socavación). Es un prediseño orientativo
—el diseño definitivo requiere el estudio geotécnico y el levantamiento de
detalle—; los tamaños se calculan con métodos reconocidos (Isbash para el
enrocado, FHWA HEC-23 para las contramedidas de socavación).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

_G = 9.81
_SS_ROCA = 2.65        # densidad relativa de la roca
_GAMMA_W = 9.81        # kN/m³


@dataclass
class ResultadoProteccion:
    velocidad_ms: float
    tirante_m: float
    # Enrocado (riprap) por Isbash:
    d50_enrocado_m: float
    d50_enrocado_pulg: float
    espesor_capa_m: float
    coef_isbash: float
    # Profundidad de empotramiento del pie de protección (bajo socavación):
    prof_empotramiento_m: Optional[float]
    # Dique/encauzamiento:
    cota_dique_sobre_fondo_m: Optional[float]
    borde_libre_dique_m: float
    # Espigones (conceptual):
    espigon_long_m: Optional[float]
    espigon_separacion_m: Optional[float]
    espigon_angulo: str
    recomendaciones: list


def _d50_isbash(V: float, C: float = 0.86, ss: float = _SS_ROCA) -> float:
    """Diámetro medio del enrocado (m) por la ecuación de Isbash.

    Vc = C·√(2g(Ss−1)·D)  →  D50 = V² / (C²·2g·(Ss−1)).
    C = 0.86 para piedra expuesta (turbulencia alta, terraplenes) — conservador;
    C = 1.20 para piedra embebida.
    """
    return V * V / (C * C * 2.0 * _G * (ss - 1.0))


def dimensionar_proteccion(*, velocidad_ms: float, tirante_m: float,
                           name_sobre_fondo_m: Optional[float] = None,
                           prof_socavacion_m: Optional[float] = None,
                           ancho_cauce_m: Optional[float] = None,
                           C_isbash: float = 0.86) -> Optional[ResultadoProteccion]:
    """Prediseño de la protección a partir de la velocidad y el tirante de diseño.

    name_sobre_fondo_m : altura del NAME (de verificación) sobre el fondo, para
        fijar la corona del dique/encauzamiento.
    prof_socavacion_m : profundidad de socavación total (para empotrar el pie).
    ancho_cauce_m : espejo de agua, para la longitud/separación de espigones.
    """
    if not velocidad_ms or velocidad_ms <= 0 or not tirante_m or tirante_m <= 0:
        return None
    V = float(velocidad_ms)
    d50 = _d50_isbash(V, C=C_isbash)
    # Espesor de la capa de enrocado: máx(2·D50, 1.5·D50 y 0.30 m) (HEC-23).
    espesor = max(2.0 * d50, 0.30)
    # Empotramiento del pie: por debajo de la socavación total + resguardo.
    empotr = (float(prof_socavacion_m) if prof_socavacion_m else None)
    # Dique/encauzamiento: corona = NAME(verif) + borde libre (0.5–1.0 m).
    bl_dique = 0.75
    cota_dique = ((float(name_sobre_fondo_m) + bl_dique)
                  if name_sobre_fondo_m else None)
    # Espigones: longitud ≈ 10–25 % del ancho; separación 2–4·L (FHWA HEC-23).
    esp_long = esp_sep = None
    if ancho_cauce_m and ancho_cauce_m > 0:
        esp_long = round(0.20 * float(ancho_cauce_m), 1)
        esp_sep = round(3.0 * esp_long, 1)

    recs = []
    # Selección del tipo de protección según la velocidad.
    if V >= 4.5:
        tipo = ("velocidad muy alta (≥ 4.5 m/s): se recomienda <b>enrocado "
                "pesado con roca de cantera</b> o <b>gaviones tipo colchón "
                "Reno</b> anclados; el hormigón ciclópeo es alternativa en "
                "estribos.")
    elif V >= 2.5:
        tipo = ("velocidad alta (2.5–4.5 m/s): <b>enrocado (riprap)</b> o "
                "<b>gaviones caja/colchón</b> en estribos y márgenes.")
    else:
        tipo = ("velocidad moderada (< 2.5 m/s): <b>enrocado ligero</b> o "
                "protección vegetal-estructural (biomantos + escollera de pie).")
    recs.append(f"Tipo de protección sugerido por velocidad: {tipo}")
    recs.append(
        f"Enrocado de protección de estribos y márgenes: roca de "
        f"D50 ≈ {d50:.2f} m ({d50*39.37:.0f}\"), colocada en una capa de "
        f"espesor ≥ {espesor:.2f} m sobre filtro granular o geotextil.")
    if empotr:
        recs.append(
            f"El pie del enrocado/gavión debe empotrarse por debajo de la "
            f"línea de socavación total ({empotr:.2f} m bajo el fondo actual) "
            f"para no ser socavado, conforme a FHWA HEC-23.")
    if cota_dique:
        recs.append(
            f"Diques de encauzamiento / defensivos: corona a "
            f"{cota_dique:.2f} m sobre el fondo = NAME de verificación + "
            f"{bl_dique:.2f} m de borde libre; talud 2H:1V protegido con "
            f"enrocado o gaviones.")
    if esp_long:
        recs.append(
            f"Si se requiere reencauzar el flujo (excentricidad en el cruce), "
            f"espigones de longitud ≈ {esp_long:.1f} m con separación "
            f"≈ {esp_sep:.1f} m (2–4·L), orientados 100–110° hacia aguas "
            f"arriba (FHWA HEC-23).")
    recs.append(
        "Dimensionamiento PRELIMINAR (Isbash + HEC-23): el diseño definitivo "
        "exige el estudio geotécnico del cauce, la granulometría real y el "
        "levantamiento topo-batimétrico de detalle.")

    return ResultadoProteccion(
        velocidad_ms=round(V, 2), tirante_m=round(float(tirante_m), 2),
        d50_enrocado_m=round(d50, 3), d50_enrocado_pulg=round(d50 * 39.37, 1),
        espesor_capa_m=round(espesor, 2), coef_isbash=C_isbash,
        prof_empotramiento_m=(round(empotr, 2) if empotr else None),
        cota_dique_sobre_fondo_m=(round(cota_dique, 2) if cota_dique else None),
        borde_libre_dique_m=bl_dique,
        espigon_long_m=esp_long, espigon_separacion_m=esp_sep,
        espigon_angulo="100–110° hacia aguas arriba",
        recomendaciones=recs)
