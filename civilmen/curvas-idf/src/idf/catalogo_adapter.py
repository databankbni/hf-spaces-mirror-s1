"""Adapter del catálogo SENAMHI (1 861 estaciones) → interfaz legacy del pipeline.

El catálogo oficial ingerido en `catalogo_senamhi.py` no incluye climatología
de precipitación (P24 media/desv) ni parámetros hidrológicos (Q medio/mín, área
de aporte), porque esos campos no están en el Excel maestro de SENAMHI. Sin
embargo todo el pipeline de Q mínimos (consistencia, ranking, ajuste de
frecuencia, plots, balance regional) espera esos campos en los dataclasses
legacy `EstacionSenamhi` y `EstacionHidro`.

Este módulo provee adapters que toman una `EstacionSENAMHI` del catálogo
oficial y la convierten a la forma legacy, completando los campos faltantes
con:

- **P24 climatológica**: interpolación IDW (1/d²) de las 3 estaciones más
  cercanas del catálogo curado de 49 (`data.ESTACIONES_SENAMHI`) que sí tienen
  estadísticos de P24 documentados.
- **Q climatológico hidro**: defaults regionales por departamento y cuenca
  macro (Amazonas / Plata / Altiplano), calibrados a partir de las 22
  estaciones hidrométricas curadas en `estaciones_hidro.ESTACIONES_HIDRO`.
- **Estado**: mapeo "Activo" → "activa", "Mantenimiento" → "intermitente",
  "Inactivo" → "pasiva".
- **Cuenca macro**: derivada de las coordenadas siguiendo divisorias
  aproximadas (Amazonas al N de -16, Plata al S, Altiplano lon ≤ -67).

Esto permite que toda la maquinaria existente del pipeline (Sección 2.1
consistencia OMM-168, 2.2 ranking, 2.3 ajustes MOVE.1, 2.4 mapa regional, 4.7
cálculos de Q ecológico, etc.) opere sobre 1 861 estaciones sin más cambios.
"""

from __future__ import annotations

from .catalogo_senamhi import EstacionSENAMHI
from .data import EstacionSenamhi, ESTACIONES_SENAMHI, estaciones_cercanas as _met_cercanas
from .estaciones_hidro import EstacionHidro


# ─────────────────── Climatología P24 por IDW ───────────────────

def p24_climatologico(lat: float, lon: float, k: int = 3) -> tuple[float, float]:
    """IDW (1/d²) de las k estaciones meteorológicas curadas más cercanas.

    Devuelve (p24_media_mm, p24_desv_mm) en mm. Si una estación cae < 1 km del
    sitio, devuelve sus valores directamente.
    """
    vecinas = _met_cercanas(lat, lon, k=k)
    if not vecinas:
        return 50.0, 15.0  # Default conservador para Bolivia central
    if vecinas[0][1] < 1.0:
        e0 = vecinas[0][0]
        return float(e0.p24_media_mm), float(e0.p24_desv_mm)
    w_sum = 0.0
    p_sum = 0.0
    d_sum = 0.0
    for e, dist in vecinas:
        w = 1.0 / max(dist, 0.5) ** 2
        w_sum += w
        p_sum += w * e.p24_media_mm
        d_sum += w * e.p24_desv_mm
    return p_sum / w_sum, d_sum / w_sum


# ─────────────────── Estado SENAMHI → legacy ───────────────────

_ESTADO_MAP = {
    "Activo": "activa",
    "activa": "activa",
    "Inactivo": "pasiva",
    "pasiva": "pasiva",
    "Mantenimiento": "intermitente",
    "intermitente": "intermitente",
}


def _estado_legacy(estado: str | None) -> str:
    if estado is None:
        return "activa"
    return _ESTADO_MAP.get(str(estado).strip(), "activa")


# ─────────────────── Códigos y nombres limpios ───────────────────

def _codigo(e: EstacionSENAMHI) -> str:
    """Genera un código alfanumérico estable de máx 16 caracteres."""
    if e.cod_omm:
        return f"OMM-{str(e.cod_omm).strip()[:11]}"
    if e.cod_oaci:
        return f"OACI-{str(e.cod_oaci).strip()[:10]}"
    # Hash corto del nombre + lat para evitar colisiones
    import hashlib
    base = f"{e.estacion}|{e.latitud:.4f}".encode("utf-8")
    h = hashlib.md5(base).hexdigest()[:6].upper()
    dep = (e.nom_dep or "BO")[:3].upper()
    return f"{dep}-{h}"


def _departamento_corto(e: EstacionSENAMHI) -> str:
    return (e.nom_dep or "Bolivia")[:24]


def _altitud(e: EstacionSENAMHI) -> float:
    if e.altura is None:
        return 0.0
    try:
        return float(e.altura)
    except (TypeError, ValueError):
        return 0.0


# ─────────────────── Adapter MET ───────────────────

def adaptar_met(e: EstacionSENAMHI) -> EstacionSenamhi:
    """Convierte una EstacionSENAMHI a EstacionSenamhi (con climatología IDW)."""
    p24m, p24d = p24_climatologico(e.latitud, e.longitud)
    return EstacionSenamhi(
        codigo=_codigo(e),
        nombre=str(e.estacion)[:40],
        departamento=_departamento_corto(e),
        latitud=float(e.latitud),
        longitud=float(e.longitud),
        altitud_msnm=_altitud(e),
        p24_media_mm=round(p24m, 1),
        p24_desv_mm=round(p24d, 1),
    )


# ─────────────────── Cuenca macro por coordenadas ───────────────────

def _cuenca_macro(lat: float, lon: float, altitud: float = 0.0) -> str:
    """Asigna la cuenca macro hidrográfica a partir de la posición geográfica.

    Reglas (basadas en los divisorios continentales aproximados):
    - Altiplano: lon ≤ -67 y lat entre -22 y -15 (depresión endorreica)
    - Amazonas: lat ≥ -17 (Beni/Mamoré/Madre de Dios) o lat < -17 con lon ≤ -65
    - Plata: el resto (sur de -17 con lon > -65)
    """
    if altitud >= 3500 and lat <= -15 and lon <= -67:
        return "Altiplano"
    if -22 <= lat <= -15 and lon <= -67.0:
        return "Altiplano"
    if lat >= -17 or (lat < -17 and lon <= -65):
        return "Amazonas"
    return "Plata"


# ─────────────────── Climatología Q por región ───────────────────

# Calibrado a partir del catálogo curado de 22 hidrométricas (estaciones_hidro.py).
# Por cuenca macro: (área_aporte_km2_default, q_medio_m3s, q_min_m3s)
_Q_DEFAULTS = {
    "Amazonas": (3000.0, 250.0, 35.0),
    "Plata":    (2500.0,  85.0,  8.0),
    "Altiplano": (800.0,  12.0,  1.5),
}


# ─────────────────── Adapter HIDRO ───────────────────

def adaptar_hidro(e: EstacionSENAMHI) -> EstacionHidro:
    """Convierte una EstacionSENAMHI a EstacionHidro con prioridad BHN sobre default.

    Estrategia:
    1. Busca en el caché BHN (poblado por scripts/scrape_bhn.py) usando el
       nombre de la estación; si hay match con ≥ 8 observaciones, usa Q
       medio/mín reales del boletín en lugar del default regional.
    2. Para el resto de campos (área aporte, cuerpo de agua, cuenca macro,
       años) se preserva la lógica de defaults regionales.
    """
    altitud = _altitud(e)
    macro = _cuenca_macro(e.latitud, e.longitud, altitud)
    area_def, q_med_def, q_min_def = _Q_DEFAULTS[macro]

    anio_ini = 1990
    if e.fecha_inicio:
        try:
            anio_ini = int(str(e.fecha_inicio)[:4])
        except (TypeError, ValueError):
            pass
    estado_leg = _estado_legacy(e.estado)
    if estado_leg == "pasiva":
        anio_fin = min(2024, anio_ini + 15)
    else:
        anio_fin = 2024
    if anio_fin <= anio_ini:
        anio_fin = anio_ini + 8

    nombre = str(e.estacion or "—")
    cuerpo = "—"
    for marcador in ("Río ", "río ", "Lago ", "Quebrada ", "Arroyo "):
        if marcador in nombre:
            cuerpo = nombre[nombre.index(marcador):][:30]
            break
    if cuerpo == "—":
        cuerpo = nombre.split("_")[0][:30]

    fuente = (e.propietario or "SENAMHI-BHN")[:20]
    q_medio = q_med_def
    q_min = q_min_def

    # Sobreescribe con BHN si está disponible para esta estación.
    try:
        from .bhn_cache import climatologia_de
        bhn = climatologia_de(nombre)
        if bhn is not None and bhn.n_observaciones >= 8:
            if bhn.caudal_medio_m3s is not None:
                q_medio = float(bhn.caudal_medio_m3s)
            if bhn.caudal_min_m3s is not None:
                q_min = float(bhn.caudal_min_m3s)
            if bhn.rio:
                cuerpo = bhn.rio[:30]
            if bhn.fecha_primera and bhn.fecha_ultima:
                try:
                    anio_ini = int(bhn.fecha_primera[:4])
                    anio_fin = int(bhn.fecha_ultima[:4])
                except ValueError:
                    pass
            fuente = "SENAMHI-BHN"
    except Exception:  # noqa: BLE001
        pass

    return EstacionHidro(
        codigo=_codigo(e),
        nombre=nombre[:32],
        cuerpo_agua=cuerpo,
        cuenca_macro=macro,
        departamento=_departamento_corto(e),
        fuente=fuente,
        latitud=float(e.latitud),
        longitud=float(e.longitud),
        altitud_msnm=altitud,
        area_aporte_km2=area_def,
        q_medio_m3s=q_medio,
        q_min_m3s=q_min,
        estado=estado_leg,
        anio_inicio=anio_ini,
        anio_fin=anio_fin,
    )


# ─────────────────── Búsqueda integrada (catálogo nuevo + adapter) ───────────────────

def met_cercanas_oficial(lat: float, lon: float,
                            radio_km: float = 100.0,
                            tope: int = 20,
                            solo_activas: bool = False
                            ) -> list[tuple[EstacionSenamhi, float]]:
    """Met del catálogo oficial dentro del radio, adaptadas a EstacionSenamhi."""
    from .catalogo_senamhi import cercanas_meteo
    pares = cercanas_meteo(lat, lon, tope=tope, radio_km=radio_km,
                              solo_activas=solo_activas)
    return [(adaptar_met(e), d) for e, d in pares]


def hidro_cercanas_oficial(lat: float, lon: float,
                              radio_km: float = 100.0,
                              tope: int = 20,
                              solo_activas: bool = False
                              ) -> list[tuple[EstacionHidro, float]]:
    """Hidro del catálogo oficial dentro del radio, adaptadas a EstacionHidro."""
    from .catalogo_senamhi import cercanas_hidro
    pares = cercanas_hidro(lat, lon, tope=tope, radio_km=radio_km,
                              solo_activas=solo_activas)
    return [(adaptar_hidro(e), d) for e, d in pares]
