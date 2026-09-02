"""Reporte ejecutivo del HYDROFRA Dataset.

Genera un PDF con el estado vivo de la base de datos `civilmen/hydrofra-runs`
(buffer local del Space + último snapshot sincronizado a HF). Pensado para
chequear cobertura y descriptivos sin tener que cargar el dataset en pandas.

Secciones:
- Portada (fecha de corte UTC, n total, modos).
- 1. Resumen general.
- 2. Cobertura geográfica (tabla por departamento × modo).
- 3. Q máximos — tipos de obra, fuentes de P24, descriptivos.
- 4. Q mínimos — usos del agua, fuentes climáticas, descriptivos.
- 5. Apéndice — últimos 25 registros.

El PDF se genera al vuelo en cada request a `/dataset_reporte.pdf`; no se
persiste en disco, así que cada descarga refleja el estado actual del
dataset (incluyendo los registros llegados en los últimos segundos).
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer)

from .report import _estilos, _tabla
from .telemetria import HF_DATASET_REPO, cargar_registros, estado_telemetria


def _fmt(v, dec: int = 2, default: str = "—") -> str:
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v) or default
    if x != x:  # NaN
        return default
    if abs(x) >= 1000:
        return f"{x:,.0f}".replace(",", " ")
    return f"{x:.{dec}f}"


def _describe(valores: list[float]) -> dict:
    xs = [float(v) for v in valores
           if v is not None and not (isinstance(v, float) and v != v)]
    if not xs:
        return {"n": 0, "media": None, "mediana": None,
                "min": None, "max": None, "std": None}
    return {
        "n": len(xs),
        "media": statistics.fmean(xs),
        "mediana": statistics.median(xs),
        "min": min(xs),
        "max": max(xs),
        "std": statistics.pstdev(xs) if len(xs) >= 2 else 0.0,
    }


def _periodo_serie(regs: list[dict]) -> tuple[Optional[str], Optional[str]]:
    ts = [r.get("timestamp_utc") for r in regs if r.get("timestamp_utc")]
    if not ts:
        return None, None
    return min(ts)[:19], max(ts)[:19]


def _portada(story, st, regs, modos, periodo):
    story.append(Spacer(1, 2.5 * cm))
    story.append(Paragraph("HYDROFRA Dataset", st["titulo"]))
    story.append(Paragraph("Reporte ejecutivo de la base de datos",
                              st["subt_centro"]))
    story.append(Spacer(1, 0.8 * cm))

    corte = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    p_ini, p_fin = periodo
    datos = [
        ["Fecha de corte", corte],
        ["Dataset", HF_DATASET_REPO],
        ["Total de análisis", str(len(regs))],
        ["Q máximos", str(modos.get("max", 0))],
        ["Q mínimos", str(modos.get("min", 0))],
        ["Primer registro (UTC)", p_ini or "—"],
        ["Último registro (UTC)", p_fin or "—"],
    ]
    story.append(_tabla(datos, col_widths=[6 * cm, 9 * cm], cabecera=False,
                          primera_col_izq=True))
    story.append(Spacer(1, 1.0 * cm))
    story.append(Paragraph(
        "Documento auto-generado a partir del buffer local del Space + "
        "snapshot remoto en Hugging Face Datasets. Cada descarga refleja "
        "el estado vivo de la base de datos al momento del request.",
        st["italica"]))
    story.append(PageBreak())


def _sec_resumen(story, st, regs, estado):
    story.append(Paragraph("1. Resumen general", st["h2"]))
    n_total = len(regs)
    if n_total == 0:
        story.append(Paragraph(
            "El buffer local está vacío y no se pudo descargar el snapshot "
            "remoto. Verificar HF_TOKEN del Space en /hf_status, o ejecutar "
            "al menos un análisis con consent='on' para arrancar el dataset.",
            st["cuerpo"]))
        return

    modos = Counter(r.get("modo", "?") for r in regs)
    consent_ok = sum(1 for r in regs if r.get("consent"))
    proyectos = sorted({(r.get("proyecto") or "—").strip() for r in regs
                          if (r.get("proyecto") or "").strip()})
    ingenieros = sorted({(r.get("ingeniero") or "—").strip() for r in regs
                           if (r.get("ingeniero") or "").strip()})

    fila = [
        ["Métrica", "Valor"],
        ["Análisis totales", str(n_total)],
        ["Q máximos", str(modos.get("max", 0))],
        ["Q mínimos", str(modos.get("min", 0))],
        ["Con consentimiento explícito", f"{consent_ok} ({100*consent_ok/n_total:.0f} %)"],
        ["Proyectos distintos", str(len(proyectos))],
        ["Ingenieros distintos", str(len(ingenieros))],
        ["Buffer local", estado.get("buffer_local", "—")],
        ["Último sync a HF (UTC)", estado.get("ultimo_sync_ts") or "nunca"],
        ["Sync periódico cada", f"{estado.get('sync_interval_sec', '—')} s"],
    ]
    story.append(_tabla(fila, col_widths=[7 * cm, 8 * cm], primera_col_izq=True))
    story.append(Spacer(1, 0.4 * cm))


def _sec_geografia(story, st, regs):
    story.append(Paragraph("2. Cobertura geográfica", st["h2"]))
    if not regs:
        return
    by = Counter()
    for r in regs:
        dep = (r.get("departamento") or "Sin clasificar").strip()
        modo = r.get("modo", "?")
        by[(dep, modo)] += 1
    deps = sorted({d for d, _ in by})
    cab = ["Departamento", "Q máx", "Q mín", "Total"]
    filas = [cab]
    tot_max = tot_min = 0
    for d in deps:
        nm = by.get((d, "max"), 0)
        nn = by.get((d, "min"), 0)
        tot_max += nm
        tot_min += nn
        filas.append([d, str(nm), str(nn), str(nm + nn)])
    filas.append(["Total", str(tot_max), str(tot_min), str(tot_max + tot_min)])
    story.append(_tabla(filas, col_widths=[7 * cm, 2.5 * cm, 2.5 * cm, 3 * cm],
                          primera_col_izq=True))

    # Bbox real de los puntos
    lats = [r.get("lat") for r in regs if r.get("lat")]
    lons = [r.get("lon") for r in regs if r.get("lon")]
    if lats and lons:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            f"Bounding box observado: latitud [{min(lats):.3f}°, "
            f"{max(lats):.3f}°] · longitud [{min(lons):.3f}°, {max(lons):.3f}°]. "
            f"Coordenadas dentro del territorio nacional de Bolivia.",
            st["cuerpo"]))


def _sec_qmax(story, st, regs):
    qmax = [r for r in regs if r.get("modo") == "max"]
    story.append(Paragraph("3. Caudales máximos", st["h2"]))
    if not qmax:
        story.append(Paragraph("Sin registros de Q máximos.", st["cuerpo"]))
        return
    story.append(Paragraph(f"Subconjunto: <b>n = {len(qmax)}</b> análisis de Q máximos.",
                              st["cuerpo"]))

    # Tipo de obra
    obras = Counter((r.get("obra_nombre") or "—") for r in qmax)
    story.append(Paragraph("3.1 Tipo de obra hidráulica", st["h3"]))
    filas = [["Obra", "n", "%"]]
    for obra, n in obras.most_common():
        filas.append([obra, str(n), f"{100*n/len(qmax):.1f}"])
    story.append(_tabla(filas, col_widths=[10 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))

    # Fuente de precipitación adoptada
    story.append(Spacer(1, 0.3 * cm))
    fuentes = Counter((r.get("fuente_adoptada") or "—") for r in qmax)
    story.append(Paragraph("3.2 Fuente de la serie P24 adoptada", st["h3"]))
    filas = [["Fuente", "n", "%"]]
    for f, n in fuentes.most_common():
        filas.append([f, str(n), f"{100*n/len(qmax):.1f}"])
    story.append(_tabla(filas, col_widths=[10 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))

    # Descriptivos numéricos
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("3.3 Descriptivos clave", st["h3"]))
    variables = [
        ("P24 de diseño (mm)", "p24_diseno_mm", 1),
        ("T de diseño (años)", "t_diseno", 0),
        ("Área de cuenca (km²)", "area_km2", 2),
        ("Pendiente media (%)", "pendiente_pct", 2),
        ("CN ponderado", "cn_ponderado", 1),
        ("Tc adoptado (min)", "tc_min", 1),
        ("Años de serie", "n_anios_serie", 0),
    ]
    cab = ["Variable", "n", "Media", "Mediana", "Mín", "Máx", "Desv σ"]
    filas = [cab]
    for label, key, dec in variables:
        d = _describe([r.get(key) for r in qmax])
        filas.append([label, str(d["n"]),
                       _fmt(d["media"], dec), _fmt(d["mediana"], dec),
                       _fmt(d["min"], dec), _fmt(d["max"], dec),
                       _fmt(d["std"], dec)])
    story.append(_tabla(filas,
                          col_widths=[5 * cm, 1.3 * cm, 2 * cm, 2 * cm,
                                       2 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))

    # Distribución de frecuencia adoptada
    story.append(Spacer(1, 0.3 * cm))
    dists = Counter((r.get("dist_freq_adoptada") or "—") for r in qmax)
    story.append(Paragraph("3.4 Distribución de frecuencia adoptada", st["h3"]))
    filas = [["Distribución", "n", "%"]]
    for d, n in dists.most_common():
        filas.append([d, str(n), f"{100*n/len(qmax):.1f}"])
    story.append(_tabla(filas, col_widths=[10 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))


def _sec_qmin(story, st, regs):
    qmin = [r for r in regs if r.get("modo") == "min"]
    story.append(Paragraph("4. Caudales mínimos", st["h2"]))
    if not qmin:
        story.append(Paragraph("Sin registros de Q mínimos.", st["cuerpo"]))
        return
    story.append(Paragraph(f"Subconjunto: <b>n = {len(qmin)}</b> análisis de Q mínimos.",
                              st["cuerpo"]))

    # Uso del agua
    story.append(Paragraph("4.1 Uso del agua declarado", st["h3"]))
    usos = Counter((r.get("nombre_uso") or r.get("uso") or "—") for r in qmin)
    filas = [["Uso", "n", "%"]]
    for u, n in usos.most_common():
        filas.append([u, str(n), f"{100*n/len(qmin):.1f}"])
    story.append(_tabla(filas, col_widths=[10 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))

    # Fuente climática
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("4.2 Fuente de la climatología P", st["h3"]))
    fuentes = Counter((r.get("clima_fuente") or "—") for r in qmin)
    filas = [["Fuente", "n", "%"]]
    for f, n in fuentes.most_common():
        filas.append([f, str(n), f"{100*n/len(qmin):.1f}"])
    story.append(_tabla(filas, col_widths=[10 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))

    # Descriptivos
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("4.3 Descriptivos clave", st["h3"]))
    variables = [
        ("P anual (mm/año)", "pann_mm", 0),
        ("ET anual (mm/año)", "etann_mm", 0),
        ("Q medio (m³/s)", "q_medio_m3s", 3),
        ("Q90 (m³/s)", "q90_m3s", 3),
        ("Q95 (m³/s)", "q95_m3s", 3),
        ("Q7,10 (m³/s)", "q7_10_m3s", 3),
        ("Coef. escorrentía", "coef_escorrentia", 3),
    ]
    cab = ["Variable", "n", "Media", "Mediana", "Mín", "Máx", "Desv σ"]
    filas = [cab]
    for label, key, dec in variables:
        d = _describe([r.get(key) for r in qmin])
        filas.append([label, str(d["n"]),
                       _fmt(d["media"], dec), _fmt(d["mediana"], dec),
                       _fmt(d["min"], dec), _fmt(d["max"], dec),
                       _fmt(d["std"], dec)])
    story.append(_tabla(filas,
                          col_widths=[5 * cm, 1.3 * cm, 2 * cm, 2 * cm,
                                       2 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))

    # Modelos CC más usados
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("4.4 Modelos CMIP6/CORDEX top adoptados", st["h3"]))
    modelos = Counter((r.get("modelo_cc_top") or "—") for r in qmin)
    filas = [["Modelo", "n", "%"]]
    for m, n in modelos.most_common(10):
        filas.append([m, str(n), f"{100*n/len(qmin):.1f}"])
    story.append(_tabla(filas, col_widths=[10 * cm, 2 * cm, 2 * cm],
                          primera_col_izq=True))


def _sec_apendice(story, st, regs, n: int = 25):
    story.append(PageBreak())
    story.append(Paragraph(f"5. Apéndice — últimos {n} registros", st["h2"]))
    if not regs:
        return
    ordenados = sorted(regs, key=lambda r: r.get("timestamp_utc", ""),
                         reverse=True)[:n]
    cab = ["#", "Fecha UTC", "Modo", "id (8)", "Lat", "Lon",
              "Departamento", "Proyecto"]
    filas = [cab]
    for i, r in enumerate(ordenados, 1):
        filas.append([
            str(i),
            (r.get("timestamp_utc") or "—")[:19],
            r.get("modo", "—"),
            (r.get("id") or "—")[:8],
            _fmt(r.get("lat"), 3),
            _fmt(r.get("lon"), 3),
            (r.get("departamento") or "—")[:18],
            ((r.get("proyecto") or "—")[:32]),
        ])
    story.append(_tabla(filas,
                          col_widths=[0.8 * cm, 3.3 * cm, 1.2 * cm, 1.8 * cm,
                                       1.8 * cm, 1.8 * cm, 3 * cm, 5 * cm],
                          primera_col_izq=True))


def generar_pdf_dataset() -> bytes:
    """Genera el reporte y devuelve el PDF como bytes (in-memory).

    No persiste a disco: cada llamada lee el buffer local (con sync-desde-HF
    si está vacío) y construye un PDF fresco. Apto para servir directamente
    en una respuesta HTTP.
    """
    regs = cargar_registros(sync_si_vacio=True)
    estado = estado_telemetria()
    modos = Counter(r.get("modo", "?") for r in regs)
    periodo = _periodo_serie(regs)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.0 * cm, rightMargin=2.0 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title="HYDROFRA Dataset — Reporte ejecutivo",
        author="HYDROFRA",
    )
    st = _estilos()
    story = []
    _portada(story, st, regs, modos, periodo)
    _sec_resumen(story, st, regs, estado)
    _sec_geografia(story, st, regs)
    _sec_qmax(story, st, regs)
    _sec_qmin(story, st, regs)
    _sec_apendice(story, st, regs)

    doc.build(story)
    return buf.getvalue()
