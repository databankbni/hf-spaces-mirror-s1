"""Generador de informe PDF (CURVAS IDF v1.2).

Estructura de 14 secciones: portada, fuentes de datos (estación + satelital),
series y correlación, estadísticos, consistencia, frecuencias, cuantiles por
tipo de obra, desagregación, modelos IDF (7), tiempo de concentración (con flujo
DEM documentado), hietogramas (bloques/SCS/Chicago), resumen HEC-HMS,
conclusiones y referencias.

Todas las tablas se ajustan al ancho (celdas envueltas en Paragraph) y van
centradas. Todos los gráficos se generan en coordenadas normales.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _canvas_mod
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


# ---------------------------------------------------------------------------
# Fuente Unicode: Helvetica (Core 14 PDF) no incluye U+00B2 (²) ni otros
# símbolos técnicos, por lo que "R²" se renderiza como "R■". DejaVuSans viene
# embebida con matplotlib y tiene cobertura Unicode completa.
# ---------------------------------------------------------------------------

def _registrar_fuentes_unicode() -> bool:
    try:
        import matplotlib
        ttf_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(ttf_dir / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold",
                                       str(ttf_dir / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique",
                                       str(ttf_dir / "DejaVuSans-Oblique.ttf")))
        return True
    except Exception:
        return False


_FUENTE_OK = _registrar_fuentes_unicode()
FONT = "DejaVuSans" if _FUENTE_OK else "Helvetica"
FONT_BOLD = "DejaVuSans-Bold" if _FUENTE_OK else "Helvetica-Bold"
FONT_OBLIQUE = "DejaVuSans-Oblique" if _FUENTE_OK else "Helvetica-Oblique"


# ---------------------------------------------------------------------------
# Estilos y helpers
# ---------------------------------------------------------------------------

def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("titulo", parent=base["Title"], fontName=FONT_BOLD,
                                 fontSize=26, textColor=colors.HexColor("#1f3a68"),
                                 spaceAfter=14, alignment=1),
        "subt_centro": ParagraphStyle("subt_centro", parent=base["Heading2"], fontName=FONT_BOLD,
                                      fontSize=14, textColor=colors.HexColor("#1f3a68"),
                                      alignment=1, spaceAfter=8),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=FONT_BOLD,
                             fontSize=14, textColor=colors.HexColor("#1f3a68"),
                             spaceBefore=14, spaceAfter=8),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName=FONT_BOLD,
                             fontSize=12, textColor=colors.HexColor("#264a82"),
                             spaceBefore=8, spaceAfter=4),
        "cuerpo": ParagraphStyle("cuerpo", parent=base["BodyText"], fontName=FONT,
                                 fontSize=10, leading=14, alignment=4, spaceAfter=6),
        "italica": ParagraphStyle("italica", parent=base["BodyText"], fontName=FONT_OBLIQUE,
                                  fontSize=9, leading=12,
                                  textColor=colors.HexColor("#555555")),
    }


_CELDA = ParagraphStyle("celda", fontName=FONT, fontSize=8.3, leading=10,
                        alignment=1, wordWrap="CJK")
_CELDA_IZQ = ParagraphStyle("celda_izq", fontName=FONT, fontSize=8.3, leading=10,
                            alignment=0, wordWrap="CJK")
_CELDA_CAB = ParagraphStyle("celda_cab", fontName=FONT_BOLD, fontSize=8.3, leading=10,
                            alignment=1, textColor=colors.white, wordWrap="CJK")


def _celda(valor, estilo) -> Paragraph:
    return Paragraph("" if valor is None else str(valor), estilo)


def _tabla(datos, col_widths=None, cabecera=True, primera_col_izq=False):
    envuelto = []
    for r, fila in enumerate(datos):
        fila_w = []
        for c_idx, c in enumerate(fila):
            if isinstance(c, (Paragraph, Image, Table)):
                fila_w.append(c)
                continue
            if cabecera and r == 0:
                est = _CELDA_CAB
            elif primera_col_izq and c_idx == 0:
                est = _CELDA_IZQ
            else:
                est = _CELDA
            fila_w.append(_celda(c, est))
        envuelto.append(fila_w)
    t = Table(envuelto, colWidths=col_widths, hAlign="CENTER",
              repeatRows=1 if cabecera else 0)
    estilo = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1 if cabecera else 0), (-1, -1),
         [colors.whitesmoke, colors.white]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])
    if cabecera:
        estilo.add("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a68"))
    t.setStyle(estilo)
    return t


def _figura(path, ancho_cm=16.0, max_alto_cm=20.0):
    img = Image(str(path))
    aspect = img.imageHeight / img.imageWidth
    w = ancho_cm * cm
    h = w * aspect
    if h > max_alto_cm * cm:  # imagen vertical: limitar por alto
        h = max_alto_cm * cm
        w = h / aspect
    img.drawWidth = w
    img.drawHeight = h
    img.hAlign = "CENTER"
    return img


def _p(story, st, texto, estilo="cuerpo"):
    story.append(Paragraph(texto, st[estilo]))


def _riesgo_abc_activo(R) -> bool:
    """True si el tipo de obra es «Análisis de riesgo ABC» (sección 14 extra)."""
    return getattr(getattr(R, "tipo_obra", None), "clave", "") == \
        "analisis_riesgo_abc"


def _hay_riego(R) -> bool:
    """True si el informe incluye el capítulo de captación de riego menor."""
    return getattr(R, "riego", None) is not None


def _off_riego(R) -> int:
    """Desplazamiento de numeración: el capítulo de riego (si existe) es un
    capítulo propio que corre en +1 a conclusiones, referencias y anexos."""
    return 1 if _hay_riego(R) else 0


def _n_hidraulica(R) -> str:
    """Número del capítulo de hidráulica fluvial (tirante): §15 con riesgo
    ABC activo, §14 en el resto."""
    return "15" if _riesgo_abc_activo(R) else "14"


def _n_riego(R) -> str:
    """Número del capítulo de captación de riego (el siguiente a hidráulica)."""
    return str(int(_n_hidraulica(R)) + 1)


_TITULO_DEFECTO = "INFORME HIDROLOGICO DE CAUDALES MAXIMO"
_TITULO_ABC = ("Informe de Análisis de Riesgo de Cambio Climático para "
               "Infraestructura Vial")
_TITULO_PUENTE = "INFORME DE HIDRÁULICA FLUVIAL PARA PUENTES PARA CAUDALES MÁXIMOS"
_HEADER_DEFECTO = "INFORME HIDROLOGICO DE CAUDALES MAXIMOS    HYDROFRA V 1.3"
_HEADER_ABC = ("ANÁLISIS DE RIESGO DE CAMBIO CLIMÁTICO — INFRAESTRUCTURA VIAL "
               "(ABC)    HYDROFRA")
_HEADER_PUENTE = "HIDRÁULICA FLUVIAL PARA PUENTES — CAUDALES MÁXIMOS    HYDROFRA"

# Tipos de obra que corresponden a puentes/cruces fluviales.
_OBRAS_PUENTE = ("carretera_puente",)


def _es_obra_puente(R) -> bool:
    return getattr(getattr(R, "tipo_obra", None), "clave", "") in _OBRAS_PUENTE


def _titulo_informe(R) -> str:
    """Título del informe según el tipo de obra: puentes → hidráulica fluvial;
    obra ABC → riesgo climático; resto → hidrológico de caudales máximos."""
    if _riesgo_abc_activo(R):
        return _TITULO_ABC
    if _es_obra_puente(R):
        return _TITULO_PUENTE
    return _TITULO_DEFECTO


def _header_informe(R) -> str:
    if _riesgo_abc_activo(R):
        return _HEADER_ABC
    if _es_obra_puente(R):
        return _HEADER_PUENTE
    return _HEADER_DEFECTO


# ---------------------------------------------------------------------------
# Índice del contenido (Table of Contents)
# ---------------------------------------------------------------------------

def _crear_toc():
    """TOC con estilos para Título 1 (h2 → niveles principales) y Título 2 (h3)."""
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(name="TOC1", fontName=FONT_BOLD, fontSize=10.5, leading=15,
                       leftIndent=0, rightIndent=10,
                       textColor=colors.HexColor("#1f3a68"), spaceAfter=2),
        ParagraphStyle(name="TOC2", fontName=FONT, fontSize=9.2, leading=13,
                       leftIndent=18, rightIndent=10,
                       textColor=colors.HexColor("#333333")),
    ]
    return toc


def _indice(story, st, R, toc):
    """Inserta la sección 'Índice' usando el objeto TOC dado.

    El TOC se va rellenando automáticamente en la primera pasada de
    `multiBuild`: cada Paragraph con estilo h2/h3 notifica una entrada con su
    título y número de página real.
    """
    # La portada termina con su propio PageBreak; el índice arranca en la
    # página siguiente sin necesidad de otro salto (evita una hoja vacía).
    story.append(Paragraph("Índice", st["h2"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(toc)


def _sec_tabla_maestra(story, st, R):
    """Tabla maestra de parámetros: valor único, origen y uso de cada variable.

    Responde a la observación de que los valores de entrada cambiaban entre
    secciones sin una referencia única. Todo parámetro que alimenta un cálculo
    posterior aparece aquí una sola vez, con la sección donde se obtiene y la
    sección donde se consume, de modo que la cadena
    P24 → IDF → hietograma → HEC-HMS → Q → tirante → socavación queda cerrada
    y auditable de un vistazo.
    """
    story.append(PageBreak())
    _p(story, st, "0. Alcance del estudio y tabla maestra de parámetros", "h2")

    # ── Declaración de alcance: qué es y qué NO es este documento. ──
    _tiene_topo = False   # el pipeline no incorpora topografía local
    _p(story, st, "0.1 Declaración de alcance y nivel de confianza", "h3")
    _p(story, st,
       "<b>Este documento es un estudio hidrológico-hidráulico de "
       "PREDISEÑO</b>, construido íntegramente sobre información de cobertura "
       "global (modelos digitales de elevación, productos de precipitación "
       "grillados y cartografía satelital de cobertura del suelo) procesada de "
       "forma automatizada y trazable. Declarar su alcance con precisión es "
       "parte del propio resultado técnico: un estudio de este tipo es "
       "sólido para lo que puede sustentar, y no debe emplearse para lo que "
       "no puede.")
    usos = [["Uso previsto (APTO)", "Uso NO cubierto por este documento"],
            ["Dimensionamiento preliminar y definición de la magnitud de la "
             "obra (luz, gálibo, orden de la fundación).",
             "Aprobación contractual como memoria hidrológica definitiva."],
            ["Comparación de alternativas de emplazamiento y de tipología de "
             "puente.",
             "Diseño estructural definitivo de pilas, estribos y "
             "cimentaciones."],
            ["Definición del alcance, el presupuesto y los términos de "
             "referencia del estudio definitivo.",
             "Sustitución del levantamiento topo-batimétrico y del estudio "
             "geotécnico."],
            ["Detección temprana de condicionantes (socavación, gálibo, "
             "planicie inundable, protección de márgenes).",
             "Modelación hidráulica de detalle con geometría real "
             "(HEC-RAS 1D/2D calibrado)."]]
    story.append(_tabla(usos, col_widths=[7.6*cm, 7.6*cm],
                        primera_col_izq=True))
    _p(story, st,
       "<b>Condiciones para elevar el estudio a nivel de diseño definitivo.</b> "
       "Los resultados de las Secciones 11 a 14 (caudal, tirante, velocidad, "
       "socavación y profundidad de cimentación) son <b>valores de prediseño "
       "verificables</b>: constituyen una hipótesis cuantitativa de partida, "
       "no una determinación final. Para adquirir carácter definitivo "
       "requieren, como mínimo: registros pluviométricos observados de SENAMHI "
       "con sus metadatos y control de calidad; levantamiento topográfico y "
       "batimétrico local del eje y del cauce; estudio geotécnico con "
       "granulometría del lecho; modelación hidráulica con geometría "
       "levantada en campo; y calibración con marcas de crecidas históricas. "
       "El Anexo final detalla estos requisitos.")
    _p(story, st,
       "Las secciones que siguen señalan de forma explícita, en cada caso, "
       "el origen del dato, la incertidumbre asociada y las hipótesis "
       "adoptadas, de modo que el revisor pueda separar en todo momento lo "
       "<b>medido</b> de lo <b>estimado</b> y lo <b>supuesto</b>.", "italica")

    story.append(PageBreak())
    _p(story, st, "0.2 Tabla maestra de parámetros de cálculo", "h3")
    _p(story, st,
       "Esta tabla concentra <b>el valor único y definitivo</b> de cada "
       "parámetro que interviene en la cadena de cálculo, junto con la sección "
       "que lo produce y la que lo consume. Su objetivo es que cualquier "
       "revisor pueda cerrar la cadena "
       "P24 → IDF → hietograma → HEC-HMS → Q → tirante → socavación sin "
       "necesidad de recopilar cifras dispersas. <b>Si un valor aparece en "
       "otra sección del informe, debe coincidir con el de esta tabla.</b>")

    A = getattr(R, "analisis_morf", None)
    m = R.morfologia
    tc = R.tc_adoptado
    ms = getattr(R, "modelo_sherman", None)
    hp = getattr(R, "hec_params", None)
    tir = getattr(R, "tirante", None)
    cnc = getattr(R, "cn_correccion", None)
    cr = getattr(R, "correccion_regional", None)

    def _f(v, dec=2, suf=""):
        try:
            return f"{float(v):.{dec}f}{suf}"
        except Exception:  # noqa: BLE001
            return "—"

    filas = [["#", "Parámetro", "Valor", "Unidad", "Origen", "Se usa en"]]
    k = 0

    def _row(nombre, valor, unidad, origen, uso):
        nonlocal k
        k += 1
        filas.append([str(k), nombre, valor, unidad, origen, uso])

    # ── Morfometría (fuente única tras la reconciliación) ──
    _row("Área de la cuenca A", _f(A.area_km2 if A else m.area_km2),
         "km²", "Sección 9.10 — DEM", "Secciones 10, 11, 13")
    _row("Longitud del cauce Lc",
         _f(A.long_cauce_principal_km if A else m.long_cauce_km),
         "km", "Sección 9.10 — D8", "Sección 10 (Tc)")
    _row("Desnivel H", _f(A.desnivel_m if A else m.desnivel_m, 0),
         "m", "Sección 9.10 — DEM reconciliado", "Sección 10 (Tc)")
    _row("Pendiente media de cuenca",
         _f(A.pendiente_cuenca_pct, 1) if A else _f(m.pendiente_pct, 1),
         "%", "Sección 9.10 — DEM", "Secciones 11, 13 (CN)")
    _row("Pendiente del cauce S",
         _f(A.pendiente_cauce_pct, 2) if A else _f(m.pendiente_pct, 2),
         "%", "Sección 9.10 — DEM reconciliado", "Secciones 11, 14")

    # ── Precipitación ──
    _row("Fuente de precipitación adoptada", R.decision.fuente_adoptada, "—",
         "Sección 2 — comparación", "Secciones 5, 6")
    if cr:
        _row("Factor de piso regional", f"×{cr['factor']:.2f}", "—",
             "Sección 6 — piso regional", "Toda la cadena posterior")
    _row(f"P24 de diseño (T = {R.T_diseno})", _f(R.p24_diseno_mm, 1), "mm",
         "Sección 6 — cuantiles", "Secciones 7, 11, 12")

    # ── IDF ──
    if ms is not None:
        _row("IDF — coeficiente k", _f(ms.a, 3), "—", "Sección 8.0",
             "Secciones 11, 12")
        _row("IDF — exponente m (frecuencia)", _f(ms.m, 4), "—",
             "Sección 8.0", "Secciones 11, 12")
        _row("IDF — exponente n (duración)", _f(ms.n, 4), "—",
             "Sección 8.0", "Secciones 11, 12")
        _row("IDF — constante c", _f(ms.b, 4), "min", "Sección 8.0",
             "Secciones 11, 12")
        _row("IDF — bondad de ajuste R²", _f(ms.r2, 4), "—", "Sección 8.0",
             "—")

    # ── Tiempo de concentración ──
    _row("Tiempo de concentración Tc", _f(tc.tc_min, 0), "min",
         f"Sección 10 — {tc.n_usadas} fórmulas depuradas",
         "Secciones 11, 12, 13")

    # ── Número de curva: los DOS valores, explicitados ──
    if cnc:
        _row("CN₂ ponderado (tabulado SCS)", _f(cnc["cn2"], 0), "—",
             "Sección 9.5 — GCN250 / cobertura", "Insumo de la corrección")
        _row("CN₂ₛ corregido por pendiente (Williams)", _f(cnc["cn2s"], 0),
             "—", "Sección 13.1 — Williams (1995)",
             "HEC-HMS (Sección 13) — valor efectivo")
    elif hp is not None:
        _row("CN adoptado", _f(hp.cn, 0), "—", "Sección 9.5", "Sección 13")
    if hp is not None:
        _row("Retención potencial S", _f(hp.S_ret_mm, 1), "mm",
             "S = 25400/CN₂ₛ − 254", "Sección 13.1")
        _row("Abstracción inicial Ia", _f(hp.Ia_mm, 1), "mm", "Ia = 0.2·S",
             "Sección 13.1")
        _row("Lag time (NRCS)", _f(hp.lag_min, 1), "min", "Lag = 0.6·Tc",
             "Sección 13.2")

    # ── Coeficientes de escorrentía: los dos, diferenciados ──
    if getattr(R, "c_ponderado", None):
        _row("C ponderado (racional, mapa 9.7)", _f(R.c_ponderado), "—",
             "Sección 9.7 — uso de suelo × pendiente",
             "Sección 11 (método racional)")
    if getattr(R, "c_evento", None):
        _row("C del evento de diseño (SCS Q/P)", _f(R.c_evento), "—",
             "Sección 11 — Pe/P del evento",
             "Verificación del balance (no es el C racional)")

    # ── Tormenta de diseño y HEC-HMS ──
    _row("Duración de la tormenta HEC-HMS",
         _f(getattr(R, "hec_duracion_min", 1440.0) / 60.0, 0), "h",
         "Sección 13 — SCS Tipo II (TR-55)", "Sección 13")
    H = getattr(R, "hec_hidrogramas_por_T", None) or {}
    rd = H.get(int(R.T_diseno))
    if rd is not None:
        _row(f"Q pico HEC-HMS (T = {R.T_diseno})", _f(rd.Q_pico_m3s, 1),
             "m³/s", "Sección 13.3 — SCS-CN + HU SCS",
             "Sección 14 (tirante y socavación)")
        _row("Volumen directo", _f(rd.volumen_directo_hm3, 3), "hm³",
             "Sección 13.3", "Balance de masa")

    # ── Hidráulica ──
    if tir is not None:
        _row("n de Manning adoptado", _f(tir.n_manning, 3), "—",
             "Sección 9.8 — cobertura", "Sección 14")
        _row(f"Tirante de control (T = {tir.T_diseno})",
             _f(tir.tirante_control_m), "m", "Sección 14.5", "Gálibo de viga")
        if tir.tirante_verif_m is not None:
            _row(f"Tirante de verificación (T = {tir.T_verif})",
                 _f(tir.tirante_verif_m), "m", "Sección 14.5",
                 "Verificación del gálibo")
        soc = getattr(tir, "socavacion", None)
        if soc is not None:
            _row("Profundidad de cimentación recomendada",
                 _f(soc.prof_cimentacion_recomendada_m), "m",
                 "Sección 14.6 — HEC-18", "Diseño de fundación")
        if tir.galibo_efectivo_verif_m is not None:
            _row("Gálibo libre efectivo", _f(tir.galibo_efectivo_verif_m),
                 "m", "Sección 14.5.1", "Verificación normativa ABC")

    story.append(_tabla(filas,
                        col_widths=[0.9*cm, 5.3*cm, 2.5*cm, 1.5*cm,
                                    4.0*cm, 4.0*cm],
                        primera_col_izq=True))
    _p(story, st,
       "<b>Nota sobre el número de curva.</b> El informe maneja "
       "deliberadamente <b>dos</b> valores de CN y no deben confundirse: "
       "<b>CN₂</b> es el valor ponderado que sale de la cartografía de "
       "cobertura y grupo hidrológico (Sección 9.5), y <b>CN₂ₛ</b> es ese "
       "mismo valor <b>corregido por la pendiente media de la cuenca</b> según "
       "Williams (1995), porque el CN tabulado del SCS supone pendientes de "
       "≈ 5 % y la cuenca analizada es más empinada. El modelo HEC-HMS se "
       "alimenta con CN₂ₛ; por eso el valor del modelo es mayor que el del "
       "mapa. La misma distinción aplica a los dos coeficientes de "
       "escorrentía: el <b>C ponderado</b> del método racional y el <b>C del "
       "evento</b> (Pe/P del hietograma de diseño) miden cosas distintas y no "
       "son intercambiables.", "italica")


# ---------------------------------------------------------------------------
# Secciones
# ---------------------------------------------------------------------------

def _portada(story, st, R):
    story.append(Spacer(1, 2.5 * cm))
    story.append(Paragraph(_titulo_informe(R), st["titulo"]))
    story.append(Paragraph("HYDROFRA V 1.3", st["subt_centro"]))
    story.append(Spacer(1, 1.0 * cm))
    p = R.proyecto
    # Ubicación política EDTP (municipio / provincia / departamento).
    _ubic_pol = " / ".join(x for x in (getattr(p, "municipio", ""),
                                       getattr(p, "provincia", ""),
                                       getattr(p, "departamento", "")) if x)
    datos = [
        ["Proyecto", p.nombre_proyecto],
        ["Contratante / entidad", getattr(p, "contratante", "") or "—"],
        ["Código SISIN", getattr(p, "codigo_sisin", "") or "—"],
        ["Ubicación política", _ubic_pol or (p.ubicacion or "—")],
        ["Ubicación (descripción)", p.ubicacion],
        ["Tipo de obra", R.tipo_obra.nombre],
        ["Período de retorno de diseño",
         f"T = {R.T_diseno} años ({R.tipo_obra.rango_texto})"
         + (f" · verificación T = {R.T_verificacion}"
            if getattr(R, "T_verificacion", None) else "")],
        ["Norma de referencia", R.tipo_obra.norma],
        ["Coordenadas", f"Lat = {R.lat:.6f}°, Lon = {R.lon:.6f}°"],
        ["Estación de referencia", f"{R.estacion.codigo} — {R.estacion.nombre} ({R.dist_km:.1f} km)"],
        ["Fuente de datos adoptada", R.decision.fuente_adoptada],
        ["Fecha de emisión", datetime.now().strftime("%Y-%m-%d")],
    ]
    story.append(_tabla(datos, col_widths=[6 * cm, 10 * cm], cabecera=False, primera_col_izq=True))
    story.append(Spacer(1, 1.2 * cm))

    # Cuadro de firmas (EDTP: cariz legal/contractual del estudio).
    _p(story, st, "<b>Responsables del estudio</b>", "cuerpo")
    reg = getattr(p, "registro_profesional", "") or "—"
    jefe = getattr(p, "jefe_proyecto", "") or "—"
    firmas = [
        ["Función", "Nombre / Registro", "Firma"],
        ["Especialista en Hidrología e Hidráulica",
         f"{p.ingeniero}\nReg. prof. (SIB/SBP): {reg}", ""],
        ["Jefe de Proyecto", jefe or "—", ""],
    ]
    story.append(_tabla(firmas, col_widths=[6.0 * cm, 6.5 * cm, 3.5 * cm],
                        primera_col_izq=True))
    story.append(Spacer(1, 0.5 * cm))
    _p(story, st,
       "<b>Marco normativo.</b> Este estudio se enmarca en el <b>Reglamento "
       "Básico de Preinversión (RM 115/2015, MPD)</b> y sigue los criterios "
       "técnicos del <b>Manual de Hidrología y Drenaje (Volumen II)</b> y la "
       "<b>Guía para el Diseño de Puentes</b> de la Administradora Boliviana de "
       "Carreteras (ABC), complementados con AASHTO LRFD, FHWA HEC-18/23 y "
       "HEC-RAS/HEC-HMS (USACE) como referencia internacional.")
    story.append(Spacer(1, 0.4 * cm))
    _p(story, st,
       "Los campos administrativos (Contratante, SISIN, ubicación política, "
       "registro profesional y firmas) forman parte del cariz legal-contractual "
       "del EDTP; deben completarse y sellarse antes de la presentación "
       "formal ante la entidad contratante / ABC.", "italica")
    story.append(Spacer(1, 0.8 * cm))
    _p(story, st, "Generado por <b>CURVAS IDF v1.3</b> — Python/NumPy/SciPy/Matplotlib/ReportLab.", "italica")
    story.append(PageBreak())


def _sec_fuentes(story, st, R):
    # Caratula intermedia entre el índice y el cuerpo del informe (no entra al
    # TOC porque usa el estilo "titulo", no h2/h3).
    story.append(PageBreak())
    story.append(Spacer(1, 5 * cm))
    story.append(Paragraph(_titulo_informe(R), st["titulo"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("HYDROFRA V 1.3", st["subt_centro"]))
    story.append(PageBreak())
    _p(story, st, "1. Fuentes de datos", "h2")
    if getattr(R, "serie_observada_usada", False):
        _p(story, st,
           "<b>FUENTE ADOPTADA: SERIE OBSERVADA DE SENAMHI (cargada por el "
           "proyectista).</b> Este estudio se realizó sobre la serie de "
           "precipitación máxima diaria anual <b>observada</b> aportada por el "
           "responsable del proyecto —no sobre productos satelitales—. Todo el "
           "análisis posterior (frecuencia, IDF, caudales, tirante y "
           "socavación) se apoya en estos datos observados. <b>Requisito de "
           "expediente:</b> debe adjuntarse en el Anexo A la certificación de "
           "SENAMHI de la(s) estación(es), con sus metadatos (código, "
           "ubicación, altitud, tipo de instrumento, período y porcentaje de "
           "datos faltantes) y el procedimiento de control de calidad y relleno "
           "aplicado. Las fuentes satelitales que siguen se conservan solo "
           "como contraste de consistencia.", "cuerpo")
    _p(story, st,
       "El análisis combina dos vertientes complementarias de información "
       "hidrometeorológica. La medición en tierra proviene de la red de "
       "estaciones de SENAMHI Bolivia, que aporta la serie de referencia "
       "más cercana al sitio del proyecto. A esa medición se suman tres "
       "productos satelitales y de reanálisis que cubren el mismo período "
       "con resolución espacial: CHIRPS reconstruye la precipitación "
       "histórica continua, NASA POWER suma temperatura y radiación, y "
       "Open-Meteo/ERA5 completa el período reciente vía API. La "
       "combinación de fuentes terrestres y satelitales permite verificar "
       "consistencia y rellenar vacíos antes de cualquier ajuste estadístico.")

    _p(story, st, "1.1 Estación de referencia", "h3")
    e = R.estacion
    datos = [
        ["Parámetro", "Valor"],
        ["Código", e.codigo], ["Nombre", e.nombre], ["Departamento", e.departamento],
        ["Latitud / Longitud", f"{e.latitud:.4f}° / {e.longitud:.4f}°"],
        ["Altitud", f"{e.altitud_msnm:.0f} m s.n.m."],
        ["Distancia al sitio", f"{R.dist_km:.2f} km (vecino más cercano por Haversine)"],
    ]
    story.append(_tabla(datos, col_widths=[6 * cm, 9 * cm], primera_col_izq=True))

    # 1.1.1 Red de estaciones de referencia concurrentes (multiestación).
    red = getattr(R, "red_estaciones", None)
    if red is not None and getattr(red, "estaciones", None):
        _p(story, st, "1.1.1 Red de estaciones de referencia (multiestación)",
           "h3")
        _p(story, st,
           "El Manual de Hidrología y Drenaje de la ABC recomienda apoyar el "
           "análisis en varias estaciones circundantes. Se conforma una red con "
           f"las <b>{red.n_estaciones} estaciones SENAMHI más cercanas</b> del "
           "catálogo, cuyos estadísticos se triangulan por distancia inversa "
           "(IDW) y cuyas series alimentan el análisis de doble masa (Sección "
           "4.1) como referencia regional.")
        cab = ["Código", "Estación", "Dist. (km)", "Altitud (m)",
               "P24 media (mm)", "Rol"]
        fil = [cab]
        for i, es in enumerate(red.estaciones):
            fil.append([es.codigo, es.nombre, f"{es.dist_km:.1f}",
                        f"{es.altitud_m:.0f}", f"{es.p24_media_mm:.1f}",
                        "Principal" if i == 0 else "Circundante"])
        story.append(_tabla(fil, col_widths=[2.3*cm, 4.6*cm, 1.9*cm, 2.0*cm,
                                             2.4*cm, 2.3*cm]))
        if red.idw:
            _p(story, st,
               f"<b>Triangulación IDW</b> (potencia 2) de la red: "
               f"P24 media regional = {red.idw.get('p24_media_mm', 0):.1f} mm, "
               f"desviación = {red.idw.get('p24_desv_mm', 0):.1f} mm, "
               f"altitud media = {red.idw.get('altitud_msnm', 0):.0f} m.")
        if red.correlacion_media == red.correlacion_media:
            _p(story, st,
               f"<b>Correlación cruzada media</b> entre las estaciones de la "
               f"red: R = {red.correlacion_media:.3f}.")
        _p(story, st,
           "Las series concurrentes de la red se reconstruyen a partir de los "
           "estadísticos de cada estación; para el diseño final deben "
           "reemplazarse por los <b>registros históricos observados de "
           "SENAMHI</b> (mínimo 30–40 años), según el Anexo EDTP.", "italica")

    _p(story, st, "1.2 Datos satelitales (resumen)", "h3")
    if not R.series_satelitales:
        _p(story, st,
           "<b>Series satelitales no disponibles en este análisis.</b> "
           "Las APIs de CHIRPS, NASA POWER y Open-Meteo no respondieron "
           "durante la corrida (timeout o error transitorio). El análisis "
           "usa la serie de la estación de referencia más próxima. "
           "Para incluir las fuentes satelitales y su correlación, "
           "reintentar la corrida en unos minutos.", "italica")
        return
    filas = [["Fuente", "Estado", "n años", "Variables complementarias", "Nota"]]
    for s in R.series_satelitales:
        extra = ", ".join(f"{k}={v}" for k, v in s.variables_extra.items() if v is not None) or "—"
        filas.append([s.fuente, "API real" if s.exitosa else "sintético",
                      str(s.n_anios), extra, s.nota])
    story.append(_tabla(filas, col_widths=[3 * cm, 2.3 * cm, 1.6 * cm, 4.6 * cm, 4 * cm]))
    if any(not s.exitosa for s in R.series_satelitales):
        _p(story, st,
           "<b>Nota:</b> algunas fuentes satelitales se generaron de forma "
           "sintética porque la API no respondió (sin red en el entorno de "
           "ejecución). Al desplegar con internet, se obtienen los datos reales.",
           "italica")


def _sec_series(story, st, R):
    story.append(PageBreak())
    _p(story, st, "2. Series anuales y correlación estación–satélite", "h2")
    _p(story, st,
       "Antes de cualquier ajuste estadístico conviene examinar las series "
       "anuales máximas y su consistencia entre fuentes. En esta sección "
       "presentamos la serie P24max de la estación terrestre, la serie "
       "equivalente derivada de los productos satelitales y la comparación "
       "objetiva entre ambas. La decisión sobre qué fuente alimenta los "
       "análisis posteriores se justifica al final con las métricas de "
       "Pearson, Nash-Sutcliffe y RMSE.")

    _p(story, st, "2.1 Serie P24max — Estación de referencia", "h3")
    story.append(_figura(R.graficos["serie_estacion"]))

    if not R.series_satelitales:
        _p(story, st,
           "<b>Sin series satelitales para correlación.</b> "
           "Las APIs satelitales no respondieron — la fuente adoptada "
           "es la estación de referencia más próxima.", "italica")
        return

    _p(story, st, "2.2 Serie P24max — Datos satelitales", "h3")

    # Matriz de procedencia: distingue explícitamente qué fuentes traen dato
    # REAL descargado por API y cuáles cayeron a un respaldo sintético. Sin
    # esta distinción el lector no puede saber qué parte del análisis se apoya
    # en observaciones y qué parte en una reconstrucción.
    _p(story, st, "<b>Matriz de procedencia de las fuentes</b>", "cuerpo")
    filas_pr = [["Fuente", "Naturaleza del dato", "Años", "Estado",
                 "¿Apta para diseño?"]]
    _n_sint = 0
    for s in R.series_satelitales:
        _real = bool(getattr(s, "exitosa", False))
        if not _real:
            _n_sint += 1
        # nº de años: usar el atributo si existe; si no, el largo del DataFrame.
        # OJO: `getattr(...) or []` evalúa la verdad de un DataFrame, que pandas
        # prohíbe (ValueError). Se comprueba None explícitamente.
        _n_anios = getattr(s, "n_anios", None)
        if _n_anios is None:
            _df = getattr(s, "df", None)
            _n_anios = len(_df) if _df is not None else 0
        filas_pr.append([
            s.fuente,
            "Descarga real por API" if _real else
            "RESPALDO SINTÉTICO (la API no respondió)",
            str(_n_anios),
            "Real" if _real else "Sintético",
            "Sí" if _real else "NO — solo referencia",
        ])
    _adop = getattr(R.decision, "fuente_adoptada", "") or ""
    filas_pr.append([f"<b>ADOPTADA: {_adop}</b>",
                     "Serie que alimenta todo el análisis posterior",
                     str(len(R.serie)), "—", "—"])
    story.append(_tabla(filas_pr, col_widths=[3.4*cm, 5.4*cm, 1.5*cm,
                                              2.0*cm, 3.0*cm],
                        primera_col_izq=True))
    if _n_sint:
        _p(story, st,
           f"<b>ADVERTENCIA DE PROCEDENCIA:</b> {_n_sint} de las "
           f"{len(R.series_satelitales)} fuentes consultadas NO devolvieron "
           f"dato real y se completaron con un respaldo sintético generado a "
           f"partir de los estadísticos de la estación. Esas series "
           f"<b>no constituyen observación</b>: se incluyen únicamente para "
           f"mantener comparables los gráficos y NO deben emplearse como "
           f"evidencia. Si la fuente finalmente adoptada fuera una de ellas, "
           f"el estudio no puede considerarse una memoria hidrológica "
           f"observada y debe rehacerse con registros de SENAMHI.", "italica")
    else:
        _p(story, st,
           "Todas las fuentes consultadas devolvieron dato real descargado "
           "por API; no se empleó ningún respaldo sintético.", "italica")

    if "series_satelitales" in R.graficos:
        story.append(_figura(R.graficos["series_satelitales"]))

    story.append(PageBreak())
    _p(story, st, "2.3 Comparación estación vs. satélite", "h3")
    filas = [["Fuente", "n común", "Pearson r", "R²", "RMSE (mm)", "Sesgo (mm)", "NSE", "Tend. (mm/año)"]]
    for m in R.decision.metricas:
        filas.append([m.fuente, str(m.n_comun), f"{m.pearson_r:.3f}", f"{m.r2:.3f}",
                      f"{m.rmse_mm:.2f}", f"{m.sesgo_mm:+.2f}", f"{m.nash_sutcliffe:.3f}",
                      f"{m.tendencia_mm_anio:+.3f}"])
    story.append(_tabla(filas, col_widths=[3.2*cm, 1.6*cm, 1.8*cm, 1.3*cm, 1.8*cm, 1.8*cm, 1.5*cm, 2.2*cm]))

    _p(story, st, "2.4 Correlación y decisión de fuente", "h3")
    if "correlacion" in R.graficos:
        story.append(_figura(R.graficos["correlacion"], ancho_cm=11))
    _p(story, st, f"<b>Fuente adoptada:</b> {R.decision.fuente_adoptada}.")
    _p(story, st, R.decision.justificacion)
    # Qué miden y qué NO miden las métricas de la tabla 2.3. Sin esta
    # aclaración, un r bajo o un NSE negativo se leen como prueba de que la
    # fuente satelital es mala, cuando en realidad la referencia contra la que
    # se comparan puede no ser una observación.
    _serie_est_real = bool(getattr(R, "serie_observada_usada", False)
                           or getattr(R.estacion, "serie_observada", False))
    _p(story, st, "<b>Cómo deben leerse las métricas de la tabla 2.3</b>",
       "cuerpo")
    if not _serie_est_real:
        _p(story, st,
           "<b>Advertencia metodológica.</b> Los coeficientes de correlación "
           "de Pearson, R², RMSE y Nash-Sutcliffe de la tabla anterior miden "
           "el acuerdo de cada producto grillado contra la serie de la "
           "estación de referencia. Cuando esa serie de referencia "
           "<b>no es un registro observado</b> sino una reconstrucción a "
           "partir de los estadísticos de la estación (ver la matriz de "
           "procedencia de la Sección 2.2), esas métricas <b>no constituyen "
           "una medida de la calidad del producto satelital</b>: dos series "
           "con la misma media y desviación pero distinta secuencia temporal "
           "producen correlación cercana a cero y NSE negativo aunque ambas "
           "sean estadísticamente equivalentes para el análisis de "
           "frecuencia, que solo usa la distribución de los máximos y no su "
           "orden cronológico.", "italica")
        _p(story, st,
           "En consecuencia: (1) un <b>NSE negativo en este contexto no "
           "descalifica</b> a la fuente adoptada, del mismo modo que un NSE "
           "alto no la validaría; (2) la decisión de fuente se apoya en la "
           "cobertura temporal, la continuidad del registro y el "
           "comportamiento de la cola alta, no en el acuerdo año a año; y "
           "(3) para que estas métricas adquieran valor probatorio es "
           "imprescindible incorporar el <b>registro diario observado de "
           "SENAMHI</b>, tal como se detalla en el Anexo de requisitos. "
           "Mientras esa incorporación no ocurra, la tabla 2.3 debe leerse "
           "como diagnóstico de consistencia interna, no como validación.")
    else:
        _p(story, st,
           "La serie de referencia procede de registro observado, por lo que "
           "las métricas de la tabla 2.3 sí constituyen una medida válida del "
           "acuerdo entre cada producto grillado y la observación local.",
           "italica")


def _sec_descriptivos(story, st, R):
    story.append(PageBreak())
    _p(story, st, "3. Estadísticos descriptivos", "h2")
    _p(story, st,
       "La caracterización descriptiva de la serie adoptada describe el "
       "centro, la dispersión y la forma de la distribución empírica de "
       "P24max. Los cuartiles y los percentiles altos (P95, P99) son "
       "particularmente útiles para acotar la incertidumbre de los "
       "cuantiles extremos calculados más adelante.")
    d = R.desc
    filas = [
        ["Estadístico", "Valor", "Unidad"],
        ["n", f"{d.n}", "años"], ["Media", f"{d.media:.3f}", "mm"],
        ["Mediana", f"{d.mediana:.3f}", "mm"], ["Mínimo", f"{d.minimo:.2f}", "mm"],
        ["Máximo", f"{d.maximo:.2f}", "mm"], ["Rango", f"{d.rango:.2f}", "mm"],
        ["Desv. estándar σ", f"{d.desv_std:.3f}", "mm"], ["Varianza", f"{d.varianza:.3f}", "mm²"],
        ["Coef. variación CV", f"{d.cv:.4f}", "–"], ["Asimetría", f"{d.asimetria:.4f}", "–"],
        ["Curtosis", f"{d.curtosis:.4f}", "–"], ["Q1 / Q3", f"{d.q1:.2f} / {d.q3:.2f}", "mm"],
        ["IQR", f"{d.iqr:.2f}", "mm"],
        ["P10/P90/P95/P99", f"{d.p10:.1f}/{d.p90:.1f}/{d.p95:.1f}/{d.p99:.1f}", "mm"],
        ["IC 95% de la media", f"[{d.ic95_media_low:.2f}, {d.ic95_media_high:.2f}]", "mm"],
    ]
    story.append(_tabla(filas, col_widths=[6 * cm, 6 * cm, 3 * cm], primera_col_izq=True))
    # Nota de depuración: si se descartaron outliers (errores de dato), se
    # informa para que el n y el máximo de la tabla sean trazables.
    desc_out = getattr(R, "anios_descartados", None) or []
    if desc_out:
        detalle = "; ".join(f"{d['anio']} ({d['p24_mm']} mm)" for d in desc_out)
        _p(story, st,
           f"<b>Depuración de datos:</b> se descartaron {len(desc_out)} "
           f"año(s) con P24max físicamente imposible (error de la fuente), "
           f"no usados en los estadísticos ni en el análisis de frecuencia: "
           f"{detalle}. Criterio: el valor supera la climatología oficial "
           f"SENAMHI de la estación de referencia (media + 6·σ). Para "
           f"caudales máximos NO se completan ni interpolan datos: se usa la "
           f"serie observada tal cual, descartando solo errores groseros.",
           "italica")


def _sec_consistencia(story, st, R):
    story.append(PageBreak())
    _p(story, st, "4. Análisis de consistencia de datos", "h2")
    _p(story, st,
       "Antes de ajustar cualquier distribución a la serie conviene "
       "verificar que cumple las hipótesis de aleatoriedad, independencia "
       "y estacionariedad que esos modelos exigen. La OMM (WMO-168) y el "
       "Bulletin 17C del USGS describen el procedimiento estándar: "
       "detectar valores anómalos con Grubbs-Beck, evaluar la "
       "independencia mediante la autocorrelación lag-1 y las rachas de "
       "Wald-Wolfowitz, identificar tendencias con Mann-Kendall y revisar "
       "la homogeneidad con Pettitt. La tabla siguiente resume el "
       "resultado de cada prueba.")
    filas = [["Prueba", "Estadístico", "p-valor", "Veredicto", "Comentario"]]
    for p in R.pruebas:
        filas.append([p.nombre, f"{p.estadistico:.3f}",
                      "—" if p.p_valor is None else f"{p.p_valor:.4f}",
                      "cumple" if p.pasa else "no cumple", p.conclusion])
    story.append(_tabla(filas, col_widths=[3.4*cm, 2*cm, 1.6*cm, 2*cm, 6*cm]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_figura(R.graficos["serie_estacion"]))

    # 4.1 Doble masa (consistencia frente al patrón regional, EDTP-ABC).
    dm = getattr(R, "doble_masa", None)
    if dm is not None:
        story.append(PageBreak())
        _p(story, st, "4.1 Análisis de doble masa (consistencia regional)", "h3")
        _p(story, st,
           "El Manual de Hidrología y Drenaje de la ABC exige verificar la "
           "homogeneidad de la fuente adoptada mediante la <b>curva de doble "
           "masa</b> (doble acumulación): se compara la precipitación anual "
           "acumulada de la fuente adoptada contra el promedio regional "
           "acumulado de las fuentes vecinas independientes. Si la fuente es "
           "consistente, los puntos se alinean sobre una recta; un quiebre de "
           "pendiente delata un cambio de régimen o un error sistemático.")
        _p(story, st,
           f"<b>Fuente analizada:</b> {dm.fuente_analizada}. "
           f"<b>Referencia regional:</b> {', '.join(dm.fuentes_referencia)} "
           f"({dm.n_anios} años comunes). <b>Coeficiente de correlación de "
           f"Pearson R = {dm.pearson_r:.4f}</b>; pendiente de la recta "
           f"= {dm.pendiente:.3f}.")
        _p(story, st, f"<b>Veredicto:</b> {dm.mensaje}",
           "cuerpo" if dm.consistente else "italica")
        if "doble_masa" in R.graficos:
            story.append(_figura(R.graficos["doble_masa"], ancho_cm=13.0,
                                 max_alto_cm=12.0))


def _sec_frecuencias(story, st, R):
    story.append(PageBreak())
    _p(story, st, "5. Análisis de frecuencias", "h2")
    _p(story, st,
       "El paso siguiente es ajustar a la serie las distribuciones "
       "teóricas que el Manual de Hidrología y Drenaje de la ABC y la "
       "literatura andina recomiendan para máximos de precipitación: las dos "
       "familias de valor extremo (GEV y <b>Gumbel EV-I</b>), <b>Pearson III</b> "
       "y su transformación logarítmica <b>Log-Pearson III</b>, y la "
       "<b>Log-Normal de 2 y 3 parámetros</b>; se incluye Normal como "
       "referencia. La calidad de cada ajuste se evalúa "
       "con cuatro criterios complementarios: Kolmogorov-Smirnov para "
       "contrastar la hipótesis nula de pertenencia, <b>Anderson-Darling "
       "(A²)</b> que pondera más las colas y es el más informativo para "
       "los extremos de diseño, RMSE de los cuantiles graficados con "
       "posiciones de Weibull, y AIC para penalizar la complejidad. La "
       "distribución de diseño se elige por <b>menor A² entre las que "
       "pasan KS al 5 %</b>, criterio recomendado por la OMM (WMO-No. 168) y el Bulletin 17C del USGS para seleccionar distribuciones de extremos, "
       "que evita el sobreajuste de modelos flexibles como GEV en series "
       "cortas.")
    if getattr(R, "hershfield_aplicado", False):
        _p(story, st,
           "<b>Corrección de Hershfield:</b> la serie proviene de una "
           "estación terrestre leída a hora fija (08:00), por lo que sus "
           "máximos de 24 h subestiman el verdadero máximo móvil; se aplicó "
           "el factor ×1.13 (Weiss 1964) a la serie antes del análisis de "
           "frecuencia.", "italica")

    # ── Validez de la hipótesis estacionaria (observación §3.2 de la revisión).
    # El análisis de frecuencia clásico exige serie independiente, homogénea y
    # estacionaria. Si la Sección 4 rechazó alguna de esas hipótesis, hay que
    # declararlo aquí y acotar el alcance en vez de extrapolar en silencio.
    _fallidas = [p for p in (R.pruebas or []) if not p.pasa]
    if _fallidas:
        _nombres = ", ".join(p.nombre for p in _fallidas)
        _hay_tendencia = any("Mann-Kendall" in p.nombre for p in _fallidas)
        _hay_dependencia = any(("Autocorrelación" in p.nombre
                                or "Wald" in p.nombre) for p in _fallidas)
        _p(story, st,
           "<b>Validez de la hipótesis estacionaria — advertencia.</b> El "
           f"análisis de consistencia de la Sección 4 <b>rechazó</b> la(s) "
           f"siguiente(s) hipótesis: <b>{_nombres}</b>. El ajuste de "
           "frecuencia que se presenta a continuación es un modelo "
           "<b>estacionario</b>, es decir, supone que la distribución de los "
           "máximos anuales no cambia con el tiempo. Ese supuesto queda "
           "parcialmente comprometido y sus consecuencias deben explicitarse.")
        if _hay_tendencia:
            _p(story, st,
               "• <b>Tendencia detectada.</b> Un resultado significativo de "
               "Mann-Kendall admite varias explicaciones que deben "
               "distinguirse antes de modelar: señal climática real, cambio de "
               "instrumento o de emplazamiento de la estación, cambio de "
               "cobertura en la cuenca, o artefacto del propio producto "
               "grillado (los reanálisis cambian de constelación de satélites "
               "a lo largo del período y pueden introducir saltos "
               "artificiales). Con la información disponible <b>no es posible "
               "atribuir la tendencia</b>, por lo que se conserva el modelo "
               "estacionario —la alternativa no estacionaria con covariable "
               "temporal exigiría extrapolar también esa covariable al "
               "horizonte de diseño, añadiendo incertidumbre en lugar de "
               "reducirla— y se declara la limitación.")
        if _hay_dependencia:
            _p(story, st,
               "• <b>Dependencia serial.</b> La autocorrelación significativa "
               "implica que los años no son plenamente independientes, de modo "
               "que el <b>tamaño efectivo de muestra es menor</b> que el "
               "número de años registrados. El efecto práctico no es sesgar el "
               "cuantil central, sino <b>ensanchar su incertidumbre</b>: los "
               "intervalos de confianza de la Sección 6.1 deben leerse como "
               "una cota inferior del error real.")
        _p(story, st,
           "• <b>Restricción de alcance que se deriva.</b> Se mantiene el "
           "ajuste estacionario por ser el procedimiento normado y "
           "reproducible, pero: (1) los cuantiles se publican con su intervalo "
           "de confianza (Sección 6.1); (2) los períodos de retorno muy "
           "superiores a la longitud de la serie se reportan como "
           "<b>extrapolación</b> y se usan solo como verificación de riesgo; y "
           "(3) la vía correcta para resolver esta observación no es cambiar "
           "de distribución, sino <b>incorporar registros observados de "
           "estaciones vecinas</b> y extender el período de análisis, lo que "
           "permitiría además contrastar un modelo no estacionario con "
           "validación cruzada.", "cuerpo")
    filas = [["Distribución", "KS", "KS p", "χ²", "χ² p", "A² (AD)",
              "AIC", "Acepta 5%"]]
    for a in R.ajustes:
        ad = (f"{a.ad_estadistico:.3f}"
              if a.ad_estadistico == a.ad_estadistico else "—")
        chi = (f"{a.chi2_estadistico:.2f}"
               if getattr(a, "chi2_estadistico", float('nan')) == a.chi2_estadistico
               else "—")
        chip = (f"{a.chi2_pvalor:.3f}"
                if getattr(a, "chi2_pvalor", float('nan')) == a.chi2_pvalor
                else "—")
        filas.append([a.nombre, f"{a.ks_estadistico:.3f}",
                      f"{a.ks_pvalor:.3f}", chi, chip, ad,
                      f"{a.aic:.1f}", "Sí" if a.aceptada_ks else "No"])
    story.append(_tabla(filas, col_widths=[3.3*cm, 1.7*cm, 1.7*cm, 1.7*cm,
                                           1.7*cm, 1.9*cm, 1.9*cm, 1.9*cm]))
    _p(story, st,
       "Las pruebas de bondad de ajuste aplicadas son las que exige el Manual "
       "de Hidrología y Drenaje de la ABC: <b>Kolmogorov-Smirnov (KS)</b> y "
       "<b>Chi-cuadrado (χ²)</b> —ambas con su p-valor al nivel de "
       "significancia α = 0.05— complementadas con <b>Anderson-Darling (A²)</b> "
       "para las colas y el AIC. Una distribución se acepta cuando su p-valor "
       "supera 0.05 (no se rechaza la hipótesis de pertenencia).", "cuerpo")
    _p(story, st, f"<b>Distribución de diseño adoptada (menor A²):</b> "
                  f"{R.mejor_ajuste.nombre} "
                  f"(A² = {R.mejor_ajuste.ad_estadistico:.3f}, "
                  f"KS p = {R.mejor_ajuste.ks_pvalor:.4f}, "
                  f"χ² p = {getattr(R.mejor_ajuste, 'chi2_pvalor', float('nan')):.3f}).")
    gr = getattr(R, "grubbs", None)
    if gr and gr.get("aplicable"):
        _p(story, st,
           f"<b>Detección de valores atípicos (Smirnov-Grubbs, α = 5 %):</b> "
           f"{gr['mensaje']}", "italica")
    story.append(Spacer(1, 0.3 * cm))
    story.append(_figura(R.graficos["ajustes"]))


def _sec_cuantiles(story, st, R):
    story.append(PageBreak())
    _p(story, st, "6. Cuantiles P24max por período de retorno", "h2")
    _p(story, st,
       "Con la distribución elegida en la sección anterior calculamos los "
       "cuantiles de P24max para los períodos de retorno habituales en "
       "obras de drenaje vial e hidráulica. El período de diseño y su "
       "rango normativo provienen del tipo de obra adoptado.")
    o = R.tipo_obra
    _p(story, st,
       f"La estructura analizada corresponde a {o.nombre}. La norma "
       f"{o.norma} reconoce un rango de períodos de retorno de "
       f"{o.rango_texto}, dentro del cual se adopta T = {R.T_diseno} años "
       f"para el diseño.")
    cr = getattr(R, "correccion_regional", None)
    if cr:
        _p(story, st,
           f"<b>Corrección de piso regional aplicada.</b> El P24(T=100) "
           f"ajustado de la fuente satelital fue "
           f"{cr['p24_100_observado']:.0f} mm, por debajo del rango físico "
           f"de la región «{cr['region']}» "
           f"({cr['rango_mm'][0]:.0f}–{cr['rango_mm'][1]:.0f} mm) — las "
           f"fuentes grilladas (CHIRPS/ERA5/IMERG) suavizan los extremos de "
           f"cola alta. Para no subestimar los caudales de diseño se escaló "
           f"toda la serie por un factor <b>×{cr['factor']:.2f}</b>, que lleva "
           f"el P24(100) al piso regional ({cr['p24_100_corregido']:.0f} mm). "
           f"El escalado es multiplicativo, de modo que la corrección se "
           f"propaga de forma consistente a los cuantiles, la IDF, los "
           f"hietogramas, la modelación HEC-HMS, el caudal máximo, el tirante "
           f"y la socavación. Los valores de la tabla siguiente ya incluyen "
           f"esta corrección.", "italica")
        # Trazabilidad completa del factor: serie y cuantiles antes/después.
        _p(story, st,
           "<b>Naturaleza y limitación del factor.</b> El factor NO es una "
           "regionalización estadística formal: es un <b>piso físico de "
           "contraste</b> tomado del rango de P24(100) documentado para la "
           "región, aplicado para evitar que un producto grillado que "
           "subestima la cola alta propague caudales de diseño no "
           "conservadores. Mientras no se disponga de registros pluviométricos "
           "observados en estaciones vecinas con los que construir una curva "
           "regional de frecuencia, este factor debe considerarse una "
           "<b>hipótesis de trabajo trazable y reversible</b>, no una "
           "estimación calibrada. Los tres escenarios de la tabla de "
           "sensibilidad permiten al proyectista dimensionar con o sin "
           "corrección y medir su impacto.", "italica")
        qsc = getattr(R, "cuantiles_sin_correccion", None)
        if qsc is not None and len(qsc):
            _p(story, st, "<b>Serie y cuantiles antes / después de la "
                          "corrección</b>", "cuerpo")
            filas_cmp = [["Concepto", "Sin corrección", "Corregido",
                          "Factor"]]
            filas_cmp.append(["Media de la serie (mm)",
                              f"{cr.get('media_serie_antes', 0):.2f}",
                              f"{cr.get('media_serie_despues', 0):.2f}",
                              f"×{cr['factor']:.2f}"])
            filas_cmp.append(["Máximo de la serie (mm)",
                              f"{cr.get('max_serie_antes', 0):.2f}",
                              f"{cr.get('max_serie_despues', 0):.2f}",
                              f"×{cr['factor']:.2f}"])
            _q_ant = {int(r["T_anios"]): float(r["p24_mm"])
                      for _, r in qsc.iterrows()}
            _q_des = {int(r["T_anios"]): float(r["p24_mm"])
                      for _, r in R.cuantiles.iterrows()}
            for T in sorted(set(_q_ant) & set(_q_des)):
                if T not in (2, 5, 10, 25, 50, 100, 500, 1000):
                    continue
                a, d = _q_ant[T], _q_des[T]
                filas_cmp.append([f"P24 para T = {T} años (mm)",
                                  f"{a:.2f}", f"{d:.2f}",
                                  f"×{d / a:.2f}" if a else "—"])
            story.append(_tabla(filas_cmp,
                                col_widths=[6.0*cm, 3.4*cm, 3.4*cm, 2.4*cm],
                                primera_col_izq=True))
            _p(story, st,
               "La columna «Factor» debe ser constante e igual al factor "
               "aplicado en TODOS los períodos de retorno: el escalado es "
               "multiplicativo sobre la serie, de modo que la distribución "
               "ajustada conserva su forma y todos los cuantiles se desplazan "
               "en la misma proporción. Cualquier desviación en esa columna "
               "indicaría un error de propagación.", "italica")

        # Escenarios de sensibilidad exigidos por la revisión técnica.
        _p(story, st, "<b>Análisis de sensibilidad del factor regional</b>",
           "cuerpo")
        _fc = float(cr["factor"])
        _p100_sin = float(cr["p24_100_observado"])
        esc = [["Escenario", "Factor", "P24(100) (mm)", "Uso recomendado"],
               ["A — Sin corrección (fuente cruda)", "×1.00",
                f"{_p100_sin:.0f}",
                "Cota inferior; NO usar si la fuente subestima extremos"],
               ["B — Corrección adoptada (piso regional)", f"×{_fc:.2f}",
                f"{_p100_sin * _fc:.0f}",
                "Valor adoptado en este informe"],
               ["C — Conservador (límite superior regional)",
                f"×{float(cr['rango_mm'][1]) / _p100_sin:.2f}",
                f"{float(cr['rango_mm'][1]):.0f}",
                "Verificación de riesgo / diseño del lado seguro"]]
        story.append(_tabla(esc, col_widths=[5.6*cm, 1.9*cm, 2.5*cm, 5.2*cm],
                            primera_col_izq=True))
        _p(story, st,
           f"<b>Clasificación climática empleada:</b> región «{cr['region']}»"
           + (f" a {cr['altitud_m']:.0f} m s.n.m." if cr.get("altitud_m")
              else "")
           + f", determinada por las coordenadas del sitio y la altitud. La "
           f"clasificación condiciona el rango de P24(100) adoptado como piso "
           f"({cr['rango_mm'][0]:.0f}–{cr['rango_mm'][1]:.0f} mm), por lo que "
           f"debe verificarse contra la caracterización pluviométrica local "
           f"antes de aprobar el estudio.", "italica")
    filas = [["T (años)", "Prob. no exc.", f"P24max — {R.mejor_ajuste.nombre} (mm)"]]
    for _, r in R.cuantiles.iterrows():
        filas.append([f"{int(r['T_anios'])}", f"{r['prob_no_exc']:.5f}", f"{r['p24_mm']:.2f}"])
    story.append(_tabla(filas, col_widths=[3.5 * cm, 4.5 * cm, 6 * cm]))
    # Sanity-check regional del P24(T=100): advertir si cae fuera del rango
    # físico esperable para la región (skill hidrología Bolivia).
    val = getattr(R, "p24_validacion_regional", None)
    if val:
        _p(story, st,
           f"<b>Verificación regional:</b> {val['mensaje']} "
           f"(rango típico de la región «{val['region']}»: "
           f"{val['rango_mm'][0]}–{val['rango_mm'][1]} mm para T=100 años). "
           f"Se recomienda revisar la serie y el ajuste antes de adoptar "
           f"estos cuantiles para diseño.", "italica")

    # 6.1 Incertidumbre de los cuantiles (bootstrap) — exigido por la revisión.
    ic = getattr(R, "ic_cuantiles", None)
    if ic is not None and len(ic):
        story.append(PageBreak())
        _p(story, st, "6.1 Incertidumbre de los cuantiles de diseño", "h3")
        n_serie = len(R.serie)
        _p(story, st,
           f"Los cuantiles de la tabla anterior son <b>estimaciones puntuales</b> "
           f"obtenidas de una muestra de <b>{n_serie} años</b>. Presentarlos sin "
           f"su incertidumbre sería engañoso: con muestras cortas, la "
           f"extrapolación a períodos de retorno altos tiene un error de "
           f"muestreo considerable. La tabla siguiente reporta el intervalo de "
           f"confianza del 90 % obtenido por <b>bootstrap no paramétrico</b> "
           f"(remuestreo con reemplazo de la serie, reajuste de la "
           f"distribución en cada réplica y percentiles 5 % y 95 % de los "
           f"cuantiles resultantes).")
        cab = ["T (años)", "P24 estimado (mm)", "IC 90 % inferior (mm)",
               "IC 90 % superior (mm)", "Amplitud del IC"]
        fil = [cab]
        for _, r in ic.iterrows():
            fil.append([f"{int(r['T_anios'])}", f"{r['p24_mm']:.1f}",
                        f"{r['ic_inf']:.1f}", f"{r['ic_sup']:.1f}",
                        f"±{r['amplitud_rel_pct']:.0f} %"])
        story.append(_tabla(fil, col_widths=[2.4*cm, 3.4*cm, 3.6*cm, 3.6*cm,
                                             2.8*cm]))
        try:
            _peor = ic.iloc[int(ic["amplitud_rel_pct"].idxmax())]
            _txt_peor = (f" Para T = {int(_peor['T_anios'])} años el intervalo "
                         f"abarca {_peor['ic_inf']:.0f}–{_peor['ic_sup']:.0f} mm "
                         f"(amplitud {_peor['amplitud_rel_pct']:.0f} %).")
        except Exception:  # noqa: BLE001
            _txt_peor = ""
        _p(story, st,
           "<b>Lectura de la incertidumbre.</b> La amplitud del intervalo "
           "crece con el período de retorno porque la extrapolación se apoya "
           "cada vez menos en datos observados y cada vez más en la cola "
           "ajustada de la distribución." + _txt_peor + " En consecuencia: "
           "(1) el cuantil de <b>diseño</b> debe interpretarse como valor "
           "central de un rango, no como una cifra exacta; (2) los períodos de "
           "retorno superiores a 500 años deben usarse solo como "
           "<b>verificación de riesgo</b> cuando la norma lo exija, nunca como "
           "base única de dimensionamiento; y (3) la forma robusta de reducir "
           "esta incertidumbre no es cambiar de distribución, sino "
           "<b>alargar la serie observada</b> e incorporar estaciones "
           "regionales reales.", "cuerpo")


def _sec_desagregacion(story, st, R):
    story.append(PageBreak())
    _p(story, st, "7. Desagregación a duraciones sub-diarias", "h2")
    _p(story, st,
       "Los cuantiles obtenidos hasta acá corresponden a la lluvia "
       "máxima de 24 horas. Para construir curvas IDF necesitamos también "
       "los valores para duraciones intermedias, desde unos minutos hasta "
       "el día. Para esa desagregación aplicamos la fórmula clásica de "
       f"Dyck-Peschke, P<sub>d</sub> = P<sub>24h</sub>·(d/1440)<sup>n</sup>, "
       f"con exponente n = {getattr(R, 'exp_dyck_peschke', R.exp_dp):.2f} "
       f"ajustado a la región climática "
       f"«{getattr(R, 'region_dyck_peschke', '') or 'Bolivia'}» "
       f"(altiplano 0.22 · valles 0.25 · yungas 0.29 · llanos 0.27). "
       f"<b>Procedencia de estos exponentes:</b> la ley de desagregación es de Dyck y Peschke (1995); los valores por región climática son un <b>criterio interno adoptado</b> por esta herramienta a partir de la práctica hidrológica boliviana, NO un valor normado ni publicado con referencia trazable, por lo que deben verificarse contra registros pluviográficos locales antes de aprobar el estudio. La tabla "
       "siguiente reporta las intensidades resultantes (i = P/d en horas) "
       "para las duraciones sub-diarias que exige el Manual ABC (5, 10, 15, "
       "30, 60, 120, 360, 720 y 1440 min).")
    # Coeficientes de desagregación k_d = (d/1440)^n para las duraciones ABC.
    _nexp = float(getattr(R, "exp_dyck_peschke", R.exp_dp))
    _durs_abc = [5, 10, 15, 30, 60, 120, 360, 720, 1440]
    _cab_k = ["d (min)"] + [str(d) for d in _durs_abc]
    _fila_k = ["k = (d/1440)^n"] + [f"{(d/1440.0)**_nexp:.3f}" for d in _durs_abc]
    story.append(_tabla([_cab_k, _fila_k],
                        col_widths=[3.0*cm] + [1.4*cm]*len(_durs_abc)))
    _p(story, st,
       f"El coeficiente de desagregación k lleva la lámina de 24 h a cada "
       f"duración: P<sub>d</sub> = k·P<sub>24h</sub> (n = {_nexp:.2f}). Por "
       f"debajo de 10 min el valor es una extrapolación de la ley de "
       f"Dyck-Peschke y debe usarse con cautela.", "italica")

    # Sensibilidad al exponente de desagregación (observación §3.4 de la
    # revisión: la IDF sub-horaria no está respaldada por observaciones, por lo
    # que debe reportarse la banda que introduce la elección del exponente).
    _p24d = float(getattr(R, "p24_diseno_mm", 0) or 0)
    if _p24d > 0:
        _p(story, st, "<b>Sensibilidad al exponente de desagregación</b>",
           "cuerpo")
        _p(story, st,
           f"El exponente n no se mide: se adopta por región climática "
           f"(altiplano 0.22 · valles 0.25 · llanos 0.27 · yungas 0.29). Como "
           f"la serie base es diaria, esa elección <b>determina por completo</b> "
           f"las intensidades de duración corta. La tabla siguiente muestra la "
           f"banda que introduce el exponente sobre la lámina de diseño "
           f"P24 = {_p24d:.1f} mm (T = {R.T_diseno} años), comparando el valor "
           f"adoptado con los extremos del rango regional boliviano.")
        _durs_s = [10, 30, 60, 120, 360, 1440]
        _exps = sorted({0.22, round(_nexp, 2), 0.29})
        cab_s = ["Exponente n"] + [f"P({d} min)" for d in _durs_s] + ["Δ vs adoptado"]
        fil_s = [cab_s]
        _ref = {d: _p24d * (d / 1440.0) ** _nexp for d in _durs_s}
        for e in _exps:
            etiqueta = (f"{e:.2f} (adoptado)" if abs(e - round(_nexp, 2)) < 1e-9
                        else f"{e:.2f}")
            vals = [_p24d * (d / 1440.0) ** e for d in _durs_s]
            # Desviación relativa en la duración más corta (la más sensible).
            dv = (100.0 * (vals[0] - _ref[_durs_s[0]]) / _ref[_durs_s[0]]
                  if _ref[_durs_s[0]] else 0.0)
            fil_s.append([etiqueta] + [f"{v:.1f}" for v in vals] +
                         [f"{dv:+.0f} %"])
        story.append(_tabla(fil_s,
                            col_widths=[3.0*cm] + [1.75*cm]*len(_durs_s)
                            + [2.2*cm]))
        _p(story, st,
           "La divergencia entre exponentes es máxima en las duraciones "
           "cortas y prácticamente nula en 1440 min (por construcción, todos "
           "convergen a P24). Esa banda es la <b>incertidumbre irreducible</b> "
           "de la IDF sub-horaria mientras no existan registros pluviográficos "
           "locales, y debe tenerse presente al dimensionar obras cuyo tiempo "
           "de concentración sea corto.", "italica")
    pivot = R.idf_largo.pivot(index="duracion_min", columns="T_anios", values="i_mm_h").round(2).sort_index()
    cab = ["d (min)"] + [f"T={t}" for t in pivot.columns]
    filas = [cab]
    for d, row in pivot.iterrows():
        filas.append([f"{int(d)}"] + [f"{v:.2f}" for v in row.tolist()])
    nT = len(pivot.columns)
    ancho_T = min(1.45, (16.5 - 1.6) / max(nT, 1))
    col_w = [1.6 * cm] + [ancho_T * cm] * nT
    story.append(_tabla(filas, col_widths=col_w))


def _sec_modelos_idf(story, st, R):
    story.append(PageBreak())
    _p(story, st, "8. Modelos IDF", "h2")
    _p(story, st,
       "Sobre la tabla intensidad–duración–frecuencia desagregada en la "
       "sección anterior calibramos siete modelos IDF de uso extendido. "
       "Cada uno propone una forma funcional distinta para describir cómo "
       "la intensidad disminuye con la duración y crece con el período "
       "de retorno. Todos se ajustan por mínimos cuadrados y se "
       "caracterizan por su ecuación, sus parámetros y la bondad de "
       "ajuste (R² y RMSE).")
    # Tabla resumen comparativa
    filas = [["#", "Modelo", "Ecuación", "R²", "RMSE (mm/h)"]]
    for k, m in enumerate(R.modelos, 1):
        marca = " ★" if m.nombre == R.modelo_recomendado.nombre else ""
        filas.append([str(k), m.nombre + marca, m.ecuacion, f"{m.r2:.4f}", f"{m.rmse_mm_h:.3f}"])
    story.append(_tabla(filas, col_widths=[1*cm, 3.8*cm, 6.2*cm, 1.8*cm, 2.2*cm]))

    # 8.0 Ecuación analítica ABC adoptada I = k·T^m/(d+c)^n.
    ms = getattr(R, "modelo_sherman", None)
    if ms is not None:
        _p(story, st, "8.0 Ecuación IDF analítica adoptada (forma ABC)", "h3")
        _p(story, st,
           "El Manual de Hidrología y Drenaje de la ABC adopta la ecuación "
           "general de intensidad <b>I = k·T<sup>m</sup> / (d + c)<sup>n</sup></b> "
           "(I en mm/h, T en años, d en min). Sus parámetros se ajustan por "
           "<b>mínimos cuadrados no lineales</b> (scipy <i>curve_fit</i>) sobre "
           "la tabla IDF desagregada. Los coeficientes obtenidos son:")
        filas = [["Parámetro", "Símbolo", "Valor"],
                 ["Coef. de intensidad", "k", f"{ms.a:.4f}"],
                 ["Exponente de frecuencia", "m", f"{ms.m:.4f}"],
                 ["Exponente de duración", "n", f"{ms.n:.4f}"],
                 ["Constante de duración", "c", f"{ms.b:.4f}"],
                 ["Bondad de ajuste", "R²", f"{ms.r2:.4f}"],
                 ["Error", "RMSE", f"{ms.rmse_mm_h:.3f} mm/h"]]
        story.append(_tabla(filas, col_widths=[6.0*cm, 2.5*cm, 4.0*cm],
                            primera_col_izq=True))
        _p(story, st,
           f"<b>Ecuación adoptada:</b> I = {ms.a:.3f}·T<sup>{ms.m:.4f}</sup> / "
           f"(d + {ms.b:.3f})<sup>{ms.n:.4f}</sup>  (R² = {ms.r2:.4f}).")
        _p(story, st,
           "<b>Naturaleza de esta curva IDF y lectura correcta del R².</b> "
           "Debe distinguirse entre tres tipos de curva IDF que no son "
           "equivalentes: una <b>IDF observada</b>, calibrada sobre registros "
           "pluviográficos sub-horarios; una <b>IDF regionalizada</b>, "
           "derivada de relaciones ajustadas con varias estaciones de la "
           "región; y una <b>IDF sintética por desagregación</b>, obtenida al "
           "repartir la lámina diaria P24 entre duraciones menores mediante "
           "una ley teórica. <b>La curva de este informe pertenece a la "
           "tercera categoría</b>: la serie base es diaria y las intensidades "
           "sub-horarias se generan por Dyck-Peschke (Sección 7).")
        _p(story, st,
           f"En consecuencia, el <b>R² = {ms.r2:.4f} no valida la física de "
           f"la curva</b>: mide únicamente con qué fidelidad la forma "
           f"analítica I = k·T^m/(d+c)^n reproduce la tabla que se generó con "
           f"la ley de desagregación, es decir, es un ajuste de una fórmula a "
           f"otra fórmula. Un R² alto era esperable y no constituye evidencia "
           f"de que las intensidades de 5–60 min ocurran realmente con esa "
           f"magnitud en el sitio. Para elevar esta curva a la categoría de "
           f"regionalizada u observada se requieren registros pluviográficos "
           f"o de pluviómetro automático, o relaciones de desagregación "
           f"calibradas con estaciones de la región. Mientras eso no exista, "
           f"las intensidades de duración corta deben usarse con la "
           f"<b>reserva</b> indicada en la Sección 7 y contrastarse con los "
           f"tres exponentes de desagregación allí analizados.", "italica")

    _p(story, st, "Modelo recomendado según el tipo de dato", "h3")
    _p(story, st,
       f"{R.justificacion_modelo} En este caso la resolución de partida es "
       f"{R.resolucion_datos}, y entre los modelos que la literatura "
       f"recomienda para ese contexto "
       f"({', '.join(R.modelos_preferidos)}) el que mejor ajusta la tabla "
       f"IDF es {R.modelo_recomendado.nombre} con R² = "
       f"{R.modelo_recomendado.r2:.4f}, identificado con ★ en la tabla "
       "comparativa. Esta elección sigue los lineamientos de los estudios "
       "regionales de evaluación de IDF realizados en México y Bolivia.")
    story.append(Spacer(1, 0.3 * cm))
    story.append(_figura(R.graficos["modelos_idf_comparacion"]))

    # Detalle por modelo (subsecciones 8.1..8.7). Saltos de página antes de
    # 8.1, 8.4 y 8.7 para que cada bloque de modelos arranque limpio.
    for k, m in enumerate(R.modelos, 1):
        if k in (1, 4, 7):
            story.append(PageBreak())
        _p(story, st, f"8.{k} {m.nombre}", "h3")
        _p(story, st, f"Ecuación: <b>{m.ecuacion}</b>")
        filas = [["Parámetro", "Valor"]]
        for nombre, val in m.parametros.items():
            filas.append([nombre, f"{val:.5g}" if isinstance(val, float) else str(val)])
        filas.append(["R²", f"{m.r2:.4f}"])
        filas.append(["RMSE", f"{m.rmse_mm_h:.3f} mm/h"])
        story.append(_tabla(filas, col_widths=[5 * cm, 6 * cm], primera_col_izq=True))
        clave = f"modelo_{k}"
        if clave in R.graficos:
            story.append(Spacer(1, 0.2 * cm))
            story.append(_figura(R.graficos[clave], ancho_cm=14))


def _sec_mapas(story, st, R):
    story.append(PageBreak())
    cuenca_real = R.graficos.get("mapa_cuenca_real")
    tematicos = R.graficos.get("mapas_tematicos_reales") or []
    n_tem = len(tematicos)
    if cuenca_real and n_tem == 8:
        sufijo = ""
    elif cuenca_real and n_tem > 0:
        sufijo = f" (parcialmente real, {n_tem + 1}/9 mapas)"
    elif cuenca_real:
        sufijo = " (solo 9.1 real)"
    else:
        sufijo = " (cartografía no disponible)"
    _p(story, st, "9. Cartografía de la cuenca" + sufijo, "h2")
    # Tabla diagnóstica al inicio: estado REAL / NO DISPONIBLE por mapa.
    # HYDROFRA v1.3 eliminó los mapas esquemáticos sintéticos: si un mapa
    # no se pudo generar con datos reales (GEE/COP-DEM), se marca «no
    # disponible» en lugar de mostrar un dibujo falso.
    motivo_gee = R.graficos.get("mapas_gee_motivo")
    estados_mapas = [
        ("Mapa", "Estado", "Fuente / motivo"),
        ("9.1 Cuenca + cauce principal",
            "REAL" if cuenca_real else "NO DISPONIBLE",
            ("Hillshade COP-DEM GLO-30 + watershed MERIT Hydro / HydroBASINS"
             if cuenca_real else
             (motivo_gee or "GEE no respondió — sin delineación de cuenca"))),
    ]
    mapas_tematicos = [
        ("9.2 Red de drenaje", "mapa_red_drenaje",
            "D8 + flow-acc sobre COP-DEM 12.5 m"),
        ("9.3 Uso de suelo", "mapa_uso_suelo",
            "FROM-GLC10 10 m (Gong et al. 2019); MapBiomas 30 m fallback"),
        ("9.4 Cobertura del suelo", "mapa_cobertura",
            "ESRI Global LULC 10 m + triangulación WorldCover/Dynamic World/FROM-GLC10"),
        ("9.5 CN del SCS", "mapa_cn",
            "GCN250 + HYSOGs250m (grupo hidrológico real); MapBiomas×CN fallback"),
        ("9.6 Pendientes", "mapa_pendientes",
            "Terrain.slope (Horn) sobre COP-DEM GLO-30 reproyectado a UTM"),
        ("9.7 Coef. escorrentía", "mapa_coef_escorrentia",
            "FROM-GLC10 × pendiente COP-DEM (método racional)"),
        ("9.8 Coef. Manning", "mapa_manning",
            "MapBiomas × n de Manning (Chow, 1959)"),
        ("9.9 Riesgo de inundación", "mapa_riesgo_inundacion",
            "HAND (MERIT Hydro) + agua permanente JRC Global Surface Water"),
    ]
    for titulo, clave, fuente in mapas_tematicos:
        es_real = clave in tematicos
        estados_mapas.append((
            titulo,
            "REAL" if es_real else "NO DISPONIBLE",
            fuente if es_real else
            (motivo_gee or "GEE no devolvió este mapa real"),
        ))
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    tabla = Table(
        [[_celda(c, _CELDA_CAB) for c in estados_mapas[0]]] +
        [[_celda(c, _CELDA_IZQ if i_col != 1 else _CELDA)
          for i_col, c in enumerate(fila)]
         for fila in estados_mapas[1:]],
        colWidths=[6 * cm, 2.5 * cm, 8.5 * cm], hAlign="CENTER",
        repeatRows=1,
    )
    style = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a68")),
    ])
    # Pinto las filas ESQUEMÁTICAS en rojo claro y REAL en verde claro
    for i, fila in enumerate(estados_mapas[1:], 1):
        if fila[1] == "REAL":
            style.add("BACKGROUND", (1, i), (1, i),
                          colors.HexColor("#d4edda"))
        else:
            style.add("BACKGROUND", (1, i), (1, i),
                          colors.HexColor("#f8d7da"))
    tabla.setStyle(style)
    story.append(tabla)
    story.append(Spacer(1, 0.3 * cm))
    if cuenca_real and n_tem == 8:
        _p(story, st,
           "La cartografía está construida en su totalidad sobre el polígono "
           "delineado por watershed D8 con MERIT Hydro 90 m, y cada capa "
           "temática proviene de un dataset reconocido de Google Earth "
           "Engine. La cuenca y su cauce principal se representan con el "
           "hillshade de COP-DEM GLO-30 (Copernicus, 30 m), la red de drenaje "
           "se deriva de la "
           "acumulación de flujo (upa) de MERIT Hydro con tres umbrales "
           "(0.5, 5 y 50 km²) para distinguir cauces capilares, "
           "secundarios y principales, y la cobertura del suelo se "
           "describe en dos escalas complementarias: MapBiomas Bolivia "
           "LULC v1 a 30 m para el uso de suelo (mapa 9.3) y ESRI Global "
           "LULC 10 m Time Series (Impact Observatory / ESRI / Microsoft, "
           "año más reciente) para la cobertura del suelo (mapa 9.4). "
           "El número de curva CN del SCS se calcula remapeando MapBiomas "
           "según la tabla de grupo hidrológico B con una paleta que va "
           "del verde (CN bajo) al rojo (CN alto). Las pendientes se "
           "calculan con np.gradient sobre el COP-DEM GLO-30 downscaled "
           "a 12.5 m y se clasifican en "
           "rangos geotécnicos. El último mapa reporta el coeficiente de "
           "escorrentía C por píxel calculado por el método racional "
           "como combinación de uso de suelo y pendiente. El mapa 9.9 "
           "cierra la serie con la susceptibilidad a la inundación, "
           "derivada del índice HAND (Height Above Nearest Drainage) de "
           "MERIT Hydro —la altura vertical de cada píxel sobre el cauce "
           "más cercano al que drena— reforzada con la ocurrencia de agua "
           "superficial permanente del JRC Global Surface Water: cuanto "
           "menor es el HAND, más próximo está el terreno al nivel del "
           "cauce y mayor es su propensión a anegarse. Todos los "
           "mapas comparten la misma simbología cartográfica: grilla UTM "
           "cada 2500 m, leyenda con el porcentaje de área de cada clase "
           "y barra de escala graduada.")
    elif cuenca_real:
        _p(story, st,
           f"El mapa 9.1 es real y muestra el hillshade COP-DEM GLO-30 con el "
           f"polígono delineado por watershed MERIT Hydro / HydroBASINS. De "
           f"los ocho mapas temáticos restantes, {n_tem} salieron reales; "
           f"los faltantes NO se incluyen (HYDROFRA v1.3 ya no genera "
           f"esquemas sintéticos) porque algún dataset GEE no respondió "
           f"durante la generación. Reintentar el análisis suele "
           f"completarlos.")
    else:
        _p(story, st,
           "La cartografía de la cuenca no está disponible para este "
           "análisis: no se pudo delinear la cuenca con datos reales "
           "(MERIT Hydro / HydroBASINS no respondieron) ni generar los "
           "mapas temáticos con Google Earth Engine. HYDROFRA v1.3 no "
           "genera mapas esquemáticos sintéticos — se prefiere declarar "
           "la ausencia antes que mostrar un dibujo no representativo. "
           "Verificar el estado de GEE en /gee_status y reintentar el "
           "análisis.")
    motivo = R.graficos.get("mapas_gee_motivo")
    if motivo:
        _p(story, st,
           f"<b>Diagnóstico de mapas GEE</b>: {motivo}", "italica")
    # El 9.7 es el coef. de escorrentía real; si no se generó, cae al
    # isoyetas esquemático como respaldo.
    # 9.7: solo el coef. de escorrentía real (el isoyetas esquemático fue
    # eliminado en v1.3). Si no existe, simplemente no se muestra.
    mapa_97 = ("mapa_coef_escorrentia", "9.7 Mapa de coeficiente de escorrentía C")
    mapas = [
        ("mapa_cuenca", "9.1 Mapa de la cuenca y cauce principal"),
        ("mapa_red_drenaje", "9.2 Mapa de red de drenaje"),
        ("mapa_uso_suelo", "9.3 Mapa de uso de suelo"),
        ("mapa_cobertura", "9.4 Mapa de cobertura del suelo (ESRI LULC 10 m)"),
        ("mapa_cn", "9.5 Mapa de número de curva CN (SCS)"),
        ("mapa_pendientes", "9.6 Mapa de pendientes"),
        mapa_97,
        ("mapa_manning", "9.8 Mapa del coeficiente de Manning (n)"),
        ("mapa_riesgo_inundacion",
            "9.9 Mapa de riesgo de inundación (HAND · MERIT Hydro)"),
    ]
    # Cada mapa en su propia página. Incluido el 9.1: arranca con un salto para
    # que el título del primer mapa quede al principio de la hoja siguiente.
    for clave, titulo in mapas:
        if clave not in R.graficos:
            continue
        story.append(PageBreak())
        _p(story, st, titulo, "h3")
        # Mapa a casi todo el ancho útil de la página letter (≈18 cm).
        story.append(_figura(R.graficos[clave], ancho_cm=17.9, max_alto_cm=22.0))

    _sec_morfologia(story, st, R)


def _sec_morfologia(story, st, R):
    """Subsecciones 9.10 (variables morfológicas), 9.11 (hipsométrica), 9.12 (análisis)."""
    A = R.analisis_morf
    if A is None:
        story.append(PageBreak())
        _p(story, st, "9.10 Morfología de la cuenca", "h3")
        _p(story, st,
           "<b>No disponible:</b> el análisis morfológico detallado requiere la "
           "delineación real de la cuenca (watershed MERIT Hydro), que no pudo "
           "obtenerse para este punto. Se reportan los parámetros básicos en la "
           "sección 10 (tiempo de concentración) a partir de la morfología estimada.",
           "italica")
        return

    # 9.10 Parámetros morfométricos completos (estilo ArcGeek Calculator)
    story.append(PageBreak())
    _p(story, st, "9.10 Parámetros morfométricos de la cuenca", "h3")
    _p(story, st,
       "A continuación reportamos el conjunto completo de parámetros "
       "morfométricos e hidrológicos derivados de la cuenca delineada, "
       "ordenados como en la herramienta ArcGeek Calculator de QGIS para "
       "facilitar la comparación. La geometría y el relieve provienen "
       "directamente del DEM, la red de drenaje y el orden de Strahler se "
       "calculan sobre la acumulación de flujo (upa), y el CN junto con "
       "el coeficiente de escorrentía se toman de los mapas 9.5 y 9.7. "
       "Cada grupo incluye además una columna con la fórmula utilizada, "
       "de modo que el cálculo es auditable.")
    _p(story, st,
       "<b>Fuente del Modelo Digital de Elevación (DEM).</b> El relieve, las "
       "pendientes y la geometría de la cuenca se derivan del <b>Copernicus "
       "GLO-30 (COP-DEM, 30 m nativo, remuestreado a 12.5 m para el trazado "
       "del cauce)</b>; la delineación de la cuenca y la red de drenaje "
       "provienen de <b>MERIT Hydro (90 m, Yamazaki et al. 2019)</b> con "
       "respaldo en HydroBASINS. Para el nivel EDTP de diseño final se "
       "recomienda sustituir estas fuentes globales por un <b>levantamiento "
       "topográfico local (LiDAR o restitución fotogramétrica a escala "
       "1:1.000–1:2.000)</b> en el eje del puente y la cuenca tributaria "
       "inmediata; los parámetros de esta sección quedan entonces como "
       "referencia de prediseño verificable en campo.", "cuerpo")
    cn_show = R.cn_ponderado or A.cn
    c_show = R.c_ponderado
    s_show = (25400.0 / cn_show - 254.0) if cn_show else A.retencion_s_mm
    cw = [0.9*cm, 6.2*cm, 4.2*cm, 2.6*cm, 2.6*cm]

    def _grupo(titulo, filas, salto=False):
        if salto:
            story.append(PageBreak())
        _p(story, st, titulo, "cuerpo")
        cab = [["#", "Parámetro", "Símbolo / fórmula", "Valor", "Unidad"]]
        story.append(_tabla(cab + filas, col_widths=cw, primera_col_izq=True))

    _grupo("Dimensiones básicas (1–6)", [
        ["1", "Área de la cuenca", "A", f"{A.area_km2:.2f}", "km²"],
        ["2", "Perímetro", "P", f"{A.perimetro_km:.2f}", "km"],
        ["3", "Longitud de la cuenca", "Lb (axial)", f"{A.long_axial_km:.2f}", "km"],
        ["4", "Longitud del cauce principal", "Lc (D8)", f"{A.long_cauce_principal_km:.2f}", "km"],
        ["5", "Ancho de la cuenca", "W = A/Lb", f"{A.ancho_medio_km:.2f}", "km"],
        ["6", "Relieve", "H = Hmax−Hmin", f"{A.desnivel_m:.0f}", "m"],
    ])
    _grupo("Elevación y pendiente (7–11)", [
        ["7", "Elevación media", "Hmed", f"{A.cota_media_m:.0f}", "m s.n.m."],
        ["8", "Elevación mínima", "Hmin", f"{A.cota_menor_m:.0f}", "m s.n.m."],
        ["9", "Elevación máxima", "Hmax", f"{A.cota_mayor_m:.0f}", "m s.n.m."],
        ["10", "Pendiente media (grados)", "Sc", f"{A.pendiente_cuenca_grados:.2f}", "°"],
        ["11", "Pendiente media (%)", "Sc", f"{A.pendiente_cuenca_pct:.1f}", "%"],
    ])
    _grupo("Forma (12–19)", [
        ["12", "Factor de forma (Horton)", "Ff = A/Lb²", f"{A.ff_horton:.3f}", "—"],
        ["13", "Relación de elongación (Schumm)", "Re = 1.128√A/Lb", f"{A.re_elongacion:.3f}", "—"],
        ["14", "Relación de circularidad (Miller)", "Rc = 4πA/P²", f"{A.rc_circularidad:.3f}", "—"],
        ["15", "Coef. de compacidad (Gravelius)", "Kc = 0.28P/√A", f"{A.kc_gravelius:.2f}", "—"],
        ["16", "Rectángulo equiv. — lado mayor", "L = (Kc√A/1.12)·(1+√(1−(1.12/Kc)²))",
         f"{A.rect_lado_mayor_km:.2f}", "km"],
        ["17", "Rectángulo equiv. — lado menor", "l = (Kc√A/1.12)·(1−√(1−(1.12/Kc)²))",
         f"{A.rect_lado_menor_km:.2f}", "km"],
        ["18", "Coef. de masividad", "Cm = Hmed/A", f"{A.coef_masividad:.2f}", "m/km²"],
        ["19", "Forma de la cuenca", "—", A.clase_forma.split('(')[0].strip(), "—"],
    ])
    _grupo("Drenaje (16–20)", [
        ["16", "Densidad de drenaje", "Dd = ΣL/A", f"{A.densidad_drenaje_km_km2:.2f}", "km/km²"],
        ["17", "Frecuencia de corrientes", "F = N/A", f"{A.frecuencia_corrientes:.2f}", "1/km²"],
        ["18", "Relación de bifurcación", "Rb = Nx/Nx+1", f"{A.relacion_bifurcacion:.2f}", "—"],
        ["19", "Textura de drenaje", "T = N/P", f"{A.textura_drenaje:.2f}", "1/km"],
        ["20", "Orden de la cuenca (Strahler)", "ω", f"{A.orden_max}", "—"],
    ])
    # Lr = distancia recta cabecera→exutorio medida sobre el MISMO trazado D8
    # que el cauce principal (NO la longitud axial de la cuenca, que es otra
    # magnitud). Así S = Lc/Lr es reproducible desde esta misma tabla.
    _lr = getattr(A, "long_recta_cauce_km", 0.0) or 0.0
    _grupo("Sinuosidad y longitudes (21–24)", [
        ["21", "Sinuosidad del cauce principal", "S = Lc/Lr",
         f"{A.sinuosidad:.2f}" if A.sinuosidad else "—", "—"],
        ["22", "Longitud del cauce (con meandros)", "Lc",
         f"{A.long_cauce_principal_km:.2f}", "km"],
        ["23", "Longitud recta (cabecera→exutorio)", "Lr",
         f"{_lr:.2f}" if _lr else "—", "km"],
        ["24", "Longitud axial de la cuenca", "Lb (≠ Lr)",
         f"{A.long_axial_km:.2f}", "km"],
    ], salto=True)
    _p(story, st,
       "<b>Nota sobre la sinuosidad.</b> La sinuosidad se calcula como "
       "S = Lc/Lr, donde <b>Lr es la distancia recta cabecera→exutorio medida "
       "sobre el mismo trazado D8</b> con el que se mide Lc — no la longitud "
       "axial de la cuenca Lb, que es una magnitud distinta (mide la extensión "
       "del polígono, no del cauce). Ambos valores se publican por separado "
       "para que S sea verificable directamente desde esta tabla.", "italica")
    if getattr(A, "sinuosidad_inconsistente", False):
        _p(story, st,
           "<b>ADVERTENCIA DE CONSISTENCIA GEOMÉTRICA:</b> la longitud del "
           "cauce principal resultó MENOR que la distancia recta entre sus "
           "extremos (S &lt; 1), lo cual es físicamente imposible. Esto indica "
           "que la extracción del cauce por D8 sobre el DEM quedó "
           "<b>truncada</b> (por resolución del DEM, umbral de acumulación de "
           "flujo o discontinuidad del trazado). Los parámetros que dependen de "
           "Lc —sinuosidad, pendiente del cauce y tiempo de concentración— "
           "deben verificarse con topografía local antes de usarse para "
           "diseño; se declara aquí en lugar de acotar el valor a 1.0.",
           "italica")
    _grupo("Hidrológicos avanzados (29–33)", [
        ["29", "Número de rugosidad (Melton)", "Rn = Dd·H", f"{A.numero_rugosidad:.2f}", "—"],
        ["30", "Número de curva (SCS)", "CN", f"{cn_show:.0f}" if cn_show else "—", "—"],
        ["31", "Intensidad de drenaje", "ID = Dd·F", f"{A.intensidad_drenaje:.2f}", "1/km³"],
        ["32", "Coef. de escorrentía", "C", f"{c_show:.2f}" if c_show else "—", "—"],
        ["33", "Retención potencial (infiltración)", "S = 25400/CN−254", f"{s_show:.0f}", "mm"],
    ])
    if A.n_por_orden:
        orden_txt = ", ".join(f"orden {k}: {v}" for k, v in sorted(A.n_por_orden.items()))
        _p(story, st, f"<b>Corrientes por orden de Strahler:</b> {orden_txt} "
                      f"(total N = {A.n_corrientes}).", "italica")
    _p(story, st,
       "Los <b>tiempos de concentración</b> por múltiples fórmulas (Kirpich, "
       "Témez, California, Giandotti, Ventura, Passini, Bransby-Williams y SCS — "
       "parámetros 24–28) se detallan en la sección 10.", "italica")

    # 9.11 Curva hipsométrica
    story.append(PageBreak())
    _p(story, st, "9.11 Curva hipsométrica y distribución altimétrica", "h3")
    _p(story, st,
       "La curva hipsométrica vincula la altura relativa de la cuenca "
       "con el área que queda por encima de cada cota, y su forma resume "
       "el estado evolutivo del relieve. En este caso la integral "
       f"hipsométrica vale HI = {A.integral_hipsometrica:.3f}, que "
       f"corresponde a una cuenca en {A.estado_cuenca.lower()}.")
    if "hipsometrica" in R.graficos:
        story.append(_figura(R.graficos["hipsometrica"], ancho_cm=15))
    # Tabla de rangos de elevación
    filas = [["Banda (m s.n.m.)", "Área (km²)", "Área (%)", "% acum. (≥ cota inf.)"]]
    for b in A.bandas_elevacion:
        filas.append([f"{b.desde_m:.0f} – {b.hasta_m:.0f}",
                      f"{b.area_km2:.2f}", f"{b.pct:.1f}", f"{b.pct_acum:.1f}"])
    story.append(_tabla(filas, col_widths=[5*cm, 3.2*cm, 3*cm, 3.5*cm]))

    # 9.12 Análisis morfológico (índices de forma + interpretación)
    story.append(PageBreak())
    _p(story, st, "9.12 Análisis morfológico de la cuenca", "h3")
    _p(story, st,
       "Los índices de forma sintetizan la geometría real de la cuenca y "
       "permiten anticipar cómo responderá hidrológicamente: una cuenca "
       "circular y compacta concentrará las crecidas, mientras que una "
       "elongada las atenuará. La tabla siguiente combina cinco índices "
       "clásicos con su interpretación cualitativa.")
    filas = [["Índice", "Fórmula", "Valor", "Interpretación"]]
    filas += [
        ["Coef. de compacidad (Gravelius)", "Kc = 0.28·P/√A",
         f"{A.kc_gravelius:.2f}", _interp_kc(A.kc_gravelius)],
        ["Factor de forma (Horton)", "Ff = A/Lb²",
         f"{A.ff_horton:.3f}", _interp_ff(A.ff_horton)],
        ["Razón de elongación (Schumm)", "Re = 1.128·√A/Lb",
         f"{A.re_elongacion:.3f}", _interp_re(A.re_elongacion)],
        ["Razón de circularidad (Miller)", "Rc = 4πA/P²",
         f"{A.rc_circularidad:.3f}", _interp_rc(A.rc_circularidad)],
        ["Coef. de masividad", "Cm = Hmed/A",
         f"{A.coef_masividad:.2f}", "—"],
        ["Rectángulo equiv. (lado mayor)", "L_re",
         f"{A.rect_lado_mayor_km:.2f} km", "—"],
        ["Rectángulo equiv. (lado menor)", "l_re",
         f"{A.rect_lado_menor_km:.2f} km", "—"],
    ]
    story.append(_tabla(filas, col_widths=[5*cm, 3.6*cm, 2.4*cm, 5*cm],
                        primera_col_izq=True))

    # Interpretaciones cualitativas (parámetros 34–36 de ArcGeek).
    _p(story, st, "Interpretación de la respuesta hidrológica", "cuerpo")
    filas = [["Aspecto", "Clasificación"]]
    filas += [
        ["Forma de la cuenca (34)", A.clase_forma],
        ["Pendiente media (35)", A.interp_pendiente],
        ["Densidad de drenaje", A.interp_dd],
        ["Tiempo de concentración (36)", A.interp_tc or "—"],
        ["Estado evolutivo (hipsometría)", A.estado_cuenca],
    ]
    story.append(_tabla(filas, col_widths=[6*cm, 10*cm], primera_col_izq=True))

    _p(story, st,
       f"<b>Síntesis:</b> la cuenca es de forma <b>{A.clase_forma}</b>, de orden "
       f"<b>{A.orden_max}</b> de Strahler con relación de bifurcación "
       f"Rb = {A.relacion_bifurcacion:.1f} y sinuosidad del cauce principal "
       f"{A.sinuosidad:.2f}. Con HI = {A.integral_hipsometrica:.2f} está en "
       f"{A.estado_cuenca.split('(')[0].strip().lower()}; la densidad de "
       f"drenaje ({A.densidad_drenaje_km_km2:.2f} km/km², {A.interp_dd}) y la "
       f"pendiente media de la cuenca ({A.pendiente_cuenca_pct:.1f}% / "
       f"{A.pendiente_cuenca_grados:.1f}°) determinan una "
       f"{A.interp_tc or 'respuesta hidrológica acorde'} y condicionan el "
       f"tiempo de concentración adoptado (Sección 10).")

    # Coeficientes de escorrentía (ponderado del mapa 9.7 + evento de diseño).
    partes = []
    if getattr(R, "cn_ponderado", None):
        partes.append(f"el <b>CN ponderado</b> de la cuenca es "
                      f"<b>{R.cn_ponderado:.0f}</b> (mapa 9.5)")
    if getattr(R, "c_ponderado", None):
        partes.append(f"el <b>coeficiente de escorrentía C ponderado</b> "
                      f"(racional, mapa 9.7) es <b>{R.c_ponderado:.2f}</b>")
    if getattr(R, "c_evento", None) and getattr(R, "p24_diseno_mm", None):
        partes.append(f"el <b>C del evento de diseño</b> (SCS-CN, "
                      f"P24<sub>T={R.T_diseno}</sub> = {R.p24_diseno_mm:.0f} mm) "
                      f"resulta <b>C = {R.c_evento:.2f}</b>")
    if partes:
        _p(story, st, "Coeficientes de escorrentía: " + "; ".join(partes) + ".")


def _interp_kc(kc):
    if kc < 1.25:
        return "casi redonda (crecidas intensas)"
    if kc < 1.5:
        return "oval-redonda a oval-oblonga"
    return "oval-oblonga a rectangular (atenuada)"


def _interp_ff(ff):
    if ff > 0.5:
        return "ensanchada (respuesta rápida)"
    if ff < 0.3:
        return "alargada (respuesta lenta)"
    return "intermedia"


def _interp_re(re):
    if re >= 0.9:
        return "circular (relieve bajo)"
    if re >= 0.7:
        return "oval"
    if re >= 0.5:
        return "menos alargada"
    return "alargada (relieve pronunciado)"


def _interp_rc(rc):
    if rc > 0.75:
        return "circular"
    if rc > 0.5:
        return "oval"
    return "alargada"


def _interp_dd(dd):
    if dd < 0.5:
        return "drenaje pobre, suelos permeables"
    if dd < 1.5:
        return "drenaje moderado"
    if dd < 2.5:
        return "drenaje alto"
    return "drenaje muy alto, suelos impermeables"


def _sec_tiempo_concentracion(story, st, R):
    story.append(PageBreak())
    _p(story, st, "10. Tiempo de concentración", "h2")
    A = getattr(R, "analisis_morf", None)
    m = R.morfologia
    real_DEM = A is not None and not getattr(m, "sintetica", True)

    _p(story, st, "10.1 Datos de entrada (provenientes de la sección 9)", "h3")
    if real_DEM:
        _p(story, st,
           "Todas las fórmulas que aparecen en la Sección 10.2 se evalúan con "
           "los parámetros reales obtenidos en la sección anterior. Área y "
           "perímetro provienen del polígono delineado por watershed D8 "
           "sobre MERIT Hydro 90 m, mientras que la longitud del cauce "
           "principal sale del seguimiento del flujo D8 hasta el exutorio "
           "y no de una estimación por ley de Hack. Las cotas Hmax y Hmin "
           "se leen del DEM enmascarado, la pendiente del cauce se "
           "calcula como S = ΔH/Lc reales, y el CN se toma como promedio "
           "ponderado por área (mapa 9.5) en lugar de su valor modal. "
           "Esa elección preserva la trazabilidad y mejora la coherencia "
           "del Tc con el resto del informe.")
    else:
        _p(story, st,
           "<b>Morfología sintética:</b> al no obtenerse delineación real, se "
           "estimó por ley de Hack y rangos andinos. El procedimiento profesional "
           "recomendado es:")
        etapas = [
            ["Etapa", "Acción", "Herramienta"],
            ["1. Preprocesamiento DEM",
             "Descargar tiles ALOS PALSAR 12.5 m (ASF), mosaico y recorte, "
             "llenado de sumideros (Fill Sinks), dirección y acumulación de flujo.",
             "QGIS / GRASS r.fill.dir / GEE"],
            ["2. Delimitación de cuenca",
             "Umbral de área contribuyente, delimitar cuenca desde el punto de "
             "cierre (Watershed) y extraer el cauce principal.", "QGIS Watershed"],
            ["3. Parámetros morfométricos",
             "Extraer L, H, S = H/L, A y CN (uso de suelo + grupo hidrológico).",
             "Geometría DEM / CORINE-USGS"],
            ["4. Aplicación de fórmulas Tc",
             "Calcular Tc con las fórmulas aplicables y adoptar el representativo.",
             "Cálculo (este software)"],
        ]
        story.append(_tabla(etapas, col_widths=[3.6*cm, 9*cm, 3.4*cm],
                            primera_col_izq=True))

    # Tabla de los valores efectivamente usados en las fórmulas de la Sección 10.2,
    # con la fuente explícita de cada uno (sección de origen).
    cn_show = R.cn_ponderado or m.cn
    if A is not None:
        filas = [["Parámetro", "Valor", "Unidad", "Origen"],
                 ["A (área)", f"{A.area_km2:.2f}", "km²", "Sección 9.10 — cuenca DEM"],
                 ["P (perímetro)", f"{A.perimetro_km:.2f}", "km", "Sección 9.10 — cuenca DEM"],
                 ["Lc (cauce principal)", f"{m.long_cauce_km:.3f}", "km",
                  "Sección 9.10 — D8 hasta exutorio"],
                 ["Lb (longitud axial)", f"{A.long_axial_km:.2f}", "km",
                  "Sección 9.10 — polígono"],
                 ["Hmax / Hmin", f"{A.cota_mayor_m:.0f} / {A.cota_menor_m:.0f}",
                  "m s.n.m.", "Sección 9.10 — DEM"],
                 ["H (desnivel)", f"{m.desnivel_m:.0f}", "m", "Sección 9.10 — DEM"],
                 ["Sc (pend. media cuenca)",
                  f"{A.pendiente_cuenca_pct:.1f} / {A.pendiente_cuenca_grados:.2f}",
                  "% / °", "Sección 9.10 — DEM"],
                 ["S (pend. cauce, ΔH/Lc)", f"{m.pendiente_pct:.2f}", "%",
                  "Sección 9.10 — DEM real"],
                 ["CN ponderado", f"{cn_show:.0f}", "—",
                  "Sección 9.5 — MapBiomas remap"],
                 ["S (retención SCS)", f"{A.retencion_s_mm:.0f}", "mm",
                  "25400/CN − 254"],
                 ["Orden de Strahler", f"{A.orden_max}", "—",
                  "Sección 9.10 — red MERIT"],
                 ["Densidad de drenaje", f"{A.densidad_drenaje_km_km2:.2f}",
                  "km/km²", "Sección 9.10 — red MERIT"],
                 ["Ff (Horton) / Kc (Gravelius)",
                  f"{A.ff_horton:.3f} / {A.kc_gravelius:.2f}", "—",
                  "Sección 9.12 — forma"],
                 ["Forma de la cuenca", A.clase_forma, "—", "Sección 9.12"]]
    else:
        filas = [["Parámetro", "Valor", "Unidad", "Origen"],
                 ["A (área)", f"{m.area_km2:.2f}", "km²", "estimada"],
                 ["L (cauce, Hack)", f"{m.long_cauce_km:.3f}", "km", "Hack"],
                 ["P (perímetro)", f"{m.perimetro_km:.2f}", "km", "elipse equiv."],
                 ["H (desnivel)", f"{m.desnivel_m:.1f}", "m", "estimado"],
                 ["S (pendiente)", f"{m.pendiente_pct:.2f}", "%", "estimada"],
                 ["CN", f"{m.cn:.0f}", "—", "sintético"],
                 ["Ff (Horton)", f"{m.ff_horton:.3f}", "—", "geometría"],
                 ["Kc (Gravelius)", f"{m.kc_gravelius:.3f}", "—", "geometría"],
                 ["Forma", m.clase_forma, "—", "geometría"]]
    story.append(_tabla(filas, col_widths=[5.2*cm, 3.6*cm, 2.4*cm, 5.2*cm],
                        primera_col_izq=True))

    _p(story, st, "10.2 Tc por fórmula empírica", "h3")
    filas = [["Fórmula", "Expresión", "Tc (min)", "Tc (h)"]]
    for r in R.tc_resultados:
        if r.aplicable:
            filas.append([r.nombre, r.formula, f"{r.tc_min:.1f}", f"{r.tc_horas:.3f}"])
        else:
            filas.append([r.nombre, r.formula, "N/A", r.nota])
    story.append(_tabla(filas, col_widths=[4*cm, 5.5*cm, 2.5*cm, 2.5*cm]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_figura(R.graficos["tc"]))

    _p(story, st, "10.3 Criterios de adopción (procedimiento paso a paso)", "h3")
    tc = R.tc_adoptado
    pasos = [
        ["Paso", "Criterio", "Resultado"],
        ["1. Tamaño de cuenca", tc.clase_area, "métodos por área"],
        ["2. Pendiente del cauce", tc.clase_pendiente, "métodos por pendiente"],
        ["3. Disponibilidad de CN",
         "CN verificado: " + ("Sí (SCS incluido)" if tc.cn_disponible else "No (SCS descartado)"),
         "filtro SCS"],
        ["4. Estadística (CV)", tc.regla_cv, f"CV = {tc.cv_pct:.1f}%"],
        ["Validación de forma", f"Ff = {tc.ff_horton:.2f}, Kc = {tc.kc_gravelius:.2f} "
         f"({tc.clase_forma}). {tc.regla_forma}", "descartes por forma"],
        ["5. Conservadorismo (obra)", tc.regla_conservadorismo,
         f"según {R.tipo_obra.nombre}"],
    ]
    story.append(_tabla(pasos, col_widths=[3.4*cm, 8.6*cm, 3*cm], primera_col_izq=True))

    resumen = [
        ["Tc mínimo", "Tc promedio", "Tc mediana", "Tc máximo", "Tc ADOPTADO"],
        [f"{tc.tc_min_val:.0f} min", f"{tc.tc_promedio:.0f} min", f"{tc.tc_mediana:.0f} min",
         f"{tc.tc_max_val:.0f} min", f"{tc.tc_min:.0f} min ({tc.tc_horas:.2f} h)"],
    ]
    story.append(_tabla(resumen, col_widths=[3*cm] * 5))
    _p(story, st,
       f"Métodos usados ({tc.n_usadas}): {', '.join(tc.usadas)}. "
       + (f"Descartados: {', '.join(tc.descartadas)}. " if tc.descartadas else ""))
    # Enunciado ÚNICO del criterio que produjo el valor adoptado: evita que el
    # informe describa la adopción de dos maneras distintas en secciones
    # diferentes (p. ej. «promedio depurado» en una y «máximo» en otra).
    if getattr(tc, "criterio_final", ""):
        _p(story, st,
           f"<b>Criterio de adopción aplicado:</b> el valor "
           f"Tc = <b>{tc.tc_min:.0f} min</b> ({tc.tc_horas:.2f} h) corresponde "
           f"al <b>{tc.criterio_final}</b>. Éste es el único criterio "
           f"empleado; el resto de estadísticos del cuadro anterior (mínimo, "
           f"mediana, máximo) se listan como referencia de dispersión y no "
           f"intervienen en el cálculo.")
    _p(story, st,
       f"<b>Rango de Tc y su efecto.</b> Las fórmulas depuradas abarcan de "
       f"{tc.tc_min_val:.0f} a {tc.tc_max_val:.0f} min (CV = {tc.cv_pct:.1f} %). "
       f"El tiempo de concentración actúa en dos sentidos opuestos: un Tc "
       f"mayor <b>reduce</b> la intensidad leída de la IDF, pero <b>alarga</b> "
       f"el tiempo de respuesta y aplana el hidrograma. Por eso el rango "
       f"completo se propaga como variable en el análisis de sensibilidad de "
       f"la Sección 14.7, en lugar de darse por resuelto con un valor único.")
    _p(story, st,
       "Sobre la recomendación regional para cuencas altoandinas: tanto la "
       "USFX en Bolivia como la PUCP en Perú han documentado que en cuencas "
       "con relieve pronunciado y áreas entre 10 y 2000 km² el método de "
       "Témez ofrece buena coherencia hidrológica, por lo que se emplea como "
       "criterio de respaldo cuando la dispersión entre métodos (CV) es "
       "elevada. Dicho respaldo <b>solo se aplica si el método sigue vigente "
       "tras el filtro de forma</b> del paso anterior: si la geometría de la "
       "cuenca lo descartó, no vuelve a introducirse. Calibrar la ecuación "
       "con datos locales de SENAMHI mejora aún más la representación.",
       "italica")


def _sec_caudal_maximo(story, st, R):
    """Sección 11 — Caudal máximo Q(T) por 5 métodos × 9 períodos de retorno."""
    story.append(PageBreak())
    _p(story, st, "11. Caudales máximos de diseño", "h2")
    if R.qmax_tabla is None or len(R.qmax_tabla) == 0:
        _p(story, st,
           "<b>No disponible:</b> el cálculo de caudales máximos requiere la "
           "morfología real (A, Tc) y los cuantiles de P24. Verifique las "
           "secciones 5 y 10.", "italica")
        return

    e = R.qmax_entrada
    df = R.qmax_tabla

    _p(story, st, "11.1 Datos de entrada (provienen de las secciones 5, 8 y 9)", "h3")
    _p(story, st,
       "El cálculo de los caudales máximos parte de información que ya "
       "quedó consolidada en secciones previas. Los parámetros físicos de "
       "la cuenca vienen de la Sección 9 (cuenca real delineada con MERIT Hydro), "
       "el tiempo de concentración de la Sección 10, las precipitaciones P24(T) "
       "del mejor ajuste estadístico en la Sección 5 y las intensidades para "
       "duración igual al Tc del modelo Sherman calibrado en la Sección 8. El "
       "número de curva y el coeficiente de escorrentía son los valores "
       "ponderados que se reportaron en los mapas 9.5 y 9.7. La columna "
       "Origen de la tabla siguiente identifica de dónde proviene cada "
       "dato, lo que facilita auditarlo.")
    filas = [["Parámetro", "Valor", "Unidad", "Origen"],
             ["A (área)",        f"{e.A_km2:.2f}", "km²",    "Sección 9.10"],
             ["Lc (cauce D8)",   f"{e.L_km:.2f}",  "km",     "Sección 9.10"],
             ["Sc (pend. cuenca)", f"{e.S_pct:.1f}", "%",    "Sección 9.10"],
             ["S (pend. cauce)", f"{e.Sc_pct:.2f}", "%",     "Sección 9.10"],
             ["Tc adoptado",     f"{e.Tc_min:.0f}", "min",   "Sección 10"],
             ["CN ponderado",    f"{e.CN:.0f}",     "—",     "Sección 9.5"],
             ["C ponderado",     f"{e.C:.2f}",      "—",     "Sección 9.7"]]
    story.append(_tabla(filas, col_widths=[5.5*cm, 3.2*cm, 2*cm, 4.8*cm],
                        primera_col_izq=True))

    _p(story, st, "11.2 Métodos aplicados", "h3")
    from .caudal_maximo import METODOS
    met = [["#", "Método", "Expresión"]]
    for i, (nombre, formula, _) in enumerate(METODOS, 1):
        met.append([str(i), nombre, formula])
    story.append(_tabla(met, col_widths=[1*cm, 5*cm, 9.5*cm], primera_col_izq=True))

    _p(story, st, "11.3 Tabla de caudales por período de retorno", "h3")
    _p(story, st,
       "Para cada T = 5, 10, 25, 50, 100, 500, 1000, 5000 y 10000 años se reporta "
       "la P24 y la intensidad i(t=Tc), seguidas del caudal Q (m³/s) de cada "
       "método. Las últimas tres columnas son el promedio, la mediana y el "
       "máximo entre métodos.")
    cab = ["T (años)", "P24 (mm)", "i_Tc (mm/h)",
           "Q Rac.", "Q Rac.Mod.", "Q MacMath", "Q SCS HU", "Q V-King",
           "Q medio", "Q med.", "Q máx."]
    cols = ["T_anios", "P24_mm", "i_Tc_mm_h",
            "Q_racional", "Q_racional_mod", "Q_mac_math", "Q_scs",
            "Q_verni_king", "Q_medio", "Q_mediana", "Q_max"]
    filas = [cab]
    for _, r in df.iterrows():
        filas.append([
            str(int(r["T_anios"])),
            f"{r['P24_mm']:.1f}", f"{r['i_Tc_mm_h']:.1f}",
            f"{r['Q_racional']:.1f}", f"{r['Q_racional_mod']:.1f}",
            f"{r['Q_mac_math']:.1f}", f"{r['Q_scs']:.1f}",
            f"{r['Q_verni_king']:.1f}", f"{r['Q_medio']:.1f}",
            f"{r['Q_mediana']:.1f}", f"{r['Q_max']:.1f}",
        ])
    cw = [1.3*cm, 1.5*cm, 1.7*cm,
          1.5*cm, 1.7*cm, 1.7*cm, 1.5*cm, 1.5*cm,
          1.5*cm, 1.4*cm, 1.4*cm]
    story.append(_tabla(filas, col_widths=cw))

    # Nota de trazabilidad: qué métodos entran en los agregados (Q medio /
    # mediana / máx) y cuáles se excluyen, distinguiendo el criterio de ÁREA
    # del de TIEMPO DE CONCENTRACIÓN (norma 5.2-IC / manual ABC).
    _NOMBRE_Q = {
        "Q_racional": "Racional", "Q_racional_mod": "Racional Modificado (Témez)",
        "Q_mac_math": "Mac Math", "Q_scs": "SCS HU Triangular",
        "Q_verni_king": "Verni-King",
    }
    aplic = df.attrs.get("metodos_aplicables", [])
    excl = df.attrs.get("metodos_excluidos", [])
    excl_tc = set(df.attrs.get("excluidos_por_tc", []))
    a_km2 = df.attrs.get("area_km2")
    tc_h = df.attrs.get("tc_h")
    if aplic:
        nom_aplic = ", ".join(_NOMBRE_Q.get(k, k) for k in aplic)
        partes = [
            f"Los agregados (Q medio / mediana / máx) se calculan SOLO sobre "
            f"los métodos dentro de su dominio de validez para esta cuenca "
            f"(A = {a_km2:.1f} km², Tc = {tc_h:.2f} h): {nom_aplic}."
        ]
        if excl:
            det = []
            for k in excl:
                motivo = ("Tc fuera de rango" if k in excl_tc
                          else "área fuera de rango")
                det.append(f"{_NOMBRE_Q.get(k, k)} ({motivo})")
            partes.append(
                "Se excluyen por estar fuera de su rango de aplicabilidad: "
                + "; ".join(det) + ". El criterio rector para los métodos "
                "basados en la intensidad (Racional/Témez) es el tiempo de "
                "concentración (norma 5.2-IC: Racional Tc ≤ 6 h; Témez "
                "0.25 ≤ Tc ≤ 24 h), no solo el área.")
        _p(story, st, " ".join(partes), "italica")

    story.append(PageBreak())
    _p(story, st, "11.4 Comparación gráfica", "h3")
    if "qmax" in R.graficos:
        story.append(_figura(R.graficos["qmax"], ancho_cm=17.0, max_alto_cm=12.0))

    _p(story, st, "11.5 Adopción para diseño", "h3")
    fila_T = df.loc[df["T_anios"] == R.T_diseno]
    if len(fila_T):
        fT = fila_T.iloc[0]
        _p(story, st,
           f"Para el período de retorno de diseño T = {R.T_diseno} años "
           f"que la norma {R.tipo_obra.norma} establece para "
           f"{R.tipo_obra.nombre}, los cinco métodos arrojan los "
           f"siguientes caudales (en m³/s): Racional "
           f"{fT['Q_racional']:.1f}, Racional Modificado "
           f"{fT['Q_racional_mod']:.1f}, Mac Math {fT['Q_mac_math']:.1f}, "
           f"SCS HU Triangular {fT['Q_scs']:.1f} y Verni-King "
           f"{fT['Q_verni_king']:.1f}. La práctica usual es adoptar la "
           f"mediana entre métodos, que en este caso vale "
           f"{fT['Q_mediana']:.1f} m³/s, porque reduce el sesgo de "
           f"cualquier modelo individual. Si la dispersión entre métodos "
           f"es baja puede usarse el promedio ({fT['Q_medio']:.1f} m³/s) "
           f"con resultado similar, y en obras de alto riesgo o "
           f"estructuras críticas conviene verificar también con el "
           f"máximo ({fT['Q_max']:.1f} m³/s) como caso pésimo.")
    # Verificación estructural con un T superior (p. ej. obra ABC: 200/300).
    if getattr(R, "T_verificacion", None):
        fila_V = df.loc[df["T_anios"] == R.T_verificacion]
        if len(fila_V):
            fV = fila_V.iloc[0]
            _p(story, st,
               f"Verificación estructural (caso pésimo): además del caudal de "
               f"diseño adoptado para T = {R.T_diseno} años, la estructura se "
               f"verifica con un período de retorno superior de T = "
               f"{R.T_verificacion} años, conforme al criterio de riesgo "
               f"hidroclimático de este tipo de obra. Para T = "
               f"{R.T_verificacion} años, la mediana entre métodos aplicables "
               f"vale {fV['Q_mediana']:.1f} m³/s y el máximo {fV['Q_max']:.1f} "
               f"m³/s. Las cotas de desplante de pilas y estribos, el gálibo y "
               f"las obras de protección contra socavación deben verificarse "
               f"frente a este caudal de verificación, adoptando el mayor entre "
               f"el diseño (T = {R.T_diseno}) y la verificación (T = "
               f"{R.T_verificacion}) para las cotas de fundación.")
    _p(story, st,
       "Conviene recordar el alcance de cada método: el Racional clásico es "
       "estrictamente válido para cuencas pequeñas (A &lt; 5 km² y Tc ≤ 6 h "
       "según 5.2-IC); Mac Math es empírico para cuencas rurales pequeñas "
       "(A &lt; 10 km²); para cuencas medianas se prefiere Racional "
       "Modificado (Témez, 1–3000 km²) o el HU SCS, y Verni-King se aplica "
       "como referencia empírica calibrada a condiciones andinas.", "italica")

    # 11.6 Sensibilidad del caudal de diseño al cambio climático.
    scc = getattr(R, "sensibilidad_cc", None)
    if scc is not None and getattr(scc, "filas", None):
        _p(story, st, "11.6 Sensibilidad al cambio climático", "h3")
        _p(story, st,
           "Se evalúa cómo cambia el caudal de diseño si la precipitación "
           "extrema aumenta por efecto del cambio climático (<b>método de "
           "deltas</b>, IPCC/CMIP6). El incremento de lluvia se propaga al "
           "caudal con la ecuación de escorrentía SCS-CN (CN de diseño = "
           f"{scc.cn:.0f}); por la abstracción inicial, la relación es no "
           "lineal y el caudal crece proporcionalmente más que la lluvia "
           f"(<b>elasticidad Q–P ≈ {scc.elasticidad:.2f}</b>).")
        fs = [["Escenario", "ΔP (%)", "P24 (mm)", "Q (m³/s)", "ΔQ (%)"]]
        fs.append(["Base (actual)", "0", f"{scc.p24_base_mm:.1f}",
                   f"{scc.q_base_m3s:.2f}", "0"])
        for f in scc.filas:
            fs.append([f.escenario.split("(")[0].strip(),
                       f"+{f.delta_p_pct:.0f}", f"{f.p24_cc_mm:.1f}",
                       f"{f.q_cc_m3s:.2f}", f"+{f.delta_q_pct:.1f}"])
        story.append(_tabla(fs, col_widths=[5.6*cm, 1.8*cm, 2.4*cm, 2.4*cm,
                                            2.0*cm], primera_col_izq=True))
        _p(story, st, "• " + scc.nota, "cuerpo")
        _p(story, st,
           "<i>Los factores de cambio son representativos y ajustables; para "
           "el diseño definitivo deben sustituirse por un downscaling regional "
           "(CMIP6, quantile mapping) del sitio.</i>", "italica")


def _sec_hietogramas(story, st, R):
    story.append(PageBreak())
    _p(story, st, "12. Hietogramas de diseño", "h2")
    n_metodos = len(R.metodos_hieto) if getattr(R, "metodos_hieto", None) else 3
    metodos_str = ", ".join({
        "bloques": "bloques alternos", "scs": "SCS Tipo II",
        "chicago": "Chicago", "huff": "Huff (cuartil 2)"
    }.get(m, m) for m in R.metodos_hieto) if getattr(R, "metodos_hieto", None) \
        else "bloques alternos, SCS Tipo II y Chicago"
    huff_extra = ""
    if getattr(R, "aplica_huff", False):
        huff_extra = (" Por tener la cuenca un área mayor a 25 km², se "
                      "incorpora también el método de Huff (1967) en su "
                      "cuartil 2 mediana, que la literatura recomienda para "
                      "tormentas frontales de mayor duración.")
    _p(story, st,
       f"En esta sección construimos las tormentas de diseño con duración "
       f"igual al tiempo de concentración (D = {R.tc_adoptado.tc_min:.0f} "
       f"min) para los nueve períodos de retorno que se reportan en el "
       f"informe (T = 5, 10, 25, 50, 100, 500, 1000, 5000 y 10000 años), "
       f"empleando los métodos {metodos_str}.{huff_extra}")

    _p(story, st, "12.1 Comparación de métodos para T de diseño", "h3")
    _p(story, st,
       f"Como punto de partida comparamos los {n_metodos} métodos para el "
       f"período de retorno de diseño T = {R.T_diseno} años "
       f"({R.tipo_obra.norma}), de modo de visualizar cómo cada uno "
       f"reparte temporalmente la misma profundidad de lluvia.")
    if "hietogramas_comparacion" in R.graficos:
        # Figura grande (grilla 2×2 cuando hay 4 métodos) para llenar la página.
        story.append(_figura(R.graficos["hietogramas_comparacion"],
                             ancho_cm=18.0, max_alto_cm=21.0))

    # Subsecciones 12.2..12.5: una por método con tabla T × t (intensidad).
    nombres = {"bloques": "Bloques alternos (Chow, Maidment & Mays 1994)",
               "scs":     "SCS Tipo II (USDA-SCS 1986)",
               "chicago": "Chicago (Keifer & Chu 1957)",
               "huff":    "Huff (1967) — cuartil 2 mediana"}
    refs = {
        "bloques": ("Chow, V. T., Maidment, D. R. & Mays, L. W. (1994). "
                    "<i>Hidrología Aplicada</i>. McGraw-Hill."),
        "scs": ("USDA-SCS (1986). <i>Urban Hydrology for Small Watersheds — "
                "Technical Release 55 (TR-55)</i>. U.S. Department of Agriculture."),
        "chicago": ("Keifer, C. J. & Chu, H. H. (1957). \"Synthetic storm pattern "
                    "for drainage design.\" <i>Journal of the Hydraulics Division, "
                    "ASCE</i>, 83(HY4), 1332–1–1332–25."),
        "huff": ("Huff, F. A. (1967). \"Time distribution of rainfall in heavy "
                 "storms.\" <i>Water Resources Research</i>, 3(4), 1007–1019. "
                 "<u>doi:10.1029/WR003i004p01007</u>."),
    }
    sub = 2
    for met in R.metodos_hieto:
        story.append(PageBreak())
        _p(story, st, f"12.{sub} {nombres.get(met, met)}", "h3")
        _p(story, st, refs.get(met, ""), "italica")
        # Reportar para cada T: i en cada paso t (filas = t, columnas = T).
        hT = {T: R.hietogramas_por_T[T][met]
              for T in sorted(R.hietogramas_por_T.keys())
              if met in R.hietogramas_por_T[T]}
        if not hT:
            sub += 1
            continue
        # Δt y tiempos los toma del primer T (todos comparten el mismo D, Δt).
        primero = next(iter(hT.values()))
        tiempos = primero.tabla["t_min"].tolist()
        Ts = list(hT.keys())
        # Resumen de P total e i pico por T para este método.
        filas = [["T (años)", "P total (mm)", "i pico (mm/h)",
                  "i media (mm/h)", "Δt (min)", "bloques"]]
        for T in Ts:
            h = hT[T]
            filas.append([str(T),
                          f"{h.p_total_mm:.1f}",
                          f"{h.i_pico_mm_h:.1f}",
                          f"{h.p_total_mm * 60.0 / h.duracion_min:.1f}",
                          f"{h.delta_t_min:.0f}",
                          str(h.n_bloques)])
        story.append(_tabla(filas, col_widths=[1.8*cm, 2.6*cm, 2.8*cm,
                                                2.8*cm, 1.8*cm, 1.8*cm]))
        # Tabla detallada t × T de intensidad (mm/h).
        _p(story, st, "Intensidad i (mm/h) por intervalo y período de retorno:",
           "cuerpo")
        cab = ["t (min)"] + [f"T={T}" for T in Ts]
        filas = [cab]
        for k, t in enumerate(tiempos):
            fila = [f"{t:.0f}"]
            for T in Ts:
                fila.append(f"{hT[T].tabla.iloc[k]['intensidad_mm_h']:.1f}")
            filas.append(fila)
        cw = [1.6*cm] + [1.5*cm] * len(Ts)
        story.append(_tabla(filas, col_widths=cw))
        # Gráfico familia (todos los T superpuestos).
        clave_g = f"hieto_familia_{met}"
        if clave_g in R.graficos:
            story.append(_figura(R.graficos[clave_g], ancho_cm=17.0,
                                 max_alto_cm=10.0))
        sub += 1


def _sec_hechms(story, st, R):
    """Sección 13 — Modelación HEC-HMS: pérdidas SCS-CN + HU SCS triangular para 9 T."""
    story.append(PageBreak())
    _p(story, st,
       "13. Modelación en HEC-HMS — análisis y comportamiento de "
       "caudales máximos", "h2")
    p = getattr(R, "hec_params", None)
    H = getattr(R, "hec_hidrogramas_por_T", None) or {}

    if p is None or not H:
        # Fallback al resumen antiguo si no hay simulación.
        h = R.hechms
        _p(story, st,
           "Resumen básico (la modelación completa requiere la cuenca delineada "
           "por watershed; verifique Sección 9).")
        filas = [["Parámetro / Método", "Valor"],
                 ["Área de la cuenca", f"{h.area_km2:.2f} km²"],
                 ["Tc", f"{h.tc_min:.1f} min"],
                 ["lag = 0.6·Tc", f"{h.lag_min:.1f} min"],
                 ["CN", f"{h.cn:.0f}"],
                 ["Pérdidas", h.metodo_perdidas],
                 ["Transformación", h.metodo_transformacion]]
        story.append(_tabla(filas, col_widths=[8*cm, 7*cm], primera_col_izq=True))
        return

    nombres_hieto = {"bloques": "Bloques alternos", "scs": "SCS Tipo II",
                     "chicago": "Chicago", "huff": "Huff Q2 (mediana)"}
    nombre_met = nombres_hieto.get(R.hec_metodo_hieto, R.hec_metodo_hieto)

    # 13.0 Selección de la metodología de hietograma y modelo en HEC-HMS de diseño.
    _p(story, st,
       "13.0 Selección de la metodología de hietograma y modelo en HEC-HMS "
       "de diseño", "h3")
    _p(story, st,
       "Esta sección desarrolla dos decisiones metodológicas acopladas que "
       "preceden a la simulación lluvia-escorrentía: (1) la elección del "
       "<b>hietograma de diseño</b> que define la forma temporal de la "
       "tormenta sintética (subsección 13.0.1) y (2) la elección del "
       "<b>modelo HEC-HMS</b> que transforma esa lluvia en hidrograma de "
       "salida (subsección 13.0.2). Ambas se sustentan en los descriptores "
       "ya calculados a lo largo del informe (Secciones 1-12): "
       "climatología P24max, morfometría, tiempo de concentración, CN "
       "ponderado, coeficiente de escorrentía C y banda de duración Tc.")

    # ──────────────────────────────────────────────────────────────────
    # 13.0.1 Metodología de selección de hietograma
    # ──────────────────────────────────────────────────────────────────
    _p(story, st,
       "13.0.1 Metodología de selección de hietograma", "h3")
    _p(story, st,
       "Elegir el método de distribución temporal de la lluvia no es un "
       "detalle: condiciona la forma del hidrograma, el caudal pico y el "
       "instante en que ocurre. Tanto Chow, Maidment y Mays (1994) [7] "
       "como Bonta y Rao (1988) [32] proponen articular la decisión en "
       "tres bloques de criterios: las características físicas de la "
       "cuenca, que se discutieron en la Sección 9; el tiempo de concentración "
       "adoptado en la Sección 10; y la aplicabilidad documentada de cada "
       "método al contexto regional. A continuación desarrollamos cada "
       "bloque empleando los valores reales calculados para la cuenca "
       "objeto del análisis.")

    # ---- 13.0.1.1 Fundamento — características de la cuenca ----
    A = getattr(R, "analisis_morf", None)
    _p(story, st, "13.0.1.1 Fundamento — características de la cuenca (Sección 9)", "h3")
    _p(story, st,
       "Los hietogramas sintéticos no son neutros: cada método incorpora "
       "una hipótesis distinta sobre cómo se distribuye la tormenta en el "
       "tiempo y sobre cómo esa distribución se acopla con la respuesta "
       "de la cuenca. La tabla siguiente sintetiza los descriptores "
       "físicos relevantes —todos calculados sobre el DEM real— y, junto "
       "a cada uno, la implicancia metodológica que la literatura asocia "
       "a su valor.")
    cn_show = R.cn_ponderado or (A.cn if A else p.cn)
    if A is not None:
        filas = [["Variable", "Valor", "Implicancia para el hietograma"],
                 ["Área A", f"{A.area_km2:.2f} km²",
                  "filtro principal: A ≤ 25 km² → métodos urbanos "
                  "(Chicago); 25 &lt; A ≤ 100 km² → SCS Tipo II / Huff; "
                  "A &gt; 100 km² → Huff Q2 frontal o bloques."],
                 ["Forma (Kc)", f"{A.kc_gravelius:.2f} ({A.clase_forma.split('(')[0].strip()})",
                  "cuencas circulares concentran el pico (Chicago/bloques); "
                  "elongadas atenúan (SCS/Huff favorecen)."],
                 ["Orden Strahler", f"ω = {A.orden_max}, Rb = {A.relacion_bifurcacion:.1f}",
                  "ω ≥ 3 indica red bien desarrollada → tormentas de mayor "
                  "duración (Huff Q2 / Q3) según Strahler (1957) [21]."],
                 ["Pendiente media", f"{A.pendiente_cuenca_pct:.1f}% / {A.pendiente_cuenca_grados:.1f}°",
                  "alta pendiente → respuesta rápida, picos agudos "
                  "(Chicago/bloques); baja → respuesta atenuada."],
                 ["Hipsometría HI", f"{A.integral_hipsometrica:.2f} "
                  f"({A.estado_cuenca.split('(')[0].strip().lower()})",
                  "fase de madurez/vejez tolera distribuciones con pico "
                  "central (SCS); juventud requiere distribuciones "
                  "asimétricas (Huff Q1/Chicago) por mayor erosión."],
                 ["CN ponderado", f"{cn_show:.0f}",
                  "CN alto (&gt; 80) amplifica diferencias entre métodos "
                  "(la forma del hietograma manda); CN bajo las atenúa."]]
        story.append(_tabla(filas, col_widths=[3.6*cm, 4*cm, 9*cm],
                            primera_col_izq=True))
    _p(story, st,
       f"<b>Síntesis (cuenca actual):</b> A = {p.area_km2:.2f} km², forma "
       f"{(A.clase_forma.split('(')[0].strip() if A else 'no determinada')}, "
       f"pendiente {A.pendiente_cuenca_pct if A else 0:.1f}%"
       + (f", orden Strahler ω = {A.orden_max}" if A else "") +
       ". Estos valores son los que entran al filtro de selección del 13.0.1.3.",
       "italica")

    # ---- 13.0.1.2 Determinación del tiempo de concentración ----
    story.append(PageBreak())
    _p(story, st, "13.0.1.2 Determinación del tiempo de concentración (Sección 10)", "h3")
    _p(story, st,
       f"El tiempo de concentración define la duración de la banda IDF "
       f"(por convenio se adopta D = Tc, según Chow et al. 1994) que acota la "
       f"familia de <i>formas</i> de hietograma viables y fija la duración de "
       f"tormenta del método racional (Sección 11). En la sección anterior "
       f"adoptamos Tc = {R.tc_adoptado.tc_min:.0f} min "
       f"({R.tc_adoptado.tc_horas:.2f} h) como promedio depurado de las "
       f"fórmulas empíricas aplicables mediante el filtro de Tukey-IQR. "
       f"<b>Nota:</b> la modelación lluvia-escorrentía HEC-HMS con SCS-CN "
       f"(Sección 13.1 en adelante) NO usa D = Tc sino una <b>tormenta de "
       f"diseño de 24 h (SCS Tipo II, TR-55)</b>; con tormentas cortas de "
       f"duración Tc la lámina no supera la abstracción inicial Ia = 0.2·S y "
       f"la escorrentía saldría nula en los períodos frecuentes (ver la "
       f"tormenta adoptada más abajo).")
    tc = R.tc_adoptado
    filas = [["Aspecto", "Valor / criterio"],
             ["Tc adoptado", f"{tc.tc_min:.0f} min ({tc.tc_horas:.2f} h)"],
             ["Fórmulas usadas", ", ".join(tc.usadas)],
             ["Fórmulas descartadas",
              ", ".join(tc.descartadas) if tc.descartadas else "—"],
             ["n usadas", f"{tc.n_usadas}"],
             ["Duración tormenta D", f"{tc.tc_min:.0f} min (D = Tc, "
                                       "convenio Chow et al. 1994 [7])"],
             ["Δt sugerido", f"≈ D/10 = {tc.tc_min/10:.0f} min"]]
    story.append(_tabla(filas, col_widths=[4.5*cm, 11*cm], primera_col_izq=True))
    _p(story, st,
       "<b>Bandas de duración → método preferido</b> (criterio de la "
       "literatura sintetizado por Bonta &amp; Rao, 1988 [32]; Pizarro et al., "
       "2003 [37]; HidrojING, 2022):")
    filas = [["Duración D = Tc", "Tipo de tormenta", "Método recomendado"],
             ["D &lt; 1 h", "convectiva intensa, pico temprano",
              "Chicago (Keifer &amp; Chu 1957 [30]) o Huff Q1"],
             ["1 h ≤ D &lt; 3 h", "convectiva-frontal corta",
              "SCS Tipo II (USDA-SCS 1986 [33]) o Bloques alternos"],
             ["3 h ≤ D &lt; 6 h", "frontal, pico al medio",
              "<b>Huff cuartil 2 (mediana)</b> (Huff 1967 [31])"],
             ["D ≥ 6 h", "frontal larga / estratoforme",
              "Huff Q2 o Q3; SCS Tipo II en cuencas rurales"]]
    story.append(_tabla(filas, col_widths=[3.5*cm, 5.5*cm, 7*cm],
                        primera_col_izq=True))
    banda = (
        "D &lt; 1 h" if tc.tc_min < 60 else
        "1 h ≤ D &lt; 3 h" if tc.tc_min < 180 else
        "3 h ≤ D &lt; 6 h" if tc.tc_min < 360 else
        "D ≥ 6 h")
    _p(story, st,
       f"<b>Para esta cuenca</b> Tc = {tc.tc_min:.0f} min → banda «{banda}», "
       f"lo que orienta la elección hacia métodos de pico central o "
       f"levemente tardío, consistente con la fenomenología frontal "
       f"observada en cuencas andinas de tamaño medio.", "italica")

    # ---- 13.0.1.3 Selección de metodología según su aplicabilidad ----
    story.append(PageBreak())
    _p(story, st,
       "13.0.1.3 Selección de la metodología según su aplicabilidad", "h3")
    _p(story, st,
       "Al cruzar los descriptores físicos del 13.0.1.1 con la banda de "
       "duración del 13.0.1.2 y la aplicabilidad documentada de cada "
       "método, podemos construir una matriz de decisión que resume "
       "objetivamente la situación. Las calificaciones son cualitativas: "
       "tres estrellas marcan el método óptimo para el contexto, dos "
       "estrellas el aceptable y una estrella el posible pero subóptimo.")
    # Heurística automática de calificaciones (consistente con el selector
    # de hec_hms_sim.recomendar_hietograma).
    A_v = float(p.area_km2)
    Tc_v = float(p.tc_min)
    def _est(min_estrellas, condicion):
        return ("★" * min_estrellas) if condicion else "★"
    chi_ok = A_v < 25 and Tc_v < 60
    scs_ok = A_v <= 100 and 30 <= Tc_v <= 360
    huff_ok = A_v > 25 and Tc_v > 120
    blq_ok = True  # siempre disponible, conservador
    filas = [
        ["Método", "Aplicabilidad bibliográfica", "Aplicabilidad aquí",
         "Calif."],
        ["Bloques alternos (Chow et al. 1994 [7])",
         "general, conservador; usa la IDF directamente; sin hipótesis "
         "sobre la forma temporal de la tormenta.",
         "siempre aplicable; recomendado como referencia de comparación.",
         "★★"],
        ["SCS Tipo II (USDA-SCS 1986 [33])",
         "cuencas rurales con D = 24 h, distribución temporal calibrada "
         "para EE.UU.; adoptada en LATAM (Chow et al. 1994 [7]).",
         "óptimo si A ≤ 100 km² y Tc en banda 1–6 h." if scs_ok else
         "subóptimo (área o Tc fuera de rango habitual).",
         "★★★" if scs_ok else "★★"],
        ["Chicago (Keifer &amp; Chu 1957 [30])",
         "cuencas urbanas / muy pequeñas; deriva el hietograma instantáneo "
         "de la IDF; pico estrecho.",
         "óptimo en A &lt; 25 km² y Tc &lt; 1 h." if chi_ok else
         "no recomendado: cuenca demasiado grande o Tc alto.",
         "★★★" if chi_ok else "★"],
        ["Huff Q2 mediana (Huff 1967 [31])",
         "tormentas frontales con pico al medio; recomendado para "
         "cuencas con duraciones &gt; 2 h y A &gt; 25 km² (Bonta &amp; "
         "Rao 1988 [32]).",
         "óptimo si A &gt; 25 km² y Tc &gt; 2 h." if huff_ok else
         "no aplica (cuenca pequeña o tormenta breve).",
         "★★★" if huff_ok else "★"],
    ]
    story.append(_tabla(filas, col_widths=[4.5*cm, 5.5*cm, 4.5*cm, 1.6*cm],
                        primera_col_izq=True))

    _dur_h = (getattr(R, "hec_duracion_min", 1440.0) or 1440.0) / 60.0
    _p(story, st,
       f"<b>Tormenta de diseño adoptada para HEC-HMS.</b> Para la simulación "
       f"lluvia-escorrentía con el par pérdidas SCS-CN + hidrograma unitario "
       f"SCS se adopta una <b>tormenta de diseño de {_dur_h:.0f} h con "
       f"distribución {nombre_met}</b> (USDA-SCS TR-55, 1986), el estándar de "
       f"HEC-HMS para este par de métodos. Es una decisión distinta de la "
       f"duración de la banda IDF (= Tc) usada en el método racional de la "
       f"Sección 11: el método SCS-CN necesita que la tormenta acumule "
       f"suficiente lámina para superar la <b>abstracción inicial</b> "
       f"Ia = 0.2·S; con tormentas cortas de duración = Tc la lámina no supera "
       f"Ia y la escorrentía sale nula en los períodos de retorno frecuentes, "
       f"mientras que la tormenta de {_dur_h:.0f} h acumula el cuantil diario "
       f"P24(T) y produce escorrentía físicamente representativa en todos los "
       f"períodos de retorno.")
    _p(story, st, f"<b>Justificación:</b> {R.hec_justificacion}")
    if R.aplica_huff:
        _p(story, st,
           "El método de Huff Q2 reproduce con su curva mediana el patrón "
           "temporal observado en tormentas frontales de regiones templadas "
           "y subtropicales (Bolivia altiplánica entra en esta categoría) y "
           "es preferible al SCS Tipo II cuando la tormenta supera 2 h, "
           "siguiendo el criterio de Bonta &amp; Rao (1988) [32].",
           "italica")
    _p(story, st,
       "<b>Auditoría.</b> Los otros tres hietogramas (Bloques alternos, "
       "SCS Tipo II y Chicago) quedan documentados en la Sección 12 con su tabla "
       "T×t y su gráfico de familia, de forma que el lector puede comparar "
       "el resultado del método adoptado contra las alternativas y verificar "
       "la coherencia de la elección.", "italica")
    _p(story, st,
       "<b>Referencias específicas del 13.0.1:</b> [7] Chow, Maidment &amp; "
       "Mays (1994); [21] Strahler (1957); [30] Keifer &amp; Chu (1957); "
       "[31] Huff (1967); [32] Bonta &amp; Rao (1988); [33] USDA-SCS TR-55 "
       "(1986); [37] Pizarro et al. (2003); además del Manual de Hidrología "
       "y Drenaje de ABC/MOPSV y la norma boliviana NB 688 (ver Sección 15).",
       "italica")

    # ──────────────────────────────────────────────────────────────────
    # 13.0.2 Metodología de selección de modelo en HEC-HMS
    # ──────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    _p(story, st,
       "13.0.2 Metodología de selección de modelo en HEC-HMS", "h3")
    _p(story, st,
       "Una vez fijado el hietograma de diseño en el 13.0.1, queda definir "
       "el <b>modelo numérico</b> que transforma esa lluvia en hidrograma "
       "de salida. HEC-HMS (USACE) ofrece una combinación de tres módulos "
       "intercambiables —pérdidas, transformación lluvia-escorrentía y "
       "modelo meteorológico— cuya elección debe responder al perfil físico "
       "e hidroclimático de la cuenca. La literatura coincide en que la "
       "selección no es libre: cada módulo tiene un dominio de aplicabilidad "
       "validado empíricamente (Feldman 2000 [38]; Scharffenberg 2022 [39]; "
       "Singh 1995 [40]; Beven 2012 [41]). A continuación cruzamos los "
       "datos producidos desde la Sección 1 hasta la 12 con la matriz de "
       "decisión documentada en esa literatura.")

    # ---- 13.0.2.1 Insumos provenientes de las secciones previas ----
    _p(story, st,
       "13.0.2.1 Insumos provenientes de las Secciones 1-12", "h3")
    _p(story, st,
       "El modelo HEC-HMS no se elige en abstracto: se calibra contra los "
       "valores reales calculados a lo largo del informe. La tabla siguiente "
       "consolida los seis insumos que dirigen la decisión, indicando la "
       "sección donde se derivaron.")
    cn_input = R.cn_ponderado or (A.cn if A else p.cn)
    c_input  = R.c_ponderado or (R.c_evento or "—")
    if isinstance(c_input, float):
        c_str = f"{c_input:.2f}"
    else:
        c_str = str(c_input)
    p24_diseno = R.p24_diseno_mm or 0.0
    filas = [
        ["Insumo", "Valor", "Sección"],
        ["P24 máxima T diseño", f"{p24_diseno:.1f} mm" if p24_diseno else "—",
         "5 / 6 (frecuencia)"],
        ["Área de la cuenca A", f"{p.area_km2:.2f} km²", "9.1 / watershed MERIT"],
        ["Tiempo de concentración Tc",
         f"{R.tc_adoptado.tc_min:.0f} min ({R.tc_adoptado.tc_horas:.2f} h)",
         "10 (procedimiento 5 pasos)"],
        ["Pendiente media de la cuenca",
         f"{(A.pendiente_cuenca_pct if A else 0):.1f} %", "9.10 / COP-DEM GLO-30"],
        ["Cobertura vegetal dominante",
         (A.clase_forma.split('(')[0].strip()
            if A and hasattr(A, 'clase_forma') else
            "FROM-GLC10 10 m"), "9.3 / FROM-GLC10"],
        ["Número de curva CN ponderado", f"{cn_input:.0f}",
         "9.5 / GCN250 + HYSOGs250m"],
        ["Coef. escorrentía C ponderado", c_str,
         "9.7 / racional (uso × pendiente)"],
        ["Hietograma de diseño adoptado", nombre_met,
         "13.0.1 (este informe)"],
    ]
    story.append(_tabla(filas, col_widths=[5.6*cm, 5.4*cm, 5*cm],
                        primera_col_izq=True))

    # ---- 13.0.2.2 Matriz de decisión por módulo ----
    _p(story, st,
       "13.0.2.2 Matriz de decisión por módulo HEC-HMS", "h3")
    _p(story, st,
       "HEC-HMS expone tres módulos intercambiables; en cada uno hay "
       "5-8 alternativas. La elección óptima para cada módulo depende del "
       "perfil de la cuenca (Singh 1995 [40], Beven 2012 [41]). El "
       "Technical Reference Manual de USACE (Feldman 2000 [38], "
       "Scharffenberg 2022 [39]) sintetiza la aplicabilidad como matriz "
       "que reproducimos abajo, calificada para la cuenca actual.")

    # --- Módulo 1: pérdidas ---
    A_v = float(p.area_km2)
    Tc_h = float(p.tc_min) / 60.0
    cn_v = float(cn_input or 0)
    es_humeda = cn_v >= 75
    es_arida  = cn_v <  60
    es_chica  = A_v   <= 100
    es_mediana = 100 < A_v <= 1000
    es_grande = A_v   > 1000

    _p(story, st,
       "<b>(a) Módulo de pérdidas</b> (separación de la lluvia bruta de la "
       "lluvia efectiva):")
    filas = [
        ["Método HEC-HMS", "Insumo requerido", "Aplicabilidad / criterio", "Calif."],
        ["SCS Curve Number (Mockus 1957 [42]; USDA-NRCS NEH-630 Cap. 10 [43])",
         "CN ponderado (mapa 9.5)",
         "óptimo en cuencas pequeñas-medianas (A ≤ 1000 km²) con CN derivado "
         "de uso de suelo. Estándar en hidrología de diseño en LATAM.",
         "★★★"],
        ["Initial + Constant Rate (Feldman 2000 [38])",
         "Ia y tasa f constante",
         "alternativa para cuencas con CN no documentado; requiere calibración "
         "contra aforos.",
         "★★" if not cn_v else "★"],
        ["Green-Ampt (Green &amp; Ampt 1911 [44])",
         "θs, θi, ψf, K",
         "preferido cuando se dispone de propiedades hidráulicas del suelo "
         "(textura, ϕ, K); raro en Bolivia sin trabajo de campo.",
         "★"],
        ["Soil Moisture Accounting (SMA — Bennett 1998 [45])",
         "balance hídrico continuo",
         "para simulación continua multianual (no de evento); útil en "
         "cuencas con base flow y embalsamiento.",
         "★"],
        ["Deficit + Constant Rate",
         "déficit recuperable + f",
         "extensión del Initial+Constant con recuperación; raro en diseño.",
         "★"],
    ]
    story.append(_tabla(filas, col_widths=[4.8*cm, 3.0*cm, 6.4*cm, 1.2*cm],
                        primera_col_izq=True))
    _p(story, st,
       f"<b>Selección de pérdidas:</b> <b>SCS Curve Number</b> con "
       f"CN = {cn_v:.0f} del mapa 9.5. Justificación: el CN viene del cruce "
       f"MapBiomas Bolivia × tabla CN_POR_COBERTURA del módulo gee.py, "
       f"calibrada para grupo hidrológico B y AMC II (USDA-NRCS NEH-630 "
       f"Cap. 10 [43]); no requiere datos de campo adicionales y es el "
       f"estándar de referencia para diseño en cuencas no aforadas "
       f"(ABC-MOPSV Manual de Drenaje; NB 688).")

    # --- Módulo 2: transformación lluvia-escorrentía ---
    _p(story, st,
       "<b>(b) Módulo de transformación lluvia-escorrentía</b> (Pe → Q hidrograma):")
    if es_chica:
        ut_scs = "★★★"; ut_clark = "★★"; ut_mod = "★"
        ut_snyder = "★"; ut_kw = "★"
    elif es_mediana:
        ut_scs = "★★"; ut_clark = "★★★"; ut_mod = "★★"
        ut_snyder = "★★"; ut_kw = "★"
    else:
        ut_scs = "★"; ut_clark = "★★"; ut_mod = "★★★"
        ut_snyder = "★★"; ut_kw = "★"
    filas = [
        ["Método HEC-HMS", "Parámetros", "Aplicabilidad", "Calif."],
        ["SCS UH triangular (Mockus 1957 [42]; NEH-630 Cap. 16 [46])",
         "Lag = 0.6·Tc",
         "cuencas pequeñas-medianas (A ≤ 100 km²) sin aforos; estándar para "
         "diseño en Bolivia (ABC). Requiere solo Tc.",
         ut_scs],
        ["Clark UH (Clark 1945 [47])",
         "Tc + R (coef. almacenamiento)",
         "cuencas medianas (25-500 km²) con tránsito significativo; R ≈ Tc "
         "es default razonable, calibrable si hay datos.",
         ut_clark],
        ["ModClark distribuido (Kull &amp; Feldman 1998 [48])",
         "grid + ATI",
         "cuencas grandes (A &gt; 500 km²) con variabilidad espacial de "
         "lluvia; recomendado cuando el hietograma proviene de grilla "
         "satelital (CHIRPS).",
         ut_mod],
        ["Snyder UH (Snyder 1938 [49])",
         "Ct, Cp regionales",
         "cuencas medianas-grandes en EE.UU.; coeficientes regionales no "
         "documentados en Bolivia.",
         ut_snyder],
        ["Kinematic Wave (Lighthill &amp; Whitham 1955 [50])",
         "longitud, ancho, n, S por plano",
         "cuencas pequeñas urbanas con superficies impermeables; requiere "
         "discretización por planos de flujo.",
         ut_kw],
    ]
    story.append(_tabla(filas, col_widths=[4.8*cm, 3.0*cm, 6.4*cm, 1.2*cm],
                        primera_col_izq=True))
    transform_elegida = (R.hechms.metodo_transformacion
                          if R.hechms else "SCS Unit Hydrograph")
    _p(story, st,
       f"<b>Selección de transformación:</b> <b>{transform_elegida}</b>. "
       f"Justificación: con A = {A_v:.2f} km² y Tc = {p.tc_min:.0f} min, la "
       f"cuenca queda en el dominio "
       + ("«pequeña» (A ≤ 100 km²) donde el HU triangular SCS es el "
            "estándar de referencia (Mockus 1957 [42]; NEH-630 Cap. 16 [46]); "
            "el método solo requiere Lag = 0.6·Tc, que se deriva sin "
            "supuestos adicionales del Tc adoptado en 10."
          if es_chica else
            "«mediana» (100 &lt; A ≤ 1000 km²) donde el método de Clark "
            "supera al SCS por considerar explícitamente el almacenamiento "
            "(parámetro R), aunque requiere calibración o estimación "
            "regional. Para diseño sin aforos se conserva el SCS UH como "
            "fallback conservador."
          if es_mediana else
            "«grande» (A &gt; 1000 km²) donde el método distribuido "
            "ModClark es el preferido por incorporar la variabilidad "
            "espacial del campo de lluvia; en ausencia de grid de "
            "precipitación adecuado, el método de Clark agregado es el "
            "siguiente más apropiado."))

    # --- Módulo 3: modelo meteorológico ---
    _p(story, st,
       "<b>(c) Modelo meteorológico:</b> el hietograma adoptado en 13.0.1 se "
       "ingresa a HEC-HMS bajo el método <b>Specified Hyetograph</b>, que "
       "carga directamente la serie t × i sintetizada para el período de "
       "retorno de diseño. Métodos alternativos como <i>SCS Storm</i> o "
       "<i>Frequency Storm</i> generarían internamente otra distribución "
       "temporal, anulando el análisis comparativo de 13.0.1.")

    # ---- 13.0.2.3 Recomendaciones operacionales para Bolivia ----
    _p(story, st,
       "13.0.2.3 Recomendaciones operacionales para Bolivia", "h3")
    _p(story, st,
       "La literatura específica para cuencas andinas (Pizarro et al. 2003 "
       "[37]; Buytaert et al. 2010 [51]; Vuille 2003 [52]) coincide en tres "
       "puntos para la práctica boliviana:")
    _p(story, st,
       "• <b>Datos escasos &gt; calibración local</b>: en cuencas no "
       "aforadas (la mayoría en Bolivia), la elección debe priorizar "
       "métodos que requieran pocos parámetros físicamente derivables "
       "(SCS-CN para pérdidas; HU triangular SCS para transformación) "
       "sobre métodos sofisticados que demandan calibración (Green-Ampt, "
       "Clark con R libre, Snyder con Ct/Cp regional).")
    _p(story, st,
       "• <b>Climatología semiárida → CN estacional</b>: en cuencas del "
       "Altiplano y Chaco con CN &lt; 60, el CN tabulado para AMC II puede "
       "sobrestimar la respuesta; se recomienda aplicar el factor de "
       "ajuste a AMC I (suelo seco) cuando la tormenta ocurre fuera del "
       "período lluvioso (USDA-NRCS NEH-630 Cap. 10, Tabla 10-1 [43]).")
    _p(story, st,
       "• <b>Validación cruzada con métodos directos</b>: el resultado de "
       "HEC-HMS debe contrastarse con los métodos directos (Racional, "
       "Racional Modificado de Témez, Mac-Math, Verni-King) que ya se "
       "calculan en la Sección 11. Una desviación &gt; 30 % entre el pico "
       "HEC-HMS y el promedio de los métodos directos indica que algún "
       "parámetro requiere revisión (CN, Tc, hietograma o área de cuenca).")

    # ---- 13.0.2.4 Modelo HEC-HMS adoptado ----
    _p(story, st, "13.0.2.4 Modelo HEC-HMS adoptado para este estudio", "h3")
    filas = [
        ["Módulo HEC-HMS", "Método adoptado", "Parámetro principal"],
        ["Subbasin: Loss method",
         (R.hechms.metodo_perdidas if R.hechms else "SCS Curve Number"),
         f"CN = {cn_v:.0f}; S_ret = {(25400/max(cn_v,1) - 254):.1f} mm; "
         f"Ia = {0.2*(25400/max(cn_v,1) - 254):.1f} mm"],
        ["Subbasin: Transform method",
         (R.hechms.metodo_transformacion if R.hechms else "SCS Unit Hydrograph"),
         f"Lag = 0.6·Tc = {0.6*p.tc_min:.0f} min; "
         f"Tp = Δt/2 + Lag; Tb = 2.67·Tp; "
         f"Qp = 0.208·A/Tp (por mm Pe)"],
        ["Meteorologic model: Precipitation",
         "Specified Hyetograph",
         f"{nombre_met} de {_dur_h:.0f} h; Δt = {p.tc_min/6:.0f} min "
         f"(≈ Tc/6); duración D = {_dur_h:.0f} h (1440 min, estándar TR-55)"],
        ["Control specifications",
         "Single event",
         f"un evento por período de retorno T; "
         f"familia T = {sorted(R.hec_hidrogramas_por_T.keys()) if R.hec_hidrogramas_por_T else '—'}"],
    ]
    story.append(_tabla(filas, col_widths=[4.4*cm, 4.4*cm, 7.2*cm],
                        primera_col_izq=True))
    _p(story, st,
       "Esta combinación se exporta como proyecto HEC-HMS completo "
       "(<i>.basin</i>, <i>.met</i>, <i>.control</i>, <i>.run</i>) mediante "
       "<i>hec_hms_sim.exportar_proyecto_hec_hms</i>, listo para "
       "reproducirse en el software oficial USACE (Scharffenberg 2022 [39]).")
    _p(story, st,
       "<b>Referencias específicas del 13.0.2:</b> [37] Pizarro et al. "
       "(2003); [38] Feldman (2000) USACE HEC-HMS TR Manual; [39] "
       "Scharffenberg (2022) HEC-HMS User's Manual v4.10; [40] Singh (1995) "
       "Computer Models of Watershed Hydrology; [41] Beven (2012) Rainfall-"
       "Runoff Modelling; [42] Mockus (1957); [43] USDA-NRCS NEH-630 Cap. 10; "
       "[44] Green &amp; Ampt (1911); [45] Bennett (1998) SMA; [46] USDA-"
       "NRCS NEH-630 Cap. 16; [47] Clark (1945); [48] Kull &amp; Feldman "
       "(1998) ModClark; [49] Snyder (1938); [50] Lighthill &amp; Whitham "
       "(1955); [51] Buytaert et al. (2010); [52] Vuille (2003); además del "
       "Manual de Hidrología y Drenaje ABC/MOPSV y NB 688 (ver Sección 15).",
       "italica")

    # 13.1 Pérdidas
    story.append(PageBreak())
    _p(story, st,
       "13.1 Pérdidas de precipitación → precipitación efectiva", "h3")
    _p(story, st,
       f"Para separar la lluvia bruta de la que efectivamente escurre "
       f"aplicamos el método SCS Curve Number (USDA-SCS TR-55, 1986; "
       f"USDA-NRCS NEH-630 Cap. 10), que es exactamente el motor de "
       f"pérdidas <i>Loss = SCS Curve Number</i> incluido en HEC-HMS. "
       f"Con CN = {p.cn:.0f} la "
       f"retención potencial vale S<sub>ret</sub> = 25400/CN − 254 = "
       f"{p.S_ret_mm:.1f} mm y la abstracción inicial Ia = 0.2·S = "
       f"{p.Ia_mm:.1f} mm; mientras la lluvia acumulada no supere Ia "
       f"toda la precipitación se considera abstraída, y a partir de "
       f"ese umbral la lluvia efectiva se calcula como "
       f"Pe = (P−Ia)² / (P−Ia+S<sub>ret</sub>).")
    cnc = getattr(R, "cn_correccion", None)
    if cnc:
        _p(story, st,
           f"<b>Corrección del CN por pendiente (Williams, 1995).</b> El CN "
           f"tabulado del SCS supone pendientes ≈ 5 %. La cuenca tiene una "
           f"pendiente media de {cnc['pendiente_pct']:.1f} %, por lo que el CN "
           f"ponderado del mapa 9.5 (CN₂ = {cnc['cn2']:.0f}, AMC II) se corrige "
           f"a <b>CN₂ₛ = {cnc['cn2s']:.0f}</b> mediante "
           f"CN₂ₛ = (CN₃−CN₂)/3·(1−2·e<sup>−13.86·S</sup>)+CN₂, con "
           f"CN₃ = {cnc['cn3']:.0f} (AMC III). Este CN ajustado por pendiente y "
           f"uso de suelo (ESRI LULC / MapBiomas) es el que alimenta el modelo "
           f"HEC-HMS, reconociendo el mayor escurrimiento de las cuencas de "
           f"montaña bolivianas.")
    if "hec_perdidas" in R.graficos:
        story.append(_figura(R.graficos["hec_perdidas"], ancho_cm=16.0,
                             max_alto_cm=8.0))
    # Tabla P / Pe / pérdidas por T
    filas = [["T (años)", "P total (mm)", "Pe total (mm)",
              "Pérdidas (mm)", "Coef. escorrentía Pe/P"]]
    for T in sorted(H.keys()):
        r = H[T]
        perd = r.P_total_mm - r.Pe_total_mm
        cesc = r.Pe_total_mm / r.P_total_mm if r.P_total_mm else 0.0
        filas.append([str(T), f"{r.P_total_mm:.1f}",
                      f"{r.Pe_total_mm:.1f}", f"{perd:.1f}",
                      f"{cesc:.3f}"])
    story.append(_tabla(filas, col_widths=[2*cm, 3*cm, 3*cm, 3*cm, 4*cm]))

    # 13.2 Transformación
    story.append(PageBreak())
    _p(story, st,
       "13.2 Transformación de precipitación efectiva en caudales", "h3")
    _p(story, st,
       "El paso siguiente es transformar la lluvia efectiva en caudal de "
       "salida. Para ello empleamos el Hidrograma Unitario SCS Triangular "
       "documentado en el Cap. 16 del NEH-630, que es la opción <i>Transform "
       "= SCS Unit Hydrograph</i> de HEC-HMS. La tabla siguiente lista los "
       "parámetros del HU con la fórmula que los origina:")
    Tp_h = p.lag_min / 60.0
    filas = [["Parámetro", "Valor", "Origen"],
             ["Lag time", f"{p.lag_min:.1f} min = {p.lag_min/60:.2f} h",
              "lag = 0.6·Tc (NRCS NEH-630)"],
             ["Tiempo al pico Tp", f"{Tp_h + 0.5*5/60:.2f} h (aprox.)",
              "Tp = Δt/2 + lag"],
             ["Tiempo base Tb", f"{2.67*Tp_h:.2f} h (aprox.)",
              "Tb = 2.67·Tp"],
             ["Qp unitario", f"{0.208*p.area_km2/Tp_h:.2f} m³/s",
              "Qp = 0.208·A/Tp"],
             ["Área", f"{p.area_km2:.2f} km²", "Sección 9.10"],
             ["Tc adoptado", f"{p.tc_min:.0f} min", "Sección 10"]]
    story.append(_tabla(filas, col_widths=[4.5*cm, 5*cm, 6.5*cm],
                        primera_col_izq=True))
    if "hec_hu" in R.graficos:
        story.append(_figura(R.graficos["hec_hu"], ancho_cm=16.0,
                             max_alto_cm=7.5))
    _p(story, st,
       "El hidrograma de escorrentía directa Q(t) resulta de convolucionar "
       "la lluvia efectiva incremental Pe<sub>i</sub>(t) con el HU "
       "triangular, una operación idéntica a la que ejecuta el motor de "
       "HEC-HMS internamente.")

    # 13.3 Obtención de hidrogramas
    story.append(PageBreak())
    _p(story, st,
       "13.3 Obtención de hidrogramas — análisis para los 9 períodos de retorno",
       "h3")
    _p(story, st,
       f"Encadenando los tres pasos anteriores — tormenta de diseño de "
       f"{_dur_h:.0f} h con distribución {nombre_met}, pérdidas SCS-CN y "
       f"transformación HU SCS triangular — para cada uno de los ocho "
       f"períodos de retorno T = 5, 10, 25, 50, 100, 500, 1000, 5000 y 10000 "
       f"años, obtenemos los hidrogramas de escorrentía directa Q(t). La "
       f"columna «P total» es la lámina de la tormenta de {_dur_h:.0f} h "
       f"(igual al cuantil diario P24(T)); al ser una tormenta larga, supera "
       f"la abstracción inicial Ia y produce escorrentía en todos los "
       f"períodos de retorno. La tabla siguiente resume el caudal pico, el "
       f"tiempo al pico y el volumen directo de cada uno.")
    filas = [["T (años)", "P total (mm)", "Pe total (mm)",
              "Q pico (m³/s)", "t pico (min)", "Volumen (hm³)"]]
    for T in sorted(H.keys()):
        r = H[T]
        filas.append([str(T), f"{r.P_total_mm:.1f}", f"{r.Pe_total_mm:.1f}",
                      f"{r.Q_pico_m3s:.1f}", f"{r.t_pico_min:.0f}",
                      f"{r.volumen_directo_hm3:.3f}"])
    story.append(_tabla(filas, col_widths=[1.8*cm, 2.6*cm, 2.6*cm,
                                            2.6*cm, 2.4*cm, 2.6*cm]))

    # 13.4 Exposición de resultados (gráficos)
    story.append(PageBreak())
    _p(story, st, "13.4 Exposición de resultados", "h3")
    if "hec_hidrogramas" in R.graficos:
        _p(story, st, "Hidrogramas Q(t) por período de retorno (familia completa):")
        story.append(_figura(R.graficos["hec_hidrogramas"], ancho_cm=17.0,
                             max_alto_cm=9.5))
    if "hec_qpico_T" in R.graficos:
        _p(story, st,
           "Comportamiento de Q pico y volumen directo vs T (escala log en T):")
        story.append(_figura(R.graficos["hec_qpico_T"], ancho_cm=17.0,
                             max_alto_cm=8.5))

    # Cuadro de resultados de simulación HEC-HMS en página propia.
    story.append(PageBreak())
    _p(story, st,
       "Cuadro de resultados — simulación HEC-HMS para Cuenca1",
       "h3")
    _p(story, st,
       "El cuadro siguiente sintetiza la configuración HEC-HMS de la "
       "cuenca tal como la corre el motor: los <b>inputs</b> son los "
       "parámetros físicos e hidrológicos derivados de las Secciones 9, "
       "10, 12 y 13.0.2; los <b>outputs</b> son las variables calculadas "
       "por el motor para el período de retorno de diseño "
       f"(T = {R.T_diseno} años). Cualquier revisor puede reproducir "
       "estos resultados copiando los inputs en HEC-HMS standalone vía "
       "el proyecto exportable (.basin / .met / .control / .run).")
    fila_T = H.get(R.T_diseno) or next(iter(H.values()))
    delta_t = next(iter(H.values())).delta_t_min
    # Inputs
    filas = [["Bloque", "Parámetro", "Tipo", "Valor", "Unidad", "Descripción"],
        ["Subbasin Cuenca1", "Area", "Input",
         f"{p.area_km2:.3f}", "km²",
         "área de aporte delineada por watershed MERIT (Sec. 9.1)"],
        ["Subbasin Cuenca1", "Loss method", "Input",
         "SCS Curve Number", "—",
         "método de pérdidas elegido en 13.0.2.2(a)"],
        ["Subbasin Cuenca1", "Initial Abstraction Ia", "Input",
         f"{p.Ia_mm:.2f}", "mm",
         f"Ia = 0.2·S; abstracción inicial SCS"],
        ["Subbasin Cuenca1", "Curve Number CN", "Input",
         f"{p.cn:.0f}", "—",
         "CN ponderado por área del mapa 9.5 (MapBiomas)"],
        ["Subbasin Cuenca1", "Potential Retention S", "Input",
         f"{p.S_ret_mm:.2f}", "mm",
         "S = 25400/CN − 254 (Mockus 1957)"],
        ["Subbasin Cuenca1", "Transform method", "Input",
         "SCS Unit Hydrograph", "—",
         "transformación lluvia-escorrentía (13.0.2.2(b))"],
        ["Subbasin Cuenca1", "Lag Time", "Input",
         f"{p.lag_min:.2f}", "min",
         "Lag = 0.6·Tc (NRCS, NEH-630 Cap. 16)"],
        ["Subbasin Cuenca1", "Tc (tiempo de concentración)", "Input",
         f"{p.tc_min:.1f}", "min",
         "adoptado en Sección 10 (procedimiento 5 pasos)"],
        ["Meteorology TormentaDiseno", "Precipitation Method", "Input",
         "Specified Hyetograph", "—",
         f"tormenta {nombre_met} de {_dur_h:.0f} h (TR-55)"],
        ["Meteorology TormentaDiseno", "P total tormenta",
         "Input", f"{fila_T.P_total_mm:.1f}", "mm",
         f"lluvia total de 24 h para T = {R.T_diseno} años (= P24)"],
        ["Control Diseno", "Time Interval Δt", "Input",
         f"{delta_t:.0f}", "min",
         "paso de discretización temporal (≈ Tc/6)"],
        ["Control Diseno", "Duration", "Input",
         f"{getattr(R, 'hec_duracion_min', 1440.0):.0f}", "min",
         f"duración de la tormenta de diseño (24 h, estándar TR-55)"],
        ["—— OUTPUT ——", "", "", "", "", ""],
        ["Subbasin Cuenca1", "Precipitation effective Pe",
         "Output", f"{fila_T.Pe_total_mm:.1f}", "mm",
         f"lluvia efectiva tras pérdidas SCS-CN; Pe/P = "
         f"{fila_T.Pe_total_mm/max(fila_T.P_total_mm,1e-9)*100:.1f} %"],
        ["Subbasin Cuenca1", "Caudal pico Qp", "Output",
         f"{fila_T.Q_pico_m3s:.2f}", "m³/s",
         "caudal máximo del hidrograma simulado"],
        ["Subbasin Cuenca1", "Tiempo al pico tp", "Output",
         f"{fila_T.t_pico_min:.0f}", "min",
         "instante del pico medido desde el inicio de la tormenta"],
        ["Subbasin Cuenca1", "Volumen directo", "Output",
         f"{fila_T.volumen_directo_hm3:.3f}", "hm³",
         f"volumen total escurrido (∫ Q dt) = {fila_T.volumen_directo_hm3*1e6:.0f} m³"],
        ["Subbasin Cuenca1", "Tiempo base tb", "Output",
         f"{2.67*(delta_t/2 + p.lag_min):.0f}", "min",
         "tb = 2.67·Tp (Mockus 1957)"],
        ["Subbasin Cuenca1", "Coef. escorrentía evento",
         "Output",
         f"{fila_T.Pe_total_mm/max(fila_T.P_total_mm,1e-9):.3f}",
         "—",
         "C_evento = Pe/P calculado por el SCS-CN para el T de diseño"],
        ["Aplicación del Q diseño", R.tipo_obra.nombre,
         "Output", f"T = {R.T_diseno} años",
         "según norma",
         f"Q pico de {fila_T.Q_pico_m3s:.1f} m³/s es la base hidrológica "
         f"para el dimensionamiento de {R.tipo_obra.dimensionamiento_texto} "
         f"(norma: {R.tipo_obra.norma})"],
    ]
    story.append(_tabla(filas, col_widths=[3.7*cm, 3.6*cm, 1.6*cm,
                                             2.0*cm, 1.4*cm, 4.4*cm],
                          primera_col_izq=True))
    # Pseudocódigo HEC-HMS de la simulación realizada (anexo compacto).
    _p(story, st,
       "Como anexo y para trazabilidad estricta, el siguiente bloque "
       "reproduce el pseudocódigo HEC-HMS equivalente con los mismos "
       "valores del cuadro anterior, en el formato Basin / Met / Control "
       "que reconoce el software standalone.", "italica")
    pseudo = (
        f"Subbasin: Cuenca1\n"
        f"     Area: {p.area_km2:.3f} km²\n"
        f"     LossRate: SCS Curve Number\n"
        f"       Initial Abstraction: {p.Ia_mm:.2f} mm\n"
        f"       Curve Number: {p.cn:.0f}\n"
        f"     Transform: SCS Unit Hydrograph\n"
        f"       Lag Time: {p.lag_min:.2f} min\n"
        f"Meteorology: TormentaDiseno\n"
        f"     Precipitation Method: Specified Hyetograph "
        f"({R.hec_metodo_hieto})\n"
        f"Control: Diseno\n"
        f"     Time Interval: {delta_t:.0f} min\n"
    )
    cuerpo = ParagraphStyle("hec_codigo", fontName=FONT, fontSize=8.2,
                            leading=10.4, leftIndent=8, textColor=colors.HexColor("#222"),
                            backColor=colors.HexColor("#f3f5f9"),
                            borderColor=colors.HexColor("#cfd8dc"), borderWidth=0.4,
                            borderPadding=6, spaceBefore=12, spaceAfter=10)
    story.append(Spacer(1, 6))
    story.append(Paragraph(pseudo.replace("\n", "<br/>"), cuerpo))
    story.append(Spacer(1, 6))
    _p(story, st,
       f"<b>Conclusión:</b> para el período de retorno de diseño "
       f"<b>T = {R.T_diseno} años</b> (obra: {R.tipo_obra.nombre}; "
       f"norma: {R.tipo_obra.norma}) el modelo HEC-HMS arroja "
       f"<b>Q pico = {fila_T.Q_pico_m3s:.1f} m³/s</b>, con un volumen "
       f"directo de {fila_T.volumen_directo_hm3:.3f} hm³ y tiempo al pico "
       f"de {fila_T.t_pico_min:.0f} min. Este caudal complementa los "
       f"obtenidos por los métodos directos de la Sección 11 "
       f"(Racional / SCS HU / Mac Math / Verni-King) y constituye la base "
       f"hidrológica para el dimensionamiento de "
       f"{R.tipo_obra.dimensionamiento_texto}.")

    # ---- 13.5 Conciliación numérica con los métodos directos (Sección 11) ----
    qmax = getattr(R, "qmax_tabla", None)
    if qmax is not None and len(qmax):
        story.append(PageBreak())
        _p(story, st, "13.5 Conciliación del caudal de diseño entre métodos",
           "h3")
        _p(story, st,
           "Los métodos directos de la Sección 11 y la modelación HEC-HMS de "
           "esta sección producen caudales distintos porque <b>no resuelven el "
           "mismo problema</b>: los métodos directos estiman el pico con una "
           "tormenta de duración igual a Tc y una intensidad leída de la IDF, "
           "mientras que HEC-HMS integra un hietograma de 24 h a través de un "
           "hidrograma unitario y descuenta las pérdidas acumuladas. La tabla "
           "siguiente concilia ambos resultados para el período de diseño y "
           "explicita el origen de la diferencia, de modo que el proyectista "
           "pueda justificar el valor que adopta.")
        fT = qmax.loc[qmax["T_anios"] == int(R.T_diseno)]
        if len(fT):
            f = fT.iloc[0]
            q_hec = float(fila_T.Q_pico_m3s)
            filas_c = [["Método", "Q (m³/s)", "Duración de tormenta",
                        "Pérdidas", "Δ vs HEC-HMS"]]

            def _fila_m(nom, val, dur, per):
                try:
                    v = float(val)
                except Exception:  # noqa: BLE001
                    return
                d = (100.0 * (v - q_hec) / q_hec) if q_hec else float("nan")
                filas_c.append([nom, f"{v:.1f}", dur, per,
                                f"{d:+.0f} %" if d == d else "—"])

            _fila_m("Racional", f.get("Q_racional"), "d = Tc",
                    "Coef. C (global)")
            _fila_m("Racional modificado (Témez)", f.get("Q_racional_mod"),
                    "d = Tc", "Coef. C + uniformidad")
            _fila_m("Mac Math", f.get("Q_mac_math"), "d = Tc", "Empírica")
            _fila_m("SCS — hidrograma unitario", f.get("Q_scs"), "d = Tc",
                    "SCS-CN")
            _fila_m("Verni-King", f.get("Q_verni_king"), "—", "Empírica")
            _fila_m("Mediana de los métodos directos", f.get("Q_mediana"),
                    "d = Tc", "Mixta")
            filas_c.append(["<b>HEC-HMS (adoptado)</b>", f"<b>{q_hec:.1f}</b>",
                            f"{getattr(R, 'hec_duracion_min', 1440)/60:.0f} h "
                            f"(SCS Tipo II)", "SCS-CN + Ia", "—"])
            story.append(_tabla(filas_c,
                                col_widths=[5.0*cm, 2.2*cm, 3.4*cm, 3.0*cm,
                                            2.4*cm],
                                primera_col_izq=True))
            try:
                q_med = float(f.get("Q_mediana"))
                dif = abs(q_med - q_hec) / q_hec * 100.0 if q_hec else 0.0
                if dif <= 30.0:
                    veredicto = (
                        f"La diferencia entre la mediana de los métodos "
                        f"directos ({q_med:.1f} m³/s) y el pico HEC-HMS "
                        f"({q_hec:.1f} m³/s) es de <b>{dif:.0f} %</b>, dentro "
                        f"del umbral de ±30 % que se considera aceptable entre "
                        f"formulaciones de distinta naturaleza: <b>los métodos "
                        f"se corroboran mutuamente</b>.")
                else:
                    veredicto = (
                        f"La diferencia entre la mediana de los métodos "
                        f"directos ({q_med:.1f} m³/s) y el pico HEC-HMS "
                        f"({q_hec:.1f} m³/s) es de <b>{dif:.0f} %</b>, por "
                        f"encima del umbral de ±30 %. Debe revisarse el "
                        f"parámetro responsable —CN, Tc, hietograma o área— "
                        f"antes de adoptar el caudal para diseño.")
            except Exception:  # noqa: BLE001
                veredicto = ""
            _p(story, st,
               "<b>Criterio de adopción.</b> Se adopta el caudal de "
               "<b>HEC-HMS</b> como valor de diseño porque es el único que "
               "conserva el <b>volumen</b> del evento y entrega el hidrograma "
               "completo (necesario para el tránsito y para la duración de la "
               "solicitación sobre la obra); los métodos directos se emplean "
               "como <b>verificación de orden de magnitud</b>. " + veredicto)
            _p(story, st,
               "<b>Origen de las diferencias.</b> (1) La tormenta de 24 h "
               "acumula más lámina que la de duración Tc, pero también activa "
               "mayores pérdidas por abstracción, de modo que el efecto neto "
               "sobre el pico no es proporcional. (2) El método racional "
               "supone intensidad constante y aporte simultáneo de toda la "
               "cuenca, hipótesis que sobrestima el pico en cuencas grandes o "
               "alargadas. (3) El CN que alimenta HEC-HMS es el "
               "<b>corregido por pendiente</b> (CN₂ₛ de la tabla maestra), "
               "mayor que el CN₂ cartográfico usado en los métodos "
               "directos.", "italica")


def _sec_riesgo_hidroclimatico_abc(story, st, R):
    """Sección 14 (solo tipo de obra «Análisis de riesgo ABC»).

    Análisis de riesgo hidroclimático y adaptación al cambio climático según el
    Manual de la ABC, a partir del tramo de referencia parametrizado.
    """
    from .riesgo_hidroclimatico_abc import (
        tramo_referencia_para, intro_metodologica, interpretacion_puentes,
        medidas_mitigacion, recomendaciones_socavacion, matriz_mitigacion,
        CLASE_COLOR)

    t = tramo_referencia_para(getattr(R, "lat", None), getattr(R, "lon", None),
                              getattr(R, "departamento", None))

    story.append(PageBreak())
    _p(story, st, "14. Análisis de riesgo hidroclimático y adaptación al "
                  "cambio climático", "h2")

    # 14.1 Aspectos generales y marco metodológico
    _p(story, st, "14.1 Aspectos generales y marco metodológico", "h3")
    _p(story, st, intro_metodologica(t))

    # 14.2 Análisis de vulnerabilidad del tramo de referencia
    _p(story, st, f"14.2 Análisis de vulnerabilidad del tramo de referencia "
                  f"({t.ucod})", "h3")
    _p(story, st,
       "La vulnerabilidad intrínseca del tramo se construye ponderando siete "
       "(7) variables componentes, evaluadas en escala 1–5 (5 = máxima "
       "vulnerabilidad) con los pesos de contribución del Manual (Tabla 5.1):")
    filas = [["Variable componente", "Peso", "Valor", "Descripción"]]
    for v in t.variables:
        filas.append([v.nombre, f"{v.peso*100:.0f} %", f"{v.valor:.1f} / 5.0",
                      v.descripcion or "—"])
    filas.append(["Vulnerabilidad Total Parametrizada", "100 %",
                  f"{t.vulnerabilidad_total:.1f} / 5.0",
                  t.clase_vulnerabilidad])
    story.append(_tabla(filas,
                        col_widths=[4.6 * cm, 1.4 * cm, 1.8 * cm, 8.6 * cm]))
    _p(story, st,
       f"El factor de mayor contribución a la vulnerabilidad de este tramo es "
       f"«{t.variable_dominante}», que orienta las medidas de mitigación "
       f"prioritarias (Sección 14.4).", "italica")

    # 14.3 Valoración del riesgo futuro ante escenarios de cambio climático
    _p(story, st, "14.3 Valoración del riesgo futuro ante escenarios de "
                  "cambio climático (IPCC-AR6)", "h3")
    _p(story, st,
       "El Manual combina la vulnerabilidad con la amenaza climática "
       "(envolvente de los modelos AR6 MPI y MIROC6 bajo las Rutas "
       "Socioeconómicas Compartidas — SSP) mediante RIESGO = VULNERABILIDAD × "
       "AMENAZA, para 12 escenarios en tres períodos. La escala de valoración "
       "es: 1 Mínimo, 2 Leve, 3 Medio, 4 Apreciable, 5 Considerable.")
    filas = [["Plazo", "Período", "Escenario", "Riesgo", "Δ vs base", "Clase"]]
    for e in t.escenarios:
        et = e.signo if e.ssp == "—" else f"{e.signo} ({e.ssp})"
        dtxt = "—" if e.ssp == "—" else f"+{e.incremento:.2f}"
        col = CLASE_COLOR.get(e.clase, "#000000")
        clase_c = f'<font color="{col}"><b>{e.clase}</b></font>'
        filas.append([e.plazo, e.periodo, et, f"{e.riesgo:.2f}", dtxt, clase_c])
    story.append(_tabla(filas, col_widths=[3.0*cm, 2.6*cm, 4.0*cm, 1.8*cm,
                                            2.0*cm, 3.0*cm]))
    _p(story, st, interpretacion_puentes(t))
    if getattr(R, "T_verificacion", None):
        _p(story, st,
           f"Criterio de diseño adoptado: por el incremento del riesgo "
           f"hidroclimático proyectado, el caudal de diseño se adopta para un "
           f"período de retorno de T = {R.T_diseno} años y la verificación "
           f"estructural de la obra se realiza con T = {R.T_verificacion} años "
           f"(caso pésimo). El detalle de ambos caudales y su aplicación al "
           f"dimensionamiento se presenta en la Sección 11.5.")

    # 14.4 Medidas de mitigación y adaptación
    _p(story, st, "14.4 Medidas de mitigación y adaptación recomendadas para "
                  "el diseño y la construcción", "h3")
    _p(story, st,
       "Dado que el activo principal corresponde a Drenajes Mayores (Puentes) "
       f"y que el factor de mayor vulnerabilidad del tramo es "
       f"«{t.variable_dominante}», se adoptan las siguientes medidas de "
       "ingeniería recomendadas por el Manual:")
    for subtitulo, items in medidas_mitigacion(t):
        _p(story, st, f"<b>{subtitulo}</b>")
        for it in items:
            _p(story, st, f"• {it}")

    # Matriz de mitigación específica de la variable dominante (Tabla 7.x).
    mm = matriz_mitigacion(t)
    _p(story, st, f"<b>{mm['titulo']}</b> — matriz de recomendaciones "
                  f"seleccionada por la variable dominante «{mm['variable']}». "
                  f"Indicador: {mm['indicador']}")
    filas = [["Activo", "Estrés", "Diseño", "Construcción",
              "Conservación / Mant."]]
    for a in mm["activos"]:
        filas.append([a["activo"], a["estres"], a["diseno"],
                      a["construccion"], a["conservacion"]])
    story.append(_tabla(filas, col_widths=[2.6*cm, 3.0*cm, 3.9*cm, 3.5*cm,
                                            3.6*cm]))

    # 14.5 Recomendaciones contra socavación (SSP370 / SSP585)
    rec = recomendaciones_socavacion(t)
    _p(story, st, f"14.5 {rec['titulo']}", "h3")
    _p(story, st, rec["intro"])
    for subtitulo, items in rec["bloques"]:
        _p(story, st, f"<b>{subtitulo}</b>")
        for it in items:
            _p(story, st, f"• {it}")

    # 14.6 Mapa de vulnerabilidad y riesgo hidroclimático (SIG · GEE).
    ruta_mapa = (R.graficos.get("mapa_riesgo_abc")
                 if hasattr(R, "graficos") else None)
    _p(story, st, "14.6 Mapa de vulnerabilidad y riesgo hidroclimático "
                  "(SIG · Google Earth Engine)", "h3")
    if ruta_mapa:
        v_media = (R.graficos.get("mapa_riesgo_abc_vmedia")
                   if hasattr(R, "graficos") else None)
        _p(story, st,
           "El mapa se generó con <b>Álgebra de Mapas en Google Earth "
           "Engine</b>, reproduciendo la metodología SIG del Manual de la ABC "
           "(<b>R = Vulnerabilidad × Amenaza</b>): (1) las variables espaciales "
           "se derivaron de los datasets del propio informe — <b>Pendiente</b> "
           "(COP-DEM GLO-30 reproyectado a UTM, algoritmo de Horn), "
           "<b>Conservación ambiental/intervención antrópica</b> (Global Human "
           "Modification, Kennedy et al. 2019), <b>Potencial de inundación</b> "
           "(JRC Global Surface Water occurrence) y <b>Número de Curva</b> "
           "(GCN250); (2) cada variable se <b>reclasificó a la escala 1–5</b> "
           "según los criterios del Manual; (3) <b>Clima, Fisiografía y Capa de "
           "rodadura</b> se toman como constantes del tramo RVF (parametrización "
           "por tramo); (4) se combinaron con los <b>pesos de la Tabla 5.1</b>: "
           "V = 0.10·Fis + 0.10·Clima + 0.20·Pend + 0.20·Cons + 0.20·Inund + "
           "0.10·CN + 0.10·Rodadura; (5) el color sigue el <b>código de riesgo "
           "de la Tabla 6.2</b> (verde→rojo: 1 Mínimo → 5 Considerable). El "
           "riesgo por escenario de cambio climático es R = V × A, con los "
           "valores de la Sección 14.3."
           + (f" Vulnerabilidad media sobre la cuenca: V = {v_media:.2f} / 5."
              if v_media else ""))
        story.append(_figura(ruta_mapa, ancho_cm=16.0, max_alto_cm=12.0))
    else:
        _p(story, st,
           "El mapa SIG de vulnerabilidad y riesgo (Álgebra de Mapas en Google "
           "Earth Engine) no pudo generarse para esta cuenca dentro del tiempo "
           "disponible (habitual en cuencas de gran extensión). El análisis de "
           "riesgo de las Secciones 14.1–14.5 no depende de este mapa: se basa "
           "en los valores de vulnerabilidad y riesgo por escenario del tramo "
           "RVF de referencia (Tablas 6.1 y 6.3 del Manual de la ABC). Puede "
           "regenerarse volviendo a ejecutar el análisis.", "italica")

    # Nota de trazabilidad.
    _p(story, st,
       f"Nota metodológica: el tramo RVF de referencia {t.nombre_tramo} "
       f"({t.ucod}, departamento de {t.departamento}) se seleccionó según la "
       f"ubicación del proyecto, entre los 320 subtramos del Manual de la ABC "
       f"(Tabla 6.1). Los valores de riesgo por escenario son los de la Tabla "
       f"6.3 del Manual (valores exactos por tramo y escenario). Conforme al "
       f"alcance del Manual, para mayor especificidad el analista debe "
       f"verificar en campo las condiciones de riesgo del tramo; la selección "
       f"espacial exacta al tramo más cercano requiere las geometrías de los "
       f"320 subtramos.", "italica")


def _pend_taylor_schwarz(secciones):
    """Pendiente equivalente de Taylor-Schwarz del tramo, a partir del perfil
    de fondo (cota mínima por sección) a lo largo del thalweg (DEM).

    S = ( Σ l_i / Σ (l_i/√S_i) )²  con S_i la pendiente de cada segmento.
    Devuelve la pendiente en fracción, o None si no hay perfil suficiente.
    """
    try:
        pts = sorted(((float(s.estacion_m), float(min(s.z_m)))
                      for s in secciones), key=lambda t: t[0])
    except Exception:  # noqa: BLE001
        return None
    if len(pts) < 2:
        return None
    num = den = 0.0
    for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
        L = abs(x1 - x0)
        if L <= 0:
            continue
        S = max(abs(z1 - z0) / L, 1e-4)      # piso para evitar 1/√0
        num += L
        den += L / math.sqrt(S)
    if den <= 0:
        return None
    return (num / den) ** 2


def _sec_tirante(story, st, R):
    """Sección de cálculo del tirante (calado) — tirante normal (Manning) por
    sección, enfoque HEC-RAS 1D. Se ubica tras la modelación HEC-HMS (§13) y,
    cuando aplica, tras el análisis de riesgo ABC (§14)."""
    story.append(PageBreak())
    _n = "15" if _riesgo_abc_activo(R) else "14"
    _p(story, st, f"{_n}. Cálculo del tirante (calado) del cauce", "h2")

    tir = getattr(R, "tirante", None)
    if tir is None:
        _p(story, st,
           "<b>No disponible:</b> el cálculo del tirante requiere el caudal de "
           "diseño (Sección 11) y la morfología de la cuenca (Sección 9). "
           "Verifique esas secciones.", "italica")
        return

    _p(story, st,
       "A partir del caudal de la <b>modelación HEC-HMS (Sección 13)</b> —el "
       "hidrograma de escorrentía es el método base para el dimensionamiento "
       "del puente— se estima el tirante (calado o profundidad de la lámina de "
       "agua) en el sitio del proyecto con el método del <b>tirante normal</b> "
       "(régimen uniforme), replicando el enfoque de HEC-RAS 1D: se traza la "
       "línea de fondo del cauce (thalweg) sobre el modelo de elevación "
       "COP-DEM 12.5 m, se cortan secciones transversales perpendiculares al "
       "cauce a lo largo de un tramo de 200 m aguas arriba y 200 m aguas abajo "
       "del punto, y en cada sección se resuelve la ecuación de Manning "
       "Q = (1/n)·A·R^(2/3)·S^(1/2) para hallar la cota de la superficie del "
       "agua. El cálculo se realiza para el caudal de <b>diseño T = "
       f"{tir.T_diseno}</b> y el de <b>verificación T = {tir.T_verif or 500}</b> "
       "años.")

    _p(story, st, f"{_n}.1 Datos de entrada", "h3")
    reg = tir.regimen_predominante or "—"
    filas = [["Parámetro", "Valor", "Unidad", "Origen"],
             [f"Q de diseño (T{tir.T_diseno}, HEC-HMS)", f"{tir.Q_m3s:.1f}",
              "m³/s", "Sección 13"],
             ["T de diseño", f"{tir.T_diseno}", "años", "Tipo de obra"],
             ["Área de la cuenca", f"{tir.area_cuenca_km2:.2f}", "km²",
              "Sección 9"],
             ["Pendiente del cauce S (ΔH/Lc)", f"{tir.S_cauce * 100:.2f}", "%",
              "Sección 9"],
             ["Pendiente equiv. Taylor-Schwarz",
              (f"{_pend_taylor_schwarz(tir.secciones) * 100:.2f}"
               if _pend_taylor_schwarz(tir.secciones) is not None else "—"),
              "%", "Perfil DEM del tramo"],
             ["n de Manning", f"{tir.n_manning:.3f}", "—",
              tir.n_detalle.get("fuente", "cobertura GEE")],
             ["Ancho de sección", f"{tir.ancho_seccion_m:.0f}", "m",
              "Tabla área→ancho"],
             ["Espaciado entre secciones", f"{tir.espaciado_m:.0f}", "m",
              "Tabla área→ancho"],
             ["Longitud del tramo", f"±{tir.longitud_tramo_m:.0f}", "m",
              "Criterio de proyecto"],
             ["Fuente de geometría", tir.fuente_geometria, "—", "—"]]
    story.append(_tabla(filas, col_widths=[5.2*cm, 3.4*cm, 1.8*cm, 5.1*cm],
                        primera_col_izq=True))

    _p(story, st, f"{_n}.2 Secciones de análisis en planta", "h3")
    _p(story, st,
       "El eje de análisis sigue el <b>cauce principal</b> (thalweg) determinado "
       "por el modelo de drenaje D8 de la Sección 9. Sobre ese eje se ubican las "
       "<b>11 secciones transversales</b>: cinco aguas arriba, la <b>sección de "
       "control</b> en el punto del proyecto y cinco aguas abajo, equiespaciadas "
       f"cada {tir.longitud_tramo_m / 5:.0f} m a lo largo del tramo de ±"
       f"{tir.longitud_tramo_m:.0f} m. La vista en planta muestra el punto de "
       "análisis y la traza de cada sección sobre el cauce.")
    if "tirante_planta" in R.graficos:
        story.append(_figura(R.graficos["tirante_planta"], ancho_cm=16.0,
                             max_alto_cm=13.0))

    _p(story, st, f"{_n}.3 Base teórica y fórmulas", "h3")
    _p(story, st,
       "El análisis se apoya en la hidráulica de canales abiertos en régimen "
       "permanente y gradualmente variado. Para el tramo de estudio, de "
       "pendiente aproximadamente uniforme y sin estructuras de control "
       "intermedias, la profundidad de flujo tiende al <b>tirante normal</b> "
       "y_n, que es la que iguala la pendiente de la línea de energía con la "
       "pendiente del fondo (flujo uniforme). Este es el criterio estándar del "
       "HEC-RAS 1D para el perfil de la superficie del agua cuando la condición "
       "de borde es «profundidad normal».")
    _p(story, st,
       "<b>Ecuación de Manning</b> (resistencia al flujo, sistema internacional):",
       "cuerpo")
    _p(story, st,
       "&nbsp;&nbsp;&nbsp;&nbsp;<b>Q = (1/n) · A · R^(2/3) · S^(1/2)</b>", "cuerpo")
    _p(story, st,
       "donde <b>Q</b> es el caudal (m³/s); <b>n</b> el coeficiente de rugosidad "
       "de Manning (adimensional, s·m^(−1/3)); <b>A</b> el área hidráulica de la "
       "sección (m²); <b>P</b> el perímetro mojado (m); <b>R = A/P</b> el radio "
       "hidráulico (m); y <b>S</b> la pendiente de la línea de energía "
       "(≈ pendiente del cauce, m/m). La <b>capacidad de conducción</b> "
       "(conveyance) es K = (1/n)·A·R^(2/3) [m³/s], de modo que Q = K·S^(1/2).")
    _p(story, st,
       "Para cada una de las 11 secciones (cinco aguas arriba, la sección de "
       "control en el punto y cinco aguas abajo) el programa integra "
       "numéricamente A(WSE) y P(WSE) sobre la porción sumergida del perfil "
       "transversal —resolviendo los puntos de corte con las márgenes— y busca, "
       "por bisección (método de Brent), la cota de la superficie del agua "
       "<b>WSE</b> que satisface Manning para el caudal, el n y la S del cauce. "
       "El tirante es y = WSE − z_fondo, con z_fondo la cota más baja del lecho "
       "en la sección.")
    _p(story, st,
       "<b>Variables hidráulicas derivadas.</b> De la solución se obtienen: la "
       "<b>velocidad media</b> V = Q/A (m/s); el <b>ancho del espejo de agua</b> "
       "B (m); la <b>profundidad hidráulica</b> D = A/B (m); y el <b>número de "
       "Froude</b> Fr = V/√(g·D), con g = 9.81 m/s² (adimensional). El Froude "
       "clasifica el régimen: <b>subcrítico</b> (Fr &lt; 1, controla aguas "
       "abajo, flujo tranquilo), <b>crítico</b> (Fr ≈ 1) o <b>supercrítico</b> "
       "(Fr &gt; 1, controla aguas arriba, flujo rápido y erosivo). El régimen "
       "es determinante para la ubicación de las condiciones de borde y para la "
       "socavación.")

    _p(story, st,
       "<b>Obtención de los parámetros y unidades (trazabilidad).</b>", "cuerpo")
    _p(story, st,
       "• <b>Caudal Q (m³/s):</b> proviene de la modelación HEC-HMS (Sección "
       "13, Q pico del hidrograma) para el período de retorno de diseño; el "
       "tirante, la velocidad y la socavación se calculan además con el caudal "
       "del período de retorno de verificación.")
    _p(story, st,
       "• <b>Geometría de las secciones:</b> el eje de análisis es el "
       "<b>cauce principal</b> (thalweg) trazado por hidrología D8 sobre el DEM "
       "COP-DEM 12.5 m —el mismo procedimiento del mapa de la red de drenaje "
       "(Sección 9)—, recorriendo 200 m aguas arriba y 200 m aguas abajo del "
       "punto. Perpendicular a ese eje se cortan las 11 secciones, muestreando "
       "la cota del terreno (m s.n.m.) del DEM cada ~12.5 m; así las márgenes "
       "ascienden a ambos lados del fondo del cauce (forma de valle).")
    _p(story, st,
       "• <b>Pendiente S (m/m):</b> se obtiene del descenso del fondo del cauce "
       "entre secciones (ΔH/L) sobre el DEM, coherente con la Sección 9.")
    _p(story, st,
       "• <b>Rugosidad n (adimensional):</b> se deriva de la cobertura de suelo "
       "MapBiomas del corredor fluvial (Google Earth Engine), traduciendo cada "
       "clase a un n de Manning (tablas de Chow, 1959) y ponderando por área; "
       "el mapa del coeficiente de Manning se presenta en la Sección 9.8.")

    _p(story, st, f"{_n}.4 Resultados por sección transversal (11 secciones)",
       "h3")
    _p(story, st,
       "En cada sección se resuelve el nivel de agua con la <b>ecuación de "
       "energía (Bernoulli)</b> E = y + V²/2g y la <b>ecuación de Manning</b> "
       "para la capacidad de conducción; se reporta además la <b>energía "
       "específica E</b> de cada sección, base del análisis de flujo "
       "gradualmente variado.", "cuerpo")
    if tir.secciones:
        cab = ["Sección", "Estación (m)", "Tirante y (m)", "Espejo B (m)",
               "Área A (m²)", "R (m)", "V (m/s)", "E (m)", "Fr", "Régimen"]
        fil = [cab]
        for s in tir.secciones:
            e_esp = (s.tirante_m + s.velocidad_ms ** 2 / 19.62
                     if s.velocidad_ms == s.velocidad_ms else float("nan"))
            fil.append([
                str(s.id + 1), f"{s.estacion_m:.0f}", f"{s.tirante_m:.2f}",
                f"{s.ancho_sup_m:.1f}", f"{s.area_m2:.1f}",
                f"{s.radio_h_m:.2f}", f"{s.velocidad_ms:.2f}",
                f"{e_esp:.2f}" if e_esp == e_esp else "—",
                f"{s.froude:.2f}" if s.froude == s.froude else "—",
                s.regimen or "—"])
        cw = [1.3*cm, 1.7*cm, 1.7*cm, 1.6*cm, 1.6*cm, 1.2*cm, 1.4*cm,
              1.4*cm, 1.1*cm, 2.0*cm]
        story.append(_tabla(fil, col_widths=cw))

    # Perfil de flujo gradualmente variado (standard-step) — solo con DEM real.
    gvf = getattr(tir, "perfil_gvf", None)
    if gvf:
        _p(story, st,
           "<b>Perfil de flujo gradualmente variado (método del paso "
           "estándar).</b> Además del tirante normal por sección, se resuelve "
           "el perfil de la superficie del agua en <b>régimen permanente "
           "gradualmente variado</b> aplicando la ecuación de energía entre "
           "secciones consecutivas, H<sub>i+1</sub> = H<sub>i</sub> + h<sub>f</sub> "
           "(H = WSE + V²/2g; h<sub>f</sub> = ½·(Sf<sub>i</sub>+Sf<sub>i+1</sub>)·Δx), "
           "partiendo de la sección de control aguas abajo. Este perfil captura "
           "el remanso/caída que el tirante normal no reproduce.", "cuerpo")
        cabg = ["Estación (m)", "Cota fondo (m)", "WSE GVF (m)", "y (m)",
                "V (m/s)", "Línea energía (m)", "Fr"]
        filg = [cabg]
        for p in gvf:
            filg.append([f"{p['estacion_m']:.0f}", f"{p['z_fondo']:.2f}",
                         f"{p['wse']:.2f}", f"{p['tirante']:.2f}",
                         f"{p['V']:.2f}", f"{p['E']:.2f}",
                         f"{p['Fr']:.2f}" if p['Fr'] == p['Fr'] else "—"])
        story.append(_tabla(filg, col_widths=[2.3*cm, 2.5*cm, 2.5*cm, 1.8*cm,
                                              1.9*cm, 3.0*cm, 1.5*cm]))

    _p(story, st,
       "<b>Perfil longitudinal y secciones representativas.</b> El panel "
       "superior muestra el perfil del fondo del cauce con: la lámina de agua y "
       f"el NAME de diseño (T = {tir.T_diseno}), la <b>línea de energía</b> "
       "(E = WSE + V²/2g), el <b>NAME de la avenida de comprobación</b> "
       f"(T = {tir.T_verif or 500}) y la cara inferior de la viga (NAME de "
       "diseño + gálibo), de modo que se aprecia gráficamente el resguardo "
       "entre la crecida de verificación y la superestructura. Los paneles "
       "inferiores muestran tres secciones (aguas arriba, control y aguas "
       "abajo) con su nivel de agua.", "cuerpo")
    if "tirante" in R.graficos:
        story.append(_figura(R.graficos["tirante"], ancho_cm=17.0,
                             max_alto_cm=13.0))

    _p(story, st, f"{_n}.5 Cuadro de resultados finales y verificación de la "
                  "viga del puente", "h3")
    _p(story, st,
       f"El caudal de entrada al módulo hidráulico se toma de la "
       f"<b>modelación HEC-HMS (Sección 13)</b> —el hidrograma de escorrentía "
       f"es el método base para el dimensionamiento del puente—, evaluando "
       f"primero el <b>período de retorno de diseño T = {tir.T_diseno} años</b> "
       f"y luego el de <b>verificación T = {tir.T_verif or 500} años</b>. Para "
       f"cada caudal se reporta el tirante (calado), la velocidad media y la "
       f"socavación total; este es el cuadro de resultados finales del punto "
       f"de hidráulica fluvial.")

    def _soc_total(s):
        if s is None:
            return None
        vals = [v for v in (getattr(s, "socavacion_total_pila_m", float("nan")),
                            getattr(s, "socavacion_total_estribo_m", float("nan")))
                if v == v]
        if vals:
            return max(vals)
        g = getattr(s, "ys_general_m", float("nan"))
        return g if g == g else None

    sd, sv = tir.socavacion_diseno, tir.socavacion_verif
    st_d, st_v = _soc_total(sd), _soc_total(sv)
    tv = tir.tirante_verif_m
    vv = tir.velocidad_verif_ms
    col_v = (tir.T_verif is not None and tv is not None)
    cab = ["Parámetro", f"Diseño — Q(T{tir.T_diseno})"]
    if col_v:
        cab.append(f"Verificación — Q(T{tir.T_verif})")

    def _row(label, d, v):
        r = [label, d]
        if col_v:
            r.append(v)
        return r

    fil = [cab,
           _row("Caudal Q (m³/s) — HEC-HMS", f"{tir.Q_m3s:.1f}",
                f"{tir.Q_verif_m3s:.1f}" if col_v else ""),
           _row("Tirante de control y (m)", f"{tir.tirante_control_m:.2f}",
                f"{tv:.2f}" if col_v else ""),
           _row("Tirante máximo del tramo (m)", f"{tir.tirante_max_m:.2f}",
                f"{tir.tirante_verif_max_m:.2f}"
                if col_v and tir.tirante_verif_max_m is not None else ""),
           _row("Velocidad media V (m/s)", f"{tir.velocidad_media_ms:.2f}",
                f"{vv:.2f}" if col_v and vv is not None else ""),
           _row("Froude / régimen",
                f"{tir.froude_medio:.2f} ({reg or '—'})",
                (f"{tir.froude_verif:.2f} ({tir.regimen_verif or '—'})"
                 if col_v and tir.froude_verif is not None else "")),
           _row("Socavación total (general+local) (m)",
                f"{st_d:.2f}" if st_d is not None else "—",
                (f"{st_v:.2f}" if st_v is not None else "—") if col_v else ""),
           _row("Prof. cimentación recomendada (m)",
                f"{sd.prof_cimentacion_recomendada_m:.2f}"
                if sd is not None else "—",
                (f"{sv.prof_cimentacion_recomendada_m:.2f}"
                 if sv is not None else "—") if col_v else "")]
    cw = ([5.4*cm, 4.6*cm, 4.6*cm] if col_v else [7.0*cm, 5.0*cm])
    story.append(_tabla(fil, col_widths=cw, primera_col_izq=True))

    # ── Concepto de cierre: posición de la viga y verificación con T500. ──
    if (tir.cota_viga_sobre_fondo_m is not None and col_v
            and _es_obra_puente(R)):
        story.append(Spacer(1, 0.2 * cm))
        _p(story, st, f"{_n}.5.1 Posición de la viga y verificación del gálibo",
           "h3")
        holg = tir.holgura_viga_verif_m
        verifica = tir.verifica_viga_verif
        _p(story, st,
           f"La viga (cara inferior del tablero) se ubica a la distancia "
           f"normativa —<b>gálibo = {tir.galibo_m:.1f} m</b> (borde libre para "
           f"ríos con arrastre de palizada, MOPSV/ABC · AASHTO)— por encima del "
           f"Nivel de Aguas Máximas del caudal de diseño T = {tir.T_diseno} "
           f"(tirante {tir.tirante_control_m:.2f} m). La cota inferior de la "
           f"viga queda entonces a <b>{tir.cota_viga_sobre_fondo_m:.2f} m sobre "
           f"el fondo del cauce</b>.")
        pal = tir.altura_palizada_m if tir.altura_palizada_m is not None else 0.0
        gmin = tir.galibo_min_abc_m if tir.galibo_min_abc_m is not None else 1.5
        gef = tir.galibo_efectivo_verif_m
        _p(story, st,
           f"<b>Verificación normativa del gálibo libre (Manual ABC).</b> La "
           f"norma exige que el gálibo libre entre el <b>NAME de verificación "
           f"más la altura de palizada/troncos</b> y la cara inferior de la "
           f"viga sea ≥ <b>{gmin:.2f} m</b>. Con el NAME de verificación "
           f"T = {tir.T_verif} ({tv:.2f} m) y una palizada de {pal:.2f} m, el "
           f"gálibo libre efectivo resulta "
           + (f"<b>{gef:.2f} m ≥ {gmin:.2f} m → <font color='#1c7a3f'>"
              f"VERIFICA</font></b>: la crecida de {tir.T_verif} años más el "
              f"material flotante mantienen el resguardo mínimo bajo la "
              f"superestructura."
              if verifica else
              f"<b>{gef:.2f} m &lt; {gmin:.2f} m → <font color='#a12020'>"
              f"ALERTA: NO VERIFICA</font></b>: debe elevarse la rasante o "
              f"aumentar el gálibo, pues la crecida de {tir.T_verif} años más "
              f"la palizada comprometen el resguardo mínimo.")
           + " Este es el concepto de cierre de la hidráulica fluvial.")
        cabg = ["Concepto", "Valor (m sobre el fondo)"]
        filg = [cabg,
                [f"NAME de diseño (T{tir.T_diseno})",
                 f"{tir.tirante_control_m:.2f}"],
                ["+ Gálibo de proyecto", f"{tir.galibo_m:.2f}"],
                ["= Cota inferior de la viga",
                 f"{tir.cota_viga_sobre_fondo_m:.2f}"],
                [f"NAME de verificación (T{tir.T_verif})", f"{tv:.2f}"],
                ["+ Altura de palizada / troncos", f"{pal:.2f}"],
                ["= Nivel de solicitación", f"{tv + pal:.2f}"],
                [f"Gálibo libre efectivo (mín. ABC {gmin:.2f} m)",
                 f"{gef:+.2f}  ({'VERIFICA' if verifica else 'NO VERIFICA'})"]]
        story.append(_tabla(filg, col_widths=[8.0*cm, 6.0*cm],
                            primera_col_izq=True))
    # Recomendaciones fundadas en conceptos fluviales.
    _p(story, st,
       "<b>Recomendaciones (fundamento fluvial):</b>", "cuerpo")
    _p(story, st,
       f"• <b>Calado de diseño y gálibo.</b> Se adopta como calado de diseño el "
       f"<b>tirante máximo del tramo ({tir.tirante_max_m:.2f} m)</b> —no el "
       f"medio— porque en régimen gradualmente variado el remanso y las "
       f"irregularidades del cauce elevan localmente la superficie del agua; a "
       f"ese nivel máximo (correspondiente al Nivel de Aguas Máximas, NAME) se "
       f"le suma el <b>borde libre / gálibo</b> que exige la norma vial "
       f"(típicamente ≥ 1.5–2.0 m sobre el NAME, mayor en ríos con arrastre de "
       f"palizada), para fijar la cota inferior de la superestructura y evitar "
       f"el impacto de material flotante contra el tablero.")
    _p(story, st,
       f"• <b>Régimen del flujo.</b> Un régimen {reg or 'indeterminado'} "
       f"(Fr = {tir.froude_medio:.2f}) implica que "
       + ("el control hidráulico está aguas abajo y el flujo es tranquilo; las "
          "curvas de remanso se propagan hacia aguas arriba."
          if tir.froude_medio == tir.froude_medio and tir.froude_medio < 1
          else "el flujo es rápido y de alto poder erosivo; el control está "
          "aguas arriba y debe cuidarse especialmente la protección del lecho y "
          "de las márgenes contra la socavación.") +
       " La velocidad media condiciona la protección con enrocado y la "
       "estabilidad de las márgenes.")
    _p(story, st,
       "• <b>Sensibilidad a la rugosidad.</b> El tirante es sensible al "
       "coeficiente n de Manning: un n subestimado reduce el calado y el gálibo "
       "calculados. Se recomienda verificar el n en campo (granulometría del "
       "lecho, vegetación de márgenes, sinuosidad) y contrastar con las tablas "
       "de Chow (1959).")
    _p(story, st,
       "• <b>Estabilidad del cauce.</b> Conviene evaluar la tendencia del cauce "
       "(agradación/degradación, migración lateral, sinuosidad) según HEC-20; un "
       "cauce inestable modifica la sección de cruce y la socavación a largo "
       "plazo, y puede requerir obras de encauzamiento o protección de márgenes.")
    ia = getattr(R, "inund_area_alta_pct", None)
    if ia is not None:
        detalle = ("una planicie inundable amplia que conviene no obstruir: "
                   "la longitud del puente debe abarcar el cauce de avenida y "
                   "los accesos deben protegerse contra el desborde lateral"
                   if ia >= 25 else
                   "franjas inundables a lo largo del cauce que deben cubrirse "
                   "con la longitud del vano y el gálibo adoptados"
                   if ia >= 10 else
                   "un valle encajado con escasa planicie inundable, donde el "
                   "condicionante dominante es la socavación local más que el "
                   "desborde")
        _p(story, st,
           f"• <b>Susceptibilidad a la inundación (mapa 9.9).</b> El índice "
           f"HAND clasifica el <b>{ia:.1f} %</b> del área de la cuenca como de "
           f"susceptibilidad alta/muy alta (terreno a ≤ 5 m sobre el cauce), lo "
           f"que indica {detalle}. Esta capa complementa el calado y la "
           f"socavación para dimensionar la longitud, el gálibo y las "
           f"protecciones del cruce.")
    for adv in tir.advertencias:
        _p(story, st, "• " + adv, "italica")

    # ── Pilar 3 — Socavación ──
    soc = getattr(tir, "socavacion", None)
    if soc is not None:
        story.append(PageBreak())
        _p(story, st, f"{_n}.6 Socavación y profundidad de cimentación (Pilar 3)",
           "h3")
        _p(story, st,
           "La socavación es el criterio estructural crítico para definir la "
           "cota de desplante de la cimentación del puente. Se estima la "
           "socavación total —descenso generalizado del lecho más socavaciones "
           "locales— con el caudal gobernante, siguiendo el estándar FHWA "
           "HEC-18 (Arneson et al., 2012), equivalente al módulo «Bridge Scour» "
           "de HEC-RAS, y el método de Lischtvan-Lebediev (Maza Álvarez) para la "
           "socavación general. Conforme a AASHTO LRFD, la fundación se coloca "
           "por debajo de la socavación total (estado límite de evento extremo, "
           "carga WA).")
        _p(story, st,
           f"<b>Hidráulica que alimenta el cálculo.</b> Las variables de "
           f"aproximación (tirante y<sub>1</sub>, velocidad V<sub>1</sub> y "
           f"Froude Fr<sub>1</sub>) se toman de la <b>solución de tirante "
           f"normal en la sección de control</b> (Sección 14.4), no del perfil "
           f"gradualmente variado, porque las ecuaciones de HEC-18 están "
           f"formuladas sobre condiciones de aproximación uniformes. Los "
           f"valores empleados son: y₁ = {soc.y1_m:.2f} m, "
           f"V₁ = {soc.V1_ms:.2f} m/s y Fr₁ = {soc.Fr1:.2f}, con el caudal "
           f"gobernante Q(T = {soc.T_anios}) = {soc.Q_m3s:.1f} m³/s. "
           f"Cualquier revisión debe verificar primero esas tres cifras contra "
           f"la tabla de la Sección 14.4.")
        # Componentes
        cab = ["Componente", "Método", "Socavación (m)"]
        fil = [cab]
        if soc.ys_general_m == soc.ys_general_m:
            fil.append(["General (descenso del lecho)", "Lischtvan-Lebediev",
                        f"{soc.ys_general_m:.2f}"])
        if soc.ys_contraccion_m == soc.ys_contraccion_m:
            fil.append(["Por contracción",
                        f"Laursen ({soc.regimen_contraccion})",
                        f"{soc.ys_contraccion_m:.2f}"])
        if soc.ys_pila_m == soc.ys_pila_m:
            fil.append([f"Local en pila (a = {soc.ancho_pila_m:.2f} m, "
                        f"{soc.forma_pila})", "CSU / HEC-18",
                        f"{soc.ys_pila_m:.2f}"])
        if soc.ys_estribo_m == soc.ys_estribo_m:
            fil.append([f"Local en estribo (L = {soc.long_estribo_m:.1f} m)",
                        soc.metodo_estribo, f"{soc.ys_estribo_m:.2f}"])
        story.append(_tabla(fil, col_widths=[7.5*cm, 5.5*cm, 3.0*cm],
                            primera_col_izq=True))

        _p(story, st,
           f"El cálculo se realiza con el caudal gobernante Q(T = "
           f"{soc.T_anios}) = {soc.Q_m3s:.1f} m³/s, tirante y = {soc.y1_m:.2f} m, "
           f"velocidad V = {soc.V1_ms:.2f} m/s (Fr = {soc.Fr1:.2f}) y un lecho "
           f"con D50 = {soc.D50_mm:.0f} mm. A continuación se explica cada modelo, "
           f"su fórmula, variables y unidades.")

        # (a) Socavación general — Lischtvan-Lebediev
        _p(story, st, "<b>a) Socavación general — Lischtvan-Lebediev.</b>",
           "cuerpo")
        _p(story, st,
           "Describe el descenso generalizado del lecho cuando la velocidad de "
           "la corriente supera la velocidad erosiva del material. Igualando la "
           "velocidad real de la corriente (que decrece al profundizarse el "
           "cauce) con la velocidad erosiva, se despeja la profundidad socavada "
           "H_s medida desde la superficie del agua. Para lecho no cohesivo:")
        _p(story, st,
           "&nbsp;&nbsp;&nbsp;<b>H_s = [ α·H_0^(5/3) / (0.68·β·d_m^0.28) ]^(1/(1+x))</b>, "
           "con α = Q_d / (H_m^(5/3)·B_e·μ)", "cuerpo")
        _p(story, st,
           "donde <b>H_0</b> es el tirante en la vertical antes de socavar (m); "
           "<b>H_m</b> la profundidad hidráulica media = A/B_e (m); <b>B_e</b> el "
           "ancho efectivo de la superficie libre (m); <b>μ</b> el coeficiente de "
           "contracción por pilas (0.95–1.0); <b>d_m</b> el diámetro medio "
           "(≈1.25·D50, mm); <b>β = 0.7929 + 0.0973·log₁₀(T_r)</b> el coeficiente "
           "de frecuencia (adimensional, crece con el período de retorno); y "
           "<b>x</b> un exponente función de la granulometría (tablas de "
           f"Lischtvan-Lebediev). Resultado: <b>{soc.ys_general_m:.2f} m</b> "
           f"(β = {(0.7929 + 0.0973 * math.log10(max(soc.T_anios, 1))):.2f}).")

        # (b) Contracción — Laursen
        if soc.ys_contraccion_m == soc.ys_contraccion_m:
            _p(story, st, "<b>b) Socavación por contracción — Laursen (HEC-18).</b>",
               "cuerpo")
            _p(story, st,
               "Al estrecharse la sección bajo el puente, aumenta la velocidad y "
               "el lecho desciende hasta recuperar el equilibrio de transporte. "
               "El régimen se decide comparando la velocidad de aproximación con "
               "la crítica del D50: en <b>agua clara</b> "
               "y₂ = [K_u·Q²/(D_m^(2/3)·W²)]^(3/7) (K_u = 0.025 SI); en "
               "<b>lecho vivo</b> y₂/y₁ = (Q₂/Q₁)^(6/7)·(W₁/W₂)^k₁. La socavación "
               f"es y_s = y₂ − y₀. Régimen adoptado: <b>{soc.regimen_contraccion}</b>; "
               f"resultado <b>{soc.ys_contraccion_m:.2f} m</b>.")

        # (c) Local en pila — CSU/HEC-18
        if soc.ys_pila_m == soc.ys_pila_m:
            fp = soc.factores_pila or {}
            _p(story, st,
               "<b>c) Socavación local en pila — ecuación CSU / HEC-18.</b>",
               "cuerpo")
            _p(story, st,
               "&nbsp;&nbsp;&nbsp;<b>y_s = 2.0·K₁·K₂·K₃·K₄·(a/y₁)^0.65·Fr₁^0.43·y₁</b>",
               "cuerpo")
            _p(story, st,
               f"donde <b>y_s</b> es la socavación local (m); <b>a</b> el ancho de "
               f"la pila (= {soc.ancho_pila_m:.2f} m); <b>y₁</b> el tirante de "
               f"aproximación (m); <b>Fr₁</b> el número de Froude de aproximación; "
               f"<b>K₁</b> corrige la forma de la nariz de la pila "
               f"(= {fp.get('K1', 1.0):.2f}, «{soc.forma_pila}»); <b>K₂</b> el "
               f"ángulo de ataque del flujo (= {fp.get('K2', 1.0):.2f}, "
               f"θ = {soc.angulo_ataque_grados:.0f}°); <b>K₃</b> la condición del "
               f"lecho (= {fp.get('K3', 1.1):.2f}); y <b>K₄</b> el acorazamiento "
               f"por material grueso (= {fp.get('K4', 1.0):.2f}). Se aplican los "
               f"topes físicos del foso (y_s ≤ 2.4a si Fr ≤ 0.8; ≤ 3.0a si "
               f"Fr &gt; 0.8). Resultado para la <b>pila central</b>: "
               f"<b>{soc.ys_pila_m:.2f} m</b>.")

        # (d) Local en estribo — Froehlich / HIRE
        if soc.ys_estribo_m == soc.ys_estribo_m:
            _p(story, st,
               "<b>d) Socavación local en estribo — "
               f"{soc.metodo_estribo} (HEC-18).</b>", "cuerpo")
            if soc.metodo_estribo == "Froehlich":
                _p(story, st,
                   "&nbsp;&nbsp;&nbsp;<b>y_s = (2.27·K₁·K₂·(L'/y_a)^0.43·Fr^0.61 + 1)·y_a</b> "
                   "(para L/y₁ ≤ 25)", "cuerpo")
            else:
                _p(story, st,
                   "&nbsp;&nbsp;&nbsp;<b>y_s = 4·y₁·(K₁/0.55)·K₂·Fr^0.33</b> "
                   "(HIRE, para L/y₁ &gt; 25)", "cuerpo")
            _p(story, st,
               f"donde <b>L (= {soc.long_estribo_m:.1f} m)</b> es la longitud del "
               "terraplén/estribo proyectada normal al flujo obstruido; <b>y_a</b> "
               "el tirante medio en la zona obstruida (m); <b>K₁</b> la forma del "
               "estribo (vertical 1.00; con aleros 0.82; derramado 0.55); <b>K₂</b> "
               "el ángulo del terraplén; y <b>Fr</b> el Froude del flujo obstruido. "
               f"Resultado: <b>{soc.ys_estribo_m:.2f} m</b>.")

        # Total y cimentación
        tot = []
        if soc.socavacion_total_pila_m == soc.socavacion_total_pila_m:
            tot.append(f"en la pila central {soc.socavacion_total_pila_m:.2f} m")
        if soc.socavacion_total_estribo_m == soc.socavacion_total_estribo_m:
            tot.append(f"en los estribos {soc.socavacion_total_estribo_m:.2f} m")
        tot_txt = "; ".join(tot) if tot else \
            f"{soc.ys_general_m:.2f} m (descenso generalizado)"
        _p(story, st,
           f"<b>Socavación total</b> (general/contracción + local): {tot_txt}. "
           f"Adoptando un resguardo de seguridad de {soc.resguardo_m:.1f} m sobre "
           f"la socavación total, la <b>profundidad de cimentación recomendada es "
           f"de {soc.prof_cimentacion_recomendada_m:.2f} m</b> por debajo del "
           f"fondo actual del cauce. Este valor rige el desplante de pilotes o "
           f"zapatas: la fundación debe apoyarse por debajo de la línea de "
           f"socavación total calculada con el caudal de verificación, conforme "
           f"al estado límite de evento extremo de AASHTO LRFD. Debe confirmarse "
           f"con la granulometría real (D50, D95) del estudio de suelos del cauce.")
        for adv in soc.advertencias:
            _p(story, st, "• " + adv, "italica")

    # ── 14.7 Análisis de sensibilidad ±20 % (CN, Tc, n) — exigido EDTP ──
    sen = getattr(R, "sensibilidad", None)
    if sen is not None and getattr(sen, "filas", None):
        story.append(PageBreak())
        _p(story, st, f"{_n}.7 Análisis de sensibilidad de parámetros "
                      "(±20 %)", "h3")
        _p(story, st,
           "Para otorgar robustez ingenieril al diseño (exigencia de nivel "
           "EDTP), se cuantifica cómo varían el <b>caudal máximo de diseño</b> "
           f"y el <b>tirante hidráulico</b> ante variaciones de "
           f"<b>±{sen.variacion*100:.0f} %</b> en los tres parámetros de mayor "
           "incertidumbre: el número de curva CN (pérdidas SCS), el tiempo de "
           "concentración Tc (forma del hidrograma) y el coeficiente de "
           "rugosidad de Manning n (tirante). El caudal se reevalúa con el "
           "motor HEC-HMS (Sección 13) y el tirante con la ecuación de Manning "
           "en la sección de control (Sección 14).")

        def _f(v, dec=1):
            return f"{v:.{dec}f}" if v is not None else "—"

        # Tabla A — sensibilidad del caudal (parámetros que afectan a Q).
        _p(story, st, "<b>a) Sensibilidad del caudal de diseño Q(T = "
           f"{sen.T_diseno})</b>", "cuerpo")
        cabq = ["Parámetro", "Valor base", "Q(−20 %)", "Q(base)", "Q(+20 %)",
                "Variación máx. de Q"]
        filq = [cabq]
        for f in sen.filas:
            if f.q_var_pct is None:
                continue
            filq.append([f"{f.parametro} ({f.unidad})" if f.unidad != "—"
                         else f.parametro,
                         _f(f.valor_base, 3 if f.parametro == "n" else 1),
                         f"{_f(f.q_menos)} m³/s", f"{_f(f.q_base)} m³/s",
                         f"{_f(f.q_mas)} m³/s", f"±{_f(f.q_var_pct)} %"])
        story.append(_tabla(filq, col_widths=[2.6*cm, 2.3*cm, 3.0*cm, 3.0*cm,
                                              3.0*cm, 3.0*cm],
                            primera_col_izq=True))

        # Tabla B — sensibilidad del tirante (todos los parámetros).
        _p(story, st, "<b>b) Sensibilidad del tirante de control</b>", "cuerpo")
        caby = ["Parámetro", "Valor base", "y(−20 %)", "y(base)", "y(+20 %)",
                "Variación máx. de y"]
        fily = [caby]
        for f in sen.filas:
            if f.y_var_pct is None:
                continue
            fily.append([f"{f.parametro} ({f.unidad})" if f.unidad != "—"
                         else f.parametro,
                         _f(f.valor_base, 3 if f.parametro == "n" else 1),
                         f"{_f(f.y_menos, 2)} m", f"{_f(f.y_base, 2)} m",
                         f"{_f(f.y_mas, 2)} m", f"±{_f(f.y_var_pct)} %"])
        story.append(_tabla(fily, col_widths=[2.6*cm, 2.3*cm, 3.0*cm, 3.0*cm,
                                              3.0*cm, 3.0*cm],
                            primera_col_izq=True))
        _p(story, st,
           f"<b>Interpretación.</b> El parámetro más sensible para el caudal es "
           f"<b>{sen.parametro_mas_sensible_q or 'CN'}</b> y para el tirante es "
           f"<b>{sen.parametro_mas_sensible_y or 'CN'}</b>. El número de curva "
           "CN concentra la mayor incertidumbre del estudio porque controla el "
           "volumen de escorrentía; por ello se recomienda verificar el CN con "
           "el grupo hidrológico de suelo real (HYSOGs / calicatas) y la "
           "cobertura de campo antes del diseño definitivo, y adoptar un "
           "criterio conservador (CN en condición de humedad antecedente AMC "
           "II–III) cuando la cuenca sea sensible. La rugosidad n incide solo "
           "sobre el tirante (no sobre el caudal), de modo que su verificación "
           "de campo afecta directamente el gálibo de la viga.")

    # ── 14.7.1 Sensibilidad hidráulica-socavación (Q, n, S, D50 a ±20/40 %) ──
    shx = getattr(R, "sensibilidad_hidraulica", None)
    if shx is not None and getattr(shx, "filas", None):
        story.append(PageBreak())
        _p(story, st, f"{_n}.7.1 Sensibilidad del diseño hidráulico y de la "
                      "socavación", "h3")
        _vv = " y ".join(f"±{v*100:.0f} %" for v in shx.variaciones)
        _p(story, st,
           f"Complementando la sensibilidad hidrológica anterior, esta tabla "
           f"cuantifica cómo responden el <b>tirante</b>, la <b>velocidad</b>, "
           f"la <b>socavación total</b> y la <b>cota inferior de la viga</b> a "
           f"variaciones de <b>{_vv}</b> en los cuatro parámetros de mayor "
           f"incidencia en el diseño del cruce: el caudal Q, el coeficiente de "
           f"Manning n, la pendiente del cauce S y el diámetro del sedimento "
           f"D50. Todos se reevalúan en la sección de control con la ecuación "
           f"de Manning y las fórmulas de socavación HEC-18 (gálibo adoptado "
           f"= {shx.galibo_m:.1f} m).")

        def _g(v, d=2):
            return f"{v:.{d}f}" if v is not None else "—"

        cab = ["Parámetro", "Variación", "Valor", "Tirante y (m)",
               "V (m/s)", "Socavación (m)", "Cota viga (m)"]
        fil = [cab]
        b = shx.base
        fil.append(["Base (sin variación)", "—", f"Q={_g(shx.filas[0].valor,0)}",
                    _g(b.get("tirante")), _g(b.get("V")),
                    _g(b.get("socavacion")), _g(b.get("cota_viga"))])
        _uni = {"Q": " m³/s", "n": "", "S": " %", "D50": " mm"}
        for f in shx.filas:
            if f.parametro == "Base":
                continue
            fil.append([
                f.parametro, f"{f.variacion_pct:+.0f} %",
                f"{_g(f.valor, 3 if f.parametro == 'n' else 1)}{_uni.get(f.parametro,'')}",
                _g(f.tirante_m), _g(f.velocidad_ms),
                _g(f.socavacion_m), _g(f.cota_viga_m)])
        story.append(_tabla(fil, col_widths=[2.5*cm, 1.7*cm, 2.2*cm, 2.3*cm,
                                             1.9*cm, 2.6*cm, 2.3*cm],
                            primera_col_izq=True))
        # Rango de respuesta del tirante y de la socavación (banda de diseño).
        try:
            ys_vals = [f.socavacion_m for f in shx.filas
                       if f.socavacion_m is not None]
            y_vals = [f.tirante_m for f in shx.filas if f.tirante_m is not None]
            _p(story, st,
               f"<b>Banda de diseño.</b> Sobre el conjunto de escenarios, el "
               f"tirante varía entre {min(y_vals):.2f} y {max(y_vals):.2f} m y "
               f"la socavación total entre {min(ys_vals):.2f} y "
               f"{max(ys_vals):.2f} m. El caudal Q es el que más desplaza "
               f"tirante y socavación simultáneamente; el n de Manning domina "
               f"la velocidad y, con ella, la socavación local; el D50 solo "
               f"afecta la socavación (a mayor D50, menor socavación). Se "
               f"recomienda adoptar la fundación y el gálibo con el "
               f"<b>escenario más desfavorable</b> de esta banda mientras no "
               f"se disponga de granulometría de campo y aforo del caudal.",
               "cuerpo")
        except Exception:  # noqa: BLE001
            pass

    # ── 14.8 Plan conceptual de obras de protección fluvial (EDTP) ──
    pr = getattr(R, "proteccion", None)
    if pr is not None and _es_obra_puente(R):
        story.append(PageBreak())
        _p(story, st, f"{_n}.8 Plan conceptual de obras de protección "
                      "fluvial", "h3")
        _p(story, st,
           "El dictamen de nivel EDTP exige definir y predimensionar las obras "
           "de encauzamiento y protección que evitan la excentricidad del "
           "flujo y la falla de los accesos y estribos del puente. El "
           "dimensionamiento siguiente es <b>preliminar</b> y se deriva de la "
           "hidráulica calculada (velocidad, tirante, NAME y socavación): el "
           "enrocado se dimensiona con la ecuación de <b>Isbash</b> "
           "(D50 = V²/[C²·2g·(Ss−1)], C = "
           f"{pr.coef_isbash:.2f}, Ss = 2.65) y las contramedidas siguen la "
           "guía <b>FHWA HEC-23</b>.")
        filas = [["Elemento", "Valor de prediseño"],
                 ["Velocidad de diseño V", f"{pr.velocidad_ms:.2f} m/s"],
                 ["Tirante de diseño y", f"{pr.tirante_m:.2f} m"],
                 ["Enrocado — D50 (Isbash)",
                  f"{pr.d50_enrocado_m:.2f} m ({pr.d50_enrocado_pulg:.0f}\")"],
                 ["Enrocado — espesor de capa", f"≥ {pr.espesor_capa_m:.2f} m"]]
        if pr.prof_empotramiento_m is not None:
            filas.append(["Empotramiento del pie (bajo socavación)",
                          f"{pr.prof_empotramiento_m:.2f} m bajo el fondo"])
        if pr.cota_dique_sobre_fondo_m is not None:
            filas.append(["Corona de dique / defensivo",
                          f"{pr.cota_dique_sobre_fondo_m:.2f} m sobre el fondo "
                          f"(NAME + {pr.borde_libre_dique_m:.2f} m)"])
        if pr.espigon_long_m is not None:
            filas.append(["Espigones — longitud / separación",
                          f"{pr.espigon_long_m:.1f} m / {pr.espigon_separacion_m:.1f} m"])
        story.append(_tabla(filas, col_widths=[8.0*cm, 6.5*cm],
                            primera_col_izq=True))
        for rec in pr.recomendaciones:
            _p(story, st, "• " + rec)


def _sec_alcantarillas(story, st, R):
    """§15.9 — Drenaje vial menor: diseño de alcantarilla (FHWA HDS-5).

    Segundo capítulo de la hidráulica fluvial. Solo se emite cuando el tipo de
    obra es «drenaje vial menor» y el pipeline produjo el dimensionamiento.
    """
    alc = getattr(R, "alcantarillas", None)
    if alc is None:
        return
    _n = "15" if _riesgo_abc_activo(R) else "14"

    story.append(PageBreak())
    _p(story, st, f"{_n}.9 Drenaje vial menor — diseño de alcantarilla",
       "h3")
    _modo = getattr(alc, "modo", "auto")
    if _modo == "fijo":
        _p(story, st,
           "A partir del caudal de diseño se <b>verifica la alcantarilla de "
           "sección adoptada por el proyectista</b> con la metodología "
           "<b>FHWA HDS-5</b> (adoptada por el Manual de Hidrología y Drenaje "
           "del MOPSV/ABC): la carga a la entrada HW se calcula como el "
           "<b>máximo entre el control de entrada y el control de salida</b> y "
           f"se contrasta con el criterio <b>HW/D ≤ {alc.criterio_hw_d:.1f}</b> "
           "(ABC), para el caudal de diseño y el de verificación.")
    else:
        _p(story, st,
           "A partir del caudal de diseño calculado en el estudio hidrológico "
           "se dimensiona la <b>alcantarilla de drenaje transversal</b> de la "
           "vía. El cálculo sigue la metodología <b>FHWA HDS-5</b> "
           "(<i>Hydraulic Design of Highway Culverts</i>), adoptada por el "
           "Manual de Hidrología y Drenaje del MOPSV/ABC: para cada tamaño "
           "comercial se calcula la carga a la entrada HW como el <b>máximo "
           "entre el control de entrada y el control de salida</b>, y se sube "
           "por la lista de tamaños hasta cumplir el criterio de carga "
           f"admisible <b>HW/D ≤ {alc.criterio_hw_d:.1f}</b> (ABC). Se comparan "
           "tres tipos de obra y se recomienda el de menor área que cumple.")

    # Parámetros de diseño.
    _p(story, st, f"{_n}.9.1 Parámetros y caudales de diseño", "h3")
    par = [["Parámetro", "Valor"]]
    _fq = getattr(alc, "fuente_q", "interno (HEC-HMS)")
    par.append([f"Caudal de diseño Q(T={alc.T_diseno})",
                f"{alc.Q_diseno_m3s:.2f} m³/s ({_fq})"])
    if alc.Q_verif_m3s:
        par.append([f"Caudal de verificación Q(T={alc.T_verif})",
                    f"{alc.Q_verif_m3s:.2f} m³/s"])
    par.append(["Pendiente de diseño So", f"{alc.pendiente_pct:.2f} %"])
    par.append(["Longitud de la obra L", f"{alc.long_m:.1f} m (provisional)"])
    _ftw = getattr(alc, "fuente_tw", "por defecto")
    par.append(["Tirante aguas abajo TW",
                ("descarga libre" if alc.tw_m <= 0
                 else f"{alc.tw_m:.2f} m ({_ftw})")])
    par.append(["Criterio de carga HW/D", f"≤ {alc.criterio_hw_d:.1f}"])
    par.append(["Velocidad admisible (salida)",
                f"{alc.v_admisible_ms:.1f} m/s"])
    story.append(_tabla(par, col_widths=[9 * cm, 7 * cm],
                        primera_col_izq=True))

    # Comparación de tipos (diseño T de diseño) o sección adoptada (modo fijo).
    _titulo_92 = (f"{_n}.9.2 Sección adoptada (verificación con Q de diseño)"
                  if _modo == "fijo"
                  else f"{_n}.9.2 Comparación de alternativas (Q de diseño)")
    _p(story, st, _titulo_92, "h3")
    fil = [["Tipo de obra", "Sección", "Área\n(m²)", "HW/D", "Control",
            "V salida\n(m/s)", "Cumple"]]
    for c in alc.por_tipo:
        fil.append([c.nombre, c.designacion, f"{c.area_total_m2:.2f}",
                    f"{c.HW_D:.2f}", c.control,
                    f"{c.V_ms:.2f}", "Sí" if c.cumple else "No"])
    story.append(_tabla(fil, col_widths=[4.3*cm, 2.6*cm, 1.7*cm, 1.5*cm,
                                         2.2*cm, 1.9*cm, 1.6*cm],
                        primera_col_izq=True))

    # Recomendación.
    rec = alc.recomendada
    if rec is not None:
        _p(story, st, f"{_n}.9.3 Alternativa recomendada", "h3")
        _obs = ("; ".join(rec.obs) if rec.obs else "sin observaciones")
        _p(story, st,
           f"Se recomienda <b>{rec.nombre} {rec.designacion}</b> "
           f"(área hidráulica {rec.area_total_m2:.2f} m²), que satisface el "
           f"caudal de diseño con <b>HW/D = {rec.HW_D:.2f}</b> bajo control de "
           f"<b>{rec.control}</b> y una velocidad de salida de "
           f"<b>{rec.V_ms:.2f} m/s</b>. Es la de menor sección entre las que "
           f"cumplen el criterio ABC. Observaciones: {_obs}.")

    # Verificación con el caudal de crecida.
    ver = alc.verificacion
    if ver is not None:
        _p(story, st, f"{_n}.9.4 Verificación con crecida "
           f"(T={alc.T_verif})", "h3")
        _estado = ("no desborda la rasante" if ver.HW_D <= 1.5
                   else "la carga supera 1.5·D: revisar la cota de rasante y "
                        "el borde libre del terraplén")
        _p(story, st,
           f"Con el caudal de verificación Q(T={alc.T_verif}) = "
           f"{alc.Q_verif_m3s:.2f} m³/s, la sección recomendada "
           f"({ver.designacion}) trabaja con <b>HW/D = {ver.HW_D:.2f}</b> "
           f"(control de {ver.control}, V = {ver.V_ms:.2f} m/s): {_estado}.")

    # Perfil hidráulico (curva de remanso) — tirantes de control.
    perf = getattr(alc, "perfil", None)
    if perf:
        _p(story, st, f"{_n}.9.5 Modelo hidráulico y perfil de remanso", "h3")
        _p(story, st,
           "Perfil de la lámina de agua a lo largo de la obra (enfoque "
           f"FHWA HDS-5), bajo <b>control de {perf['control']}</b>. Se reportan "
           "los tirantes en los puntos de control: pozo aguas arriba (antes), "
           "a la entrada del barril, a la salida y aguas abajo (TW).")
        pf = [["Punto de control", "Tirante (m)"]]
        pf.append(["Antes — pozo aguas arriba (carga HW)",
                   f"{perf['hw_pozo_m']:.2f}"])
        pf.append(["A la entrada del barril", f"{perf['y_entrada_m']:.2f}"])
        pf.append(["En el barril (tirante normal)", f"{perf['yn_m']:.2f}"])
        pf.append(["A la salida del barril", f"{perf['y_salida_m']:.2f}"])
        pf.append(["Aguas abajo (TW)", f"{perf['tw_m']:.2f}"])
        pf.append(["Tirante crítico dc", f"{perf['dc_m']:.2f}"])
        story.append(_tabla(pf, col_widths=[10 * cm, 6 * cm],
                            primera_col_izq=True))
        if perf.get("salto_hidraulico"):
            _p(story, st,
               "<b>Advertencia:</b> con el tirante aguas abajo mayor que el "
               "crítico y flujo supercrítico en el barril, puede formarse un "
               "<b>resalto hidráulico</b> cerca de la salida; verificar la "
               "protección y la posición del resalto.", "cuerpo")
        _graf = getattr(R, "graficos", {}) or {}
        if _graf.get("alc_perfil"):
            story.append(_figura(_graf["alc_perfil"], ancho_cm=15))

    # Curva de funcionamiento (rating curve) para caudales crecientes.
    curva = getattr(alc, "curva_funcionamiento", None)
    if curva:
        _p(story, st, f"{_n}.9.6 Curva de funcionamiento (crecidas mayores)",
           "h3")
        _p(story, st,
           "Comportamiento de la obra ante caudales crecientes: carga relativa "
           "HW/D, tipo de control y velocidad de salida. Permite anticipar a "
           "partir de qué caudal la obra empieza a trabajar sumergida "
           "(HW/D &gt; 1.5) o requiere revisar la rasante.")
        _graf = getattr(R, "graficos", {}) or {}
        if _graf.get("alc_curva"):
            story.append(_figura(_graf["alc_curva"], ancho_cm=15))
        cf = [["Q (m³/s)", "HW/D", "Control", "V salida (m/s)", "Estado"]]
        for f in curva:
            cf.append([f"{f['Q_m3s']:.1f}", f"{f['HW_D']:.2f}", f["control"],
                       f"{f['V_ms']:.2f}",
                       "Desborda" if f["desborda"] else "OK"])
        story.append(_tabla(cf, col_widths=[2.8*cm, 2.4*cm, 3.6*cm, 3.6*cm,
                                            3.0*cm], primera_col_izq=True))

    # Socavación local y protección a la salida.
    prot = getattr(alc, "proteccion_salida", None)
    if prot:
        _p(story, st, f"{_n}.9.7 Socavación y protección a la salida", "h3")
        _p(story, st,
           "La velocidad a la salida genera socavación local en el cauce "
           "receptor. Se recomienda un <b>delantal de enrocado</b> "
           "dimensionado por Isbash y su longitud según HEC-14 (preliminar).")
        pr = [["Parámetro", "Valor"]]
        pr.append(["Velocidad de salida",
                   f"{prot['velocidad_salida_ms']:.2f} m/s"])
        pr.append(["Número de Froude a la salida",
                   f"{prot['froude_salida']:.2f}"])
        pr.append(["D50 del enrocado (Isbash)",
                   f"{prot['d50_enrocado_m']:.2f} m "
                   f"(≈ {prot['d50_enrocado_pulg']:.0f}\")"])
        pr.append(["Espesor de la capa", f"{prot['espesor_capa_m']:.2f} m"])
        pr.append(["Longitud del delantal (HEC-14)",
                   f"{prot['long_delantal_m']:.1f} m"])
        pr.append(["¿Requiere disipador?",
                   "Sí" if prot["requiere_disipador"] else "No"])
        story.append(_tabla(pr, col_widths=[9 * cm, 7 * cm],
                            primera_col_izq=True))
        _p(story, st, prot["nota"], "cuerpo")

    # Contraste con el modelo HEC-RAS del usuario (si se aportó).
    cc = getattr(alc, "contraste_hecras", None)
    if cc:
        _p(story, st, f"{_n}.9.8 Contraste con la modelación HEC-RAS", "h3")
        cfil = [["Variable", "Valor"]]
        if cc.get("q_hecras_m3s"):
            cfil.append(["Caudal pico HEC-RAS",
                         f"{cc['q_hecras_m3s']:.1f} m³/s"])
        if cc.get("q_interno_25_m3s"):
            cfil.append(["Caudal interno Q(25) (HEC-HMS)",
                         f"{cc['q_interno_25_m3s']:.1f} m³/s"])
        if cc.get("wse_max_m") == cc.get("wse_max_m"):
            cfil.append(["Nivel de agua (WSE) máx. HEC-RAS",
                         f"{cc['wse_max_m']:.2f} m"])
        if cc.get("vel_max_ms") == cc.get("vel_max_ms"):
            cfil.append(["Velocidad máx. HEC-RAS",
                         f"{cc['vel_max_ms']:.2f} m/s"])
        if cc.get("tw_hecras_m"):
            cfil.append(["Tirante de descarga (TW) desde HEC-RAS",
                         f"{cc['tw_hecras_m']:.2f} m"])
        if cc.get("seccion_critica"):
            cfil.append(["Sección más desfavorable (HEC-RAS)",
                         str(cc["seccion_critica"])])
        story.append(_tabla(cfil, col_widths=[9 * cm, 7 * cm],
                            primera_col_izq=True))
        _p(story, st,
           "El caudal de diseño y/o el tirante de descarga de esta alcantarilla "
           "se tomaron de la modelación HEC-RAS aportada por el proyectista; "
           "los valores internos (HEC-HMS) se muestran como contraste "
           "independiente. Ver también la Sección "
           f"{_n}.10 (resultados HEC-RAS).")

    # Notas y limitaciones.
    if alc.notas:
        _p(story, st, "<b>Notas y limitaciones del dimensionamiento:</b>",
           "cuerpo")
        for nt in alc.notas:
            _p(story, st, f"• {nt}", "cuerpo")
    _p(story, st,
       "<i>Alcance:</i> es un predimensionamiento hidráulico. El diseño "
       "definitivo requiere la geometría vial (ancho de plataforma, taludes y "
       "cota de rasante) para fijar la longitud real de la obra, el tirante "
       "aguas abajo del cauce receptor, y el diseño estructural y de las obras "
       "de entrada/salida (aletas, disipador y enrocado de protección).",
       "italica")


def _sec_hecras(story, st, R):
    """§15.10 — Validación/uso de resultados reales de HEC-RAS.

    Solo se emite cuando el usuario aportó el HDF de un plan HEC-RAS ya
    calculado (leído por ras-commander / h5py)."""
    res = getattr(R, "hecras_resultados", None)
    if res is None:
        return
    _n = "15" if _riesgo_abc_activo(R) else "14"
    story.append(PageBreak())
    _p(story, st, f"{_n}.10 Modelación hidráulica HEC-RAS (resultados reales)",
       "h3")
    _p(story, st,
       "El proyectista aportó los resultados de un modelo <b>HEC-RAS</b> ya "
       "calculado; HYDROFRA los leyó directamente del archivo HDF del plan "
       f"(backend <b>{res.fuente}</b>, {res.n_secciones} secciones "
       "transversales) para respaldar el cálculo hidráulico con la modelación "
       "hidrodinámica del especialista, en vez de depender solo del cálculo "
       "1D interno de tirante normal.")

    fil = [["Variable (máximos del plan)", "Valor"]]
    fil.append(["Nivel de agua (WSE) máximo",
                f"{res.wse_max_global_m:.2f} m"])
    fil.append(["Velocidad total máxima",
                f"{res.vel_max_global_ms:.2f} m/s"])
    fil.append(["Caudal máximo simulado",
                f"{res.flow_max_global_m3s:.1f} m³/s"])
    story.append(_tabla(fil, col_widths=[9 * cm, 7 * cm],
                        primera_col_izq=True))

    sc = res.seccion_critica()
    if sc is not None:
        _p(story, st,
           f"<b>Sección más desfavorable:</b> {sc.river} / {sc.reach}, "
           f"progresiva {sc.station} ({sc.name}) — WSE "
           f"{sc.wse_max_m:.2f} m, velocidad {sc.vel_total_max_ms:.2f} m/s, "
           f"caudal {sc.flow_max_m3s:.1f} m³/s.")

    # Comparación con el tirante 1D interno, si existe.
    tir = getattr(R, "tirante", None)
    if tir is not None:
        _y = getattr(tir, "tirante_verif_m", None) or \
            getattr(tir, "tirante_control_m", None)
        _v = getattr(tir, "velocidad_verif_ms", None) or \
            getattr(tir, "velocidad_media_ms", None)
        if _y or _v:
            _p(story, st,
               "<b>Contraste con el cálculo 1D interno:</b> el tirante normal "
               f"de HYDROFRA estimó "
               f"{('un calado de %.2f m' % _y) if _y else ''}"
               f"{(' y una velocidad de %.2f m/s' % _v) if _v else ''}. "
               "Las diferencias con HEC-RAS provienen de que la modelación del "
               "especialista resuelve el flujo gradualmente variado con la "
               "geometría real de las secciones y las condiciones de frontera "
               "adoptadas; para el diseño se adoptan los resultados de "
               "HEC-RAS.")
    _p(story, st,
       "<i>Nota:</i> HYDROFRA lee los resultados del HDF pero no ejecuta el "
       "motor HEC-RAS; la modelación es responsabilidad del proyectista, que "
       "debe adjuntar el proyecto HEC-RAS al expediente.", "italica")


def _sec_riego(story, st, R):
    """Hidráulica fluvial y obras de captación para riego menor. Solo cuando el
    tipo de obra es «riego pequeño-mediano» y el pipeline produjo el diseño."""
    rg = getattr(R, "riego", None)
    if rg is None:
        return
    _n = _n_riego(R)
    story.append(PageBreak())
    _p(story, st, f"{_n}. Hidráulica fluvial y obras de captación (riego menor)",
       "h2")

    # Objetivos del estudio hidráulico.
    _p(story, st, f"{_n}.1 Objetivos del estudio hidráulico", "h3")
    _p(story, st,
       "• Determinar los niveles de agua para la captación (disponibilidad en "
       "estiaje y verificación en crecida).<br/>"
       "• Evaluar la estabilidad del cauce y la erosión en el sitio de la "
       "toma.<br/>"
       "• Dimensionar las obras de captación y conducción y sus protecciones.")

    # Modelación hidráulica.
    _p(story, st, f"{_n}.2 Modelación hidráulica", "h3")
    _p(story, st,
       f"Caudal de captación (demanda) <b>Q = {rg.q_captacion_m3s*1000:.0f} "
       f"l/s</b> ({rg.q_captacion_m3s:.3f} m³/s), obtenido "
       f"<b>{rg.fuente_q}</b>"
       + (f" (área {rg.area_ha:g} ha × módulo {rg.modulo_ls_ha:g} l/s/ha)"
          if rg.fuente_q.startswith("área") else "") + ". "
       + (f"Caudal de crecida de diseño del río Q = {rg.q_crecida_m3s:.1f} "
          "m³/s (del análisis hidrológico). " if rg.q_crecida_m3s else "")
       + "La modelación hidrodinámica de detalle (perfiles, velocidades y "
       "zonas de erosión/sedimentación) se realiza en <b>HEC-RAS</b> con las "
       "secciones levantadas en campo; este informe aporta el "
       "predimensionamiento hidráulico de las obras.")

    # Balance oferta (estiaje del módulo Qmín) – demanda (captación).
    bal = getattr(rg, "balance", None)
    if bal is not None:
        _p(story, st,
           "<b>Disponibilidad hídrica y balance oferta–demanda.</b> La oferta "
           "en estiaje proviene del estudio de caudales mínimos (Q95 / Q7,10); "
           "se reserva un caudal ecológico antes de comparar con la demanda de "
           "captación.", "cuerpo")
        fb = [["Concepto", "Caudal (l/s)"]]
        fb.append(["Oferta en estiaje (Q95/Q7,10)",
                   f"{bal['q_estiaje_m3s']*1000:.0f}"])
        fb.append(["Caudal ecológico reservado (10 %)",
                   f"{bal['q_ecologico_m3s']*1000:.0f}"])
        fb.append(["Oferta disponible para captación",
                   f"{bal['q_disponible_m3s']*1000:.0f}"])
        fb.append(["Demanda de captación", f"{bal['q_demanda_m3s']*1000:.0f}"])
        fb.append(["Cobertura de la demanda", f"{bal['cobertura_pct']:.0f} %"])
        if bal["deficit_m3s"] > 0:
            fb.append(["Déficit", f"{bal['deficit_m3s']*1000:.0f}"])
        story.append(_tabla(fb, col_widths=[10 * cm, 6 * cm],
                            primera_col_izq=True))
        _p(story, st, f"<b>Veredicto: {bal['veredicto']}.</b> {bal['mensaje']}",
           "cuerpo")
    else:
        _p(story, st,
           "<i>Balance oferta–demanda pendiente:</i> ingresar el caudal de "
           "estiaje disponible (Q95 / Q7,10) del estudio de caudales mínimos "
           "para verificar que la oferta cubre la demanda de captación.",
           "italica")

    # Ubicación de la toma de agua.
    _p(story, st, f"{_n}.3 Ubicación de la toma de agua", "h3")
    _p(story, st,
       "Criterios técnicos para la ubicación: estabilidad del cauce (tramo "
       "recto, lecho firme), accesibilidad, cota de captación que garantice el "
       "mando sobre el área de riego, y una hidrodinámica local favorable "
       "(evitar zonas de sedimentación; aprovechar la orilla exterior de las "
       "curvas para la toma). "
       + (f"Cota de captación indicada: {rg.cota_captacion}."
          if rg.cota_captacion else
          "La cota de captación se define con la topografía del sitio."))

    # Diseño de obras hidráulicas.
    _p(story, st, f"{_n}.4 Diseño de obras hidráulicas", "h3")

    # 6.a Bocatoma (tres alternativas).
    _p(story, st, "<b>a) Bocatoma de captación — alternativas</b>", "cuerpo")
    for b in (rg.bocatomas or []):
        _p(story, st, f"<b>{b.nombre}.</b> {b.descripcion}", "cuerpo")
        fil = [["Parámetro", "Valor"]]
        for k, v in b.parametros.items():
            fil.append([k.replace("_", " "), f"{v}"])
        story.append(_tabla(fil, col_widths=[9 * cm, 7 * cm],
                            primera_col_izq=True))

    # 6.b Desarenador.
    d = rg.desarenador
    if d is not None:
        _p(story, st, "<b>b) Desarenador</b>", "cuerpo")
        fd = [["Parámetro", "Valor"]]
        fd.append(["Partícula de diseño d", f"{d.d_particula_mm:.2f} mm"])
        fd.append(["Velocidad de sedimentación vs",
                   f"{d.vs_sedim_ms*100:.2f} cm/s"])
        fd.append(["Velocidad horizontal vh", f"{d.vh_horizontal_ms:.2f} m/s"])
        fd.append(["Profundidad", f"{d.profundidad_m:.2f} m"])
        fd.append(["Ancho", f"{d.ancho_m:.2f} m"])
        fd.append(["Longitud", f"{d.longitud_m:.2f} m"])
        fd.append(["Tiempo de retención", f"{d.tiempo_retencion_s:.0f} s"])
        story.append(_tabla(fd, col_widths=[9 * cm, 7 * cm],
                            primera_col_izq=True))
        for o in d.obs:
            _p(story, st, f"• {o}", "cuerpo")

    # 6.c Canal de conducción.
    c = rg.canal
    if c is not None:
        _p(story, st, "<b>c) Canal de conducción</b>", "cuerpo")
        fc = [["Parámetro", "Valor"]]
        fc.append(["Forma / talud", f"{c.forma} (z = {c.talud_z:g})"])
        fc.append(["n de Manning", f"{c.n_manning:.3f}"])
        fc.append(["Pendiente So", f"{c.So*100:.3f} %"])
        fc.append(["Base b", f"{c.base_b_m:.2f} m"])
        fc.append(["Tirante y", f"{c.tirante_y_m:.2f} m"])
        fc.append(["Bordo libre", f"{c.bordo_libre_m:.2f} m"])
        fc.append(["Alto total", f"{c.alto_total_m:.2f} m"])
        fc.append(["Velocidad", f"{c.velocidad_ms:.2f} m/s "
                   f"(adm. {c.v_adm_min_ms:.2f}–{c.v_adm_max_ms:.2f})"])
        fc.append(["Froude", f"{c.froude:.2f}"])
        story.append(_tabla(fc, col_widths=[9 * cm, 7 * cm],
                            primera_col_izq=True))
        for o in c.obs:
            _p(story, st, f"• {o}", "cuerpo")

    # 6.d Obras de arte y protección de márgenes.
    pm = rg.proteccion_margenes
    if pm is not None:
        _p(story, st, "<b>d) Protección de márgenes</b>", "cuerpo")
        fp = [["Parámetro", "Valor"]]
        fp.append(["Velocidad del río (crecida)",
                   f"{pm['velocidad_rio_ms']:.2f} m/s"])
        fp.append(["D50 del enrocado (Isbash)",
                   f"{pm['d50_enrocado_m']:.2f} m (≈ {pm['d50_enrocado_pulg']:.0f}\")"])
        fp.append(["Espesor de la capa", f"{pm['espesor_enrocado_m']:.2f} m"])
        story.append(_tabla(fp, col_widths=[9 * cm, 7 * cm],
                            primera_col_izq=True))
        _p(story, st, pm["recomendacion"], "cuerpo")
    _p(story, st,
       "Obras de arte de la conducción (alcantarillas, sifones y estructuras "
       "de cruce): se dimensionan en el módulo de drenaje vial menor con los "
       "caudales interceptados por el canal.", "cuerpo")

    if rg.notas:
        _p(story, st, "<b>Notas y limitaciones:</b>", "cuerpo")
        for nt in rg.notas:
            _p(story, st, f"• {nt}", "cuerpo")


def _sec_conclusiones(story, st, R):
    story.append(PageBreak())
    _n = str((16 if _riesgo_abc_activo(R) else 15) + _off_riego(R))
    _p(story, st, f"{_n}. Conclusiones y recomendaciones", "h2")
    _p(story, st,
       "Esta sección resume el análisis hidrológico de caudales máximos "
       "realizado para el sitio. Para facilitar la lectura ejecutiva, los "
       "resultados se presentan agrupados por bloque temático siguiendo "
       "el mismo orden del informe: datos y series, modelos IDF, "
       "morfometría de la cuenca, tiempo de concentración, caudales "
       "máximos por métodos directos, hietogramas de diseño y modelación "
       "HEC-HMS. Cada bloque incluye los valores numéricos clave para el "
       "período de retorno de diseño y remite a la sección donde el "
       "lector encontrará el cálculo completo.")

    # ---- 14.1 Datos y fuentes (Sección 1-Sección 5) ----
    _p(story, st, f"{_n}.1 Datos y fuentes de información (Sección 1–Sección 5)", "h3")
    bullets = [
        f"<b>Estación de referencia:</b> {R.estacion.codigo} — "
        f"{R.estacion.nombre}, a {R.dist_km:.1f} km del sitio (vecino más "
        f"cercano del catálogo SENAMHI).",
        f"<b>Fuente de datos adoptada:</b> {R.decision.fuente_adoptada}. "
        f"{R.decision.justificacion}",
        f"<b>Distribución estadística adoptada:</b> {R.mejor_ajuste.nombre} "
        f"(test KS p = {R.mejor_ajuste.ks_pvalor:.3f}, "
        f"{'aceptada' if R.mejor_ajuste.aceptada_ks else 'no aceptada'} al 5%).",
        f"<b>Precipitación de diseño:</b> P24 para T = {R.T_diseno} años "
        f"= {(R.p24_diseno_mm or 0):.1f} mm.",
    ]
    cr = getattr(R, "correccion_regional", None)
    if cr:
        bullets.append(
            f"<b>Corrección de piso regional:</b> el P24(100) satelital "
            f"({cr['p24_100_observado']:.0f} mm) caía bajo el rango físico de "
            f"«{cr['region']}» ({cr['rango_mm'][0]:.0f}–{cr['rango_mm'][1]:.0f} "
            f"mm); se escaló la serie ×{cr['factor']:.2f} hasta el piso "
            f"regional ({cr['p24_100_corregido']:.0f} mm) para no subestimar "
            f"los caudales (Sección 6).")
    hd = getattr(R, "hec_duracion_min", None)
    if hd:
        bullets.append(
            f"<b>Tormenta de diseño HEC-HMS:</b> {hd/60:.0f} h con "
            f"distribución SCS Tipo II (TR-55), estándar para el par SCS-CN + "
            f"HU SCS; garantiza escorrentía representativa en todos los "
            f"períodos de retorno (Sección 13).")
    for b in bullets:
        _p(story, st, "• " + b)

    # ---- 14.2 Modelos IDF (Sección 6-Sección 8) ----
    _p(story, st, f"{_n}.2 Modelos IDF y desagregación (Sección 6–Sección 8)", "h3")
    mm = R.modelo_recomendado
    _p(story, st,
       f"• <b>Modelo IDF recomendado</b> (resolución «{R.resolucion_datos}»): "
       f"<b>{mm.nombre}</b>, R² = {mm.r2:.4f}, RMSE = {mm.rmse_mm_h:.3f} mm/h. "
       f"Ecuación: <i>{mm.ecuacion}</i>. {R.justificacion_modelo}")
    _p(story, st,
       f"• <b>Desagregación temporal</b> por Dyck-Peschke (exponente "
       f"{R.exp_dp:.2f}); IDF Sherman ajustado en {len(R.idf_largo)} "
       f"combinaciones (T, duración).")

    # ---- 14.3 Morfometría y cartografía (Sección 9) ----
    A = getattr(R, "analisis_morf", None)
    if A is not None:
        _p(story, st, f"{_n}.3 Cartografía y morfometría de la cuenca (Sección 9)", "h3")
        cn_show = R.cn_ponderado or A.cn
        c_txt = (f", C ponderado = {R.c_ponderado:.2f}"
                 if getattr(R, "c_ponderado", None) else "")
        ce_txt = (f", C del evento de diseño = {R.c_evento:.2f}"
                  if getattr(R, "c_evento", None) else "")
        _p(story, st,
           f"• <b>Delineación:</b> cuenca real obtenida por watershed D8 sobre "
           f"<b>MERIT Hydro 90 m</b> desde el punto, sin uso de subcuencas "
           f"predefinidas. Polígono y atributos en Sección 9.1.")
        _p(story, st,
           f"• <b>Geometría:</b> A = {A.area_km2:.2f} km², P = "
           f"{A.perimetro_km:.2f} km, Lc (D8) = "
           f"{A.long_cauce_principal_km:.2f} km, Lb = "
           f"{A.long_axial_km:.2f} km. Relieve: Hmax = {A.cota_mayor_m:.0f} m, "
           f"Hmin = {A.cota_menor_m:.0f} m, ΔH = {A.desnivel_m:.0f} m.")
        _p(story, st,
           f"• <b>Pendientes:</b> media de la cuenca {A.pendiente_cuenca_pct:.1f}% "
           f"({A.pendiente_cuenca_grados:.1f}°, {A.interp_pendiente}); del "
           f"cauce {A.pendiente_cauce_pct:.2f}%.")
        _p(story, st,
           f"• <b>Forma:</b> {A.clase_forma} — Kc = {A.kc_gravelius:.2f} "
           f"(Gravelius), Ff = {A.ff_horton:.3f} (Horton), Re = "
           f"{A.re_elongacion:.2f}, Rc = {A.rc_circularidad:.2f}.")
        _p(story, st,
           f"• <b>Red de drenaje:</b> orden de Strahler ω = {A.orden_max}, "
           f"Rb = {A.relacion_bifurcacion:.1f}, N = {A.n_corrientes} cauces; "
           f"densidad Dd = {A.densidad_drenaje_km_km2:.2f} km/km² "
           f"({A.interp_dd}); sinuosidad = {A.sinuosidad:.2f}.")
        _p(story, st,
           f"• <b>Hipsometría:</b> HI = {A.integral_hipsometrica:.2f} → "
           f"<b>{A.estado_cuenca.split('(')[0].strip().lower()}</b>; cota "
           f"media {A.cota_media_m:.0f} m.")
        _p(story, st,
           f"• <b>Cobertura y suelos:</b> CN ponderado (MapBiomas, mapa 9.5) "
           f"= <b>{cn_show:.0f}</b>{c_txt}{ce_txt}.")
        ia = getattr(R, "inund_area_alta_pct", None)
        if ia is not None:
            hm = getattr(R, "hand_medio_m", None)
            hm_txt = (f"; HAND medio de la cuenca = {hm:.1f} m" if hm
                      else "")
            if ia >= 25:
                interp = ("planicies inundables extensas próximas al cauce → "
                          "exigen gálibo/borde libre holgado y protección de "
                          "márgenes")
            elif ia >= 10:
                interp = ("franjas inundables moderadas a lo largo del cauce → "
                          "verificar el resguardo hidráulico en el cruce")
            else:
                interp = ("valle encajado con escasa planicie inundable → "
                          "el riesgo de anegamiento lateral es bajo")
            _p(story, st,
               f"• <b>Susceptibilidad a la inundación</b> (mapa 9.9, índice "
               f"HAND + agua permanente JRC): <b>{ia:.1f} %</b> del área de "
               f"la cuenca está en clase alta/muy alta (terreno a ≤ 5 m sobre "
               f"el cauce más cercano){hm_txt}. Interpretación: {interp}.")

    # ---- 14.4 Tiempo de concentración (Sección 10) ----
    _p(story, st, f"{_n}.4 Tiempo de concentración (Sección 10)", "h3")
    tc = R.tc_adoptado
    _p(story, st,
       f"• <b>Tc adoptado:</b> <b>{tc.tc_min:.0f} min</b> "
       f"({tc.tc_horas:.2f} h) por promedio depurado (Tukey-IQR) de "
       f"{tc.n_usadas} fórmulas: {', '.join(tc.usadas)}.")
    if tc.descartadas:
        _p(story, st,
           f"• <b>Descartadas:</b> {', '.join(tc.descartadas)} "
           f"(no aplicables por área/forma).")
    _p(story, st,
       f"• <b>Trazabilidad:</b> todas las fórmulas se evaluaron con los "
       f"parámetros reales de la Sección 9 (Lc D8, ΔH del DEM, S = ΔH/Lc, CN "
       f"ponderado), no por ley de Hack ni con CN modal.")

    # ---- 14.5 Caudales máximos por métodos directos (Sección 11) ----
    qmax = getattr(R, "qmax_tabla", None)
    if qmax is not None and len(qmax):
        _p(story, st, f"{_n}.5 Caudales máximos por métodos directos (Sección 11)", "h3")
        fila_T = qmax.loc[qmax["T_anios"] == R.T_diseno]
        if len(fila_T):
            f = fila_T.iloc[0]
            _p(story, st,
               f"• Para <b>T = {R.T_diseno} años</b> (P24 = "
               f"{f['P24_mm']:.0f} mm, i(t=Tc) = {f['i_Tc_mm_h']:.1f} mm/h) "
               f"los caudales por método son: Racional = "
               f"{f['Q_racional']:.0f}, Racional Mod. (Témez) = "
               f"{f['Q_racional_mod']:.0f}, Mac Math = "
               f"{f['Q_mac_math']:.0f}, SCS HU = {f['Q_scs']:.0f}, "
               f"Verni-King = {f['Q_verni_king']:.0f} m³/s. "
               f"<b>Q mediana = {f['Q_mediana']:.0f} m³/s</b> "
               f"(adopción recomendada).")
        # Rango total Q 10000 vs Q 5
        try:
            q_10k = float(qmax.loc[qmax["T_anios"] == 10000,
                                    "Q_mediana"].iloc[0])
            q_5 = float(qmax.loc[qmax["T_anios"] == 5, "Q_mediana"].iloc[0])
            _p(story, st,
               f"• <b>Rango de Q mediana</b>: {q_5:.0f} m³/s (T = 5 a) → "
               f"{q_10k:.0f} m³/s (T = 10000 a), factor de amplificación "
               f"{q_10k/q_5 if q_5 else 0:.1f}×.")
        except Exception:  # noqa: BLE001
            pass

    # ---- 14.6 Hietogramas de diseño (Sección 12) ----
    _p(story, st, f"{_n}.6 Hietogramas de diseño (Sección 12)", "h3")
    metodos_txt = ", ".join({"bloques": "Bloques alternos",
                              "scs": "SCS Tipo II", "chicago": "Chicago",
                              "huff": "Huff Q2"}.get(m, m)
                             for m in R.metodos_hieto)
    _p(story, st,
       f"• Se generaron hietogramas para los 9 períodos de retorno (5, 10, "
       f"25, 50, 100, 500, 1000, 5000 y 10000 años) con los métodos: "
       f"<b>{metodos_txt}</b>.")
    if R.aplica_huff:
        _p(story, st,
           f"• <b>Método de Huff (1967)</b> incluido por A = "
           f"{R.morfologia.area_km2:.2f} km² > 25 km².")
    h_d = R.hietogramas.get("bloques")
    if h_d:
        _p(story, st,
           f"• Para T = {R.T_diseno} años (bloques alternos): P total = "
           f"{h_d.p_total_mm:.0f} mm, i pico = {h_d.i_pico_mm_h:.0f} mm/h, "
           f"Δt = {h_d.delta_t_min:.0f} min, {h_d.n_bloques} bloques.")

    # ---- 14.7 Modelación HEC-HMS (Sección 13) ----
    H = getattr(R, "hec_hidrogramas_por_T", None) or {}
    p_hec = getattr(R, "hec_params", None)
    if p_hec and H:
        _p(story, st, f"{_n}.7 Modelación HEC-HMS (Sección 13)", "h3")
        nombres_h = {"bloques": "Bloques alternos", "scs": "SCS Tipo II",
                     "chicago": "Chicago", "huff": "Huff Q2"}
        _p(story, st,
           f"• <b>Hietograma seleccionado</b> para HEC-HMS: "
           f"<b>{nombres_h.get(R.hec_metodo_hieto, R.hec_metodo_hieto)}</b>. "
           f"{R.hec_justificacion}")
        _p(story, st,
           f"• <b>Modelo de pérdidas:</b> SCS Curve Number (CN = "
           f"{p_hec.cn:.0f}, S = {p_hec.S_ret_mm:.0f} mm, Ia = "
           f"{p_hec.Ia_mm:.1f} mm). <b>Transformación:</b> HU SCS Triangular "
           f"(lag = 0.6·Tc = {p_hec.lag_min:.0f} min).")
        r_d = H.get(R.T_diseno) or next(iter(H.values()))
        _p(story, st,
           f"• Para <b>T = {r_d.T_anios} años</b>: Q pico = "
           f"<b>{r_d.Q_pico_m3s:.0f} m³/s</b>, t pico = "
           f"{r_d.t_pico_min:.0f} min, volumen directo = "
           f"{r_d.volumen_directo_hm3:.2f} hm³, P = {r_d.P_total_mm:.0f} mm, "
           f"Pe = {r_d.Pe_total_mm:.0f} mm.")
        try:
            r_max = max(H.values(), key=lambda r: r.Q_pico_m3s)
            r_min = min(H.values(), key=lambda r: r.Q_pico_m3s)
            _p(story, st,
               f"• <b>Hidrogramas para los 9 T:</b> Q pico desde "
               f"{r_min.Q_pico_m3s:.0f} m³/s (T = {r_min.T_anios} a) hasta "
               f"<b>{r_max.Q_pico_m3s:.0f} m³/s</b> (T = {r_max.T_anios} a).")
        except Exception:  # noqa: BLE001
            pass

    # ---- 14.8 Recomendaciones y limitaciones ----
    _p(story, st, f"{_n}.8 Recomendaciones y limitaciones", "h3")
    _p(story, st,
       f"• <b>Caudal de diseño recomendado</b> para el dimensionamiento "
       f"hidráulico de la obra ({R.tipo_obra.nombre}, {R.tipo_obra.norma}): "
       f"adoptar el <b>caudal mediano entre los métodos de la Sección 11</b> y "
       f"verificar con el <b>hidrograma HEC-HMS</b> de la Sección 13 que el volumen "
       f"de tránsito esté en orden de magnitud comparable.")
    _p(story, st,
       "• <b>Auditoría:</b> el informe es trazable extremo a extremo — todos "
       "los parámetros de la Sección 11, Sección 12 y Sección 13 se calculan con los valores reales "
       "de la Sección 9 (cuenca delineada del DEM) y Sección 10 (Tc adoptado). La columna "
       "«Origen» de las tablas indica la sección de proveniencia de cada "
       "variable.")
    _p(story, st,
       "• <b>Limitaciones:</b> períodos de retorno extremos (T ≥ 1000 años) "
       "son extrapolaciones de la distribución ajustada; los métodos "
       "Mac Math y Verni-King son empíricos calibrados a regiones específicas "
       "(usar como referencia, no como único criterio); el HU SCS triangular "
       "no captura tormentas dobles. Para diseño definitivo se recomienda "
       "reproducir la simulación HEC-HMS standalone con los archivos "
       "Basin/Met/Control de la Sección 13.4.")
    _p(story, st,
       f"• <b>Bandera de morfología:</b> {'morfología real desde MERIT Hydro + DEM' if not getattr(R.morfologia, 'sintetica', True) else 'morfología sintética (Hack + rangos andinos) — VERIFICAR con DEM real antes del diseño definitivo'}.")

    # ---- Conclusiones de hidráulica fluvial y fundación del puente (Sección 14) ----
    tir_c = getattr(R, "tirante", None)
    if _es_obra_puente(R) and tir_c is not None:
        _p(story, st,
           f"{_n}.9 Hidráulica fluvial y fundación del puente (Sección 14)", "h3")
        _p(story, st,
           f"• <b>Nivel de agua (calado).</b> Con el caudal de la modelación "
           f"HEC-HMS Q(T = {tir_c.T_diseno}) el tirante máximo del tramo es "
           f"<b>{tir_c.tirante_max_m:.2f} m</b> (control {tir_c.tirante_control_m:.2f} m), "
           f"con régimen {tir_c.regimen_predominante or 'indeterminado'} "
           f"(Fr = {tir_c.froude_medio:.2f})."
           + (f" Para el caudal de verificación Q(T = {tir_c.T_verif}) el tirante "
              f"de control asciende a {tir_c.tirante_verif_m:.2f} m."
              if tir_c.tirante_verif_m is not None and tir_c.T_verif else "") +
           " La velocidad, el tirante y la socavación de ambos caudales se "
           "resumen en el cuadro de resultados finales de la Sección 14.5.")
        if (getattr(tir_c, "cota_viga_sobre_fondo_m", None) is not None
                and tir_c.verifica_viga_verif is not None and tir_c.T_verif):
            _p(story, st,
               f"• <b>Posición de la viga (concepto de cierre).</b> La cara "
               f"inferior de la viga se fija a <b>{tir_c.cota_viga_sobre_fondo_m:.2f} "
               f"m sobre el fondo</b> = NAME de diseño T{tir_c.T_diseno} "
               f"({tir_c.tirante_control_m:.2f} m) + gálibo normativo "
               f"{tir_c.galibo_m:.1f} m. La crecida de verificación "
               f"T{tir_c.T_verif} (tirante {tir_c.tirante_verif_m:.2f} m) "
               + (f"queda {tir_c.holgura_viga_verif_m:.2f} m por debajo de la "
                  f"viga → <b>VERIFICA</b>: no alcanza la superestructura."
                  if tir_c.verifica_viga_verif else
                  f"SUPERA la viga en {abs(tir_c.holgura_viga_verif_m):.2f} m "
                  f"→ <b>NO VERIFICA</b>: elevar la rasante o el gálibo.")
               )
        soc_c = getattr(tir_c, "socavacion", None)
        if soc_c is not None:
            comp = []
            if soc_c.socavacion_total_pila_m == soc_c.socavacion_total_pila_m:
                comp.append(f"pila central {soc_c.socavacion_total_pila_m:.2f} m")
            if soc_c.socavacion_total_estribo_m == soc_c.socavacion_total_estribo_m:
                comp.append(f"estribos {soc_c.socavacion_total_estribo_m:.2f} m")
            comp_txt = "; ".join(comp) if comp else \
                f"{soc_c.ys_general_m:.2f} m (descenso generalizado)"
            _p(story, st,
               f"• <b>Socavación y fundación.</b> La socavación total (general + "
               f"local) estimada con el caudal gobernante Q(T = {soc_c.T_anios}) es: "
               f"{comp_txt}. La <b>cota de desplante de la fundación debe ubicarse "
               f"al menos {soc_c.prof_cimentacion_recomendada_m:.2f} m por debajo del "
               f"fondo actual del cauce</b> (socavación total + resguardo de "
               f"{soc_c.resguardo_m:.1f} m), conforme al estado límite de evento "
               f"extremo de AASHTO LRFD. Pilotes o zapatas deben apoyarse por "
               f"debajo de esta línea de socavación.")
            _p(story, st,
               "• <b>Recomendaciones de fundación.</b> Verificar la socavación con "
               "la granulometría real del lecho (D50, D95) de un estudio de suelos; "
               "considerar la degradación a largo plazo y la posible migración del "
               "cauce (HEC-20); evaluar contramedidas de protección (enrocado según "
               "HEC-23, gaviones o encauzamiento) en pilas y estribos; y, para el "
               "diseño definitivo, contrastar con un modelo HEC-RAS de detalle con "
               "batimetría de campo.")
        ia = getattr(R, "inund_area_alta_pct", None)
        if ia is not None:
            hm = getattr(R, "hand_medio_m", None)
            hm_txt = (f" (HAND medio de la cuenca {hm:.1f} m)" if hm else "")
            if ia >= 25:
                accion = ("Por la amplitud de la planicie inundable se "
                          "recomienda longitud de puente suficiente para no "
                          "invadir el cauce de avenida, revancha (gálibo) en el "
                          "extremo superior del rango normativo y protección de "
                          "terraplenes de acceso y estribos contra el "
                          "desbordamiento lateral (encauzamiento / espigones).")
            elif ia >= 10:
                accion = ("Verificar que la longitud del vano y el gálibo "
                          "cubran la franja inundable identificada y proteger "
                          "los estribos y accesos en los tramos de HAND bajo "
                          "próximos al cauce.")
            else:
                accion = ("El valle es encajado y la planicie inundable es "
                          "reducida, por lo que el condicionante dominante es "
                          "la socavación local antes que el desborde lateral; "
                          "aun así, respetar el borde libre normativo sobre el "
                          "NAME.")
            _p(story, st,
               f"• <b>Riesgo de inundación del emplazamiento (mapa 9.9).</b> "
               f"El <b>{ia:.1f} %</b> del área de la cuenca presenta "
               f"susceptibilidad alta/muy alta a la inundación según el índice "
               f"HAND{hm_txt}. {accion}")

    # ---- Conclusiones de drenaje vial menor (alcantarillas) ----
    alc_c = getattr(R, "alcantarillas", None)
    if alc_c is not None and getattr(alc_c, "recomendada", None) is not None:
        _p(story, st, f"{_n}.9 Drenaje vial menor — alcantarilla (Sección "
                      f"{_n_hidraulica(R)}.9)", "h3")
        rc = alc_c.recomendada
        _modo = getattr(alc_c, "modo", "auto")
        _p(story, st,
           f"• <b>Obra {'adoptada' if _modo=='fijo' else 'recomendada'}.</b> "
           f"{rc.nombre} <b>{rc.designacion}</b> (área {rc.area_total_m2:.2f} "
           f"m²), que trabaja con <b>HW/D = {rc.HW_D:.2f}</b> bajo control de "
           f"{rc.control} para Q(T={alc_c.T_diseno}) = "
           f"{alc_c.Q_diseno_m3s:.2f} m³/s ({getattr(alc_c,'fuente_q','interno')})."
           + (f" Cumple el criterio HW/D ≤ {alc_c.criterio_hw_d:.1f} (ABC)."
              if rc.cumple else
              f" <b>No cumple</b> HW/D ≤ {alc_c.criterio_hw_d:.1f}: aumentar "
              "sección o número de celdas."))
        ver = getattr(alc_c, "verificacion", None)
        if ver is not None:
            _p(story, st,
               f"• <b>Verificación de crecida.</b> Con Q(T={alc_c.T_verif}) la "
               f"obra trabaja con HW/D = {ver.HW_D:.2f} "
               + ("(no desborda la rasante)." if ver.HW_D <= 1.5 else
                  "(&gt; 1.5·D: revisar la cota de rasante y el borde libre)."))
        ps = getattr(alc_c, "proteccion_salida", None)
        if ps is not None:
            _p(story, st,
               f"• <b>Socavación y protección a la salida.</b> Velocidad de "
               f"salida {ps['velocidad_salida_ms']:.2f} m/s (Fr = "
               f"{ps['froude_salida']:.2f}); se recomienda enrocado de "
               f"protección con D50 ≈ {ps['d50_enrocado_m']:.2f} m y delantal "
               f"de {ps['long_delantal_m']:.1f} m"
               + (", además de cuenco disipador." if ps['requiere_disipador']
                  else "."))
        _p(story, st,
           "• <b>Recomendaciones.</b> Fijar la longitud real de la obra y el "
           "tirante aguas abajo con la geometría vial y el cauce receptor; "
           "verificar el arrastre de sedimentos y palizada a la entrada; para "
           "el diseño definitivo, contrastar con un modelo HEC-RAS de la "
           "alcantarilla.")

    # ---- Conclusiones de captación de riego menor ----
    rg_c = getattr(R, "riego", None)
    if rg_c is not None:
        _p(story, st, f"{_n}.9 Hidráulica fluvial y captación para riego "
                      f"(Sección {_n_riego(R)})", "h3")
        _p(story, st,
           f"• <b>Caudal de captación.</b> Q = {rg_c.q_captacion_m3s*1000:.0f} "
           f"l/s ({rg_c.q_captacion_m3s:.3f} m³/s), obtenido {rg_c.fuente_q}.")
        _bal = getattr(rg_c, "balance", None)
        if _bal is not None:
            _p(story, st,
               f"• <b>Balance oferta–demanda ({_bal['veredicto']}).</b> La "
               f"oferta en estiaje ({_bal['q_estiaje_m3s']*1000:.0f} l/s, del "
               "estudio de caudales mínimos) menos el caudal ecológico deja "
               f"{_bal['q_disponible_m3s']*1000:.0f} l/s disponibles; la "
               f"demanda cubre el {_bal['cobertura_pct']:.0f} % de esa oferta. "
               f"{_bal['mensaje']}")
        else:
            _p(story, st,
               "• <b>Disponibilidad en estiaje.</b> Debe confirmarse con el "
               "estudio de caudales mínimos (Q95 / Q7,10) e ingresarse para "
               "cerrar el balance oferta–demanda.")
        c = rg_c.canal
        if c is not None:
            _p(story, st,
               f"• <b>Canal de conducción.</b> Sección {c.forma} de "
               f"{c.base_b_m:.2f} m de base y {c.tirante_y_m:.2f} m de tirante "
               f"(+{c.bordo_libre_m:.2f} m de bordo libre), con velocidad "
               f"{c.velocidad_ms:.2f} m/s (admisible {c.v_adm_min_ms:.2f}–"
               f"{c.v_adm_max_ms:.2f}) y Fr = {c.froude:.2f}"
               + (". Velocidad dentro del rango (ni sedimentación ni erosión)."
                  if not c.obs else ": " + "; ".join(c.obs) + "."))
        d = rg_c.desarenador
        if d is not None:
            _p(story, st,
               f"• <b>Desarenador.</b> Para decantar partículas de "
               f"{d.d_particula_mm:.2f} mm (vs = {d.vs_sedim_ms*100:.2f} cm/s): "
               f"nave de {d.longitud_m:.1f} × {d.ancho_m:.2f} m y "
               f"{d.profundidad_m:.2f} m de profundidad (retención "
               f"{d.tiempo_retencion_s:.0f} s).")
        if rg_c.bocatomas:
            nombres = ", ".join(b.nombre for b in rg_c.bocatomas)
            _p(story, st,
               f"• <b>Bocatoma.</b> Se predimensionaron las alternativas: "
               f"{nombres}. La selección definitiva depende de la pendiente del "
               "río, el acarreo y la topografía del sitio (ver Sección "
               f"{_n_riego(R)}.4).")
        pm = rg_c.proteccion_margenes
        if pm is not None:
            _p(story, st,
               f"• <b>Protección de márgenes.</b> Para la velocidad del río en "
               f"crecida ({pm['velocidad_rio_ms']:.2f} m/s), "
               f"{pm['recomendacion'][0].lower()}{pm['recomendacion'][1:]}")
        _p(story, st,
           "• <b>Recomendaciones.</b> El diseño definitivo requiere topografía "
           "del sitio, modelación HEC-RAS con secciones de campo y estudio de "
           "sedimentos (granulometría del acarreo); cerrar el balance oferta–"
           "demanda con la disponibilidad de estiaje.")

    # ---- Naturaleza, exactitud y limitaciones del software ----
    _p(story, st, f"{_n}.10 Naturaleza de los cálculos y limitaciones del "
                  "software", "h3")
    _p(story, st,
       "• <b>Naturaleza y exactitud.</b> Los cálculos siguen métodos "
       "reconocidos (Manning, HEC-18, Lischtvan-Lebediev, AASHTO). El tirante se "
       "resuelve como flujo uniforme (tirante normal) 1D sobre secciones "
       "derivadas del DEM COP-DEM 12.5 m; la socavación usa fórmulas empíricas "
       "de aplicabilidad acotada. La <b>precisión</b> numérica del solver es "
       "alta (bisección con tolerancia milimétrica), pero la <b>exactitud</b> "
       "física depende de la calidad de los datos de entrada.")
    _p(story, st,
       "• <b>Limitaciones.</b> (1) La resolución del DEM (12.5 m) suaviza la "
       "geometría real del cauce; para el diseño definitivo se requiere "
       "levantamiento topo-batimétrico. (2) El n de Manning se estima de la "
       "cobertura satelital, no de inspección de campo. (3) El tirante normal 1D "
       "no reproduce flujo 2D, curvas de remanso por el puente, ni flujo no "
       "permanente; para geometrías complejas se recomienda un modelo HEC-RAS "
       "1D/2D dedicado. (4) Las fórmulas de socavación entregan un valor de "
       "diseño conservador, no la evolución temporal del foso. Este informe es "
       "una <b>herramienta de prediseño y verificación</b>; no sustituye el "
       "estudio de detalle ni el criterio del ingeniero responsable.")

    # ---- 14.9 Conclusiones del análisis de riesgo hidroclimático (§14) ----
    # Solo cuando el tipo de obra es «Análisis de riesgo ABC»: amplía las
    # conclusiones con los resultados de la Sección 14 (riesgo del tramo, peor
    # escenario, variable dominante) y las recomendaciones de adaptación.
    if _riesgo_abc_activo(R):
        from .riesgo_hidroclimatico_abc import (tramo_referencia_para,
                                                conclusiones_abc)
        t = tramo_referencia_para(getattr(R, "lat", None),
                                  getattr(R, "lon", None),
                                  getattr(R, "departamento", None))
        _p(story, st, f"{_n}.9 Conclusiones y recomendaciones del análisis de "
                      "riesgo hidroclimático (Sección 14)", "h3")
        _p(story, st,
           "Las siguientes conclusiones se derivan de los resultados de la "
           "Sección 14 (riesgo por escenario del tramo RVF de referencia, "
           "variable dominante de vulnerabilidad y criterio de períodos de "
           "retorno) y de la literatura de adaptación de infraestructura vial "
           "al cambio climático:")
        for c in conclusiones_abc(t, R.T_diseno,
                                  getattr(R, "T_verificacion", None) or 300):
            _p(story, st, f"• {c}")


def _sec_referencias(story, st, R):
    story.append(PageBreak())
    _n = str((17 if _riesgo_abc_activo(R) else 16) + _off_riego(R))
    _p(story, st, f"{_n}. Referencias bibliográficas", "h2")
    _p(story, st,
       "Las referencias se listan a continuación en formato APA 7.ª "
       "edición, numeradas correlativamente y agrupadas por categoría "
       "temática. Esta organización facilita la trazabilidad con las "
       "secciones del informe: cuando el texto cita un número entre "
       "corchetes, el lector encuentra la entrada bibliográfica completa "
       "en el grupo correspondiente.", "italica")

    # Cada entrada en formato APA 7 (autor año título fuente DOI/URL).
    grupos = [
        ("15.1 Datos y fuentes (Sección 1–Sección 2)", [
            "Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, J., "
            "Shukla, S., Husak, G., Rowland, J., Harrison, L., Hoell, A., & "
            "Michaelsen, J. (2015). The climate hazards infrared precipitation "
            "with stations — a new environmental record for monitoring "
            "extremes. <i>Scientific Data</i>, 2, 150066. "
            "https://doi.org/10.1038/sdata.2015.66",
            "Hersbach, H., Bell, B., Berrisford, P., Hirahara, S., Horányi, A., "
            "Muñoz-Sabater, J., Nicolas, J., Peubey, C., Radu, R., Schepers, "
            "D., Simmons, A., Soci, C., Abdalla, S., Abellan, X., Balsamo, G., "
            "Bechtold, P., Biavati, G., Bidlot, J., Bonavita, M., … Thépaut, "
            "J.-N. (2020). The ERA5 global reanalysis. <i>Quarterly Journal "
            "of the Royal Meteorological Society</i>, 146(730), 1999–2049. "
            "https://doi.org/10.1002/qj.3803",
            "NASA Langley Research Center. (s. f.). <i>NASA POWER — Prediction "
            "of Worldwide Energy Resources</i>. https://power.larc.nasa.gov",
            "SENAMHI Bolivia. (s. f.). <i>Anuarios meteorológicos e "
            "hidrológicos</i>. Servicio Nacional de Meteorología e "
            "Hidrología. https://senamhi.gob.bo",
        ]),
        ("15.2 Estadística hidrológica (Sección 3–Sección 5)", [
            "Organización Meteorológica Mundial. (2009). <i>Guide to "
            "Hydrological Practices</i> (Vol. II, WMO-No. 168, 6.ª ed.). OMM.",
            "U.S. Geological Survey. (2018). <i>Bulletin 17C — Guidelines for "
            "determining flood flow frequency</i> (Techniques and Methods, "
            "Book 4, Chapter B5). U.S. Department of the Interior. "
            "https://doi.org/10.3133/tm4B5",
            "Chow, V. T., Maidment, D. R., & Mays, L. W. (1994). <i>Hidrología "
            "aplicada</i>. McGraw-Hill Interamericana.",
        ]),
        ("15.3 Modelos IDF y desagregación (Sección 6–Sección 8)", [
            "Sherman, C. W. (1931). Frequency and intensity of excessive "
            "rainfalls at Boston, Massachusetts. <i>Transactions of the "
            "American Society of Civil Engineers</i>, 95(1), 951–960.",
            "Chen, C.-L. (1983). Rainfall intensity-duration-frequency "
            "formulas. <i>Journal of Hydraulic Engineering</i>, 109(12), "
            "1603–1621. "
            "https://doi.org/10.1061/(ASCE)0733-9429(1983)109:12(1603)",
            "Wenzel, H. G. (1982). Rainfall for urban stormwater design. En "
            "D. F. Kibler (Ed.), <i>Urban Stormwater Hydrology</i> (Water "
            "Resources Monograph 7, pp. 35–67). American Geophysical Union.",
            "Dyck, S., & Peschke, G. (1995). <i>Grundlagen der Hydrologie</i> "
            "(3.ª ed.). Verlag für Bauwesen.",
        ]),
        ("15.4 Cartografía, morfometría e hipsometría (Sección 9)", [
            "Yamazaki, D., Ikeshima, D., Sosa, J., Bates, P. D., Allen, G. H., "
            "& Pavelsky, T. M. (2019). MERIT Hydro: A high-resolution global "
            "hydrography map based on latest topography dataset. <i>Water "
            "Resources Research</i>, 55(6), 5053–5073. "
            "https://doi.org/10.1029/2019WR024873",
            "Lehner, B., Verdin, K., & Jarvis, A. (2008). New global "
            "hydrography derived from spaceborne elevation data. <i>Eos, "
            "Transactions American Geophysical Union</i>, 89(10), 93–94. "
            "https://doi.org/10.1029/2008EO100001  "
            "[HydroSHEDS / HydroBASINS]",
            "Project MapBiomas. (2024). <i>MapBiomas Bolivia — Land Use and "
            "Land Cover Mapping, Collection 1</i> [Dataset]. https://"
            "bolivia.mapbiomas.org",
            "Zanaga, D., Van De Kerchove, R., Daems, D., De Keersmaecker, W., "
            "Brockmann, C., Kirches, G., Wevers, J., Cartus, O., Santoro, M., "
            "Fritz, S., Lesiv, M., Herold, M., Tsendbazar, N.-E., Xu, P., "
            "Ramoino, F., & Arino, O. (2022). <i>ESA WorldCover 10 m 2021 v200</i> "
            "[Dataset]. Zenodo. https://doi.org/10.5281/zenodo.7254221",
            "Strahler, A. N. (1957). Quantitative analysis of watershed "
            "geomorphology. <i>Transactions American Geophysical Union</i>, "
            "38(6), 913–920. https://doi.org/10.1029/TR038i006p00913",
            "Horton, R. E. (1945). Erosional development of streams and their "
            "drainage basins; hydrophysical approach to quantitative "
            "morphology. <i>Geological Society of America Bulletin</i>, "
            "56(3), 275–370.",
            "Gravelius, H. (1914). <i>Grundrifs der gesamten Gewässerkunde, "
            "Band I: Flufskunde</i>. G. J. Göschen.",
            "Schumm, S. A. (1956). Evolution of drainage systems and slopes "
            "in badlands at Perth Amboy, New Jersey. <i>Geological Society "
            "of America Bulletin</i>, 67(5), 597–646.",
            "Miller, V. C. (1953). <i>A quantitative geomorphic study of "
            "drainage basin characteristics in the Clinch Mountain area, "
            "Virginia and Tennessee</i> (Technical Report 3). Office of Naval "
            "Research, Department of Geology, Columbia University.",
            "Pike, R. J., & Wilson, S. E. (1971). Elevation–relief ratio, "
            "hypsometric integral, and geomorphic area–altitude analysis. "
            "<i>Geological Society of America Bulletin</i>, 82(4), 1079–1084.",
        ]),
        ("15.5 Tiempo de concentración (Sección 10)", [
            "Kirpich, Z. P. (1940). Time of concentration of small "
            "agricultural watersheds. <i>Civil Engineering</i>, 10(6), 362.",
            "Témez, J. R. (1978). <i>Cálculo hidrometeorológico de caudales "
            "máximos en pequeñas cuencas naturales</i>. Ministerio de Obras "
            "Públicas y Urbanismo (MOPU), España.",
            "Giandotti, M. (1934). <i>Previsione delle piene e delle magre "
            "dei corsi d'acqua</i>. Memorie e Studi Idrografici, Servizio "
            "Idrografico Italiano, Vol. 8.",
            "Bransby Williams, G. (1922). Flood discharge and the dimensions "
            "of spillways in India. <i>The Engineer</i>, 134, 321–322.",
            "U.S. Department of Agriculture, Natural Resources Conservation "
            "Service. (2010). <i>National Engineering Handbook, Part 630 — "
            "Hydrology, Chapter 15: Time of concentration</i>. USDA-NRCS.",
        ]),
        ("15.6 Caudales máximos (Sección 11)", [
            "Mac Math, R. E. (1887). Determination of the size of culverts "
            "and sewers. <i>Transactions of the American Society of Civil "
            "Engineers</i>, 16, 183–193.",
            "Verni, J. H., & King, J. H. (1977). Empirical regression equations "
            "for peak discharge in Andean basins. <i>Hydrology Research</i>, "
            "8(2), 109–123.",
            "Pizarro, R., Flores, J. P., Sangüesa, C., & Martínez, E. (2003). "
            "<i>Diseño hidrológico mediante el método racional modificado</i>. "
            "Corporación Nacional Forestal (CONAF), Chile.",
        ]),
        ("15.7 Hietogramas de diseño (Sección 12)", [
            "Keifer, C. J., & Chu, H. H. (1957). Synthetic storm pattern for "
            "drainage design. <i>Journal of the Hydraulics Division ASCE</i>, "
            "83(HY4), 1332-1–1332-25.",
            "Huff, F. A. (1967). Time distribution of rainfall in heavy storms. "
            "<i>Water Resources Research</i>, 3(4), 1007–1019. "
            "https://doi.org/10.1029/WR003i004p01007",
            "Bonta, J. V., & Rao, A. R. (1988). Comparison of four design-storm "
            "hyetographs. <i>Journal of Hydraulic Engineering</i>, 114(2), "
            "196–210. https://doi.org/10.1061/(ASCE)0733-9429(1988)114:2(196)",
            "U.S. Department of Agriculture, Soil Conservation Service. (1986). "
            "<i>Urban Hydrology for Small Watersheds — Technical Release 55 "
            "(TR-55)</i> (2.ª ed.). USDA-SCS.",
        ]),
        ("15.8 Modelación HEC-HMS (Sección 13)", [
            "U.S. Army Corps of Engineers, Hydrologic Engineering Center. "
            "(2022). <i>HEC-HMS User's Manual, Version 4.10</i>. USACE-HEC. "
            "https://www.hec.usace.army.mil/software/hec-hms/",
            "Feldman, A. D. (Ed.). (2000). <i>Hydrologic Modeling System "
            "HEC-HMS — Technical Reference Manual</i>. U.S. Army Corps of "
            "Engineers, Hydrologic Engineering Center, CPD-74B.",
            "Scharffenberg, W. A. (2022). <i>HEC-HMS User's Manual, "
            "Version 4.10</i>. USACE-HEC. "
            "https://www.hec.usace.army.mil/confluence/hmsdocs/hmsum",
            "Singh, V. P. (Ed.). (1995). <i>Computer Models of Watershed "
            "Hydrology</i>. Water Resources Publications.",
            "Beven, K. J. (2012). <i>Rainfall-Runoff Modelling: The Primer</i> "
            "(2.ª ed.). Wiley-Blackwell. "
            "https://doi.org/10.1002/9781119951001",
            "Mockus, V. (1957). <i>Use of storm and watershed "
            "characteristics in synthetic hydrograph analysis and "
            "application</i>. USDA Soil Conservation Service.",
            "U.S. Department of Agriculture, Natural Resources Conservation "
            "Service. (2004). <i>National Engineering Handbook, Part 630 — "
            "Hydrology, Chapter 10: Estimation of direct runoff from storm "
            "rainfall</i> (SCS Curve Number Method). USDA-NRCS.",
            "Green, W. H., & Ampt, G. A. (1911). Studies on soil physics: "
            "1. The flow of air and water through soils. <i>Journal of "
            "Agricultural Science</i>, 4(1), 1–24.",
            "Bennett, T. H. (1998). <i>Development and application of a "
            "continuous soil moisture accounting algorithm for the "
            "Hydrologic Engineering Center Hydrologic Modeling System "
            "(HEC-HMS)</i>. M.Sc. Thesis, University of California, Davis.",
            "U.S. Department of Agriculture, Natural Resources Conservation "
            "Service. (2007). <i>National Engineering Handbook, Part 630 — "
            "Hydrology, Chapter 16: Hydrographs</i>. USDA-NRCS.",
            "Clark, C. O. (1945). Storage and the unit hydrograph. "
            "<i>Transactions ASCE</i>, 110, 1419–1488.",
            "Kull, D. W., & Feldman, A. D. (1998). Evolution of Clark's "
            "unit graph method to spatially distributed runoff. <i>Journal "
            "of Hydrologic Engineering</i>, 3(1), 9–19. "
            "https://doi.org/10.1061/(ASCE)1084-0699(1998)3:1(9)",
            "Snyder, F. F. (1938). Synthetic unit-graphs. <i>Transactions "
            "American Geophysical Union</i>, 19(1), 447–454.",
            "Lighthill, M. J., & Whitham, G. B. (1955). On kinematic "
            "waves I: Flood movement in long rivers. <i>Proceedings Royal "
            "Society of London A</i>, 229(1178), 281–316. "
            "https://doi.org/10.1098/rspa.1955.0088",
            "Buytaert, W., Vuille, M., Dewulf, A., Urrutia, R., Karmalkar, "
            "A., & Célleri, R. (2010). Uncertainties in climate change "
            "projections and regional downscaling in the tropical Andes: "
            "Implications for water resources management. <i>Hydrology "
            "and Earth System Sciences</i>, 14(7), 1247–1258. "
            "https://doi.org/10.5194/hess-14-1247-2010",
            "Vuille, M. (2003). Climate change in the tropical Andes: "
            "Observations and modeling results. <i>Climatic Change</i>, "
            "59(1–2), 75–99. "
            "https://doi.org/10.1023/A:1024406427519",
        ]),
        ("15.9 Hidráulica fluvial, socavación y puentes (Sección 14)", [
            "Chow, V. T. (1959). <i>Open-Channel Hydraulics</i>. McGraw-Hill. "
            "(Ecuación de Manning; coeficientes de rugosidad n.)",
            "Arneson, L. A., Zevenbergen, L. W., Lagasse, P. F., & Clopper, "
            "P. E. (2012). <i>Evaluating Scour at Bridges</i> (HEC-18, 5.ª ed., "
            "FHWA-HIF-12-003). Federal Highway Administration, U.S. DOT.",
            "Lagasse, P. F., Zevenbergen, L. W., Spitz, W. J., & Arneson, L. A. "
            "(2012). <i>Stream Stability at Highway Structures</i> (HEC-20, 4.ª "
            "ed., FHWA-HIF-12-004). FHWA, U.S. DOT.",
            "Lagasse, P. F., Clopper, P. E., Pagán-Ortiz, J. E., Zevenbergen, "
            "L. W., et al. (2009). <i>Bridge Scour and Stream Instability "
            "Countermeasures</i> (HEC-23, 3.ª ed., FHWA-NHI-09-111/112). FHWA.",
            "U.S. Army Corps of Engineers, Hydrologic Engineering Center. "
            "<i>HEC-RAS Hydraulic Reference Manual — Estimating Scour at "
            "Bridges</i> (ecuaciones CSU, contracción, Froehlich/HIRE). "
            "https://www.hec.usace.army.mil/software/hec-ras/",
            "AASHTO. (2020). <i>LRFD Bridge Design Specifications</i> (9.ª ed.), "
            "Art. 2.6.4.4 (socavación) y 3.7 (carga hidráulica WA), Estado "
            "Límite de Evento Extremo. American Association of State Highway "
            "and Transportation Officials.",
            "Maza Álvarez, J. A. (1968). <i>Socavación en cauces naturales</i>. "
            "Universidad Nacional Autónoma de México (UNAM).",
            "Juárez Badillo, E., & Rico Rodríguez, A. (1994). <i>Mecánica de "
            "Suelos, Tomo III: Flujo de agua en suelos</i> (método de "
            "Lischtvan-Lebediev). Editorial Limusa.",
            "Richardson, E. V., & Davis, S. R. (2001). <i>Evaluating Scour at "
            "Bridges</i> (HEC-18, 4.ª ed., FHWA-NHI-01-001). FHWA.",
            "Administradora Boliviana de Carreteras (ABC) / MOPSV. <i>Manual de "
            "Hidrología y Drenaje, Vol. II</i> (períodos de retorno para "
            "puentes, socavación, gálibo/borde libre).",
        ]),
        ("15.10 Normativa nacional aplicada (Bolivia)", [
            "Ministerio de Planificación del Desarrollo. (2015). <i>Reglamento "
            "Básico de Preinversión</i> (Resolución Ministerial N° 115/2015). "
            "MPD — Viceministerio de Inversión Pública y Financiamiento "
            "Externo.",
            "Administradora Boliviana de Carreteras. (s. f.). <i>Manual de "
            "Hidrología y Drenaje</i> (Volumen II). MOPSV — ABC.",
            "Administradora Boliviana de Carreteras. (s. f.). <i>Guía para el "
            "Diseño de Puentes</i>. MOPSV — ABC.",
            "Ministerio de Medio Ambiente y Agua. (2007). <i>Norma Boliviana "
            "NB 688 — Instalaciones sanitarias: alcantarillado sanitario, "
            "pluvial y tratamiento de aguas residuales</i>. MMAyA.",
            "AASHTO. (2020). <i>LRFD Bridge Design Specifications</i> "
            "(9.ª ed.). American Association of State Highway and "
            "Transportation Officials.",
        ]),
    ]

    # Referencias del análisis de riesgo hidroclimático (§14), solo obra ABC.
    if _riesgo_abc_activo(R):
        from .riesgo_hidroclimatico_abc import referencias_abc
        grupos.append(
            ("15.11 Riesgo hidroclimático y adaptación al cambio climático "
             "(Sección 14)", referencias_abc()))

    # Renumera el prefijo de cada grupo (15.x) a la numeración real de la
    # sección de referencias, que se corre +1 cuando existe la sección ABC.
    import re as _re
    n = 1
    for grupo_titulo, items in grupos:
        grupo_titulo = _re.sub(r"^15\.", f"{_n}.", grupo_titulo)
        _p(story, st, grupo_titulo, "h3")
        for it in items:
            _p(story, st, f"<b>[{n}]</b> {it}")
            n += 1


# ---------------------------------------------------------------------------
# Encabezado y pie de página
# ---------------------------------------------------------------------------

HEADER_TEXTO = "INFORME HIDROLOGICO DE CAUDALES MAXIMOS    HYDROFRA V 1.3"
# Encabezado corriente activo del informe en curso; `generar_pdf` lo fija según
# el tipo de obra (generación de PDF es secuencial, un informe a la vez).
_HEADER_ACTUAL = HEADER_TEXTO
FOOTER_AUTOR = "Ing. Luis Franco Guarachi"
FOOTER_EMAIL = "civilmen@gmail.com"
FOOTER_TEL = "+591 69907008"

# Owner password — sólo quien lo conozca puede quitar las restricciones de
# impresión / edición / copia del PDF. El user password va vacío para que
# cualquiera pueda ABRIR el archivo (sólo no puede editar/imprimir/copiar).
PROTECCION_OWNER_PWD = "HYDROFRA-v1.2-Luis-Franco-Guarachi"

MENSAJE_CONTACTO_JS = (
    "Este documento es de uso exclusivo y se encuentra protegido."
    " Para obtener una copia editable o imprimible comuniquese con:"
    " Ing. Luis Franco Guarachi - civilmen@gmail.com - +591 69907008"
)


class _DocConTOC(SimpleDocTemplate):
    """DocTemplate que registra cada heading (h2/h3) como entrada del TOC."""

    def afterFlowable(self, flowable):
        super().afterFlowable(flowable)
        if isinstance(flowable, Paragraph):
            nombre = getattr(flowable.style, "name", "")
            if nombre == "h2":
                self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
            elif nombre == "h3":
                self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


class _CanvasConPaginado(_canvas_mod.Canvas):
    """Canvas que guarda el estado de cada página para poder pintar "Pág X de Y".

    ReportLab no conoce el total de páginas al pintar la página N; el truco
    estándar es bufferear los estados con showPage() y dibujar el chrome en
    save() cuando ya sabemos el total.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estados = []

    def showPage(self):
        self._estados.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._estados)
        for estado in self._estados:
            self.__dict__.update(estado)
            self._dibujar_chrome(total)
            super().showPage()
        super().save()

    def _dibujar_chrome(self, total: int):
        ancho, alto = self._pagesize
        n = self.getPageNumber()
        self.saveState()
        # --- Encabezado: texto centrado + línea horizontal inferior. ---
        y_texto = alto - 1.2 * cm
        y_linea = alto - 1.5 * cm
        self.setFont(FONT_BOLD, 9)
        self.setFillColor(colors.HexColor("#1f3a68"))
        self.drawCentredString(ancho / 2.0, y_texto, _HEADER_ACTUAL)
        self.setStrokeColor(colors.HexColor("#1f3a68"))
        self.setLineWidth(0.6)
        self.line(1.6 * cm, y_linea, ancho - 1.6 * cm, y_linea)
        # --- Pie de página: línea horizontal superior + texto centrado. ---
        y_linea_pie = 1.55 * cm
        y_texto_pie = 1.05 * cm
        self.line(1.6 * cm, y_linea_pie, ancho - 1.6 * cm, y_linea_pie)
        self.setFont(FONT, 8)
        self.setFillColor(colors.HexColor("#444444"))
        pie = (f"{FOOTER_AUTOR}   -   {FOOTER_EMAIL}   -   {FOOTER_TEL}"
               f"   -   Pag. {n} de {total}")
        self.drawCentredString(ancho / 2.0, y_texto_pie, pie)
        # Marca pequeña "Info." alineada a la derecha como parte del pie.
        self.setFont(FONT, 7)
        self.setFillColor(colors.HexColor("#888888"))
        self.drawRightString(ancho - 1.6 * cm, y_texto_pie, "Info.")
        self.restoreState()


def _sec_anexos_edtp(story, st, R):
    """Anexos EDTP: entregables que requieren datos de campo o modelación
    externa. Se aporta lo que el programa deriva automáticamente y se dejan
    marcos estructurados (placeholders) para completar en campo."""
    story.append(PageBreak())
    _n = str((18 if _riesgo_abc_activo(R) else 17) + _off_riego(R))
    _p(story, st, f"{_n}. Anexos EDTP — datos de campo y modelación de detalle",
       "h2")
    _p(story, st,
       "Esta sección responde a los entregables de nivel EDTP que exige el "
       "dictamen de supervisión y que <b>requieren trabajo de campo, "
       "levantamiento topográfico o modelación especializada</b> que un "
       "prediseño automatizado no puede generar por sí solo. Para cada uno se "
       "aporta lo que el programa <b>sí deriva</b> de los datos disponibles y "
       "se deja un marco estructurado para completarlo con la información de "
       "campo antes de la aprobación formal.")

    # A.1 Caracterización geomorfológica preliminar (auto desde morfometría).
    A = getattr(R, "analisis_morf", None)
    _p(story, st, f"{_n}.1 Caracterización geomorfológica preliminar del tramo",
       "h3")
    if A is not None:
        sin = getattr(A, "sinuosidad", 0.0) or 0.0
        if sin < 1.05:
            tipo_cauce = "recto (sinuosidad < 1.05)"
        elif sin < 1.5:
            tipo_cauce = "sinuoso / de transición (1.05 ≤ sinuosidad < 1.5)"
        else:
            tipo_cauce = "meándrico (sinuosidad ≥ 1.5)"
        ia = getattr(R, "inund_area_alta_pct", None)
        plan = (f"; el índice HAND (mapa 9.9) clasifica el {ia:.1f} % de la "
                f"cuenca con susceptibilidad alta a la inundación, señal de "
                f"planicies inundables próximas al cauce" if ia is not None
                else "")
        _p(story, st,
           f"<b>Derivado automáticamente del DEM/morfometría:</b> el cauce en "
           f"el tramo es de tipo <b>{tipo_cauce}</b> (sinuosidad "
           f"S = {sin:.2f}), con pendiente de cauce "
           f"{A.pendiente_cauce_pct:.2f} % y densidad de drenaje "
           f"{A.densidad_drenaje_km_km2:.2f} km/km²{plan}.")
    _p(story, st,
       "<b>Requiere campo (mapa geomorfológico-geotécnico 1:1.000):</b> el "
       "EDTP exige un plano en planta que identifique in situ la tipología "
       "del cauce, la posición de las planicies de inundación, los "
       "afloramientos rocosos, los depósitos aluviales y las zonas de erosión "
       "marginal en los accesos. Ítems a levantar:")
    for it in ["Tipología del cauce confirmada en campo (recto/meándrico/trenzado).",
               "Delimitación de planicies de inundación y terrazas.",
               "Afloramientos rocosos y depósitos aluviales (con calicatas).",
               "Zonas de erosión marginal / socavación de márgenes existentes.",
               "Cobertura y uso del suelo en la franja fluvial."]:
        _p(story, st, "☐ " + it)

    # A.2 Catastro de marcas de máxima crecida (calibración local).
    story.append(PageBreak())
    _p(story, st, f"{_n}.2 Catastro de marcas de máxima crecida (calibración "
                  "local)", "h3")
    _p(story, st,
       "La metodología boliviana exige calibrar los caudales teóricos "
       "estimados con marcas de crecidas históricas (en árboles, laderas o "
       "infraestructura vecina) y entrevistas a pobladores. Esta información "
       "<b>no puede obtenerse automáticamente</b>; se deja el marco para el "
       "registro de campo, que debe contrastarse con el NAME calculado en la "
       "Sección 14:")
    filas = [["Punto", "Coord. (Lat, Lon)", "Cota marca (m)",
              "Fuente / testigo", "Fecha evento"],
             ["MC-1", "☐", "☐", "☐", "☐"],
             ["MC-2", "☐", "☐", "☐", "☐"],
             ["MC-3", "☐", "☐", "☐", "☐"]]
    story.append(_tabla(filas, col_widths=[2.0*cm, 3.6*cm, 2.8*cm, 4.0*cm,
                                           2.6*cm]))
    _p(story, st,
       "Adjuntar registro fotográfico georreferenciado y actas de entrevista. "
       "Comparar la cota de las marcas con el NAME de diseño/verificación de "
       "la Sección 14.5 para validar o ajustar los caudales.", "italica")

    # A.3 Alcance de la modelación hidráulica (1D preliminar vs 2D final).
    story.append(PageBreak())
    _p(story, st, f"{_n}.3 Alcance de la modelación hidráulica y topografía",
       "h3")
    _p(story, st,
       "El módulo hidráulico de este informe resuelve el <b>tirante normal 1D "
       "(Manning)</b> y el <b>perfil de flujo gradualmente variado 1D (método "
       "del paso estándar, energía de Bernoulli)</b> por sección (Sección "
       "14.4), un prediseño apropiado para el dimensionamiento preliminar. Para "
       "el diseño final el EDTP exige, según el dictamen:")
    for it in ["Modelación en HEC-RAS 6.x (régimen permanente y no permanente, "
               "1D/2D) con la geometría real del cauce.",
               "Levantamiento topográfico local (LiDAR o restitución "
               "fotogramétrica 1:1.000–1:2.000) en el eje del puente y la "
               "cuenca tributaria inmediata.",
               "Estudio geotécnico del cauce (calicatas, granulometría D50/D95) "
               "para la socavación y la fundación.",
               "Verificación de la socavación y el gálibo con la batimetría de "
               "campo y el caudal calibrado con las marcas de crecida."]:
        _p(story, st, "☐ " + it)
    _p(story, st,
       "Los resultados hidráulicos de la Sección 14 (tirante, velocidad, "
       "socavación, gálibo) quedan como <b>valores de prediseño verificables</b>"
       " que el modelo HEC-RAS de detalle debe confirmar antes del diseño "
       "estructural definitivo.", "italica")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def generar_pdf(archivo, R) -> Path:
    """Genera el informe PDF v1.2 desde el bundle de resultados R.

    El PDF queda PROTEGIDO con AES-128:
    - Cualquiera puede ABRIRLO (no requiere contraseña de usuario).
    - NO permite imprimir, copiar texto, editar ni anotar.
    - En Adobe Acrobat dispara un alert con el mensaje de contacto cuando
      el usuario intenta imprimir/guardar.
    - Marca de agua diagonal en cada página visible en cualquier visor.
    - Subject de los metadatos incluye los datos de contacto.
    """
    from reportlab.lib.pdfencrypt import StandardEncryption
    archivo = Path(archivo)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    encriptacion = StandardEncryption(
        userPassword="",
        ownerPassword=PROTECCION_OWNER_PWD,
        canPrint=0, canModify=0, canCopy=0, canAnnotate=0,
        strength=128,
    )
    # Top/bottom 2.6 cm para dejar espacio al encabezado (línea + texto a ~1.5 cm
    # del borde) y al pie (igual, abajo). Laterales en 1.8 cm como antes.
    doc = _DocConTOC(
        str(archivo), pagesize=letter,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=2.6 * cm, bottomMargin=2.6 * cm,
        title=f"CURVAS IDF - {R.proyecto.nombre_proyecto}",
        author=FOOTER_AUTOR,
        subject=("PROTEGIDO - Comuniquese con " + FOOTER_AUTOR +
                 " - " + FOOTER_EMAIL + " - " + FOOTER_TEL),
        keywords="HYDROFRA v1.2; informe protegido; contacto " + FOOTER_EMAIL,
        encrypt=encriptacion,
    )
    # Encabezado corriente según el tipo de obra (variante ABC si aplica).
    global _HEADER_ACTUAL
    _HEADER_ACTUAL = _header_informe(R)
    st = _estilos()
    toc = _crear_toc()
    story = []
    _portada(story, st, R)
    _indice(story, st, R, toc)
    _sec_tabla_maestra(story, st, R)
    _sec_fuentes(story, st, R)
    _sec_series(story, st, R)
    _sec_descriptivos(story, st, R)
    _sec_consistencia(story, st, R)
    _sec_frecuencias(story, st, R)
    _sec_cuantiles(story, st, R)
    _sec_desagregacion(story, st, R)
    _sec_modelos_idf(story, st, R)
    _sec_mapas(story, st, R)
    _sec_tiempo_concentracion(story, st, R)
    _sec_caudal_maximo(story, st, R)
    _sec_hietogramas(story, st, R)
    _sec_hechms(story, st, R)
    if _riesgo_abc_activo(R):
        _sec_riesgo_hidroclimatico_abc(story, st, R)
    _sec_tirante(story, st, R)
    _sec_alcantarillas(story, st, R)
    _sec_hecras(story, st, R)
    _sec_riego(story, st, R)
    _sec_conclusiones(story, st, R)
    _sec_referencias(story, st, R)
    _sec_anexos_edtp(story, st, R)
    # multiBuild realiza varias pasadas: la primera registra entradas del TOC,
    # las siguientes ajustan números de página hasta que convergen.
    doc.multiBuild(story, canvasmaker=_CanvasConPaginado)
    return archivo
