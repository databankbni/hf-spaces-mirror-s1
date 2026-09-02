"""Resumen de parámetros para importación en HEC-HMS.

Reúne los parámetros del modelo de cuenca (basin), meteorológico y de
transformación lluvia-escorrentía listos para cargar en HEC-HMS, y recomienda
el método de transformación más adecuado según las características de la cuenca.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResumenHecHms:
    area_km2: float
    tc_min: float
    tc_horas: float
    lag_min: float            # tiempo de retardo = 0.6·Tc (SCS)
    cn: float                 # número de curva (referencial, requiere uso de suelo)
    metodo_perdidas: str
    metodo_transformacion: str
    metodo_lluvia: str
    p_total_mm: float
    T_anios: int
    recomendacion: str


def _recomendar_transformacion(area_km2: float, tc_horas: float) -> tuple[str, str]:
    """Recomienda método de transformación de HEC-HMS según la cuenca."""
    if area_km2 <= 25:
        metodo = "SCS Unit Hydrograph (hidrograma unitario adimensional SCS)"
        razon = (
            "Cuenca pequeña (≤ 25 km²) sin aforos: el HU del SCS es robusto y "
            "sólo requiere el lag (= 0.6·Tc) y el CN, ambos estimables sin "
            "registros de caudal."
        )
    elif area_km2 <= 250:
        metodo = "Clark Unit Hydrograph (Tc + coeficiente de almacenamiento R)"
        razon = (
            "Cuenca mediana: el método de Clark representa mejor el tránsito y "
            "el almacenamiento; usar Tc adoptado y R ≈ Tc (calibrar si hay datos)."
        )
    else:
        metodo = "ModClark / Snyder Unit Hydrograph"
        razon = (
            "Cuenca grande: conviene un método distribuido (ModClark) o Snyder, "
            "idealmente con calibración contra caudales observados."
        )
    return metodo, razon


def resumen_hec_hms(
    *,
    area_km2: float,
    tc_min: float,
    hietograma,
    cn: float = 75.0,
) -> ResumenHecHms:
    tc_h = tc_min / 60.0
    lag = 0.6 * tc_min
    metodo_tr, razon = _recomendar_transformacion(area_km2, tc_h)
    recomendacion = (
        f"Para esta cuenca ({area_km2:.1f} km², Tc = {tc_min:.0f} min) se "
        f"recomienda el método de transformación <b>{metodo_tr}</b>. {razon} "
        f"Pérdidas: SCS Curve Number (CN = {cn:.0f}, referencial — debe derivarse "
        f"de uso de suelo CORINE/USGS + grupo hidrológico). Modelo meteorológico: "
        f"hietograma especificado (Specified Hyetograph) con la tormenta de "
        f"diseño T = {hietograma.T_anios} años."
    )
    return ResumenHecHms(
        area_km2=round(area_km2, 2),
        tc_min=round(tc_min, 1),
        tc_horas=round(tc_h, 3),
        lag_min=round(lag, 1),
        cn=cn,
        metodo_perdidas="SCS Curve Number",
        metodo_transformacion=metodo_tr,
        metodo_lluvia="Specified Hyetograph (hietograma de diseño)",
        p_total_mm=round(hietograma.p_total_mm, 2),
        T_anios=hietograma.T_anios,
        recomendacion=recomendacion,
    )
