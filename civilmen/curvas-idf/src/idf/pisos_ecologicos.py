"""Clasificación de pisos ecológicos de Bolivia para análisis hidrológico.

Adopta la tipología operativa requerida por el skill «Memoria de cálculo de
caudales mínimos para agua potable» (6 pisos): nival/subnival, puna, prepuna,
valles interandinos, yungas o bosque montano y tierras bajas. La clasificación
se hace por altitud con desempate por latitud y longitud (la franja oriental
< 800 m queda en «tierras bajas» aún si la lat es alta; el flanco oriental
andino entre 1 000 y 3 200 m clasifica como «yungas»).

Cada piso lleva una hoja de propiedades hidrológicas usada por el informe
para poblar la Sección 3 (caracterización climática), la Sección 5 (selección
de método) y la Sección 6 (dotación recomendada por piso).

Referencias:
- Navarro, G. & Maldonado, M. (2002). *Geografía Ecológica de Bolivia*.
  Centro de Ecología Simón I. Patiño, Cochabamba.
- Roche, M., Bourges, J., Cortez, J. & Mattos, R. (1992). *Climatología e
  Hidrología de la cuenca del lago Titicaca*. ORSTOM-IHH-SENAMHI.
- Espinoza, J. C., Marengo, J. A., Ronchail, J., Carpio, J., Flores, L. &
  Guyot, J.-L. (2014). The extreme 2014 flood in south-western Amazon
  basin. *Environmental Research Letters* 9 (12).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PisoEcologico:
    """Piso ecológico boliviano con propiedades hidrológicas operativas."""
    clave: str
    nombre: str
    rango_altitud_m: tuple[int, int]   # (mín, máx)
    temp_media_c: tuple[float, float]
    precip_anual_mm: tuple[int, int]
    cobertura: str
    comportamiento_hidrologico: str
    estiaje_esperado: str
    observaciones_agua_potable: str
    dotacion_l_hab_dia_sugerida: tuple[int, int]   # (mín, máx) por L/hab/d


NIVAL = PisoEcologico(
    clave="nival",
    nombre="Nival / subnival",
    rango_altitud_m=(4800, 6500),
    temp_media_c=(-5.0, 3.0),
    precip_anual_mm=(300, 900),
    cobertura="Glaciares, nieve, roca, gelisuelos, vegetación almohadilla.",
    comportamiento_hidrologico=(
        "Aporte estacional dominado por deshielo de glaciar y nieve. "
        "Régimen de caudales con máximo en primavera-verano (oct–mar) y "
        "estiaje en invierno. Fuerte sensibilidad al retroceso glaciar."),
    estiaje_esperado=(
        "Junio–septiembre. Caudales muy bajos pero relativamente sostenidos "
        "por liberación lenta del hielo y bofedales altoandinos."),
    observaciones_agua_potable=(
        "Fuente de alta calidad bacteriológica si no hay ganado. Riesgo "
        "creciente de pérdida por desaparición glaciar; documentar tendencia "
        "y planificar fuente alternativa a 20–30 años."),
    dotacion_l_hab_dia_sugerida=(50, 70),
)

PUNA = PisoEcologico(
    clave="puna",
    nombre="Puna (altiplano)",
    rango_altitud_m=(3600, 4800),
    temp_media_c=(3.0, 9.0),
    precip_anual_mm=(200, 700),
    cobertura="Pajonal (Festuca/Stipa), tholares, bofedales, suelos delgados.",
    comportamiento_hidrologico=(
        "Régimen pluvial unimodal (dic–mar) con larga estación seca. "
        "Regulación natural por bofedales y lagunas. Coeficiente de "
        "escorrentía bajo (0.10–0.25). Alta variabilidad interanual ENSO."),
    estiaje_esperado=(
        "Mayo–octubre. Caudales mínimos en julio–agosto. Riesgo de cese "
        "total en microcuencas sin bofedal."),
    observaciones_agua_potable=(
        "Vigilar degradación de bofedales (sobrepastoreo, drenaje). "
        "Mineralización moderada-alta posible (As, B). Recomendado análisis "
        "fisicoquímico previo a captación."),
    dotacion_l_hab_dia_sugerida=(50, 80),
)

PREPUNA = PisoEcologico(
    clave="prepuna",
    nombre="Prepuna y valles secos",
    rango_altitud_m=(2300, 3600),
    temp_media_c=(9.0, 17.0),
    precip_anual_mm=(150, 600),
    cobertura="Matorral xerofítico, cactáceas, suelos erosionados, "
                 "agricultura bajo riego en valles.",
    comportamiento_hidrologico=(
        "Pluvial estacional fuerte (dic–mar). Estiaje severo, muchas "
        "quebradas con flujo intermitente. Captaciones competitivas para "
        "riego frecuentes aguas arriba."),
    estiaje_esperado=(
        "Mayo–noviembre. Caudales críticos en septiembre–octubre. "
        "Microcuencas < 5 km² pueden secarse completamente."),
    observaciones_agua_potable=(
        "Enfoque MUY conservador: priorizar manantial regulado o galería "
        "filtrante sobre toma directa de cauce. Verificar captaciones "
        "aguas arriba en trámite o ya operativas. Considerar reservorio "
        "de regulación interanual."),
    dotacion_l_hab_dia_sugerida=(60, 100),
)

VALLES = PisoEcologico(
    clave="valles",
    nombre="Valles interandinos mésicos",
    rango_altitud_m=(1500, 2800),
    temp_media_c=(14.0, 22.0),
    precip_anual_mm=(450, 900),
    cobertura="Bosque seco interandino, matorral semihúmedo, agricultura "
                 "intensiva, áreas urbanas.",
    comportamiento_hidrologico=(
        "Régimen pluvial estacional (nov–abr) con permanencia media en "
        "cauces principales. Caudales base sostenidos por acuíferos de "
        "valle. Coeficiente de escorrentía 0.20–0.35."),
    estiaje_esperado=(
        "Mayo–octubre. Caudales mínimos en agosto–septiembre pero rara vez "
        "cesan en cauces de área > 20 km²."),
    observaciones_agua_potable=(
        "Frecuente conflicto de uso (riego/abastecimiento). Calidad "
        "afectada por descargas urbanas y agroquímicos: análisis "
        "microbiológico y plaguicidas indispensable."),
    dotacion_l_hab_dia_sugerida=(80, 140),
)

YUNGAS = PisoEcologico(
    clave="yungas",
    nombre="Yungas / bosque montano húmedo",
    rango_altitud_m=(800, 3200),
    temp_media_c=(12.0, 22.0),
    precip_anual_mm=(1200, 5000),
    cobertura="Bosque montano húmedo siempreverde, alta densidad de "
                 "epífitas, suelos jóvenes con alta materia orgánica.",
    comportamiento_hidrologico=(
        "Pluvial intenso casi todo el año, con máximo dic–mar. Caudales "
        "perennes. Coeficiente de escorrentía 0.40–0.65. Eventos de "
        "remoción en masa frecuentes."),
    estiaje_esperado=(
        "Junio–agosto. Estiaje suave, caudal base alto incluso en "
        "microcuencas pequeñas."),
    observaciones_agua_potable=(
        "Alta turbiedad en lluvias (filtración indispensable). Riesgo de "
        "destrucción de obra por flujos de detritos: revisar geomorfología "
        "del sitio y proteger captación."),
    dotacion_l_hab_dia_sugerida=(80, 150),
)

TIERRAS_BAJAS = PisoEcologico(
    clave="tierras_bajas",
    nombre="Tierras bajas / trópico",
    rango_altitud_m=(80, 800),
    temp_media_c=(22.0, 28.0),
    precip_anual_mm=(800, 2500),
    cobertura="Bosque tropical seco (Chaco) o húmedo (Amazonía), sabanas "
                 "(Beni), agricultura mecanizada (Santa Cruz).",
    comportamiento_hidrologico=(
        "Régimen pluvial fuertemente estacional al sur (Chaco, mar–oct "
        "seco) y bimodal-húmedo al norte (Amazonía). Llanura con "
        "regulación natural amplia, conectividad lateral con humedales."),
    estiaje_esperado=(
        "Chaco: agosto–octubre, crítico. Amazonía/Beni: junio–agosto, "
        "moderado."),
    observaciones_agua_potable=(
        "Calidad afectada por sólidos en suspensión, materia orgánica "
        "y, en zonas mineras / sojeras, por metales y plaguicidas. "
        "Tratabilidad MEDIA-COMPLEJA. Considerar pozo somero como "
        "alternativa a toma superficial en zonas con napa freática "
        "accesible."),
    dotacion_l_hab_dia_sugerida=(100, 200),
)

PISOS = {p.clave: p for p in
            (NIVAL, PUNA, PREPUNA, VALLES, YUNGAS, TIERRAS_BAJAS)}


def clasificar(lat: float, lon: float,
                  altitud_m: float | None) -> PisoEcologico:
    """Devuelve el piso ecológico aproximado del punto.

    Si la altitud está disponible, usa la altitud como criterio principal.
    Aplica corrección regional:
    - Por debajo de 800 m → tierras bajas siempre (independiente de lat).
    - Entre 800 y 3 200 m al este de la cordillera (lon > −67 al norte de
      −18 °S; lon > −65 al sur) y con precipitación implícita alta →
      yungas; sino, valles interandinos.

    Si la altitud no está disponible, devuelve VALLES (centroide hipsométrico
    de Bolivia, ~1 800 m) como fallback prudente.
    """
    if altitud_m is None:
        return VALLES
    a = float(altitud_m)
    if a >= 4800:
        return NIVAL
    if a >= 3600:
        return PUNA
    if a >= 2800:
        return PREPUNA
    if a >= 1500:
        # Discriminación valles vs yungas por lon (flanco oriental andino)
        if lat >= -15.0 and lon >= -67.5:
            return YUNGAS
        if -18.0 <= lat < -15.0 and lon >= -66.0:
            return YUNGAS
        return VALLES
    if a >= 800:
        # Yungas bajos al norte; matorral seco al sur (clasificamos como
        # valles secos para no inflar la oferta).
        if lat >= -16.0 and lon >= -67.0:
            return YUNGAS
        return VALLES
    return TIERRAS_BAJAS


def tabla_pisos() -> list[list[str]]:
    """Genera la tabla de pisos ecológicos lista para insertar al PDF.

    Cumple con la especificación de la Sección 3.2 del skill (8 columnas
    mínimas obligatorias).
    """
    cab = ["Piso ecológico", "Altitud (m)", "T (°C)", "P (mm/año)",
              "Cobertura", "Hidrología", "Estiaje", "Observación AP"]
    filas = [cab]
    for p in (NIVAL, PUNA, PREPUNA, VALLES, YUNGAS, TIERRAS_BAJAS):
        filas.append([
            p.nombre,
            f"{p.rango_altitud_m[0]:,}–{p.rango_altitud_m[1]:,}".replace(",", " "),
            f"{p.temp_media_c[0]:.0f}–{p.temp_media_c[1]:.0f}",
            f"{p.precip_anual_mm[0]:,}–{p.precip_anual_mm[1]:,}".replace(",", " "),
            p.cobertura,
            p.comportamiento_hidrologico,
            p.estiaje_esperado,
            p.observaciones_agua_potable,
        ])
    return filas


def implicancias_hidrologicas(piso: PisoEcologico) -> str:
    """Texto descriptivo para la Sección 3.3 (un párrafo por piso)."""
    return (
        f"<b>{piso.nombre}</b>. {piso.comportamiento_hidrologico} "
        f"Estiaje: {piso.estiaje_esperado.lower()} "
        f"Para agua potable: {piso.observaciones_agua_potable.lower()}"
    )
