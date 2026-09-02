"""Estaciones hidrométricas e hidrológicas para el módulo de caudales mínimos.

Cataloga las fuentes de datos de caudal disponibles para Bolivia:

- SENAMHI BHN (Boletines Hidrológicos Nacionales): aforos mensuales en
  cuencas principales (Mamoré, Beni, Pilcomayo, Desaguadero).
- GRDC (Global Runoff Data Centre, WMO/BfG): estaciones bolivianas
  incluidas en el catálogo global.
- ABT (Autoridad de Bosques y Tierra) y SEARPI: aforos puntuales para
  proyectos específicos.

Los códigos y coordenadas son representativos del catálogo oficial; las
medias y desviaciones son climatológicas referenciales para validación.
La consulta principal es por proximidad al punto de análisis.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Literal


EstadoEstacion = Literal["activa", "pasiva", "intermitente"]


@dataclass(frozen=True)
class EstacionHidro:
    """Estación de aforo / caudal con metadata para selección por proximidad."""
    codigo: str
    nombre: str
    cuerpo_agua: str
    cuenca_macro: str       # Amazonas / Plata / Altiplano
    departamento: str
    fuente: str             # SENAMHI-BHN / GRDC / SEARPI / ABT
    latitud: float
    longitud: float
    altitud_msnm: float
    area_aporte_km2: float  # área de cuenca aguas arriba
    q_medio_m3s: float      # caudal medio anual (climatología)
    q_min_m3s: float        # caudal mínimo medio anual histórico
    estado: EstadoEstacion
    anio_inicio: int        # año inicio de la serie
    anio_fin: int           # año fin (o el año más reciente disponible)


# Catálogo representativo de estaciones hidrométricas en Bolivia.
# Coordenadas y nombres tomados del catálogo SENAMHI-BHN y GRDC; los
# valores de caudal son climatológicos (no son medidas oficiales).
ESTACIONES_HIDRO: tuple[EstacionHidro, ...] = (
    # ─────────── Cuenca del Amazonas (Mamoré-Beni-Madre de Dios) ───────────
    EstacionHidro("BNI-MM-001", "Puerto Villarroel", "Río Ichilo",
                  "Amazonas", "Cochabamba", "SENAMHI-BHN",
                  -16.8400, -64.7900, 195, 13800, 1230, 380, "activa",
                  1965, 2024),
    EstacionHidro("BNI-MM-002", "Puerto Ganadero", "Río Mamoré",
                  "Amazonas", "Beni", "SENAMHI-BHN",
                  -14.8300, -64.9100, 145, 110000, 6800, 1980, "activa",
                  1970, 2024),
    EstacionHidro("BNI-MM-003", "Guayaramerín", "Río Mamoré",
                  "Amazonas", "Beni", "GRDC",
                  -10.8200, -65.3500, 130, 230000, 8400, 2350, "activa",
                  1968, 2022),
    EstacionHidro("BNI-MM-004", "Cachuela Esperanza", "Río Beni",
                  "Amazonas", "Beni", "SENAMHI-BHN",
                  -10.5333, -65.6000, 140, 285000, 8900, 2500, "activa",
                  1972, 2024),
    EstacionHidro("BNI-MM-005", "Rurrenabaque", "Río Beni",
                  "Amazonas", "Beni", "SENAMHI-BHN",
                  -14.4400, -67.5300, 200, 72500, 3500, 850, "activa",
                  1969, 2024),
    EstacionHidro("BNI-MM-006", "Abapó", "Río Grande",
                  "Amazonas", "Santa Cruz", "SENAMHI-BHN",
                  -18.7700, -63.4000, 470, 59800, 280, 28, "activa",
                  1973, 2024),
    EstacionHidro("BNI-MM-007", "Puerto Maldonado-frontera", "Madre de Dios",
                  "Amazonas", "Pando", "GRDC",
                  -11.0400, -68.7800, 230, 47600, 2100, 600, "intermitente",
                  1980, 2018),
    EstacionHidro("BNI-MM-008", "Vuelta Grande", "Río Chapare",
                  "Amazonas", "Cochabamba", "SENAMHI-BHN",
                  -16.7000, -65.0200, 220, 7500, 580, 145, "pasiva",
                  1968, 2010),
    # ─────────── Cuenca del Plata (Pilcomayo-Bermejo-Paraguay) ───────────
    EstacionHidro("PLT-PC-001", "Villa Montes", "Río Pilcomayo",
                  "Plata", "Tarija", "SENAMHI-BHN",
                  -21.2553, -63.4072, 405, 78400, 220, 12, "activa",
                  1968, 2024),
    EstacionHidro("PLT-PC-002", "Misión La Paz", "Río Pilcomayo",
                  "Plata", "Tarija", "GRDC",
                  -22.3700, -62.5300, 270, 96100, 270, 18, "activa",
                  1971, 2022),
    EstacionHidro("PLT-PC-003", "Aguairenda", "Río Bermejo",
                  "Plata", "Tarija", "SENAMHI-BHN",
                  -22.4200, -64.3500, 360, 4900, 195, 38, "activa",
                  1975, 2024),
    EstacionHidro("PLT-PC-004", "Puente Sucre", "Río Pilcomayo",
                  "Plata", "Chuquisaca", "SENAMHI-BHN",
                  -19.0500, -64.9000, 1900, 21800, 78, 4.5, "pasiva",
                  1972, 2008),
    EstacionHidro("PLT-PC-005", "Tarabuco", "Río Tarabuquillo",
                  "Plata", "Chuquisaca", "SENAMHI-BHN",
                  -19.1700, -64.9100, 3060, 480, 5.2, 0.6, "intermitente",
                  1978, 2015),
    # ─────────── Cuenca del Altiplano (Desaguadero-Titicaca-Poopó) ─────
    EstacionHidro("ALT-DG-001", "Calacoto", "Río Desaguadero",
                  "Altiplano", "La Paz", "SENAMHI-BHN",
                  -17.2800, -68.6200, 3810, 29200, 75, 3.8, "activa",
                  1965, 2024),
    EstacionHidro("ALT-DG-002", "Chuquiña", "Río Desaguadero",
                  "Altiplano", "Oruro", "SENAMHI-BHN",
                  -17.7500, -67.6000, 3700, 40500, 92, 5.2, "activa",
                  1968, 2024),
    EstacionHidro("ALT-DG-003", "Aroma", "Río Mauri",
                  "Altiplano", "La Paz", "SENAMHI-BHN",
                  -17.4500, -68.7300, 3970, 6800, 11.5, 0.9, "activa",
                  1972, 2024),
    EstacionHidro("ALT-DG-004", "Achacachi", "Río Keka",
                  "Altiplano", "La Paz", "SENAMHI-BHN",
                  -16.0500, -68.6800, 3850, 2100, 8.4, 1.1, "intermitente",
                  1980, 2016),
    EstacionHidro("ALT-DG-005", "Poopó-Aroifilla", "Lago Poopó tributario",
                  "Altiplano", "Oruro", "SENAMHI-BHN",
                  -18.9000, -66.9700, 3690, 8900, 14.0, 0.5, "pasiva",
                  1975, 2005),
    # ─────────── Cuencas regionales menores (Cochabamba valles) ─────────
    EstacionHidro("CBB-RR-001", "Angostura", "Río Rocha",
                  "Amazonas", "Cochabamba", "SENAMHI-BHN",
                  -17.4800, -66.1500, 2480, 480, 2.8, 0.18, "activa",
                  1970, 2024),
    EstacionHidro("CBB-RR-002", "Sipe Sipe", "Río Tapacarí",
                  "Amazonas", "Cochabamba", "SENAMHI-BHN",
                  -17.4400, -66.3800, 2410, 1750, 8.5, 0.6, "activa",
                  1968, 2024),
    EstacionHidro("CBB-RR-003", "Vacas", "Río Vacas",
                  "Amazonas", "Cochabamba", "SENAMHI-BHN",
                  -17.6300, -65.6200, 3490, 86, 0.9, 0.06, "intermitente",
                  1985, 2018),
    EstacionHidro("CBB-RR-004", "Lope Mendoza", "Río Tunari",
                  "Amazonas", "Cochabamba", "SENAMHI-BHN",
                  -17.3600, -66.2100, 2740, 220, 1.6, 0.10, "pasiva",
                  1975, 2008),
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia gran-círculo entre dos coordenadas (km)."""
    R = 6371.0088
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def estaciones_cercanas(lat: float, lon: float,
                         tope: int = 12,
                         radio_km: float | None = None
                         ) -> list[tuple[EstacionHidro, float]]:
    """Devuelve las estaciones más cercanas con su distancia (km), ordenadas.

    Si `radio_km` viene, filtra primero todas las estaciones dentro de ese
    radio y devuelve hasta `tope` (o todas, si `tope` es grande). Sin
    `radio_km`, mantiene la semántica original (top-`tope` globales).
    """
    pares = [(e, _haversine_km(lat, lon, e.latitud, e.longitud))
             for e in ESTACIONES_HIDRO]
    pares.sort(key=lambda p: p[1])
    if radio_km is not None:
        pares = [p for p in pares if p[1] <= radio_km]
    return pares[:tope]


def estaciones_por_estado() -> dict[str, int]:
    """Cuenta del catálogo por estado (activa / pasiva / intermitente)."""
    out: dict[str, int] = {}
    for e in ESTACIONES_HIDRO:
        out[e.estado] = out.get(e.estado, 0) + 1
    return out
