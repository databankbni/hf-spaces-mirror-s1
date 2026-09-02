"""Estimación de parámetros morfológicos de la cuenca a partir de coordenadas.

ADVERTENCIA: derivar la morfología real de una cuenca (área, longitud del cauce,
pendiente) requiere un Modelo Digital de Elevación (DEM) y delineación
hidrológica (flow accumulation, watershed delineation). Este módulo NO hace eso:
genera una estimación SINTÉTICA, internamente consistente y reproducible a partir
de la coordenada, usando relaciones geomorfológicas empíricas (ley de Hack para
L–A y rangos de pendiente típicos de cuencas andinas/bolivianas pequeñas).

Los valores son apropiados para análisis preliminar o demostración. Para diseño
definitivo deben reemplazarse por parámetros obtenidos de un DEM (SRTM/ALOS) en
un SIG (QGIS, ArcGIS).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np


@dataclass
class MorfologiaCuenca:
    area_km2: float
    long_cauce_km: float
    cota_mayor_m: float
    cota_menor_m: float
    desnivel_m: float
    pendiente_media_mm: float   # m/m
    perimetro_km: float = 0.0
    cn: float = 75.0            # número de curva SCS (sintético, no verificado)
    sintetica: bool = True

    @property
    def pendiente_pct(self) -> float:
        return self.pendiente_media_mm * 100.0

    @property
    def ff_horton(self) -> float:
        """Factor de forma de Horton: Ff = A / Lb²  (Lb ≈ longitud de cuenca)."""
        return self.area_km2 / (self.long_cauce_km ** 2) if self.long_cauce_km else 0.0

    @property
    def kc_gravelius(self) -> float:
        """Coeficiente de compacidad de Gravelius: Kc = 0.2821·P/√A."""
        return 0.2821 * self.perimetro_km / (self.area_km2 ** 0.5) if self.area_km2 else 0.0

    @property
    def clase_forma(self) -> str:
        ff, kc = self.ff_horton, self.kc_gravelius
        if ff > 0.5 and kc < 1.25:
            return "circular (crecidas rápidas, Tc cortos)"
        if ff < 0.3 and kc > 1.5:
            return "elongada (crecidas atenuadas, Tc largos)"
        return "intermedia (oval-oblonga)"


def _semilla_desde_coordenadas(lat: float, lon: float) -> int:
    """Semilla determinística (misma coordenada -> misma cuenca)."""
    clave = f"{lat:.5f},{lon:.5f}".encode("utf-8")
    return int(hashlib.sha256(clave).hexdigest()[:8], 16)


def estimar_morfologia_desde_coordenadas(
    lat: float,
    lon: float,
    altitud_salida_m: float,
) -> MorfologiaCuenca:
    """Estima morfología sintética coherente para una cuenca pequeña.

    - Área A ~ U(8, 60) km² (cuenca de aporte típica para una pasarela).
    - Longitud del cauce por ley de Hack: L = 1.4 · A^0.6  [km].
    - Pendiente media S ~ U(0.03, 0.12) m/m (terreno andino).
    - Desnivel H = S · L · 1000  [m].
    - Cota menor = altitud de la estación/salida; cota mayor = menor + H.
    """
    rng = np.random.default_rng(_semilla_desde_coordenadas(lat, lon))
    area = float(rng.uniform(8.0, 60.0))
    long_cauce = 1.4 * area ** 0.6
    pendiente = float(rng.uniform(0.03, 0.12))
    desnivel = pendiente * long_cauce * 1000.0
    cota_menor = float(altitud_salida_m)
    cota_mayor = cota_menor + desnivel
    # Perímetro por elipse equivalente (longitud Lb = cauce, ancho W = A/Lb).
    Lb = long_cauce
    W = area / Lb
    a, b = Lb / 2.0, W / 2.0
    perimetro = float(np.pi * (3 * (a + b) - np.sqrt((3 * a + b) * (a + 3 * b))))
    cn = float(round(rng.uniform(68.0, 82.0), 1))  # CN sintético (no verificado)
    return MorfologiaCuenca(
        area_km2=round(area, 2),
        long_cauce_km=round(long_cauce, 3),
        cota_mayor_m=round(cota_mayor, 1),
        cota_menor_m=round(cota_menor, 1),
        desnivel_m=round(desnivel, 1),
        pendiente_media_mm=round(pendiente, 4),
        perimetro_km=round(perimetro, 3),
        cn=cn,
        sintetica=True,
    )
