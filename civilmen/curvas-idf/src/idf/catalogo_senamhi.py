"""Catálogo oficial SENAMHI Bolivia — 1 861 estaciones meteorológicas e hidrológicas.

Reemplaza el catálogo manual de 49 estaciones por la planilla oficial publicada
por SENAMHI, ingerida desde Excel y serializada como `estaciones_senamhi_full.json.gz`
en el mismo directorio. Cada registro mantiene las 28 columnas originales del
catálogo (estación, lat/lon, altura, activo, orden, fechas, códigos OMM/OACI,
propietario, operador, departamento, municipio, provincia, categoría, tipo,
estado, observador, etc.) más helpers de proximidad y filtrado por tipo.

Distribución del catálogo:
- 1 861 estaciones totales (al 2026)
- 420 activas + 1 274 inactivas + 151 en mantenimiento + 16 sin estado
- 902 meteorológicas + 189 hidrológicas + 770 sin categoría
- 1 393 convencionales + 265 telemétricas GPRS + 153 automáticas + 47 satelitales
- Distribución departamental (top): La Paz 510 · Cochabamba 320 · Tarija 244 ·
  Santa Cruz 220 · Potosí 190 · Chuquisaca 171 · Oruro 100 · Beni 74 · Pando 8
- Propietarios (top): SENAMHI 416 · NAABOL 72 · UCEP-Mi Riego 33 · MMAyA-UGCK 27 ·
  Dirección del Pilcomayo 12 · VRHR-MMAyA 11 · SENASAG 11 · HELVETAS 11

El catálogo NO incluye climatología de precipitación (P24 media/desv); para los
49 sitios con climatología documentada, ver `data.ESTACIONES_SENAMHI`. Para
estaciones nuevas la climatología se obtiene por interpolación IDW de las 3
vecinas climatológicas más cercanas o por descarga via NOAA GHCN-D / CHIRPS
(ver `conectores_externos.py`).

Síntesis del deep-research que generó este catálogo (ver docs/SENAMHI_research_report.md).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Iterable, Optional


_CATALOGO_JSON = Path(__file__).parent / "estaciones_senamhi_full.json.gz"


@dataclass(frozen=True)
class EstacionSENAMHI:
    """Estación del catálogo oficial SENAMHI con sus 28 atributos originales."""
    estacion: str
    latitud: float
    longitud: float
    altura: Optional[float]
    activo: bool
    orden: Optional[str]
    fecha_inicio: Optional[str]
    cod_omm: Optional[str]
    cod_oaci: Optional[str]
    cod_otro: Optional[str]
    propietario: Optional[str]
    telefono: Optional[str]
    direccion: Optional[str]
    correo: Optional[str]
    web: Optional[str]
    observacion: Optional[str]
    clasificacion: Optional[str]
    operador: Optional[str]
    financiador: Optional[str]
    nom_dep: Optional[str]
    nom_mun: Optional[str]
    nom_prov: Optional[str]
    categoria: Optional[str]
    tipo_estacion: Optional[str]
    nombre_obs: Optional[str]
    ci_obs: Optional[str]
    estado: Optional[str]
    pronostico: Optional[str]


def _cargar() -> tuple[EstacionSENAMHI, ...]:
    if not _CATALOGO_JSON.exists():
        return tuple()
    with gzip.open(_CATALOGO_JSON, "rt", encoding="utf-8") as f:
        rows = json.load(f)
    return tuple(EstacionSENAMHI(**r) for r in rows)


# Catálogo cargado al import (≤ 90 KB gzipped, ~7 MB descomprimido en memoria).
CATALOGO: tuple[EstacionSENAMHI, ...] = _cargar()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * R * asin(sqrt(a))


# ───────────────────────── Filtros ─────────────────────────

def filtrar(estaciones: Iterable[EstacionSENAMHI] = CATALOGO, *,
            categoria: Optional[str] = None,
            estado: Optional[str] = None,
            tipo_estacion: Optional[str] = None,
            departamento: Optional[str] = None,
            propietario: Optional[str] = None,
            activo: Optional[bool] = None) -> tuple[EstacionSENAMHI, ...]:
    """Devuelve un subconjunto del catálogo filtrado por los criterios dados.

    Los argumentos `None` se ignoran. Cada filtro es comparación de igualdad
    (insensible a mayúsculas para los strings).
    """
    def _eq(a, b):
        if a is None or b is None:
            return a == b
        return str(a).strip().lower() == str(b).strip().lower()

    salida = []
    for e in estaciones:
        if categoria is not None and not _eq(e.categoria, categoria):
            continue
        if estado is not None and not _eq(e.estado, estado):
            continue
        if tipo_estacion is not None and not _eq(e.tipo_estacion, tipo_estacion):
            continue
        if departamento is not None and not _eq(e.nom_dep, departamento):
            continue
        if propietario is not None and not _eq(e.propietario, propietario):
            continue
        if activo is not None and e.activo != activo:
            continue
        salida.append(e)
    return tuple(salida)


# ───────────────────────── Búsqueda por proximidad ─────────────────────────

def cercanas(lat: float, lon: float,
              tope: int = 10,
              radio_km: Optional[float] = None,
              **filtros) -> list[tuple[EstacionSENAMHI, float]]:
    """Devuelve las estaciones más cercanas al punto con su distancia (km).

    `tope` limita el resultado; `radio_km` (si se da) descarta las que caen
    más lejos. Cualquier kwarg adicional se pasa a `filtrar()` para acotar
    por categoría/estado/tipo/departamento/propietario/activo.

    Ejemplos:
        cercanas(-17.4, -66.2, tope=5, radio_km=100, categoria="Meteorológica")
        cercanas(-17.4, -66.2, tope=20, estado="Activo", activo=True)
        cercanas(-17.4, -66.2, categoria="Hidrológica", departamento="Cochabamba")
    """
    base = filtrar(CATALOGO, **filtros) if filtros else CATALOGO
    pares = [(e, _haversine_km(lat, lon, e.latitud, e.longitud)) for e in base]
    pares.sort(key=lambda p: p[1])
    if radio_km is not None:
        pares = [p for p in pares if p[1] <= radio_km]
    return pares[:tope]


def cercanas_meteo(lat: float, lon: float, tope: int = 10,
                     radio_km: Optional[float] = None,
                     solo_activas: bool = False) -> list[tuple[EstacionSENAMHI, float]]:
    """Atajo: estaciones meteorológicas más cercanas (filtra inactivas opcional)."""
    if solo_activas:
        return cercanas(lat, lon, tope=tope, radio_km=radio_km,
                          categoria="Meteorológica", estado="Activo")
    return cercanas(lat, lon, tope=tope, radio_km=radio_km,
                      categoria="Meteorológica")


def cercanas_hidro(lat: float, lon: float, tope: int = 10,
                    radio_km: Optional[float] = None,
                    solo_activas: bool = False) -> list[tuple[EstacionSENAMHI, float]]:
    """Atajo: estaciones hidrológicas más cercanas."""
    if solo_activas:
        return cercanas(lat, lon, tope=tope, radio_km=radio_km,
                          categoria="Hidrológica", estado="Activo")
    return cercanas(lat, lon, tope=tope, radio_km=radio_km,
                      categoria="Hidrológica")


# ───────────────────────── Estadísticas del catálogo ─────────────────────────

def estadisticas() -> dict:
    """Conteos por categoría / estado / tipo / departamento — útil para reporte."""
    from collections import Counter
    cat = Counter(e.categoria for e in CATALOGO)
    estado = Counter(e.estado for e in CATALOGO)
    tipo = Counter(e.tipo_estacion for e in CATALOGO)
    dep = Counter(e.nom_dep for e in CATALOGO)
    prop = Counter(e.propietario for e in CATALOGO)
    return {
        "total": len(CATALOGO),
        "por_categoria": dict(cat.most_common()),
        "por_estado": dict(estado.most_common()),
        "por_tipo": dict(tipo.most_common()),
        "por_departamento": dict(dep.most_common()),
        "por_propietario": dict(prop.most_common(10)),
    }
