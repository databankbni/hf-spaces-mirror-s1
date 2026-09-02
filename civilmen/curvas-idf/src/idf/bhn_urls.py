"""Generador de URLs canónicas para los boletines hidrológicos SENAMHI.

Encapsula los patrones de URL verificados por el deep-research (junio 2026) y
todas las inconsistencias del servidor: capitalización de mes, dobles espacios,
acentos variables, etc.

El servidor expone 5 familias de boletines bajo
`https://senamhi.gob.bo/meteorologia/boletines/`:

1. **Pronóstico hidrológico** (L, Mi, V): tres formatos por día (nacional,
   SAT-1, SAT-3, RESILIENTE).
2. **Monitoreo diario de niveles** (diario): el sustituto operativo del «BHN».
3. **Lago Titicaca técnico** (quincenal numerado) y **semanal**.
4. **Agromet decenal** (3 por mes × 6 macrorregiones).
5. **Predicción climática trimestral** (nacional + 9 departamentales).

Este módulo NO descarga; solo construye las URLs. La descarga la hace
`bhn_scraper.descargar_bhn_pdf`. Para cada URL «teórica» el servidor
devuelve 404 si el archivo no existe (días feriados, fines de semana
sin pronóstico, etc.).
"""

from __future__ import annotations

import datetime as dt
from typing import Iterator


BASE = "https://senamhi.gob.bo/meteorologia/boletines"

# Meses en castellano con capitalización inicial (hidrológico).
_MESES_CAP = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
# Meses en MAYÚSCULAS (agromet decenal).
_MESES_UPP = tuple(m.upper() for m in _MESES_CAP)
# Día de la semana publicado (L, Mi, V suelen tener pronóstico nacional).
_DIAS = {0: "LUNES", 1: "MARTES", 2: "MIÉRCOLES", 3: "JUEVES",
          4: "VIERNES", 5: "SÁBADO", 6: "DOMINGO"}


def url_monitoreo_diario(fecha: dt.date) -> str:
    """URL del «Boletín de monitoreo diario de niveles» (~BHN operativo)."""
    return (f"{BASE}/hidrologico/{fecha.year}/{_MESES_CAP[fecha.month-1]}/"
              f"BOLETIN DE MONITOREO DIARIO DE NIVELES "
              f"{fecha.day:02d}{fecha.month:02d}{fecha.year}.pdf")


def urls_pronostico_hidrologico(fecha: dt.date) -> list[str]:
    """Variantes del pronóstico hidrológico nacional para un día dado.

    Devuelve hasta 3 candidatos (resumen, nacional largo, nacional sin día).
    El servidor presenta inconsistencias (dobles espacios, acento opcional);
    se enumeran ambas alternativas y el scraper prueba en orden.
    """
    dia = _DIAS[fecha.weekday()]
    f1 = f"{fecha.day:02d}-{fecha.month:02d}-{fecha.year}"
    mes = _MESES_CAP[fecha.month-1]
    base = f"{BASE}/pronostico_hidrologico/{fecha.year}/{mes}"
    variantes = []
    # Con día y doble espacio
    for prefijo in ("RESUMEN DEL BOLETÍN DE PRONÓSTICO HIDROLÓGICO SENAMHI",
                      "PRONÓSTICO HIDROLÓGICO SENAMHI",
                      "PRONÓSTICO HIDROLÓGICO"):
        variantes.append(f"{base}/{prefijo} {dia}  {f1}.pdf")  # doble espacio real
        variantes.append(f"{base}/{prefijo} {dia} {f1}.pdf")
    # Sin día
    variantes.append(f"{base}/PRONÓSTICO HIDROLÓGICO {f1}.pdf")
    # Sin acento (a veces)
    variantes.append(f"{base}/PRONOSTICO HIDROLOGICO {f1}.pdf")
    return variantes


def urls_pronostico_resiliente(fecha: dt.date, programa: str = "sat1") -> list[str]:
    """Pronóstico hidrológico para los programas Bolivia Resiliente / SAT-1 / SAT-3."""
    dia = _DIAS[fecha.weekday()]
    f1 = f"{fecha.day:02d}-{fecha.month:02d}-{fecha.year}"
    mes = _MESES_CAP[fecha.month-1]
    sub = {"sat1": "BoliviaResiliente/sat1",
            "sat3": "BoliviaResiliente/sat3",
            "resumen": "BoliviaResiliente/resumen"}.get(programa, programa)
    prefijo = {"sat1": "SAT-1 PRONÓSTICO HIDROLÓGICO SENAMHI",
                "sat3": "SAT-3 PRONÓSTICO HIDROLÓGICO SENAMHI",
                "resumen": "RESILIENTE PRONÓSTICO HIDROLÓGICO SENAMHI"}.get(
                    programa, programa)
    base = f"{BASE}/pronostico_hidrologico/{sub}/{fecha.year}/{mes}"
    return [f"{base}/{prefijo} {dia}  {f1}.pdf",
            f"{base}/{prefijo} {dia} {f1}.pdf"]


def url_lago_titicaca_tecnico(fecha: dt.date) -> str:
    return (f"{BASE}/hidrologico/LagoTiticaca/{fecha.year}/"
              f"{_MESES_CAP[fecha.month-1]}/"
              f"Boletin Tecnico Hidrologico - Lago Titicaca "
              f"{fecha.day:02d}{fecha.month:02d}{fecha.year}.pdf")


def url_lago_titicaca_semanal(fecha: dt.date) -> str:
    """Boletín semanal del Titicaca: usa fecha de actualización con guion bajo."""
    fact = f"{fecha.day:02d}_{fecha.month:02d}_{fecha.year}"
    return (f"{BASE}/hidrologico/LagoTiticaca/{fecha.year}/"
              f"{_MESES_CAP[fecha.month-1]}/"
              f"LAGO TITICACA - BOLETIN Semanal (Actualizado {fact}).pdf")


def url_agromet_decenal(anio: int, mes: int, decena: int, region_idx: int,
                          region_nombre: str) -> str:
    """URL del agromet decenal para una región/decena/mes.

    `decena` ∈ {1,2,3}; `region_nombre` es el sufijo en MAYÚSCULAS
    (ALTIPLANO, LLANOS, AMAZONIA, CHIQUITANIA, YUNGAS Y CHAPARE, VALLES).
    `region_idx` es el orden visible en la URL (1..6).
    """
    return (f"https://senamhi.gob.bo/agromet/boletines_agrometeorologia/"
              f"boletines_decenales/{anio}/{_MESES_UPP[mes-1]}/"
              f"{decena} DECENA/{region_idx} BOLETÍN {region_nombre} "
              f"{anio}-{mes}-{decena}.pdf")


def url_agroclimatico_mensual(anio: int, mes: int, indice: int) -> str:
    return ("https://senamhi.gob.bo/agromet/boletines_agrometeorologia/"
              f"boletines_Agroclimatico/mensual_{anio}/"
              f"{indice} BOLETÍN_AGROCLIMÁTICO_{_MESES_UPP[mes-1]}_{anio}.pdf")


def url_prediccion_trimestral(anio: int, trimestre: str,
                                indice: int = 1,
                                departamento: str | None = None) -> str:
    """Predicción climática trimestral (nacional o por departamento).

    `trimestre` ∈ {EFM, FMA, MAM, AMJ, MJJ, JJA, JAS, ASO, SON, OND, NDE, DEF}.
    `indice` es el orden visible en la URL (típicamente correlacionado con
    el mes inicial del trimestre).
    """
    base = (f"{BASE}/tendencias/{anio}/"
              f"{indice:02d}_BOLETIN_PREDICCIÓN_{trimestre}_{anio}")
    if departamento:
        return f"{base}_{departamento.upper()}.pdf"
    return f"{base}.pdf"


def url_focos_calor(fecha: dt.date) -> str:
    return ("https://senamhi.gob.bo/focoscalor/"
              f"{fecha.year}/FC_{fecha.month:02d}_{_MESES_UPP[fecha.month-1]}_"
              f"{fecha.year}/Pron_Focos_Bolivia_"
              f"{fecha.year}{fecha.month:02d}{fecha.day:02d}.pdf")


# ─────────────────── Iteradores de rangos ───────────────────

def rango_monitoreo_diario(inicio: dt.date, fin: dt.date) -> Iterator[tuple[dt.date, str]]:
    """Itera fechas y URLs de monitoreo diario en el rango cerrado [inicio, fin]."""
    d = inicio
    while d <= fin:
        yield d, url_monitoreo_diario(d)
        d += dt.timedelta(days=1)


def rango_pronostico_hidrologico(inicio: dt.date, fin: dt.date,
                                      dias_publicacion: tuple = (0, 2, 4)
                                      ) -> Iterator[tuple[dt.date, list[str]]]:
    """Itera fechas L/Mi/V (default) con todas las variantes URL por fecha."""
    d = inicio
    while d <= fin:
        if d.weekday() in dias_publicacion:
            yield d, urls_pronostico_hidrologico(d)
        d += dt.timedelta(days=1)
