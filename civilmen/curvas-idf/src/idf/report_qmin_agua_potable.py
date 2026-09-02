"""Memoria de cálculo de caudales mínimos para agua potable — informe PDF.

Implementa la estructura obligatoria del skill «Memoria de cálculo de
caudales mínimos para agua potable en Bolivia» (10 secciones + 8 anexos +
15 tablas mínimas obligatorias).

Esta es la fase 1 (PR1):
- Secciones 1–4 pobladas con datos reales del análisis.
- Secciones 5–9 con esqueleto y marcadores `[Pendiente — PR2/PR3]`.
- Bibliografía (Sección 10) completa con normas bolivianas.
- Lista de anexos A–H con descripción y marcador editable.

Las fases 2–3 reemplazarán los marcadores por cálculos reales (demanda
poblacional, balance oferta-demanda, verificación normativa, etc.).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from .report import (
    FONT, FONT_BOLD, FOOTER_AUTOR, FOOTER_EMAIL, FOOTER_TEL,
    PROTECCION_OWNER_PWD, _CanvasConPaginado, _estilos, _figura, _tabla,
)
from .pisos_ecologicos import (clasificar as clasificar_piso, tabla_pisos,
                                 implicancias_hidrologicas)
from .marco_normativo_bolivia import (tabla_marco_normativo, bibliografia_apa,
                                        NORMAS_PRIMARIAS)


HEADER_TEXTO = ("MEMORIA DE CALCULO - CAUDALES MINIMOS PARA AGUA POTABLE   "
                  "HYDROFRA V 1.3")


def _p(story, st, texto, estilo="cuerpo"):
    story.append(Paragraph(texto, st[estilo]))


def _img_si_existe(path: Path | None, ancho_cm: float = 16.0):
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return _figura(p, ancho_cm=ancho_cm)


def _pendiente(story, st, etiqueta: str, fase: str) -> None:
    """Inserta un marcador de sección/subseción pendiente de PRs futuras."""
    _p(story, st,
        f"[<b>{etiqueta}</b> — se desarrollará en {fase} del refactor. "
        f"Estructura editable, no genérica: cuando se incorporen los "
        f"cálculos de esta fase, esta nota se reemplaza por el contenido "
        f"calculado y verificable.]",
        "italica")


# ───────────────────────────────── Portada ────────────────────────────────

def _portada(story, st, d):
    fecha = datetime.utcnow().strftime("%d/%m/%Y")
    cuenca = d.get("cuenca_qmin")
    altitud = (getattr(cuenca, "cota_menor_m", None) if cuenca else None)
    piso = clasificar_piso(d["lat"], d["lon"], altitud)
    d["_piso_ecologico"] = piso

    story.append(Spacer(1, 3.0 * cm))
    _p(story, st,
        "MEMORIA DE CALCULO HIDROLOGICA", "titulo")
    _p(story, st,
        "Caudales mínimos para sistema de agua potable", "subt_centro")
    story.append(Spacer(1, 1.0 * cm))

    proyecto = d["proyecto"]
    cuenca_nombre = (d.get("ubicacion_cuenca")
                       or getattr(proyecto, "ubicacion", "—"))
    info = [
        ["Proyecto", getattr(proyecto, "nombre_proyecto", "—")],
        ["Cuenca / subcuenca", cuenca_nombre],
        ["Departamento / Municipio", d.get("ubicacion_admin",
                                            getattr(proyecto, "ubicacion", "—"))],
        ["Piso ecológico", piso.nombre],
        ["Punto de captación", f"Lat {d['lat']:.6f}°  ·  "
                                 f"Lon {d['lon']:.6f}°"],
        ["Altitud", (f"{altitud:.0f} m" if altitud is not None
                     else "[validar con DEM o aforo]")],
        ["Ingeniero a cargo", getattr(proyecto, "ingeniero", "—")],
        ["Entidad / consultora", "HYDROFRA — Ing. Luis Franco Guarachi"],
        ["Fecha de emisión", fecha],
        ["Código del documento",
            f"HYDROFRA-QMIN-AP-{datetime.utcnow().strftime('%Y%m')}"],
        ["Versión", "1.0 (PR1 — estructura y secciones 1–4 completas)"],
    ]
    story.append(_tabla(info, col_widths=[6 * cm, 11 * cm], cabecera=False,
                          primera_col_izq=True))
    story.append(Spacer(1, 1.2 * cm))
    _p(story, st,
        "Documento protegido (AES-128). El archivo se puede abrir y leer "
        "pero no imprimir, copiar, editar ni anotar. Para uso y citación "
        f"contactar a {FOOTER_AUTOR} ({FOOTER_EMAIL}, {FOOTER_TEL}).",
        "italica")
    story.append(PageBreak())


# ─────────────────────────── 1. Generalidades ─────────────────────────────

def _seccion_1(story, st, d):
    _p(story, st, "1. GENERALIDADES", "h2")

    _p(story, st, "1.1 Objeto y alcance", "h3")
    _p(story, st,
        "El presente informe tiene por objeto determinar el caudal mínimo "
        "disponible de la fuente para el abastecimiento de agua potable del "
        f"proyecto «{getattr(d['proyecto'], 'nombre_proyecto', '—')}», "
        "evaluando la suficiencia hídrica frente a la demanda poblacional "
        "proyectada, las restricciones ambientales aplicables y la "
        "confiabilidad del aprovechamiento en el horizonte de diseño.")

    _p(story, st, "1.2 Antecedentes", "h3")
    _p(story, st,
        "[Resumir el problema de abastecimiento que motiva el proyecto, "
        "la fuente propuesta, las gestiones previas realizadas y el "
        "contexto territorial del área servida — completar con datos "
        "del expediente del proyecto.]", "italica")

    _p(story, st, "1.3 Objetivos", "h3")
    _p(story, st, "<b>Objetivo general.</b> Determinar el caudal mínimo "
                     "disponible de la fuente y verificar su suficiencia para "
                     "abastecer la demanda de agua potable proyectada, en "
                     "cumplimiento del marco normativo boliviano vigente.")
    _p(story, st, "<b>Objetivos específicos:</b>")
    for it in (
        "Caracterizar la cuenca de aporte y la fuente hidrológicamente.",
        "Inventariar y evaluar la información hidrometeorológica disponible.",
        "Estimar el caudal mínimo de diseño con enfoque multimétodo.",
        "Calcular la demanda de agua potable para el horizonte de diseño.",
        "Verificar el cumplimiento de la normativa nacional aplicable.",
        "Emitir conclusión técnica sobre la viabilidad de la fuente.",
    ):
        _p(story, st, f"• {it}")

    _p(story, st, "1.4 Alcance técnico", "h3")
    _p(story, st, "El estudio cubre:")
    for it in (
        "Diagnóstico de la fuente (Sección 2).",
        "Clasificación por piso ecológico y caracterización climática (Sección 3).",
        "Inventario de información hidrometeorológica (Sección 4).",
        "Estimación de caudal mínimo por método multivariable (Sección 5 — PR2).",
        "Cálculo de demanda de agua potable según NB 689 (Sección 6 — PR2).",
        "Balance oferta-demanda con respeto a caudal ecológico (Sección 7 — PR2).",
        "Verificación normativa (NB 512, Ley 1333, RMCH) (Sección 8 — PR3).",
        "Anexos cartográficos y hojas de cálculo (Anexos A–H — PR3).",
    ):
        _p(story, st, f"• {it}")

    _p(story, st, "1.5 Marco normativo aplicable (Tabla 1)", "h3")
    story.append(_tabla(tabla_marco_normativo(),
                          col_widths=[5.5 * cm, 5.5 * cm, 6 * cm]))

    _p(story, st, "1.6 Limitaciones de información", "h3")
    diags = d.get("diagnosticos_consistencia") or []
    n_hidro = sum(1 for x in diags if x.tipo == "hidro")
    n_met = sum(1 for x in diags if x.tipo == "met")
    _p(story, st,
        f"Se procesaron {n_met} estaciones meteorológicas y {n_hidro} "
        f"hidrométricas del catálogo SENAMHI dentro del radio operativo "
        f"de {d.get('radio_km', 100)} km. Limitaciones detectadas:")
    for it in (
        ("Cobertura hidrométrica escasa para microcuencas: en Bolivia muchas "
         "cuencas pequeñas no tienen estación de caudal directa, lo que "
         "obliga a estimaciones indirectas (balance hídrico, transposición)."),
        ("Discontinuidad de series: las series operativas muestran vacíos y "
         "cambios de operador (SENAMHI-BHN, GRDC, MMAyA), por lo que se "
         "aplica panel de consistencia OMM-168 antes de seleccionar."),
        ("Representatividad espacial limitada cuando las estaciones más "
         "próximas pertenecen a otro piso ecológico que el de la cuenca de "
         "estudio."),
        ("Uso necesario de métodos indirectos (balance P→Q, fórmulas "
         "regionales, transposición) implica una incertidumbre que se "
         "explicita en cada paso y se compensa con criterios conservadores."),
    ):
        _p(story, st, f"• {it}")


# ────────────────────── 2. Descripción de la cuenca ───────────────────────

def _seccion_2(story, st, d, sesion_dir: Path):
    story.append(PageBreak())
    _p(story, st, "2. DESCRIPCIÓN GENERAL DE LA CUENCA", "h2")

    _p(story, st, "2.1 Ubicación geográfica (Tabla 2)", "h3")
    cuenca = d.get("cuenca_qmin")
    altitud_capt = (getattr(cuenca, "cota_menor_m", None) if cuenca else None)
    ub = [
        ["Departamento", "[completar — datos administrativos del sitio]"],
        ["Municipio", "[completar]"],
        ["Comunidad", "[completar]"],
        ["Coordenadas geográficas",
            f"Lat {d['lat']:.6f}°  ·  Lon {d['lon']:.6f}°"],
        ["Datum / sistema", "WGS-84 (EPSG:4326)"],
        ["Zona UTM", "[derivar de la longitud según corresponda 19/20 K-S]"],
        ["Altitud del punto de captación",
            (f"{altitud_capt:.0f} m s.n.m." if altitud_capt is not None
             else "[validar con DEM SRTM 90 m]")],
        ["Cuenca principal", "[completar — cuenca hidrográfica nivel 1]"],
        ["Subcuenca / microcuenca",
            (f"Aporte delineado por MERIT Hydro D8 — A = "
             f"{cuenca.area_km2:.2f} km²" if cuenca is not None
             else "[delineación no disponible — verificar manualmente]")],
    ]
    story.append(_tabla(ub, col_widths=[6.5 * cm, 10 * cm], cabecera=False,
                          primera_col_izq=True))

    _p(story, st, "2.2 Accesibilidad y descripción de la fuente", "h3")
    _p(story, st,
        "[Describir: tipo de acceso al sitio; estado actual del cauce o "
        "manantial; uso actual del agua; infraestructura existente; "
        "condiciones de estiaje observadas en campo; posibles "
        "interferencias por captaciones aguas arriba — completar con "
        "ficha de inspección.]", "italica")

    _p(story, st, "2.3 Parámetros morfométricos de la cuenca (Tabla 3)", "h3")
    if cuenca is not None:
        morf = [
            ["Parámetro", "Valor", "Unidad", "Observación"],
            ["Área de cuenca (A)", f"{cuenca.area_km2:.2f}", "km²",
                "Delineada con MERIT Hydro 90 m + D8 watershed"],
            ["Perímetro (P)", f"{cuenca.perimetro_km:.2f}", "km",
                "Perímetro de la cuenca proyectado"],
            ["Longitud del cauce principal (L)",
                f"{cuenca.long_cauce_km:.2f}", "km",
                "Cauce de mayor recorrido desde divisoria"],
            ["Pendiente media del cauce (S)",
                f"{cuenca.pendiente_media_mm * 100:.2f}", "%",
                "Δh_cauce / L"],
            ["Altitud máxima (H_máx)",
                f"{cuenca.cota_mayor_m:.0f}", "m s.n.m.",
                "Punto más alto de la cuenca"],
            ["Altitud mínima (H_mín)",
                f"{cuenca.cota_menor_m:.0f}", "m s.n.m.",
                "Cota del punto de captación"],
            ["Desnivel total (ΔH)",
                f"{cuenca.desnivel_m:.0f}", "m", "H_máx − H_mín"],
        ]
        # Coeficiente de compacidad Kc, factor de forma Ff, densidad de drenaje
        from math import pi, sqrt
        Kc = 0.282 * cuenca.perimetro_km / sqrt(cuenca.area_km2)
        Ff = cuenca.area_km2 / (cuenca.long_cauce_km ** 2)
        red = getattr(cuenca, "red_drenaje", None) or {}
        long_total = red.get("long_total_km")
        Dd = (long_total / cuenca.area_km2) if long_total else None
        morf.append(["Coeficiente de compacidad (Kc)", f"{Kc:.2f}", "—",
                      ("Kc≈1: circular; Kc>1.5: alargada, menor riesgo "
                       "de crecidas concentradas")])
        morf.append(["Factor de forma (Ff)", f"{Ff:.3f}", "—",
                      "A / L²; valores bajos indican cuenca alargada"])
        morf.append(["Densidad de drenaje (Dd)",
                      (f"{Dd:.2f}" if Dd is not None
                       else "[calcular con red MERIT detallada]"),
                      "km/km²",
                      "Σ longitudes cauces / A"])
        morf.append(["Tiempo de concentración (Tc)",
                      "[calcular si se requiere — referencia complementaria]",
                      "min",
                      "Para Q mín no es crítico; reportar en informe Q máx"])
        story.append(_tabla(morf,
                              col_widths=[5 * cm, 3 * cm, 1.5 * cm, 6.5 * cm]))
        img = _img_si_existe(sesion_dir / "qmin_cuenca.png", ancho_cm=15)
        if img:
            story.append(Spacer(1, 6))
            story.append(img)
    else:
        _p(story, st,
            "[Delineación MERIT Hydro no disponible. Completar con "
            "herramienta SIG externa (QGIS + DEM SRTM 90 m + r.watershed).]",
            "italica")

    _p(story, st, "2.4 Fórmulas morfométricas mínimas", "h3")
    formulas = [
        ["Variable", "Fórmula", "Notas"],
        ["Coef. compacidad (Kc)", "Kc = 0.282 · P / √A",
            "Gravelius. Kc=1 → circular; Kc>1.5 → alargada"],
        ["Factor de forma (Ff)", "Ff = A / L²",
            "Horton. Ff < 0.3 → cuenca alargada"],
        ["Densidad de drenaje (Dd)", "Dd = Σ Lᵢ / A",
            "Horton. Dd alto → respuesta rápida, mayor erosión"],
        ["Pendiente media cauce (S)", "S = ΔH_cauce / L",
            "Adoptada para análisis general; alternativas: S₈₅₋₁₀ o "
            "método del rectángulo equivalente"],
    ]
    story.append(_tabla(formulas, col_widths=[5 * cm, 5 * cm, 6 * cm]))


# ─────────────────── 3. Piso ecológico y caracterización ──────────────────

def _seccion_3(story, st, d, sesion_dir: Path):
    story.append(PageBreak())
    _p(story, st, "3. PISO ECOLÓGICO Y CARACTERIZACIÓN CLIMÁTICA", "h2")

    piso = d.get("_piso_ecologico")
    if piso is None:
        cuenca = d.get("cuenca_qmin")
        altitud = (getattr(cuenca, "cota_menor_m", None) if cuenca else None)
        piso = clasificar_piso(d["lat"], d["lon"], altitud)

    _p(story, st, "3.1 Identificación del piso ecológico", "h3")
    _p(story, st,
        f"Con base en la altitud del punto de captación y su ubicación "
        f"regional, la cuenca se clasifica en el piso ecológico "
        f"<b>{piso.nombre}</b> (rango altitudinal "
        f"{piso.rango_altitud_m[0]:,}–{piso.rango_altitud_m[1]:,} m s.n.m.). "
        f"Esta clasificación condiciona el régimen hidrológico esperable, "
        f"la temporada óptima de aforo y los criterios de dotación a aplicar "
        f"en la Sección 6.".replace(",", " "))

    _p(story, st, "3.2 Tabla de pisos ecológicos de Bolivia (Tabla 4)", "h3")
    story.append(_tabla(tabla_pisos(),
                          col_widths=[2.3 * cm, 2.0 * cm, 1.3 * cm, 1.8 * cm,
                                       2.5 * cm, 2.5 * cm, 2.3 * cm, 2.3 * cm]))

    _p(story, st, "3.3 Implicancias hidrológicas por piso ecológico", "h3")
    _p(story, st, implicancias_hidrologicas(piso))
    _p(story, st,
        "El comportamiento descrito justifica los criterios adoptados en "
        "la Sección 5 (multimétodo) y en la Sección 7 (balance "
        "oferta-demanda) para esta cuenca.")

    _p(story, st, "3.4 Caracterización climática", "h3")
    stats = d.get("stats_qmin") or {}
    pq = d.get("pq")
    pann = stats.get("pann_mm") or (getattr(pq, "pann_mm", None)
                                       if pq else None)
    eta = stats.get("eta_mm") or (getattr(pq, "etann_mm", None)
                                     if pq else None)
    p_mes = (pq.p_mes_mm.tolist() if pq is not None
              and hasattr(pq, "p_mes_mm") and pq.p_mes_mm is not None
              else None)
    clima = [
        ["Variable", "Valor", "Fuente"],
        ["Precipitación media anual",
            (f"{pann:.0f} mm/año" if pann else "[validar con SENAMHI]"),
            d.get("clima_fuente", "—")],
        ["Evapotranspiración real anual",
            (f"{eta:.0f} mm/año" if eta else "[Budyko / Penman]"),
            "Aprox. Budyko sobre PET"],
        ["Temperatura media",
            f"{piso.temp_media_c[0]:.0f}–{piso.temp_media_c[1]:.0f} °C "
            f"(rango del piso)",
            "Pisos ecológicos"],
        ["Meses húmedos",
            ("nov–mar (ENE-FEB pico)" if piso.clave in ("puna", "prepuna",
                                                            "valles")
             else "dic–mar / oct–abr"),
            "Régimen pluvial regional"],
        ["Meses secos",
            piso.estiaje_esperado, "Estiaje del piso ecológico"],
        ["Mes crítico de estiaje",
            ("Julio–agosto" if piso.clave in ("puna", "nival")
             else "Agosto–septiembre" if piso.clave in ("prepuna", "valles")
             else "Septiembre–octubre"),
            "Régimen pluvial regional"],
    ]
    story.append(_tabla(clima, col_widths=[5 * cm, 5 * cm, 6 * cm]))

    # Si hay precipitación mensual, dejamos la fila «P media mensual» como
    # tabla compacta adicional.
    if p_mes and len(p_mes) == 12:
        meses = ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
        cab = ["Mes"] + meses + ["Total"]
        vals = ["P (mm)"] + [f"{x:.0f}" for x in p_mes] + [
            f"{sum(p_mes):.0f}"]
        story.append(Spacer(1, 6))
        story.append(_tabla([cab, vals],
                              col_widths=[2 * cm] + [1 * cm] * 12 + [1.5 * cm]))

    _p(story, st, "3.5 Interpretación climática para el proyecto", "h3")
    _p(story, st,
        f"La fuente se ubica en un piso <b>{piso.nombre.lower()}</b>, con "
        f"el patrón climático arriba descrito. Esto implica que:")
    for it in (
        (f"La temporada recomendada de aforo para captura del estiaje es "
         f"<b>{piso.estiaje_esperado.lower()}</b>."),
        (f"La confiabilidad de la fuente es {('alta' if piso.clave in ('yungas', 'valles', 'tierras_bajas') else 'moderada con riesgo de cese en años secos')}."),
        (f"La vulnerabilidad frente a sequía multianual y a cambio "
         f"climático es {('alta' if piso.clave in ('nival', 'puna', 'prepuna') else 'moderada')}, lo que se evalúa en la Sección 8.3."),
    ):
        _p(story, st, f"• {it}")


# ─────────────────── 4. Información hidrometeorológica ────────────────────

def _seccion_4(story, st, d, sesion_dir: Path):
    story.append(PageBreak())
    _p(story, st, "4. INFORMACIÓN HIDROMETEOROLÓGICA DISPONIBLE", "h2")

    met = d.get("met_cercanas") or []
    hidro = d.get("hidro_cercanas") or []

    _p(story, st, "4.1 Inventario de estaciones (Tabla 5)", "h3")
    if met or hidro:
        cab = ["#", "Código", "Nombre", "Tipo", "Operador",
                  "Coord. (lat, lon)", "Altitud (m)", "Distancia (km)"]
        filas = [cab]
        i = 0
        for e, dist in met[:15]:
            i += 1
            filas.append([str(i), e.codigo, e.nombre, "Met.", "SENAMHI",
                            f"{e.lat:.4f}, {e.lon:.4f}",
                            f"{e.altitud_msnm:.0f}", f"{dist:.1f}"])
        for e, dist in hidro[:15]:
            i += 1
            filas.append([str(i), e.codigo, e.nombre, "Hidro.",
                            getattr(e, "fuente", "SENAMHI-BHN"),
                            f"{e.lat:.4f}, {e.lon:.4f}",
                            (f"{e.altitud_msnm:.0f}"
                             if getattr(e, "altitud_msnm", None) else "—"),
                            f"{dist:.1f}"])
        story.append(_tabla(filas, col_widths=[0.8 * cm, 2 * cm, 3.5 * cm,
                                                  1.3 * cm, 2 * cm, 3 * cm,
                                                  1.6 * cm, 1.8 * cm]))
    else:
        _p(story, st,
            "[Sin estaciones dentro del radio operativo — completar con "
            "ampliación del radio o búsqueda manual en catálogo SENAMHI.]",
            "italica")

    _p(story, st, "4.2 Fuentes de información", "h3")
    for it in (
        "<b>Estaciones SENAMHI</b>: catálogo oficial 1 861 sitios "
        "(meteorológicas + hidrométricas).",
        "<b>Aforos de campo</b>: a documentar en Anexo E (planilla por "
        "fecha, hora, método, sección, ancho, tirante, velocidad, caudal).",
        "<b>Cartografía base</b>: hojas IGM 1:50 000 y/o cartografía "
        "departamental cuando disponible.",
        "<b>DEM</b>: SRTM v3 30 m + MERIT Hydro 90 m para delineación de "
        "cuenca y caracterización hipsométrica.",
        "<b>Ortofotos / imágenes satelitales</b>: Sentinel-2 L2A (10 m) "
        "para inspección de la fuente y la cobertura.",
        "<b>Productos de precipitación</b>: CHIRPS Daily 0.05° (1981–"
        "presente), NASA POWER (1981–presente), Open-Meteo ERA5 reanálisis, "
        "Saavedra & Ureña 2022 (Zenodo) cuando aplique.",
    ):
        _p(story, st, f"• {it}")

    _p(story, st, "4.3 Evaluación de calidad y completitud", "h3")
    diags = d.get("diagnosticos_consistencia") or []
    if diags:
        _p(story, st,
            "Panel OMM-168 (5 pruebas) aplicado a cada serie candidata: "
            "Mann-Kendall (tendencia), Pettitt (cambio brusco), rachas "
            "(aleatoriedad), autocorrelación Lag-1 (independencia) y "
            "Kolmogorov-Smirnov (mejor distribución).")
        cab = ["#", "Código", "Tipo", "n años", "Kendall", "Pettitt",
                  "Rachas", "Lag-1", "KS", "Pasa", "Clase", "Apta"]
        filas = [cab]
        for i, x in enumerate(diags[:20], 1):
            filas.append([
                str(i), x.codigo, "Met." if x.tipo == "met" else "Hidro.",
                str(x.n_anios),
                "✓" if x.pasa_kendall else "✗",
                "✓" if x.pasa_pettitt else "✗",
                "✓" if x.pasa_rachas else "✗",
                "✓" if x.pasa_lag1 else "✗",
                "✓" if x.pasa_ks else "✗",
                f"{x.pruebas_pasadas}/5",
                x.clase,
                "✓" if x.apta else "—",
            ])
        story.append(_tabla(filas))
    else:
        _p(story, st,
            "[Sin diagnóstico de consistencia disponible — ejecutar panel "
            "OMM-168 sobre las series candidatas y volcar resultado.]",
            "italica")

    _p(story, st, "4.4 Tratamiento de series", "h3")
    for it in (
        "<b>Corrección de vacíos</b>: regresión lineal con estación de "
        "mayor correlación; vacíos > 20 % anuales descartan el año.",
        "<b>Homogeneización</b>: doble masa contra promedio regional; "
        "puntos de inflexión activan la subdivisión de la serie.",
        "<b>Período adoptado</b>: el de mayor traslapo común que cumpla "
        "el panel OMM-168 con n ≥ 15 años hidrológicos completos.",
    ):
        _p(story, st, f"• {it}")

    _p(story, st, "4.5 Datos de precipitación (Tabla 6)", "h3")
    pq = d.get("pq")
    if pq is not None and getattr(pq, "p_mes_mm", None) is not None:
        meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        cab = ["Estadístico"] + meses + ["Anual"]
        vals = list(pq.p_mes_mm)
        media = [f"{x:.1f}" for x in vals]
        filas = [
            cab,
            ["Media (mm)"] + media + [f"{sum(vals):.0f}"],
            ["Mín."] + [f"{0.6 * x:.1f}" for x in vals]
                + [f"{0.6 * sum(vals):.0f} (∼año seco)"],
            ["Máx."] + [f"{1.4 * x:.1f}" for x in vals]
                + [f"{1.4 * sum(vals):.0f} (∼año húmedo)"],
        ]
        story.append(_tabla(filas,
                              col_widths=[2 * cm] + [1 * cm] * 12 + [2 * cm]))
        _p(story, st,
            f"Fuente climatológica adoptada: <b>{d.get('clima_fuente', '—')}</b>. "
            f"Los valores mín/máx mostrados son referenciales (±40 % sobre la "
            f"media climática) hasta que se incorpore la serie diaria al "
            f"análisis.", "italica")
    else:
        _p(story, st,
            "[Sin climatología mensual disponible — completar con grilla "
            "CHIRPS Daily o SENAMHI-IDW para el centroide de la cuenca.]",
            "italica")

    _p(story, st, "4.6 Datos de caudal disponibles", "h3")
    if hidro:
        _p(story, st,
            f"Se identificaron <b>{len(hidro)}</b> estaciones hidrométricas "
            f"dentro del radio operativo. Datos resumen de las 5 más "
            f"próximas:")
        cab = ["#", "Código", "Cuerpo de agua", "Q medio (m³/s)",
                  "Q mín (m³/s)", "Período", "Limitación"]
        filas = [cab]
        for i, (e, _) in enumerate(hidro[:5], 1):
            filas.append([
                str(i), e.codigo,
                f"{e.nombre} — {getattr(e, 'cuerpo_agua', '—')}",
                f"{getattr(e, 'q_medio_m3s', 0):.2f}",
                f"{getattr(e, 'q_min_m3s', 0):.2f}",
                (f"{e.anio_inicio}–{e.anio_fin}"
                 if getattr(e, 'anio_inicio', None) else "—"),
                getattr(e, 'estado', '—'),
            ])
        story.append(_tabla(filas))
    else:
        _p(story, st,
            "<b>NO existe estación hidrométrica directa en la microcuenca de "
            "estudio.</b> El análisis se sostiene en métodos indirectos "
            "(balance hídrico, transposición regional y aforos de "
            "verificación de campo), conforme a lo previsto en la "
            "Sección 5.")


# ────── Secciones 5–9: estructura editable con marcadores [PR2/PR3] ──────

def _seccion_5(story, st, d, sesion_dir: Path):
    story.append(PageBreak())
    _p(story, st, "5. METODOLOGÍA PARA ESTIMACIÓN DE CAUDALES MÍNIMOS", "h2")
    _p(story, st,
        "Por la realidad de la red hidrométrica boliviana, se adopta un "
        "enfoque multimétodo. El valor final adoptado es el más "
        "conservador entre los métodos confiables, con factor de seguridad "
        "explícito cuando la incertidumbre es alta.")

    pq = d.get("pq")
    transpo = d.get("ap_transposicion")
    estimaciones = d.get("ap_estimaciones") or []
    balance = d.get("ap_balance")

    _p(story, st, "5.1 Método 1 — Aforo directo en campo", "h3")
    _p(story, st,
        "Aforos en al menos 3 jornadas de estiaje (jul–ago) con metodología "
        "ISO 748: molinete / sección-velocidad para Q > 50 L/s; vertedero "
        "portátil o método volumétrico para Q < 50 L/s. Planilla por aforo "
        "en el Anexo E. <b>Estado en este informe:</b> pendiente de campaña "
        "de campo — necesario antes de aprobar la obra.")

    _p(story, st,
        "5.2 Método 2 — Balance hídrico mensual (Thornthwaite-Mather)", "h3")
    if pq is not None:
        bal_mes = [
            ["Mes", "P (mm)", "ETR (mm)", "Q (mm)", "Q (m³/s)"],
        ]
        try:
            for i, mes in enumerate(("Ene", "Feb", "Mar", "Abr", "May", "Jun",
                                          "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")):
                p_m = pq.p_mes_mm[i] if hasattr(pq, "p_mes_mm") else 0
                q_m = pq.q_mes_m3s[i] if hasattr(pq, "q_mes_m3s") else 0
                # ETR ≈ P − Q (cierre del balance) sin ΔS detallado
                etr = max(p_m - q_m * 1000 * 86400 * 30 / 1e6, 0)
                bal_mes.append([mes, f"{p_m:.1f}", f"{etr:.1f}",
                                  f"{(p_m - etr):.1f}", f"{q_m:.3f}"])
            story.append(_tabla(bal_mes,
                                  col_widths=[1.5 * cm, 1.8 * cm,
                                               1.8 * cm, 1.8 * cm, 2 * cm]))
        except Exception:
            _p(story, st,
                "[Tabla mensual no disponible — completar a partir de la "
                "serie mensual del balance P→Q.]", "italica")
        _p(story, st,
            f"Q mínimo mensual estimado: <b>{pq.q_min_m3s * 1000:.2f} L/s</b> "
            f"(coef. escorrentía anual {pq.coef_escorrentia_anual:.2f}; "
            f"CAW={pq.caw_usada_mm:.0f} mm).")
    else:
        _p(story, st,
            "[Balance P→Q no disponible — climatología insuficiente.]",
            "italica")

    _p(story, st,
        "5.3 Método 3 — Transposición hidrológica (cuenca análoga)", "h3")
    if transpo is not None:
        from .transposicion_hidrologica import tabla_comparativa
        _p(story, st,
            f"Q₂ = Q₁ · (A₂/A₁)^n  con n = {transpo.exponente_n:.2f}. Donante "
            f"seleccionada por similitud: <b>{transpo.donante.codigo} — "
            f"{transpo.donante.nombre}</b> "
            f"(distancia {transpo.donante.distancia_km:.0f} km, "
            f"similitud {transpo.similitud_clasificacion.upper()}).")
        story.append(_tabla(tabla_comparativa(transpo),
                              col_widths=[5.5 * cm, 5.5 * cm, 6 * cm]))
        if transpo.advertencias:
            _p(story, st, "Advertencias detectadas:", "h3")
            for a in transpo.advertencias:
                _p(story, st, f"• {a}")
    else:
        _p(story, st,
            "[Sin cuenca donante adecuada en el radio operativo — método "
            "no aplicado. Buscar manualmente en catálogo GRDC o repetir "
            "análisis ampliando el radio.]", "italica")

    _p(story, st, "5.4 Método 4 — Curva de duración, Q95 y 7Q10", "h3")
    if pq is not None:
        _p(story, st,
            f"De la FDC simulada del balance P→Q: Q95 = "
            f"<b>{pq.q95 * 1000:.2f} L/s</b>, Q90 = {pq.q90 * 1000:.2f} L/s, "
            f"Q75 = {pq.q75 * 1000:.2f} L/s. Q7,10 ≈ "
            f"<b>{pq.q7_10 * 1000:.2f} L/s</b>. Valores reemplazables "
            f"cuando se incorpore la serie diaria hidrométrica.")
    else:
        _p(story, st, "[FDC no calculada — sin serie suficiente.]", "italica")

    _p(story, st, "5.5 Método 5 — Criterio de caudal ecológico", "h3")
    if balance and balance.q_ecologico_m3s > 0:
        _p(story, st,
            f"Caudal ecológico adoptado: <b>"
            f"{balance.q_ecologico_m3s * 1000:.2f} L/s</b> "
            f"(método: <i>{balance.q_ecologico_metodo}</i>). Se computa "
            f"como la mediana de los métodos calculados (Tennant 30 %, "
            f"Tessman, Smakhtin Q90, Texas TPWD, Q7,10 ecológico) y se "
            f"resta de la oferta antes de calcular el balance.")
    else:
        _p(story, st,
            "[Caudal ecológico no calculado — verificar bloque de eco "
            "(ce_lista) del worker.]", "italica")

    _p(story, st,
        "5.6 Comparación de resultados entre métodos (Tabla 10)", "h3")
    if balance:
        from .balance_oferta_demanda import tabla_sintesis_oferta
        story.append(_tabla(tabla_sintesis_oferta(balance),
                              col_widths=[4.5 * cm, 2 * cm, 4.5 * cm,
                                           2 * cm, 4 * cm]))

    _p(story, st, "5.7 Selección del caudal mínimo de diseño", "h3")
    if balance:
        _p(story, st,
            f"Caudal mínimo adoptado: "
            f"<b>{balance.q_min_adoptado_m3s * 1000:.2f} L/s</b>. "
            f"Criterio: {balance.metodo_adoptado}. "
            f"Factor de seguridad aplicado: {balance.factor_seguridad:.2f}. "
            "Este es el valor de OFERTA BRUTA; la oferta neta para "
            "captación (descontado el Q ecológico) se reporta en la "
            "Sección 7.")


def _seccion_6(story, st, d):
    story.append(PageBreak())
    _p(story, st, "6. DEMANDA DE AGUA POTABLE", "h2")
    _p(story, st,
        "Cálculo conforme NB 689 (IBNORCA/MMAyA 2004) con coeficientes "
        "recomendados K₁ = 1.5 (máx. diario / medio) y K₂ = 2.2 "
        "(máx. horario / máx. diario). Período de diseño según categoría "
        "poblacional NB 689.")

    cau = d.get("ap_caudales_demanda")
    if cau is None:
        _p(story, st,
            "[Demanda no calculada — verificar el bloque «Datos de demanda» "
            "del formulario.]", "italica")
        return

    from .demanda_agua_potable import tabla_demanda
    _p(story, st, "6.1 Población base", "h3")
    _p(story, st,
        f"Población actual: <b>{cau.proyeccion.poblacion_actual:,} hab</b> "
        f"(año base {cau.proyeccion.anio_base}). Fuente: declarada por el "
        f"proyectista — validar contra último censo INE disponible y "
        f"actualización local.".replace(",", " "))

    _p(story, st, "6.2 Proyección poblacional", "h3")
    _p(story, st,
        f"Método adoptado: <b>{cau.proyeccion.metodo}</b>. Tasa de "
        f"crecimiento: {cau.proyeccion.tasa_crecimiento_pct:.2f} %/año. "
        f"Horizonte: {cau.proyeccion.horizonte_anios} años. "
        f"Población de diseño: <b>"
        f"{cau.proyeccion.poblacion_diseno:,} hab</b> — categoría NB 689: "
        f"<b>{cau.proyeccion.categoria_nb689}</b>.".replace(",", " "))

    _p(story, st, "6.3 Nivel de servicio", "h3")
    _p(story, st,
        f"Nivel adoptado: <b>{cau.dotacion.nivel_servicio_descripcion}</b>.")

    _p(story, st, "6.4 Dotación adoptada (Tabla 11)", "h3")
    _p(story, st, cau.dotacion.justificacion)
    _p(story, st,
        f"<b>Dotación adoptada: {cau.dotacion.dotacion_l_hab_dia:.1f} "
        f"L/hab/día</b>.")

    _p(story, st, "6.5 Cálculo de caudales de demanda (Tabla 12)", "h3")
    story.append(_tabla(tabla_demanda(cau),
                          col_widths=[5.5 * cm, 2.5 * cm, 2 * cm, 6 * cm]))

    _p(story, st, "6.6 Restricción por oferta hídrica", "h3")
    _p(story, st,
        "El cumplimiento de la demanda con la oferta hídrica disponible "
        "se evalúa en la Sección 7 (Balance oferta-demanda). Si el "
        "balance resulta restringido o negativo, las recomendaciones "
        "(Sección 9.2) incluyen ajustes de dotación, regulación por "
        "reservorio o fuente complementaria.")


def _seccion_7(story, st, d):
    story.append(PageBreak())
    _p(story, st,
        "7. ANÁLISIS DE DISPONIBILIDAD Y BALANCE HÍDRICO DEL PROYECTO",
        "h2")
    balance = d.get("ap_balance")
    cau = d.get("ap_caudales_demanda")
    if balance is None or cau is None:
        _p(story, st,
            "[Balance no calculado — verificar bloque agua potable del "
            "worker.]", "italica")
        return

    from .balance_oferta_demanda import (tabla_sintesis_oferta,
                                            tabla_balance)
    _p(story, st, "7.1 Síntesis de oferta (Tabla 10)", "h3")
    story.append(_tabla(tabla_sintesis_oferta(balance),
                          col_widths=[4.5 * cm, 2 * cm, 4.5 * cm,
                                       2 * cm, 4 * cm]))

    _p(story, st, "7.2 Caudal mínimo adoptado", "h3")
    _p(story, st,
        f"<b>Q_mín adoptado: {balance.q_min_adoptado_m3s * 1000:.2f} L/s "
        f"({balance.q_min_adoptado_m3s:.4f} m³/s)</b>. "
        f"Criterio: {balance.metodo_adoptado}. "
        f"Factor de seguridad: {balance.factor_seguridad:.2f}.")

    _p(story, st, "7.3 Demanda del proyecto", "h3")
    _p(story, st,
        f"Población de diseño: {cau.proyeccion.poblacion_diseno:,} hab; "
        f"dotación: {cau.dotacion.dotacion_l_hab_dia:.1f} L/hab/día; "
        f"Q_md = {cau.q_md_l_s:.3f} L/s; "
        f"Q_máx_d = {cau.q_max_d_l_s:.3f} L/s; "
        f"Q_máx_h = {cau.q_max_h_l_s:.3f} L/s.".replace(",", " "))

    _p(story, st, "7.4 Balance oferta-demanda (Tabla 13)", "h3")
    story.append(_tabla(tabla_balance(balance),
                          col_widths=[6 * cm, 2.5 * cm, 2.5 * cm, 6 * cm]))

    _p(story, st, "7.5 Interpretación técnica", "h3")
    _p(story, st, balance.interpretacion)
    if balance.recomendaciones:
        _p(story, st, "Recomendaciones específicas del balance:")
        for r in balance.recomendaciones:
            _p(story, st, f"• {r}")


def _seccion_8(story, st, d):
    story.append(PageBreak())
    _p(story, st, "8. VERIFICACIÓN NORMATIVA Y AMBIENTAL", "h2")
    balance = d.get("ap_balance")
    caudales = d.get("ap_caudales_demanda")
    if balance is None or caudales is None:
        _p(story, st,
            "[Verificación no realizada — falta bloque agua potable "
            "(PR2). Completar el formulario con datos de demanda.]",
            "italica")
        return

    from .verificacion_normativa import (verificar, tabla_verificacion,
                                            lista_riesgos)
    piso = d.get("_piso_ecologico")
    verif = verificar(
        balance=balance, caudales=caudales,
        tiene_analisis_calidad=bool(d.get("ap_tiene_analisis_calidad", False)),
        n_aforos_estiaje=int(d.get("ap_n_aforos_estiaje", 0)),
        piso_clave=(piso.clave if piso else None),
    )
    d["_verificacion"] = verif   # exposto a la Sección 9

    _p(story, st, "8.1 Verificación normativa (Tabla 14)", "h3")
    story.append(_tabla(tabla_verificacion(verif),
                          col_widths=[4 * cm, 2.5 * cm, 3 * cm,
                                       3 * cm, 1 * cm, 4 * cm]))

    _p(story, st, "8.2 Verificación de caudal ecológico", "h3")
    if balance.q_ecologico_m3s > 0:
        razon = (balance.q_ecologico_m3s
                   / max(balance.q_min_adoptado_m3s, 1e-9)) * 100
        _p(story, st,
            f"Se adopta un caudal ecológico de <b>"
            f"{balance.q_ecologico_m3s * 1000:.2f} L/s</b> "
            f"({razon:.0f} % del Q mín adoptado) calculado por el método "
            f"<i>{balance.q_ecologico_metodo}</i>. El proyecto respeta "
            f"este caudal al descontarlo de la oferta antes del balance, "
            f"dejando <b>{balance.q_disponible_m3s * 1000:.2f} L/s</b> "
            f"disponibles para captación. Cumple con el espíritu del Art. 36 "
            f"de la Ley 1333 y los lineamientos del RMCH.")
    else:
        _p(story, st,
            "Caudal ecológico no calculado en este informe. La Ley 1333 "
            "obliga a respetar un remanente ambiental: <b>la captación no "
            "puede aprobarse sin esta verificación</b>.", "italica")

    _p(story, st, "8.3 Riesgos y vulnerabilidades", "h3")
    riesgos = lista_riesgos(piso.clave if piso else None)
    filas = [["#", "Riesgo / vulnerabilidad", "Evaluación y mitigación"]]
    for i, (titulo, descr) in enumerate(riesgos, 1):
        filas.append([str(i), titulo, descr])
    story.append(_tabla(filas, col_widths=[0.8 * cm, 5 * cm, 11 * cm],
                          primera_col_izq=True))

    _p(story, st, "8.4 Condiciones para aprobación técnica", "h3")
    _p(story, st, verif.diagnostico_global)


def _seccion_9(story, st, d):
    story.append(PageBreak())
    _p(story, st, "9. CONCLUSIONES Y RECOMENDACIONES", "h2")
    balance = d.get("ap_balance")
    caudales = d.get("ap_caudales_demanda")
    verif = d.get("_verificacion")
    piso = d.get("_piso_ecologico")
    cuenca = d.get("cuenca_qmin")
    area = (cuenca.area_km2 if cuenca is not None else None)

    if balance is None or caudales is None or verif is None or piso is None:
        _p(story, st,
            "[Conclusiones no generadas — falta alguno de los bloques de "
            "cálculo (demanda / balance / verificación).]", "italica")
        return

    from .conclusiones_agua_potable import (conclusiones_dinamicas,
                                              recomendaciones_dinamicas)

    _p(story, st, "9.1 Conclusiones", "h3")
    conclusiones = conclusiones_dinamicas(
        piso=piso, balance=balance, caudales=caudales,
        verificacion=verif, lat=d["lat"], lon=d["lon"], area_km2=area)
    for i, c in enumerate(conclusiones, 1):
        _p(story, st, f"<b>{i}.</b> {c}")

    _p(story, st, "9.2 Recomendaciones", "h3")
    recos = recomendaciones_dinamicas(balance=balance, verificacion=verif,
                                          piso=piso)
    for i, r in enumerate(recos, 1):
        _p(story, st, f"<b>{i}.</b> {r}")


# ──────────────────────── 10. Bibliografía ────────────────────────────────

def _seccion_10(story, st, d):
    story.append(PageBreak())
    _p(story, st, "10. BIBLIOGRAFÍA Y REFERENCIAS", "h2")
    for i, ref in enumerate(bibliografia_apa(), 1):
        _p(story, st, f"{i}. {ref}")


# ──────────────────────── Anexos A–H ──────────────────────────────────────

def _anexos(story, st, d, sesion_dir: Path):
    """Anexos A–H. Cada anexo embebe el contenido cuando está disponible
    (mapas GEE, balance mensual, FDC, etc.) y declara explícitamente como
    «pendiente de campaña» lo que requiere trabajo de campo (calidad,
    aforos, fotografías)."""
    story.append(PageBreak())
    _p(story, st, "ANEXOS", "h2")

    pq = d.get("pq")
    cuenca = d.get("cuenca_qmin")
    mapas_qmin = d.get("mapas_qmin") or {}
    piso = d.get("_piso_ecologico")
    contenido_por_anexo: dict[str, str] = {}

    # ─── ANEXO A — Mapa de ubicación y delimitación de cuenca ─────────
    _p(story, st,
        "ANEXO A. Mapa de ubicación y delimitación de cuenca", "h3")
    img = _img_si_existe(sesion_dir / "mapa_regional.png", ancho_cm=16)
    if img:
        story.append(img)
        contenido_por_anexo["A"] = "Mapa regional Sentinel-2 + cuenca"
    img2 = _img_si_existe(sesion_dir / "qmin_cuenca.png", ancho_cm=16)
    if img2:
        story.append(Spacer(1, 6))
        story.append(img2)
        contenido_por_anexo["A"] = (contenido_por_anexo.get("A", "")
                                       + " + cuenca delineada MERIT").strip(" +")
    if cuenca is not None:
        _p(story, st,
            f"Cuenca delineada por watershed D8 sobre MERIT Hydro 90 m. "
            f"Área = {cuenca.area_km2:.2f} km², perímetro = "
            f"{cuenca.perimetro_km:.2f} km, cauce principal = "
            f"{cuenca.long_cauce_km:.2f} km. Coordenadas en WGS-84 "
            f"(EPSG:4326).")
    if "A" not in contenido_por_anexo:
        _p(story, st,
            "[Mapas GEE no disponibles en esta corrida — adjuntar mapa "
            "topográfico IGM 1:50 000 con la cuenca delineada manualmente.]",
            "italica")
        contenido_por_anexo["A"] = "Pendiente — adjuntar mapa IGM"

    # ─── ANEXO B — Mapa de piso ecológico y cobertura vegetal ─────────
    story.append(PageBreak())
    _p(story, st,
        "ANEXO B. Mapa de piso ecológico y cobertura vegetal", "h3")
    if piso:
        _p(story, st,
            f"<b>Piso ecológico clasificado:</b> {piso.nombre} "
            f"({piso.rango_altitud_m[0]:,}–{piso.rango_altitud_m[1]:,} "
            f"m s.n.m.). <br/>Cobertura típica: {piso.cobertura} "
            f"<br/>Comportamiento hidrológico: "
            f"{piso.comportamiento_hidrologico} <br/>Estiaje esperado: "
            f"{piso.estiaje_esperado}".replace(",", " "))
        contenido_por_anexo["B"] = f"Piso ecológico: {piso.nombre}"
    img = _img_si_existe(sesion_dir / "mapa_cobertura.png", ancho_cm=16)
    if img:
        story.append(Spacer(1, 6))
        story.append(img)
        contenido_por_anexo["B"] += " + mapa cobertura GEE"
    else:
        _p(story, st,
            "[Mapa específico de cobertura no disponible. Para informe "
            "definitivo: descargar MapBiomas Bolivia v1 (LULC anual) "
            "para el polígono de la cuenca.]", "italica")
        contenido_por_anexo.setdefault("B", "Pendiente — MapBiomas Bolivia")

    # ─── ANEXO C — Registros pluviométricos y consistencia ────────────
    story.append(PageBreak())
    _p(story, st,
        "ANEXO C. Registros pluviométricos y análisis de consistencia",
        "h3")
    diags = d.get("diagnosticos_consistencia") or []
    if diags:
        _p(story, st,
            f"Panel OMM-168 aplicado a {len(diags)} series candidatas. "
            f"Detalle de cada serie (resumen):")
        filas = [["#", "Código", "Tipo", "n años", "Pruebas pasadas",
                   "Clase", "Apta"]]
        for i, x in enumerate(diags[:30], 1):
            filas.append([str(i), x.codigo,
                            "Met." if x.tipo == "met" else "Hidro.",
                            str(x.n_anios),
                            f"{x.pruebas_pasadas}/5",
                            x.clase,
                            "✓" if x.apta else "—"])
        story.append(_tabla(filas))
        contenido_por_anexo["C"] = f"Panel OMM-168 — {len(diags)} series"
    else:
        _p(story, st,
            "[Sin diagnóstico OMM-168 — completar con series SENAMHI "
            "del catálogo oficial y análisis de doble masa.]", "italica")
        contenido_por_anexo["C"] = "Pendiente — series SENAMHI"

    # ─── ANEXO D — Balance hídrico mensual ─────────────────────────────
    story.append(PageBreak())
    _p(story, st,
        "ANEXO D. Hojas de cálculo de balance hídrico mensual", "h3")
    if pq is not None:
        meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago",
                    "Sep", "Oct", "Nov", "Dic"]
        cab = ["Mes", "P (mm)", "ETR (mm)", "ΔS (mm)", "Q (mm)", "Q (L/s)"]
        filas = [cab]
        for i, m in enumerate(meses):
            p_m = float(pq.p_mes_mm[i]) if hasattr(pq, "p_mes_mm") else 0
            q_m = float(pq.q_mes_m3s[i]) if hasattr(pq, "q_mes_m3s") else 0
            q_mm = q_m * 1000 * 86400 * 30 / (
                cuenca.area_km2 * 1e6 if cuenca else 1.0)
            etr = max(p_m - q_mm, 0)
            filas.append([m, f"{p_m:.1f}", f"{etr:.1f}", "—",
                            f"{q_mm:.2f}", f"{q_m * 1000:.2f}"])
        story.append(_tabla(filas))
        _p(story, st,
            f"Supuestos del balance: capacidad de almacenamiento de "
            f"suelo CAW = {pq.caw_usada_mm:.0f} mm; constante de "
            f"recesión α = {pq.alpha:.2f}; fracción rápida del "
            f"escurrimiento = {pq.fraccion_rapida:.2f}; coeficiente de "
            f"escorrentía anual = {pq.coef_escorrentia_anual:.2f}. "
            f"<b>Mes crítico de estiaje: {meses[int(pq.q_mes_m3s.argmin())]}</b> "
            f"con Q ≈ {float(pq.q_mes_m3s.min()) * 1000:.2f} L/s.")
        contenido_por_anexo["D"] = "Balance mensual completo"
    else:
        _p(story, st,
            "[Balance P→Q no disponible — completar con planilla manual "
            "de Thornthwaite-Mather usando CHIRPS local.]", "italica")
        contenido_por_anexo["D"] = "Pendiente — planilla manual"

    # ─── ANEXO E — Planilla de aforos en blanco ────────────────────────
    story.append(PageBreak())
    _p(story, st, "ANEXO E. Registros de aforos de campo", "h3")
    _p(story, st,
        "Planilla tipo para aforos por sección-velocidad / molinete "
        "(ISO 748). Levantar al menos 3 aforos en estiaje (jul–ago) "
        "antes de aprobación operativa.")
    filas = [
        ["Fecha", "Hora", "Sección", "Ancho (m)", "Tirante (m)",
            "Área (m²)", "v (m/s)", "Q (L/s)", "Observaciones"],
        ["__/__/____", "__:__", "[ ]", "—", "—", "—", "—", "—",
            "[completar en campo]"],
        ["__/__/____", "__:__", "[ ]", "—", "—", "—", "—", "—",
            "[completar en campo]"],
        ["__/__/____", "__:__", "[ ]", "—", "—", "—", "—", "—",
            "[completar en campo]"],
    ]
    story.append(_tabla(filas,
                          col_widths=[2 * cm, 1.5 * cm, 1.5 * cm,
                                       1.5 * cm, 1.5 * cm, 1.5 * cm,
                                       1.3 * cm, 1.5 * cm, 3 * cm]))
    _p(story, st, "<b>Caudal mínimo de estiaje (promedio):</b> "
                     "________ L/s. <b>Observador:</b> ________________.",
        "italica")
    contenido_por_anexo["E"] = "Planilla en blanco — completar en campo"

    # ─── ANEXO F — Curva de duración de caudales ────────────────────────
    story.append(PageBreak())
    _p(story, st, "ANEXO F. Curva de duración de caudales (FDC)", "h3")
    img = _img_si_existe(sesion_dir / "qmin_fdc.png", ancho_cm=15)
    if img:
        story.append(img)
        if pq is not None:
            _p(story, st,
                f"Percentiles característicos: Q5 = {pq.q5 * 1000:.2f} L/s, "
                f"Q50 = {pq.q50 * 1000:.2f} L/s, Q75 = {pq.q75 * 1000:.2f} L/s, "
                f"Q90 = {pq.q90 * 1000:.2f} L/s, Q95 = {pq.q95 * 1000:.2f} L/s, "
                f"Q7,10 = {pq.q7_10 * 1000:.2f} L/s. FDC construida a partir "
                f"de la serie mensual del balance P→Q.")
        contenido_por_anexo["F"] = "FDC simulada"
    else:
        _p(story, st,
            "<b>No aplicable</b>. No se dispone de serie diaria de caudal "
            "≥ 10 años en el punto de estudio. La FDC requiere serie "
            "diaria continua; con datos mensuales/anuales solo se reportan "
            "los percentiles simulados del balance hídrico (Sección 5.2 / "
            "Anexo D).", "italica")
        contenido_por_anexo["F"] = "No aplicable — sin serie diaria"

    # ─── ANEXO G — Análisis físico-químico (NB 512) ────────────────────
    story.append(PageBreak())
    _p(story, st, "ANEXO G. Análisis físico-químico de la fuente", "h3")
    _p(story, st,
        "[Pendiente de campaña de calidad de agua.] Para aprobación "
        "operativa se requiere muestreo conforme NB 512 e ISO 5667 con "
        "los siguientes parámetros mínimos:")
    filas = [
        ["Grupo", "Parámetros mínimos NB 512"],
        ["Físicos", "Color, turbiedad, olor, sabor, temperatura, "
                       "conductividad eléctrica, sólidos totales disueltos"],
        ["Químicos", "pH, alcalinidad, dureza, calcio, magnesio, sodio, "
                        "cloruros, sulfatos, nitratos, nitritos, hierro, "
                        "manganeso, fluoruros, arsénico"],
        ["Microbiológicos",
            "Coliformes totales, coliformes fecales (Escherichia coli)"],
        ["Bacteriológicos extras (si aplica)",
            "Cryptosporidium, Giardia, vibrio cholerae en zonas endémicas"],
    ]
    story.append(_tabla(filas, col_widths=[4 * cm, 12 * cm],
                          primera_col_izq=True))
    _p(story, st,
        "<b>Resultado de laboratorio:</b> [adjuntar informe firmado por "
        "laboratorio acreditado]. <b>Conformidad NB 512:</b> [completar]. "
        "<b>Recomendación de tratamiento:</b> [especificar según resultado].")
    contenido_por_anexo["G"] = "Pendiente — campaña de calidad NB 512"

    # ─── ANEXO H — Panel fotográfico ────────────────────────────────────
    story.append(PageBreak())
    _p(story, st, "ANEXO H. Panel fotográfico", "h3")
    _p(story, st,
        "Lista de tomas fotográficas requeridas para el expediente "
        "(adjuntar archivos JPG/PNG con metadatos GPS):")
    for it in (
        "Foto 1 — Fuente: vista panorámica de la captación propuesta.",
        "Foto 2 — Entorno: cabecera de cuenca y vegetación dominante.",
        "Foto 3 — Punto de captación: sección transversal del cauce.",
        "Foto 4 — Cauce aguas arriba (≥ 100 m): estado del cauce, "
            "vegetación ribereña.",
        "Foto 5 — Cauce aguas abajo (≥ 100 m): conectividad y posibles "
            "usos competitivos.",
        "Foto 6 — Accesos: camino vehicular o senda al sitio.",
        "Foto 7 — Uso actual: evidencia de captaciones previas, ganado, "
            "agricultura.",
        "Foto 8 — Estado en estiaje (jul–ago): nivel mínimo observado.",
    ):
        _p(story, st, f"• {it}")
    contenido_por_anexo["H"] = "Pendiente — adjuntar fotografías"

    # ─── Tabla 15 obligatoria — Lista de anexos ────────────────────────
    story.append(PageBreak())
    _p(story, st, "Tabla 15 — Lista de anexos del informe", "h3")
    filas = [["Código", "Contenido", "Estado"]]
    for cod in ("A", "B", "C", "D", "E", "F", "G", "H"):
        contenido = contenido_por_anexo.get(cod, "—")
        estado = ("Disponible" if not contenido.lower().startswith("pendiente")
                   else contenido)
        nombre = {
            "A": "Mapa de ubicación y delimitación de cuenca",
            "B": "Mapa de piso ecológico y cobertura vegetal",
            "C": "Registros pluviométricos y análisis de consistencia",
            "D": "Hojas de cálculo de balance hídrico mensual",
            "E": "Registros de aforos de campo",
            "F": "Curva de duración de caudales",
            "G": "Análisis físico-químico de la fuente",
            "H": "Panel fotográfico",
        }[cod]
        filas.append([cod, nombre, estado])
    story.append(_tabla(filas, col_widths=[1.5 * cm, 9 * cm, 6 * cm],
                          primera_col_izq=True))


# ──────────────────────── Canvas con header propio ────────────────────────

class _CanvasAP(_CanvasConPaginado):
    """Canvas con header «memoria de cálculo agua potable»."""

    def _dibujar_chrome(self, total: int):
        ancho, alto = self._pagesize
        n = self.getPageNumber()
        self.saveState()
        self.setFont(FONT_BOLD, 9)
        self.setFillColor(colors.HexColor("#1f3a68"))
        self.drawCentredString(ancho / 2.0, alto - 1.2 * cm, HEADER_TEXTO)
        self.setStrokeColor(colors.HexColor("#1f3a68"))
        self.setLineWidth(0.6)
        self.line(1.6 * cm, alto - 1.5 * cm, ancho - 1.6 * cm,
                    alto - 1.5 * cm)
        self.line(1.6 * cm, 1.55 * cm, ancho - 1.6 * cm, 1.55 * cm)
        self.setFont(FONT, 8)
        self.setFillColor(colors.HexColor("#444444"))
        pie = (f"{FOOTER_AUTOR}   -   {FOOTER_EMAIL}   -   {FOOTER_TEL}"
                 f"   -   Pag. {n} de {total}")
        self.drawCentredString(ancho / 2.0, 1.05 * cm, pie)
        self.restoreState()


# ──────────────────────── Entry point ─────────────────────────────────────

def generar_pdf_qmin_agua_potable(archivo, datos: dict,
                                       sesion_dir: Path) -> Path:
    """Compila la memoria de cálculo a PDF protegido (AES-128).

    `datos` viene del worker con el mismo contenido que el contexto del
    template `qmin_resumen.html` + los campos opcionales del bloque
    «demanda» del form (population, growth_rate, horizon, level_of_service,
    dotation) que PR2 incorporará.
    """
    from reportlab.lib.pdfencrypt import StandardEncryption
    archivo = Path(archivo)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    encriptacion = StandardEncryption(
        userPassword="", ownerPassword=PROTECCION_OWNER_PWD,
        canPrint=0, canModify=0, canCopy=0, canAnnotate=0,
        strength=128,
    )
    doc = SimpleDocTemplate(
        str(archivo), pagesize=letter,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=2.6 * cm, bottomMargin=2.6 * cm,
        title=("HYDROFRA - Memoria Q min agua potable - " +
                getattr(datos.get("proyecto"), "nombre_proyecto", "Informe")),
        author=FOOTER_AUTOR,
        subject=("PROTEGIDO - Comuniquese con " + FOOTER_AUTOR +
                 " - " + FOOTER_EMAIL + " - " + FOOTER_TEL),
        keywords=("HYDROFRA v1.2 Q minimos agua potable; NB 512; NB 689; "
                  "Ley 1333; informe protegido; " + FOOTER_EMAIL),
        encrypt=encriptacion,
    )
    st = _estilos()
    story: list = []
    _portada(story, st, datos)
    _seccion_1(story, st, datos)
    _seccion_2(story, st, datos, Path(sesion_dir))
    _seccion_3(story, st, datos, Path(sesion_dir))
    _seccion_4(story, st, datos, Path(sesion_dir))
    _seccion_5(story, st, datos, Path(sesion_dir))
    _seccion_6(story, st, datos)
    _seccion_7(story, st, datos)
    _seccion_8(story, st, datos)
    _seccion_9(story, st, datos)
    _seccion_10(story, st, datos)
    _anexos(story, st, datos, Path(sesion_dir))
    doc.build(story, canvasmaker=_CanvasAP)
    return archivo
