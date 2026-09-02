"""Transposición hidrológica para cuencas con datos limitados.

Implementa el Método 3 (Sección 5.3) del informe de agua potable: cuando la
cuenca de estudio no tiene serie hidrométrica directa, se transfiere un
caudal característico (Q medio, Q mín, Q95) desde una cuenca «donante»
hidrológicamente similar usando la relación de áreas elevada a un
exponente n.

Fórmula adoptada:
    Q₂ = Q₁ · (A₂ / A₁)^n

donde n ∈ [0.65, 0.85] según la similitud hidrológica entre las cuencas.
Adoptamos n = 0.75 como valor por defecto siguiendo recomendaciones de la
OMM (Guía de Prácticas Hidrológicas, 2008) y la práctica regional en
Bolivia (Mariaca & Espinoza 2018 para el Beni).

Criterios de selección de la cuenca donante (Tabla 9 del informe):
1. Cercanía geográfica (idealmente la cuenca adyacente).
2. Mismo piso ecológico (clasificación según `pisos_ecologicos.clasificar`).
3. Relación de áreas A_receptora / A_donante en [0.25, 4.0] (factor de
   escala razonable; fuera de ese rango el exponente n pierde validez).
4. Precipitación media anual similar (±20 %).
5. Cobertura vegetal y régimen pluvial similar (juicio experto).

Cuando no hay cuenca donante con estos criterios cumplidos, el método no
se aplica y se reporta como tal en el informe.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pisos_ecologicos import PisoEcologico, clasificar as clasificar_piso


# ─── Selección y transposición ───────────────────────────────────────────

@dataclass(frozen=True)
class CuencaDonante:
    """Cuenca donante candidata (típicamente una estación SENAMHI-BHN)."""
    codigo: str
    nombre: str
    cuerpo_agua: str
    lat: float
    lon: float
    area_km2: float
    altitud_msnm: float | None
    precipitacion_anual_mm: float | None
    q_medio_m3s: float
    q_min_m3s: float | None
    q_95_m3s: float | None
    distancia_km: float


@dataclass(frozen=True)
class ResultadoTransposicion:
    donante: CuencaDonante
    receptora_area_km2: float
    receptora_piso: PisoEcologico
    exponente_n: float
    razon_areas: float
    q_medio_transpuesto_m3s: float
    q_min_transpuesto_m3s: float | None
    q_95_transpuesto_m3s: float | None
    similitud_clasificacion: str  # alta / media / baja
    advertencias: list[str]


def evaluar_similitud(donante: CuencaDonante,
                        receptora_area_km2: float,
                        receptora_lat: float,
                        receptora_lon: float,
                        receptora_altitud_m: float | None,
                        receptora_pann_mm: float | None
                        ) -> tuple[str, list[str]]:
    """Clasifica la similitud (alta/media/baja) y emite advertencias."""
    msgs: list[str] = []
    pa_donante = clasificar_piso(donante.lat, donante.lon,
                                    donante.altitud_msnm)
    pa_receptora = clasificar_piso(receptora_lat, receptora_lon,
                                      receptora_altitud_m)
    mismo_piso = (pa_donante.clave == pa_receptora.clave)
    if not mismo_piso:
        msgs.append(f"Pisos ecológicos distintos (donante: "
                      f"{pa_donante.nombre}; receptora: {pa_receptora.nombre}). "
                      f"Reducir el exponente n y verificar resultado.")
    razon = donante.area_km2 / max(receptora_area_km2, 1e-3)
    if razon < 0.25 or razon > 4.0:
        msgs.append(f"Relación de áreas {razon:.2f} fuera del rango "
                      f"[0.25, 4.0]: la transposición pierde validez.")
    if donante.distancia_km > 100:
        msgs.append(f"Donante a {donante.distancia_km:.0f} km — "
                      f"considerar buscar una cuenca más próxima si existe.")
    if (donante.precipitacion_anual_mm and receptora_pann_mm
            and abs(donante.precipitacion_anual_mm - receptora_pann_mm)
            / max(receptora_pann_mm, 1.0) > 0.20):
        msgs.append("Diferencia de precipitación anual > 20 % — "
                      "ajustar Q transpuesto proporcionalmente o descartar.")
    # Resumen
    if mismo_piso and 0.5 <= razon <= 2.0 and len(msgs) == 0:
        return "alta", msgs
    if mismo_piso and 0.25 <= razon <= 4.0:
        return "media", msgs
    return "baja", msgs


def transponer(donante: CuencaDonante,
                receptora_area_km2: float,
                receptora_lat: float,
                receptora_lon: float,
                receptora_altitud_m: float | None,
                receptora_pann_mm: float | None,
                exponente_n: float = 0.75
                ) -> ResultadoTransposicion:
    """Transfiere caudales desde donante a receptora.

    Q_receptora = Q_donante · (A_receptora / A_donante)^n
    """
    receptora_piso = clasificar_piso(receptora_lat, receptora_lon,
                                         receptora_altitud_m)
    razon = receptora_area_km2 / donante.area_km2
    factor = razon ** exponente_n
    similitud, advertencias = evaluar_similitud(
        donante, receptora_area_km2, receptora_lat, receptora_lon,
        receptora_altitud_m, receptora_pann_mm)
    return ResultadoTransposicion(
        donante=donante,
        receptora_area_km2=receptora_area_km2,
        receptora_piso=receptora_piso,
        exponente_n=exponente_n,
        razon_areas=razon,
        q_medio_transpuesto_m3s=donante.q_medio_m3s * factor,
        q_min_transpuesto_m3s=(donante.q_min_m3s * factor
                                  if donante.q_min_m3s is not None else None),
        q_95_transpuesto_m3s=(donante.q_95_m3s * factor
                                 if donante.q_95_m3s is not None else None),
        similitud_clasificacion=similitud,
        advertencias=advertencias,
    )


def desde_estacion_hidro(estacion_hidro,
                            distancia_km: float,
                            receptora_area_km2: float,
                            receptora_lat: float,
                            receptora_lon: float,
                            receptora_altitud_m: float | None,
                            receptora_pann_mm: float | None,
                            exponente_n: float = 0.75
                            ) -> ResultadoTransposicion | None:
    """Construye una `CuencaDonante` a partir de un objeto del catálogo
    SENAMHI-hidrométrico y aplica la transposición.

    Devuelve `None` si la estación no tiene los campos mínimos para
    transponer (área de aporte + caudal medio).
    """
    A_d = getattr(estacion_hidro, "area_aporte_km2", None)
    Q_med = getattr(estacion_hidro, "q_medio_m3s", None)
    if not A_d or not Q_med:
        return None
    donante = CuencaDonante(
        codigo=getattr(estacion_hidro, "codigo", "—"),
        nombre=getattr(estacion_hidro, "nombre", "—"),
        cuerpo_agua=getattr(estacion_hidro, "cuerpo_agua", "—"),
        lat=getattr(estacion_hidro, "lat", 0.0),
        lon=getattr(estacion_hidro, "lon", 0.0),
        area_km2=float(A_d),
        altitud_msnm=getattr(estacion_hidro, "altitud_msnm", None),
        precipitacion_anual_mm=getattr(estacion_hidro,
                                          "precipitacion_anual_mm", None),
        q_medio_m3s=float(Q_med),
        q_min_m3s=getattr(estacion_hidro, "q_min_m3s", None),
        q_95_m3s=getattr(estacion_hidro, "q_95_m3s", None),
        distancia_km=float(distancia_km),
    )
    return transponer(donante, receptora_area_km2, receptora_lat,
                         receptora_lon, receptora_altitud_m,
                         receptora_pann_mm, exponente_n)


def seleccionar_mejor_donante(hidro_cercanas,
                                  receptora_area_km2: float,
                                  receptora_lat: float,
                                  receptora_lon: float,
                                  receptora_altitud_m: float | None,
                                  receptora_pann_mm: float | None,
                                  exponente_n: float = 0.75
                                  ) -> ResultadoTransposicion | None:
    """Recorre las estaciones hidro candidatas y devuelve la transposición
    con mayor similitud (preferencia alta > media > baja, luego menor
    distancia)."""
    candidatos: list[ResultadoTransposicion] = []
    for e, dist in (hidro_cercanas or []):
        r = desde_estacion_hidro(e, dist, receptora_area_km2,
                                     receptora_lat, receptora_lon,
                                     receptora_altitud_m, receptora_pann_mm,
                                     exponente_n)
        if r is not None:
            candidatos.append(r)
    if not candidatos:
        return None
    orden = {"alta": 0, "media": 1, "baja": 2}
    candidatos.sort(key=lambda r: (orden.get(r.similitud_clasificacion, 9),
                                      r.donante.distancia_km))
    return candidatos[0]


# ─── Helpers para el informe ─────────────────────────────────────────────

def tabla_comparativa(r: ResultadoTransposicion) -> list[list[str]]:
    """Tabla 9 — Cuenca donante y transposición hidrológica."""
    return [
        ["Parámetro", "Donante", "Receptora"],
        ["Código / nombre",
            f"{r.donante.codigo} — {r.donante.nombre}",
            "Cuenca de estudio (objeto de captación)"],
        ["Cuerpo de agua", r.donante.cuerpo_agua, "[completar]"],
        ["Área de cuenca (km²)", f"{r.donante.area_km2:.2f}",
            f"{r.receptora_area_km2:.2f}"],
        ["Razón A_recep/A_don", "—", f"{r.razon_areas:.3f}"],
        ["Altitud (m s.n.m.)",
            (f"{r.donante.altitud_msnm:.0f}"
             if r.donante.altitud_msnm else "—"),
            f"{r.receptora_piso.rango_altitud_m[0]}–"
            f"{r.receptora_piso.rango_altitud_m[1]}"],
        ["Piso ecológico",
            "—",
            r.receptora_piso.nombre],
        ["Precipitación anual (mm)",
            (f"{r.donante.precipitacion_anual_mm:.0f}"
             if r.donante.precipitacion_anual_mm else "—"),
            "[validar con CHIRPS local]"],
        ["Q medio (m³/s)", f"{r.donante.q_medio_m3s:.3f}",
            f"{r.q_medio_transpuesto_m3s:.3f}  "
            f"= Q_don · ({r.razon_areas:.3f})^{r.exponente_n}"],
        ["Q mínimo (m³/s)",
            (f"{r.donante.q_min_m3s:.3f}"
             if r.donante.q_min_m3s is not None else "—"),
            (f"{r.q_min_transpuesto_m3s:.3f}"
             if r.q_min_transpuesto_m3s is not None else "—")],
        ["Q95 (m³/s)",
            (f"{r.donante.q_95_m3s:.3f}"
             if r.donante.q_95_m3s is not None else "—"),
            (f"{r.q_95_transpuesto_m3s:.3f}"
             if r.q_95_transpuesto_m3s is not None else "—")],
        ["Distancia (km)", f"{r.donante.distancia_km:.1f}", "0.0 (referencia)"],
        ["Similitud hidrológica", "—", r.similitud_clasificacion.upper()],
    ]
