"""Generador del informe PDF de caudales mínimos — HYDROFRA v1.2.

Reusa la infraestructura de `report.py` (fuentes Unicode, estilos, tablas,
canvas con paginado, encriptación AES-128) y la adapta a las secciones del
informe de Q mín (Secciones 1-7, incluyendo 2.1-2.9, 3.1, 4.7 y 5.0).

Modo de uso:

    from idf.report_qmin import generar_pdf_qmin
    pdf_path = generar_pdf_qmin(sesion_dir / "qmin.pdf", datos)

`datos` es un dict con el mismo contenido que el contexto del template
`qmin_resumen.html` (proyecto, lat/lon, uso, marco, cuenca_qmin, mapas_qmin,
stats_qmin, pq, s3_1, s4_7, s5_0, s5, s6_conclusiones, s6_recomendaciones,
s7_refs, etc.). El worker lo construye una vez y lo pasa a ambos
(render HTML + PDF) — ver `webapp/app.py:_qmin_worker`.

El PDF queda protegido con AES-128: cualquiera puede abrirlo, nadie puede
imprimir / copiar / editar / anotar. Encabezado HYDROFRA y pie con
contacto del autor en cada página.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
)

from .report import (
    FONT, FONT_BOLD, FOOTER_AUTOR, FOOTER_EMAIL, FOOTER_TEL,
    PROTECCION_OWNER_PWD, _CELDA, _CELDA_CAB, _CELDA_IZQ, _CanvasConPaginado,
    _estilos, _figura, _tabla,
)


HEADER_TEXTO_QMIN = "INFORME HIDROLOGICO DE CAUDALES MINIMOS    HYDROFRA V 1.3"


def _p(story, st, texto, estilo="cuerpo"):
    story.append(Paragraph(texto, st[estilo]))


def _img_si_existe(path: Path | None, ancho_cm: float = 16.0):
    """Devuelve un Image listo para añadir al story, o None si no existe."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return _figura(p, ancho_cm=ancho_cm)


def _portada(story, st, d):
    story.append(Spacer(1, 4.5 * cm))
    _p(story, st, "INFORME HIDROLOGICO DE CAUDALES MINIMOS", "titulo")
    _p(story, st, "HYDROFRA V 1.3", "subt_centro")
    story.append(Spacer(1, 2 * cm))
    proyecto = d["proyecto"]
    info = [
        ["Proyecto:", getattr(proyecto, "nombre_proyecto", "—")],
        ["Ingeniero:", getattr(proyecto, "ingeniero", "—")],
        ["Ubicación:", getattr(proyecto, "ubicacion", "—")],
        ["Coordenadas:", f"Lat {d['lat']:.6f}°  ·  Lon {d['lon']:.6f}°"],
        ["Tipo de aprovechamiento:", d.get("nombre_uso", d.get("uso", "—"))],
        ["Años de serie objetivo:", str(d.get("anios", "—"))],
    ]
    t = _tabla(info, col_widths=[6 * cm, 10 * cm], cabecera=False,
                primera_col_izq=True)
    story.append(t)
    story.append(Spacer(1, 4 * cm))
    _p(story, st,
        "Documento protegido (AES-128). Cualquiera puede abrirlo, nadie "
        "puede imprimir, copiar, editar ni anotar. Para uso y citación, "
        f"comuníquese con {FOOTER_AUTOR} ({FOOTER_EMAIL}, {FOOTER_TEL}).",
        "italica")
    story.append(PageBreak())


def _seccion_1(story, st, d):
    _p(story, st, "1. Caracterización de la cuenca o zona de estudio", "h2")
    _p(story, st,
        "Delineación de la cuenca por watershed D8 con MERIT Hydro 90 m, "
        "parámetros morfométricos sobre el DEM SRTM y mapas temáticos GEE "
        "específicos para caudales mínimos.")
    cuenca = d.get("cuenca_qmin")
    if cuenca is not None:
        red = getattr(cuenca, "red_drenaje", None) or {}
        tabla = [
            ["Coordenadas",
              f"Lat {d['lat']:.6f}°  ·  Lon {d['lon']:.6f}°"],
            ["Área de aporte (km²)", f"{cuenca.area_km2:.2f}"],
            ["Perímetro (km)", f"{cuenca.perimetro_km:.2f}"],
            ["Cota mínima (m)", f"{cuenca.cota_menor_m:.0f}"],
            ["Cota máxima (m)", f"{cuenca.cota_mayor_m:.0f}"],
            ["Desnivel (m)", f"{cuenca.desnivel_m:.0f}"],
            ["Longitud del cauce principal (km)",
              f"{cuenca.long_cauce_km:.2f}"],
            ["Pendiente media del cauce (%)",
              f"{cuenca.pendiente_media_mm * 100:.2f}"],
        ]
        if red:
            tabla.append(["Orden de Strahler máx · # corrientes · Rb",
                           f"{red.get('max_order', '—')} · "
                           f"{red.get('n_total', '—')} · "
                           f"{red.get('rb', '—')}"])
        story.append(_tabla(tabla, col_widths=[8 * cm, 8 * cm],
                              cabecera=False, primera_col_izq=True))
    else:
        _p(story, st,
            "No fue posible delinear la cuenca con MERIT Hydro (GEE no "
            "respondió o el punto cayó en zona degenerada).", "italica")
    # Nota de rango operativo (siempre visible).
    amin = d.get("area_min_km2", 1)
    amax = d.get("area_max_km2", 2000)
    nota = (f"<b>Nota — rango operativo.</b> El análisis de caudales mínimos "
             f"está diseñado para cuencas locales con área de aporte entre "
             f"<b>{int(amin)} km²</b> y <b>{int(amax)} km²</b>. Por debajo "
             f"del mínimo la delineación MERIT 90 m puede ser degenerada; "
             f"por encima del máximo los mapas temáticos GEE dejan de "
             f"representar la hidrología local y la transferencia regional "
             f"pierde consistencia.")
    if cuenca is not None and d.get("cuenca_fuera_rango"):
        nota += (f" <b>En este caso la cuenca delineada "
                  f"({cuenca.area_km2:.2f} km²) cae fuera del rango "
                  f"operativo</b>, por lo que se omiten los 6 mapas temáticos "
                  f"GEE y la transformación P→Q.")
    _p(story, st, nota, "italica")


def _seccion_2(story, st, d, sesion_dir: Path):
    _p(story, st, "2. Información local disponible", "h2")
    _p(story, st,
        "Identificación y selección de estaciones meteorológicas SENAMHI e "
        "hidrométricas SENAMHI-BHN / GRDC dentro de un radio operativo, "
        "aplicación del panel OMM-168 de pruebas de consistencia, "
        "metodología de selección ponderada y rellenado de huecos por "
        "regresión.")

    # 2.1 Consistencia
    diags = d.get("diagnosticos_consistencia") or []
    if diags:
        _p(story, st,
            "2.1 Análisis de consistencia estadística de las series candidatas",
            "h3")
        cabecera = ["#", "Código", "Tipo", "n años", "Kendall", "Pettitt",
                     "Rachas", "Lag-1", "KS (mejor)", "Pasa", "Clase", "Apta"]
        filas = [cabecera]
        for i, x in enumerate(diags, 1):
            filas.append([
                str(i), x.codigo, "Met." if x.tipo == "met" else "Hidro",
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

    # 2.2 Selección
    sel = d.get("seleccionadas") or []
    if sel:
        _p(story, st, "2.2 Estaciones seleccionadas (ranking final)", "h3")
        filas = [["#", "Código", "Tipo", "Distancia (km)", "Clase", "Estado",
                  "Cons.", "Cerc.", "Morf.", "Op.", "Puntaje"]]
        for i, (x, puntaje, fac) in enumerate(sel, 1):
            filas.append([
                str(i), x.codigo, "Met." if x.tipo == "met" else "Hidro",
                f"{x.distancia_km:.1f}", x.clase, x.estado,
                f"{fac['consistencia']:.2f}", f"{fac['distancia']:.2f}",
                f"{fac['morfometria']:.2f}", f"{fac['estado']:.2f}",
                f"{puntaje}",
            ])
        story.append(_tabla(filas))

    # 2.3 Ajustes
    comp = d.get("comparadas") or []
    if comp:
        _p(story, st, "2.3 Ajustes, rellenado y comparación de las series",
            "h3")
        filas = [["#", "Código", "Tipo", "Huecos", "r doble masa",
                   "RMS doble masa"]]
        for i, c in enumerate(comp, 1):
            filas.append([
                str(i), c["codigo"],
                "Met." if c["tipo"] == "met" else "Hidro",
                str(c["n_huecos"]),
                f"{c['r_doble_masa']:.3f}",
                f"{c['rms_doble_masa']:.2f}",
            ])
        story.append(_tabla(filas))
        img = _img_si_existe(sesion_dir / "qmin_series.png", ancho_cm=16)
        if img:
            story.append(img)

    # 2.4 Mapa regional (Sentinel-2 + estaciones + ciudades)
    img = _img_si_existe(sesion_dir / "mapa_regional.png", ancho_cm=16)
    if img:
        _p(story, st, "2.4 Mapa regional — punto de estudio y estaciones",
            "h3")
        story.append(img)

    # 2.5 Cuenca
    img = _img_si_existe(sesion_dir / "qmin_cuenca.png", ancho_cm=16)
    if img:
        _p(story, st, "2.5 Cuenca de aporte delineada (MERIT Hydro 90 m)",
            "h3")
        story.append(img)

    # 2.6 Mapas GEE
    mapas = d.get("mapas_qmin") or {}
    if mapas:
        _p(story, st, "2.6 Mapas temáticos GEE", "h3")
        for clave, archivo in mapas.items():
            img = _img_si_existe(sesion_dir / archivo, ancho_cm=15)
            if img:
                story.append(img)
                story.append(Spacer(1, 4))

    # 2.7 Met
    met = d.get("met_cercanas") or []
    if met:
        _p(story, st,
            f"2.7 Estaciones meteorológicas en {d.get('radio_km', 100)} km "
            f"({len(met)})", "h3")
        filas = [["#", "Distancia (km)", "Código", "Nombre",
                   "Depto.", "Altitud (m)", "P24 (mm)"]]
        for i, (e, dist) in enumerate(met, 1):
            filas.append([str(i), f"{dist:.1f}", e.codigo, e.nombre,
                            e.departamento, f"{e.altitud_msnm:.0f}",
                            f"{e.p24_media_mm:.1f}"])
        story.append(_tabla(filas))

    # 2.8 Hidro
    hidro = d.get("hidro_cercanas") or []
    if hidro:
        _p(story, st,
            f"2.8 Estaciones hidrométricas en {d.get('radio_km', 100)} km "
            f"({len(hidro)})", "h3")
        filas = [["#", "Distancia (km)", "Código", "Nombre / cuerpo",
                   "Fuente", "Estado", "Q medio (m³/s)", "Período"]]
        for i, (e, dist) in enumerate(hidro, 1):
            filas.append([str(i), f"{dist:.1f}", e.codigo,
                            f"{e.nombre} — {e.cuerpo_agua}",
                            e.fuente, e.estado,
                            f"{e.q_medio_m3s:.1f}",
                            f"{e.anio_inicio}–{e.anio_fin}"])
        story.append(_tabla(filas))

    # 2.9 Transformación P→Q
    pq = d.get("pq")
    if pq is not None:
        _p(story, st,
            "2.9 Transformación precipitación → caudal (balance mensual)",
            "h3")
        tabla = [
            ["Q medio (m³/s)", f"{pq.q_medio_m3s:.3f}"],
            ["Q mínimo mensual (m³/s)", f"{pq.q_min_m3s:.3f}"],
            ["Q5 / Q50 (m³/s)",
              f"{pq.q5:.3f} / {pq.q50:.3f}"],
            ["Q75 / Q85 / Q90 / Q95 (m³/s)",
              f"{pq.q75:.3f} / {pq.q85:.3f} / {pq.q90:.3f} / "
              f"{pq.q95:.3f}"],
            ["Q7,10 estimado (m³/s)", f"{pq.q7_10:.3f}"],
            ["Coef. escorrentía anual", f"{pq.coef_escorrentia_anual:.2f}"],
            ["α recesión / f rápida / CAW",
              f"{pq.alpha:.2f} / {pq.fraccion_rapida:.2f} / "
              f"{pq.caw_usada_mm:.0f} mm"],
        ]
        story.append(_tabla(tabla, col_widths=[8 * cm, 8 * cm],
                              cabecera=False, primera_col_izq=True))
        clima_fuente = d.get("clima_fuente")
        if clima_fuente:
            _p(story, st,
                f"<b>Fuente de la precipitación climatológica:</b> "
                f"{clima_fuente}.", "italica")
        img = _img_si_existe(sesion_dir / "qmin_balance.png", ancho_cm=16)
        if img:
            story.append(img)
        img = _img_si_existe(sesion_dir / "qmin_fdc.png", ancho_cm=16)
        if img:
            story.append(img)


def _seccion_3(story, st, d):
    story.append(PageBreak())
    _p(story, st, "3. Modelos de cambio climático disponibles", "h2")
    _p(story, st,
        "Modelos CMIP6 (NEX-GDDP-CMIP6), regionales CORDEX-SAM, el Atlas "
        "MMAyA y CHIRP-GEFS proyectado disponibles para la cuenca de "
        "estudio, con su nivel de confiabilidad regional documentado.")
    s3_1 = d.get("s3_1") or {}
    if not s3_1:
        return
    _p(story, st,
        "3.1 Metodología para la selección del modelo de cambio climático",
        "h3")
    _p(story, st,
        f"Región climática detectada: <b>{s3_1.get('region_nombre', '—')}</b>.")
    modelos = s3_1.get("modelos_region") or {}
    if modelos:
        tabla = [
            ["CMIP6 curados", " · ".join(modelos.get("cmip6_curados") or [])],
            ["CORDEX-CORE / RCMs",
              " · ".join(modelos.get("cordex_core") or [])],
            ["Sesgo regional documentado", modelos.get("sesgo", "—")],
            ["Estudios de respaldo",
              "; ".join(modelos.get("fuentes") or [])],
        ]
        story.append(_tabla(tabla, col_widths=[5.5 * cm, 10.5 * cm],
                              cabecera=False, primera_col_izq=True))
    _p(story, st, "Pasos de la metodología", "h3")
    for nombre, descripcion in s3_1.get("pasos") or []:
        _p(story, st, f"<b>{nombre}</b><br/>{descripcion}")
    # Tablas resumidas (métricas, bias correction, ensemble).
    for titulo, clave, cabecera in [
        ("Métricas de desempeño", "metricas",
          ["Métrica", "Fórmula", "Umbral", "Referencia"]),
        ("Métricas críticas para Q mín", "metricas_min",
          ["Métrica", "Definición", "Umbral", "Referencia"]),
        ("Corrección de sesgo", "bias_correction",
          ["Método", "Principio", "Tendencia", "Multi.", "Recomendado", "Ref."]),
        ("Esquemas de ensemble", "ensemble",
          ["Método", "Pesos", "Reduce", "Ref."]),
    ]:
        items = s3_1.get(clave) or []
        if not items:
            continue
        _p(story, st, titulo, "h3")
        filas = [cabecera]
        for it in items:
            if clave == "metricas" or clave == "metricas_min":
                filas.append([it["metrica"], it["formula"],
                                it["umbral"], it["ref"]])
            elif clave == "bias_correction":
                filas.append([it["metodo"], it["principio"],
                                it["preserva_tendencia"], it["multivariado"],
                                it["recomendado"], it["ref"]])
            else:
                filas.append([it["metodo"], it["pesos"],
                                it["reduce"], it["ref"]])
        story.append(_tabla(filas))


def _seccion_4(story, st, d, sesion_dir: Path):
    story.append(PageBreak())
    marco = d["marco"]
    _p(story, st, marco.get("titulo", "4. Marco normativo del uso"), "h2")
    _p(story, st, marco.get("introduccion", ""))

    _p(story, st, "4.1 Marco normativo nacional (Bolivia)", "h3")
    for nombre, desc in marco.get("marco_nacional") or []:
        _p(story, st, f"<b>{nombre}</b><br/>{desc}")

    _p(story, st, "4.2 Marco internacional y referencias", "h3")
    for nombre, desc in marco.get("marco_internacional") or []:
        _p(story, st, f"<b>{nombre}</b><br/>{desc}")

    if marco.get("limites_captacion"):
        _p(story, st,
            f"4.3 {marco.get('limites_titulo', 'Límites de captación')}",
            "h3")
        cabecera = ["Normativa", "Disposición / límite", "Referencia"]
        filas = [cabecera] + list(marco["limites_captacion"])
        story.append(_tabla(filas))

    n_sec = 4
    n_sub = 4 if marco.get("limites_captacion") else 3
    if marco.get("flujo_tecnico"):
        _p(story, st, f"{n_sec}.{n_sub} Flujo técnico del análisis", "h3")
        for nombre, desc in marco["flujo_tecnico"]:
            _p(story, st, f"<b>{nombre}</b><br/>{desc}")
        n_sub += 1

    if marco.get("metodos"):
        _p(story, st,
            f"{n_sec}.{n_sub} Métodos de cálculo aplicables", "h3")
        for nombre, desc in marco["metodos"]:
            _p(story, st, f"<b>{nombre}</b><br/>{desc}")
        n_sub += 1

    if marco.get("parametros_clave"):
        _p(story, st,
            f"{n_sec}.{n_sub} Parámetros clave a reportar", "h3")
        for p in marco["parametros_clave"]:
            _p(story, st, f"• {p}")
        n_sub += 1

    if marco.get("consideraciones"):
        _p(story, st,
            f"{n_sec}.{n_sub} Consideraciones técnicas", "h3")
        _p(story, st, marco["consideraciones"])
        n_sub += 1

    # 4.7 Cálculos operacionales (si están).
    s4_7 = d.get("s4_7") or {}
    if s4_7 and s4_7.get("mejor_dist"):
        _p(story, st,
            "4.7 Cálculos operacionales — caudales mínimos para el uso",
            "h3")
        T_lista = s4_7.get("T_lista") or (2, 5, 10, 25, 50, 100)
        _p(story, st,
            f"Mejor distribución por Kolmogorov-Smirnov: "
            f"<b>{s4_7['mejor_dist']}</b> sobre "
            f"<b>{s4_7.get('n_serie', '—')} años</b> de serie.")
        cabecera = ["Período de retorno T (años)"] + [f"T = {T}" for T in T_lista]
        valores = ["Q mín T (m³/s)"] + [
            f"{s4_7['cuantiles'][T]:.3f}" for T in T_lista]
        story.append(_tabla([cabecera, valores]))
        img = _img_si_existe(sesion_dir / "qmin_frecuencia.png", ancho_cm=16)
        if img:
            story.append(img)
        # Caudal ecológico
        ce = s4_7.get("caudal_ecologico") or []
        if ce:
            _p(story, st,
                f"Q7,10 ≈ <b>{s4_7.get('q7_10', 0):.3f} m³/s</b>. Cinco "
                "métodos comparativos para el caudal ecológico residual:")
            filas = [["Método", "Descripción", "Q eco (m³/s)", "Referencia"]]
            for c in ce:
                filas.append([c.metodo, c.descripcion,
                                f"{c.q_eco_m3s:.3f}", c.referencia])
            story.append(_tabla(filas))
            img = _img_si_existe(sesion_dir / "qmin_eco.png", ancho_cm=16)
            if img:
                story.append(img)


def _seccion_5(story, st, d, sesion_dir: Path):
    story.append(PageBreak())
    s5 = d["s5"]
    _p(story, st, s5["titulo"], "h2")
    _p(story, st, s5.get("introduccion", ""))

    # 5.0 Cálculos operacionales (SPI + ranking modelos CC) si están.
    s5_0 = d.get("s5_0") or {}
    if s5_0 and (s5_0.get("plot_spi_url") or s5_0.get("modelos_evaluados")):
        _p(story, st,
            "5.0 Cálculos operacionales — SPI y evaluación de modelos CC",
            "h3")
        img = _img_si_existe(sesion_dir / "qmin_spi.png", ancho_cm=16)
        if img:
            story.append(img)
        mods = s5_0.get("modelos_evaluados") or []
        if mods:
            filas = [["#", "Modelo", "KGE", "r", "α", "β", "NSE",
                       "PBIAS (%)", "KGE_log"]]
            for i, m in enumerate(mods, 1):
                filas.append([str(i), m["modelo"],
                                f"{m['KGE']:.3f}", f"{m['r']:.3f}",
                                f"{m['alpha']:.3f}", f"{m['beta']:.3f}",
                                f"{m['NSE']:.3f}", f"{m['PBIAS']:.1f}",
                                f"{m['KGE_log']:.3f}"])
            story.append(_tabla(filas))
            img = _img_si_existe(sesion_dir / "qmin_taylor.png", ancho_cm=16)
            if img:
                story.append(img)

    # 5.1 a 5.5 — descripción de cada subsección.
    for clave, titulo in [
        ("no_estacionariedad", None),
        ("integracion", None),
        ("eventos_compuestos", None),
        ("sat", None),
        ("contextos", None),
    ]:
        bloque = s5.get(clave) or {}
        if not bloque:
            continue
        _p(story, st, bloque.get("titulo", titulo or clave), "h3")
        if bloque.get("descripcion"):
            _p(story, st, bloque["descripcion"])


def _seccion_6(story, st, d):
    story.append(PageBreak())
    _p(story, st, "6. Conclusiones y recomendaciones", "h2")
    conclusiones = d.get("s6_conclusiones") or []
    for titulo, parrafo in conclusiones:
        _p(story, st, titulo, "h3")
        _p(story, st, parrafo)
    recom = d.get("s6_recomendaciones") or {}
    if recom.get("especificas"):
        _p(story, st,
            "6.6 Recomendaciones específicas para el uso seleccionado", "h3")
        for r in recom["especificas"]:
            _p(story, st, f"• {r}")
    if recom.get("generales"):
        _p(story, st, "6.7 Recomendaciones generales", "h3")
        for r in recom["generales"]:
            _p(story, st, f"• {r}")


def _seccion_7(story, st, d):
    story.append(PageBreak())
    _p(story, st, "7. Referencias bibliográficas (APA 7.ª edición)", "h2")
    refs = d.get("s7_refs") or []
    if not refs:
        return
    n = 1
    for categoria, lista_refs in refs:
        _p(story, st, categoria, "h3")
        for r in lista_refs:
            _p(story, st, f"<b>[{n}]</b> {r}")
            n += 1


class _CanvasQmin(_CanvasConPaginado):
    """Subclase con HEADER_TEXTO específico de caudales mínimos."""

    def _dibujar_chrome(self, total: int):
        # Sobrescribimos el HEADER_TEXTO original (que dice «MAXIMOS») por
        # el de mínimos. Resto idéntico a la implementación de report.py.
        ancho, alto = self._pagesize
        n = self.getPageNumber()
        self.saveState()
        y_texto = alto - 1.2 * cm
        y_linea = alto - 1.5 * cm
        self.setFont(FONT_BOLD, 9)
        self.setFillColor(colors.HexColor("#1f3a68"))
        self.drawCentredString(ancho / 2.0, y_texto, HEADER_TEXTO_QMIN)
        self.setStrokeColor(colors.HexColor("#1f3a68"))
        self.setLineWidth(0.6)
        self.line(1.6 * cm, y_linea, ancho - 1.6 * cm, y_linea)
        y_linea_pie = 1.55 * cm
        y_texto_pie = 1.05 * cm
        self.line(1.6 * cm, y_linea_pie, ancho - 1.6 * cm, y_linea_pie)
        self.setFont(FONT, 8)
        self.setFillColor(colors.HexColor("#444444"))
        pie = (f"{FOOTER_AUTOR}   -   {FOOTER_EMAIL}   -   {FOOTER_TEL}"
               f"   -   Pag. {n} de {total}")
        self.drawCentredString(ancho / 2.0, y_texto_pie, pie)
        self.setFont(FONT, 7)
        self.setFillColor(colors.HexColor("#888888"))
        self.drawRightString(ancho - 1.6 * cm, y_texto_pie, "Info.")
        self.restoreState()


def generar_pdf_qmin(archivo, datos: dict, sesion_dir: Path) -> Path:
    """Compila el informe Q mín a PDF protegido (AES-128).

    Despacha al generador específico según el uso del agua:
    - `captacion_agua` → memoria de cálculo de agua potable (10 secciones +
      anexos A–H según skill normativo boliviano).
    - cualquier otro uso → informe genérico Q mín original (7 secciones).

    `datos` viene del worker con el mismo contenido que el contexto del
    template `qmin_resumen.html`. `sesion_dir` se usa para resolver las
    rutas de las imágenes (mapa Bolivia, cuenca, 6 mapas GEE, balance,
    FDC, series, frecuencia, eco, SPI, Taylor).
    """
    if datos.get("uso") == "captacion_agua":
        from .report_qmin_agua_potable import generar_pdf_qmin_agua_potable
        return generar_pdf_qmin_agua_potable(archivo, datos, sesion_dir)
    return _generar_pdf_qmin_generico(archivo, datos, sesion_dir)


def _generar_pdf_qmin_generico(archivo, datos: dict, sesion_dir: Path) -> Path:
    """Informe Q mín genérico para usos no-agua-potable (riego, hidro, eco)."""
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
        title=("HYDROFRA Q min - " +
                getattr(datos.get("proyecto"), "nombre_proyecto", "Informe")),
        author=FOOTER_AUTOR,
        subject=("PROTEGIDO - Comuniquese con " + FOOTER_AUTOR +
                 " - " + FOOTER_EMAIL + " - " + FOOTER_TEL),
        keywords="HYDROFRA v1.2 Q minimos; informe protegido; contacto "
                  + FOOTER_EMAIL,
        encrypt=encriptacion,
    )
    st = _estilos()
    story = []
    _portada(story, st, datos)
    _seccion_1(story, st, datos)
    _seccion_2(story, st, datos, Path(sesion_dir))
    _seccion_3(story, st, datos)
    _seccion_4(story, st, datos, Path(sesion_dir))
    _seccion_5(story, st, datos, Path(sesion_dir))
    _seccion_6(story, st, datos)
    _seccion_7(story, st, datos)
    doc.build(story, canvasmaker=_CanvasQmin)
    return archivo
