"""Gráficos para diagnóstico estadístico y curvas IDF."""

from __future__ import annotations

import gc
import math
from pathlib import Path
from typing import Sequence

import matplotlib
matplotlib.use("Agg")  # backend headless, sin GUI
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .idf import ModeloIDF
from .stats import AjusteDistribucion, _posiciones_weibull  # type: ignore


# DPI reducido para minimizar memoria/tiempo en el free tier de Render
# (512 MB, CPU compartida); matplotlib + reportlab apilados llegan al borde.
_DPI = 80


def plot_serie_anual_maxima(
    serie: pd.DataFrame,
    titulo: str,
    archivo: str | Path,
) -> Path:
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(serie["anio"], serie["p24_mm"], color="#1f77b4", edgecolor="black", alpha=0.85)
    ax.axhline(serie["p24_mm"].mean(), color="red", linestyle="--", label=f"media = {serie['p24_mm'].mean():.1f} mm")
    ax.set_xlabel("Año")
    ax.set_ylabel("P24max (mm)")
    ax.set_title(titulo)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=_DPI)
    plt.close(fig)
    plt.close('all')
    gc.collect()
    return out


def plot_ajuste_distribucion(
    serie: Sequence[float],
    ajustes: Sequence[AjusteDistribucion],
    archivo: str | Path,
) -> Path:
    """Grafica los ajustes en papel de probabilidad (Weibull plotting)."""
    x = np.sort(np.asarray(serie, dtype=float))
    n = x.size
    p = _posiciones_weibull(n)
    T_emp = 1.0 / (1.0 - p)

    T_teor = np.array([2, 5, 10, 25, 50, 100, 200, 500], dtype=float)
    p_teor = 1.0 - 1.0 / T_teor

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(T_emp, x, color="black", zorder=5, label="Empírico (Weibull)")

    from .stats import _cuantil  # type: ignore
    for aj in ajustes:
        y = [_cuantil(aj, pi) for pi in p_teor]
        ax.plot(
            T_teor,
            y,
            marker="o",
            label=f"{aj.nombre}  (KS p={aj.ks_pvalor:.3f}, RMSE={aj.rmse_cuantiles:.2f})",
        )
    # Coordenadas normales (sin escala logarítmica).
    ax.set_xlabel("Período de retorno T (años)")
    ax.set_ylabel("P24max (mm)")
    ax.set_title("Ajuste de distribuciones a la serie anual máxima")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=_DPI)
    plt.close(fig)
    plt.close('all')
    gc.collect()
    return out


def plot_curvas_idf(
    modelo: ModeloIDF,
    periodos_retorno: Sequence[int],
    duraciones_min: Sequence[int],
    archivo: str | Path,
    titulo: str = "Curvas IDF (modelo de Sherman)",
) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    d = np.asarray(duraciones_min, dtype=float)
    for T in periodos_retorno:
        i = modelo.a * (T ** modelo.m) / ((d + modelo.b) ** modelo.n)
        ax.plot(d, i, marker="o", label=f"T = {T} años")
    # Coordenadas normales (sin escala logarítmica).
    ax.set_xlabel("Duración d (min)")
    ax.set_ylabel("Intensidad i (mm/h)")
    ax.set_title(titulo)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.text(
        0.5,
        -0.02,
        f"i = {modelo.a:.3f}·T^{modelo.m:.4f} / (d + {modelo.b:.3f})^{modelo.n:.4f}   "
        f"[R² = {modelo.r2:.4f}]",
        ha="center",
        fontsize=9,
        style="italic",
    )
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    plt.close('all')
    gc.collect()
    return out


def plot_tiempo_concentracion(
    resultados,
    tc_adoptado_min: float,
    archivo: str | Path,
) -> Path:
    """Barras de Tc por fórmula con línea del Tc adoptado (coordenadas normales)."""
    nombres = [r.nombre for r in resultados if r.aplicable]
    valores = [r.tc_min for r in resultados if r.aplicable]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    barras = ax.bar(range(len(nombres)), valores, color="#1f77b4",
                    edgecolor="black", alpha=0.85)
    ax.axhline(tc_adoptado_min, color="red", linestyle="--",
               label=f"Tc adoptado = {tc_adoptado_min:.1f} min")
    ax.set_xticks(range(len(nombres)))
    ax.set_xticklabels(nombres, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Tiempo de concentración (min)")
    ax.set_title("Tiempo de concentración por fórmula")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
    for b, v in zip(barras, valores):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}",
                ha="center", va="bottom", fontsize=7)
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=_DPI)
    plt.close(fig)
    plt.close('all')
    gc.collect()
    return out


def plot_hietograma(
    hietograma,
    archivo: str | Path,
    titulo: str | None = None,
) -> Path:
    """Hietograma de bloques alternos: barras de intensidad por intervalo."""
    tabla = hietograma.tabla
    dt = hietograma.delta_t_min
    # Centro de cada bloque para ubicar la barra
    centros = tabla["t_min"].to_numpy() - dt / 2.0
    intens = tabla["intensidad_mm_h"].to_numpy()

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(centros, intens, width=dt * 0.92, color="#1f5fa8",
           edgecolor="black", align="center")
    ax.set_xlabel("Tiempo (min)")
    ax.set_ylabel("Intensidad (mm/h)")
    if titulo is None:
        titulo = (f"Hietograma de bloques alternos — T = {hietograma.T_anios} años, "
                  f"D = {hietograma.duracion_min:.0f} min, Δt = {dt:.0f} min")
    ax.set_title(titulo)
    ax.grid(True, axis="y", alpha=0.3)
    # Eje secundario con profundidad incremental
    ax2 = ax.twinx()
    ax2.plot(centros, tabla["p_acumulada_mm"].to_numpy(), color="red",
             marker="o", label="P acumulada (mm)")
    ax2.set_ylabel("Profundidad acumulada (mm)", color="red")
    ax2.tick_params(axis="y", labelcolor="red")
    fig.tight_layout()
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=_DPI)
    plt.close(fig)
    plt.close('all')
    gc.collect()
    return out


def _guardar(fig, archivo, bbox=None):
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=_DPI, bbox_inches=bbox)
    plt.close(fig)
    plt.close('all')
    gc.collect()
    return out


def plot_doble_masa(dm, archivo):
    """Curva de doble masa: acumulado de la fuente adoptada vs promedio regional.

    `dm` es un doble_masa.ResultadoDobleMasa. Grafica los puntos acumulados, la
    recta de mejor ajuste y anota el R de Pearson. Devuelve None si dm es None.
    """
    if dm is None or not getattr(dm, "acum_referencia", None):
        return None
    xr = np.asarray(dm.acum_referencia, dtype=float)
    ya = np.asarray(dm.acum_analizada, dtype=float)
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    ax.plot(xr, ya, "o-", color="#1f6fb4", lw=1.4, ms=5,
            label=f"Doble masa ({dm.fuente_analizada})")
    # Recta de mejor ajuste.
    if len(xr) >= 2:
        xx = np.array([xr.min(), xr.max()])
        ax.plot(xx, dm.pendiente * xx + (ya[0] - dm.pendiente * xr[0]),
                "--", color="#cb181d", lw=1.2,
                label=f"Recta ajustada (pend. {dm.pendiente:.3f})")
    # Anotar años en algunos puntos.
    for i in range(0, len(xr), max(1, len(xr) // 6)):
        ax.annotate(str(dm.anios[i]), (xr[i], ya[i]), fontsize=7,
                    textcoords="offset points", xytext=(4, -8), color="#555")
    ax.set_xlabel("Precipitación acumulada — promedio regional (mm)")
    ax.set_ylabel(f"Precipitación acumulada — {dm.fuente_analizada} (mm)")
    ax.set_title(f"Curva de doble masa  ·  R = {dm.pearson_r:.4f}  ·  "
                 f"n = {dm.n_anios} años\nReferencia: "
                 f"{', '.join(dm.fuentes_referencia)}", fontsize=9.5)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    return _guardar(fig, archivo, bbox="tight")


def plot_series_satelitales(serie_estacion, series_satelitales, archivo,
                            nombre_estacion="Estación"):
    """Compara la serie de la estación con las series satelitales (líneas)."""
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(serie_estacion["anio"], serie_estacion["p24_mm"], marker="o",
            color="black", linewidth=2, label=nombre_estacion)
    for s in series_satelitales:
        etiqueta = s.fuente + ("" if s.exitosa else " (sintético)")
        ax.plot(s.df["anio"], s.df["p24_mm"], marker=".", alpha=0.85, label=etiqueta)
    ax.set_xlabel("Año")
    ax.set_ylabel("P24max (mm)")
    ax.set_title("P24max anual: estación vs. fuentes satelitales")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_correlacion(serie_estacion, series_satelitales, archivo):
    """Dispersión estación (x) vs cada fuente satelital (y) en años comunes."""
    import pandas as pd
    fig, ax = plt.subplots(figsize=(8, 8))
    todo = []
    for s in series_satelitales:
        m = pd.merge(serie_estacion, s.df, on="anio", suffixes=("_est", "_sat"))
        if len(m) >= 3:
            ax.scatter(m["p24_mm_est"], m["p24_mm_sat"], alpha=0.7, label=s.fuente)
            todo.extend(m["p24_mm_est"].tolist() + m["p24_mm_sat"].tolist())
    if todo:
        lo, hi = min(todo), max(todo)
        ax.plot([lo, hi], [lo, hi], "k--", alpha=0.6, label="1:1")
    ax.set_xlabel("P24max estación (mm)")
    ax.set_ylabel("P24max satelital (mm)")
    ax.set_title("Correlación estación vs. satélite (años comunes)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_modelos_idf(modelos, periodos_retorno, duraciones_min, archivo,
                     T_destacado=100):
    """Compara los modelos IDF para un T destacado (coordenadas normales)."""
    d = np.asarray(duraciones_min, dtype=float)
    fig, ax = plt.subplots(figsize=(10, 6))
    for mod in modelos:
        i = np.array([mod.intensidad(T_destacado, dd) for dd in d])
        ax.plot(d, i, marker=".", label=f"{mod.nombre} (R²={mod.r2:.3f})")
    ax.set_xlabel("Duración d (min)")
    ax.set_ylabel("Intensidad i (mm/h)")
    ax.set_title(f"Comparación de modelos IDF — T = {T_destacado} años")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_modelo_idf_curvas(modelo, periodos_retorno, duraciones_min, archivo):
    """Curvas IDF (varios T) de un modelo dado, en coordenadas normales."""
    d = np.asarray(duraciones_min, dtype=float)
    fig, ax = plt.subplots(figsize=(10, 6))
    for T in periodos_retorno:
        i = np.array([modelo.intensidad(T, dd) for dd in d])
        ax.plot(d, i, marker="o", label=f"T = {T} años")
    ax.set_xlabel("Duración d (min)")
    ax.set_ylabel("Intensidad i (mm/h)")
    ax.set_title(f"Curvas IDF — {modelo.nombre}")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_hietograma_comparado(hietogramas: dict, archivo):
    """Compara hietogramas (3 o 4 métodos) en una grilla optimizada para la página.

    Para 4 métodos usa una grilla 2×2 (más amigable que 1×4 alargada) y un
    tamaño base grande para que el gráfico llene la página letter manteniendo
    aspecto legible. Para 3 o menos, mantiene fila única ampliada.
    """
    n = len(hietogramas)
    if n == 4:
        nrows, ncols = 2, 2
        fig, axes = plt.subplots(nrows, ncols, figsize=(13, 11),
                                  sharex=False, sharey=True)
        axes_flat = axes.flatten()
    else:
        nrows, ncols = 1, max(n, 1)
        fig, axes = plt.subplots(nrows, ncols, figsize=(7.5 * ncols, 6.5),
                                  sharey=True)
        axes_flat = [axes] if n == 1 else list(axes)

    for ax, (nombre, h) in zip(axes_flat, hietogramas.items()):
        centros = h.tabla["t_min"].to_numpy() - h.delta_t_min / 2.0
        ax.bar(centros, h.tabla["intensidad_mm_h"].to_numpy(),
               width=h.delta_t_min * 0.9, color="#1f5fa8", edgecolor="black")
        ax.set_title(
            f"{nombre}\nP = {h.p_total_mm:.0f} mm  ·  i pico = "
            f"{h.i_pico_mm_h:.0f} mm/h",
            fontsize=11)
        ax.set_xlabel("t (min)", fontsize=10)
        ax.tick_params(axis="both", labelsize=9)
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_ylabel("Intensidad (mm/h)", fontsize=10)
    # Para grilla 2×2: ocultar ejes vacíos si hubiera menos hietogramas.
    for ax in axes_flat[len(hietogramas):]:
        ax.axis("off")
    fig.tight_layout(pad=2.0, h_pad=3.0, w_pad=2.0)
    return _guardar(fig, archivo)


def plot_curva_hipsometrica(analisis, archivo):
    """Curva hipsométrica (% área acumulada vs altura relativa) + bandas de elevación.

    Panel izquierdo: la curva hipsométrica clásica (x = % de área por encima,
    y = altura relativa) con la integral hipsométrica sombreada. Panel derecho:
    histograma de frecuencias altimétricas (% de área por banda de elevación).
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6))

    x = np.asarray(analisis.hipso_area_pct)
    y = np.asarray(analisis.hipso_altura_rel)
    ax1.plot(x, y, color="#1f3a68", lw=2.2, zorder=3)
    ax1.fill_between(x, y, color="#9ec3e6", alpha=0.45, zorder=1)
    ax1.set_xlabel("Área acumulada por encima (%)")
    ax1.set_ylabel("Altura relativa  h* = (h−Hmin)/(Hmax−Hmin)")
    ax1.set_xlim(0, 100)
    ax1.set_ylim(0, 1)
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"Curva hipsométrica — HI = {analisis.integral_hipsometrica:.3f}",
                  fontsize=10)
    ax1.text(0.5, 0.92, analisis.estado_cuenca.split('(')[0].strip(),
             transform=ax1.transAxes, ha="center", fontsize=8.5,
             color="#264a82", style="italic")

    bandas = analisis.bandas_elevacion
    etiquetas = [f"{b.desde_m:.0f}–{b.hasta_m:.0f}" for b in bandas]
    pcts = [b.pct for b in bandas]
    ypos = np.arange(len(bandas))
    ax2.barh(ypos, pcts, color="#4477b3", edgecolor="black", alpha=0.85)
    ax2.set_yticks(ypos)
    ax2.set_yticklabels(etiquetas, fontsize=8)
    ax2.invert_yaxis()
    ax2.set_xlabel("Área de la cuenca (%)")
    ax2.set_ylabel("Banda de elevación (m s.n.m.)")
    ax2.set_title("Distribución altimétrica", fontsize=10)
    ax2.grid(True, axis="x", alpha=0.3)
    for i, p in enumerate(pcts):
        ax2.text(p + 0.4, i, f"{p:.1f}%", va="center", fontsize=7.5)

    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_caudal_maximo(qmax_tabla, archivo):
    """Compara Q(T) de los cinco métodos en escala semilogarítmica (T en log)."""
    fig, ax = plt.subplots(figsize=(10, 5.2))
    T = qmax_tabla["T_anios"].to_numpy()
    metodos = [
        ("Q_racional",     "Racional",                "#1f3a68", "o"),
        ("Q_racional_mod", "Racional Modif. (Témez)", "#3b8bd8", "s"),
        ("Q_mac_math",     "Mac Math",                "#e67e22", "^"),
        ("Q_scs",          "SCS HU Triangular",       "#27ae60", "D"),
        ("Q_verni_king",   "Verni-King",              "#c0392b", "v"),
    ]
    for col, etq, color, marker in metodos:
        if col not in qmax_tabla.columns:
            continue
        ax.plot(T, qmax_tabla[col].to_numpy(), color=color, marker=marker,
                lw=1.8, ms=6, label=etq, alpha=0.92)
    ax.set_xscale("log")
    ax.set_xlabel("Período de retorno T (años)")
    ax.set_ylabel("Caudal máximo Q (m³/s)")
    ax.set_title("Caudal máximo por período de retorno — cinco métodos",
                 fontsize=11)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8.5, loc="upper left")
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_hietogramas_familia_T(hietogramas_por_T, metodo: str, archivo):
    """Superpone los hietogramas del mismo método para todos los T como barras
    centradas (eje t en min, eje i en mm/h). Útil para ver la familia de
    tormentas de diseño por método.
    """
    fig, ax = plt.subplots(figsize=(10, 4.6))
    Ts = sorted(hietogramas_por_T.keys())
    cmap = plt.cm.viridis
    for k, T in enumerate(Ts):
        h = hietogramas_por_T[T].get(metodo)
        if h is None:
            continue
        centros = h.tabla["t_min"].to_numpy() - h.delta_t_min / 2.0
        color = cmap(k / max(len(Ts) - 1, 1))
        ax.step(centros, h.tabla["intensidad_mm_h"].to_numpy(),
                where="mid", color=color, lw=1.4, label=f"T = {T} años")
    ax.set_xlabel("Tiempo t (min)")
    ax.set_ylabel("Intensidad i (mm/h)")
    titulos = {"bloques": "Bloques alternos", "scs": "SCS Tipo II",
               "chicago": "Chicago", "huff": "Huff (cuartil 2, mediana)"}
    ax.set_title(f"Hietogramas por período de retorno — {titulos.get(metodo, metodo)}",
                 fontsize=10.5)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=4, loc="upper right")
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_hec_perdidas(hec_resultado, archivo):
    """Lluvia acumulada P vs lluvia efectiva Pe acumulada (método SCS-CN)."""
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    t = hec_resultado.tabla["t_min"].to_numpy()
    P = hec_resultado.tabla["P_mm"].to_numpy()
    Pe = hec_resultado.tabla["Pe_mm"].to_numpy()
    ax.plot(t, P, color="#1f3a68", lw=2, label="Lluvia bruta P (mm)")
    ax.plot(t, Pe, color="#d7191c", lw=2,
            label="Lluvia efectiva Pe (mm) — SCS-CN")
    ax.fill_between(t, Pe, P, color="#a6cee3", alpha=0.45,
                    label="Pérdidas (Ia + infiltración)")
    ax.set_xlabel("Tiempo t (min)")
    ax.set_ylabel("Lámina acumulada (mm)")
    ax.set_title(f"Pérdidas SCS-CN — T = {hec_resultado.T_anios} años",
                 fontsize=10.5)
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_hec_hu(delta_t_min, tc_min, area_km2, archivo):
    """Hidrograma unitario SCS triangular (para 1 mm de lluvia efectiva)."""
    from .hec_hms_sim import hu_scs_triangular
    hu = hu_scs_triangular(delta_t_min, tc_min, area_km2)
    t = np.arange(len(hu)) * delta_t_min / 60.0
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    ax.plot(t, hu, color="#1f3a68", lw=2)
    ax.fill_between(t, hu, color="#9ec3e6", alpha=0.45)
    ax.axvline(t[int(np.argmax(hu))], color="#d7191c", lw=1, ls="--",
               label=f"Tp = {t[int(np.argmax(hu))]:.2f} h")
    ax.set_xlabel("Tiempo (h)")
    ax.set_ylabel("Q unitario (m³/s por mm)")
    ax.set_title("Hidrograma unitario SCS triangular", fontsize=10.5)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_hec_hidrogramas_familia(hec_por_T, archivo):
    """Hidrogramas Q(t) para los 9 períodos de retorno (familia HEC-HMS)."""
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    Ts = sorted(hec_por_T.keys())
    cmap = plt.cm.viridis
    for k, T in enumerate(Ts):
        r = hec_por_T[T]
        t = r.tabla["t_min"].to_numpy() / 60.0
        Q = r.tabla["Q_m3s"].to_numpy()
        ax.plot(t, Q, color=cmap(k / max(len(Ts) - 1, 1)),
                lw=1.6, label=f"T = {T} a — Qp = {r.Q_pico_m3s:.0f} m³/s")
    ax.set_xlabel("Tiempo (h)")
    ax.set_ylabel("Caudal Q (m³/s)")
    ax.set_title("Hidrogramas de escorrentía directa — modelación HEC-HMS",
                 fontsize=10.5)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, ncol=2, loc="upper right")
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_hec_qpico_vs_T(hec_por_T, archivo):
    """Qpico vs T (escala log T) y volumen vs T."""
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    Ts = sorted(hec_por_T.keys())
    Qp = [hec_por_T[T].Q_pico_m3s for T in Ts]
    Vol = [hec_por_T[T].volumen_directo_hm3 for T in Ts]
    ax.plot(Ts, Qp, color="#1f3a68", marker="o", lw=2, ms=7,
            label="Q pico (m³/s)")
    ax.set_xscale("log")
    ax.set_xlabel("Período de retorno T (años)")
    ax.set_ylabel("Caudal pico Q (m³/s)", color="#1f3a68")
    ax.tick_params(axis="y", labelcolor="#1f3a68")
    ax.grid(True, which="both", alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(Ts, Vol, color="#d7191c", marker="s", lw=1.6, ms=6,
             label="Volumen directo (hm³)")
    ax2.set_ylabel("Volumen directo (hm³)", color="#d7191c")
    ax2.tick_params(axis="y", labelcolor="#d7191c")
    ax.set_title("HEC-HMS: caudal pico y volumen directo por período de retorno",
                 fontsize=10.5)
    fig.tight_layout()
    return _guardar(fig, archivo)


def plot_tirante(resultado, archivo):
    """Perfil longitudinal del cauce con lámina de agua + secciones transversales.

    `resultado` es un `hidraulica_fluvial.ResultadoTirante`. Panel superior:
    cota mínima de fondo y superficie del agua (WSE) a lo largo del thalweg.
    Paneles inferiores: hasta tres secciones (aguas arriba, control, aguas
    abajo) con el fondo y el nivel de agua rellenado.
    """
    secc = [s for s in resultado.secciones if np.isfinite(s.tirante_m)]
    fig = plt.figure(figsize=(10, 7.2))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.1], hspace=0.42, wspace=0.28)

    # ── Panel superior: perfil longitudinal ──
    ax0 = fig.add_subplot(gs[0, :])
    if secc:
        _g = 9.81
        est = np.array([s.estacion_m for s in secc])
        z_fondo = np.array([float(np.nanmin(s.z_m)) for s in secc])
        wse = np.array([s.wse_m for s in secc])
        # Línea de energía (design): E = WSE + V²/2g.
        egl = np.array([s.wse_m + (s.velocidad_ms ** 2) / (2 * _g)
                        if np.isfinite(s.velocidad_ms) else s.wse_m
                        for s in secc])
        ax0.fill_between(est, z_fondo, wse, color="#a6cee3", alpha=0.6,
                         label="Lámina de agua")
        ax0.plot(est, z_fondo, color="#6b4423", lw=2.0, label="Fondo del cauce")
        ax0.plot(est, wse, color="#1f6fb4", lw=1.8, ls="--",
                 label=f"NAME diseño T{resultado.T_diseno} (WSE)")
        ax0.plot(est, egl, color="#e6550d", lw=1.1, ls=":",
                 label="Línea de energía (E = WSE + V²/2g)")
        # Perfil gradualmente variado (standard-step), si está disponible.
        gvf = getattr(resultado, "perfil_gvf", None)
        if gvf:
            eg = np.array([p["estacion_m"] for p in gvf])
            wg = np.array([p["wse"] for p in gvf])
            ax0.plot(eg, wg, color="#6a51a3", lw=1.7, ls="-",
                     marker="o", ms=3,
                     label="WSE gradualmente variado (paso estándar)")
        # NAME de verificación (T500) si hay secciones de verificación.
        scv = [s for s in getattr(resultado, "secciones_verif", [])
               if np.isfinite(getattr(s, "wse_m", float("nan")))]
        if scv and resultado.T_verif:
            estv = np.array([s.estacion_m for s in scv])
            wsev = np.array([s.wse_m for s in scv])
            ax0.plot(estv, wsev, color="#cb181d", lw=1.6, ls="-.",
                     label=f"NAME verificación T{resultado.T_verif}")
        # Cara inferior de la viga = cota de fondo (control) + altura de la viga
        # sobre el fondo (NAME diseño + gálibo). cota_viga_sobre_fondo_m es
        # una ALTURA sobre el lecho; se lleva a cota absoluta con z del fondo.
        cota_viga = getattr(resultado, "cota_viga_sobre_fondo_m", None)
        if cota_viga is not None and getattr(resultado, "galibo_m", None):
            z_ctrl = float(z_fondo[len(secc) // 2])
            ax0.axhline(z_ctrl + cota_viga, color="#333333", lw=1.2,
                        ls=(0, (6, 3)),
                        label=f"Cara inferior viga (gálibo {resultado.galibo_m:.1f} m)")
        ax0.set_xlabel("Estación a lo largo del cauce (m)")
        ax0.set_ylabel("Cota (m s.n.m.)")
    ax0.set_title(
        f"Perfil longitudinal — Q(T={resultado.T_diseno}) = "
        f"{resultado.Q_m3s:.1f} m³/s · n = {resultado.n_manning:.3f} · "
        f"S = {resultado.S_cauce * 100:.2f} %", fontsize=10.5)
    ax0.grid(True, alpha=0.3)
    ax0.legend(fontsize=8, loc="best")

    # ── Paneles inferiores: secciones representativas ──
    if secc:
        idx = sorted({0, len(secc) // 2, len(secc) - 1})
        etiquetas = {0: "Aguas arriba",
                     len(secc) // 2: "Sección de control (punto)",
                     len(secc) - 1: "Aguas abajo"}
    else:
        idx = []
    for col, i in enumerate(idx[:3]):
        ax = fig.add_subplot(gs[1, col])
        s = secc[i]
        x = np.asarray(s.x_local_m, dtype=float)
        z = np.asarray(s.z_m, dtype=float)
        ax.plot(x, z, color="#6b4423", lw=1.8)
        agua = np.minimum(z, s.wse_m)
        ax.fill_between(x, agua, s.wse_m, where=(s.wse_m > z),
                        color="#a6cee3", alpha=0.7, interpolate=True)
        ax.axhline(s.wse_m, color="#1f6fb4", lw=1.0, ls="--")
        ax.set_title(f"{etiquetas.get(i, 'Sección')}\n"
                     f"y = {s.tirante_m:.2f} m · V = {s.velocidad_ms:.2f} m/s "
                     f"· Fr = {s.froude:.2f}", fontsize=8.5)
        ax.set_xlabel("Abscisa transversal (m)", fontsize=8)
        if col == 0:
            ax.set_ylabel("Cota (m)", fontsize=8)
        ax.tick_params(labelsize=7.5)
        ax.grid(True, alpha=0.3)

    fig.suptitle("Cálculo de tirante (calado) — método del tirante normal "
                 "(Manning) por sección", fontsize=11.5, y=0.98)
    return _guardar(fig, archivo, bbox="tight")


def plot_tirante_planta(resultado, archivo):
    """Vista en planta del tramo de análisis: cauce principal (thalweg), las 11
    secciones transversales (traza perpendicular) y el punto del proyecto.

    `resultado` es un hidraulica_fluvial.ResultadoTirante con thalweg_lonlat
    (Nx2 [lon,lat]). Si no hay thalweg (geometría estimada sin DEM), no genera
    gráfico y devuelve None.
    """
    thal = getattr(resultado, "thalweg_lonlat", None)
    if thal is None:
        return None
    thal = np.asarray(thal, dtype=float)
    if thal.ndim != 2 or len(thal) < 2:
        return None
    lat0 = float(np.mean(thal[:, 1]))
    m_lon = 111412.84 * math.cos(math.radians(lat0))
    m_lat = 111132.92 - 559.82 * math.cos(2 * math.radians(lat0))
    ancho = float(getattr(resultado, "ancho_seccion_m", 40.0))

    fig, ax = plt.subplots(figsize=(9, 8))
    # Cauce principal (thalweg).
    ax.plot(thal[:, 0], thal[:, 1], color="#1f6fb4", lw=2.2, zorder=3,
            label="Cauce principal (thalweg)")

    # Trazas perpendiculares de cada sección.
    secc = getattr(resultado, "secciones", []) or []
    n = len(secc)
    for k, s in enumerate(secc):
        c = getattr(s, "centro_lonlat", None)
        if c is None or not np.all(np.isfinite(c)):
            continue
        lon_c, lat_c = float(c[0]), float(c[1])
        # Dirección local del thalweg (por el vértice más cercano).
        d = np.hypot((thal[:, 0] - lon_c) * m_lon, (thal[:, 1] - lat_c) * m_lat)
        j = int(np.argmin(d))
        j0, j1 = max(0, j - 1), min(len(thal) - 1, j + 1)
        dx = (thal[j1, 0] - thal[j0, 0]) * m_lon
        dy = (thal[j1, 1] - thal[j0, 1]) * m_lat
        norm = math.hypot(dx, dy) or 1.0
        # Perpendicular unitaria (en metros) → a grados.
        px, py = -dy / norm, dx / norm
        half = ancho / 2.0
        x1 = lon_c + (px * half) / m_lon; y1 = lat_c + (py * half) / m_lat
        x2 = lon_c - (px * half) / m_lon; y2 = lat_c - (py * half) / m_lat
        es_control = (k == n // 2)
        ax.plot([x1, x2], [y1, y2],
                color="#c0392b" if es_control else "#e67e22",
                lw=2.0 if es_control else 1.2, zorder=4)
        ax.annotate(str(k + 1), (lon_c, lat_c), fontsize=7, ha="center",
                    va="center", zorder=6,
                    bbox=dict(boxstyle="circle,pad=0.15", fc="white",
                              ec="#555", lw=0.5))

    # Punto del proyecto.
    p = getattr(resultado, "punto_lonlat", None)
    if p is not None and np.all(np.isfinite(p)):
        ax.plot(p[0], p[1], marker="*", color="#c0392b", ms=18, zorder=7,
                label="Punto del proyecto (sección de control)")

    ax.set_xlabel("Longitud (°)")
    ax.set_ylabel("Latitud (°)")
    ax.set_aspect(m_lat / m_lon)
    ax.set_title("Vista en planta — secciones de análisis sobre el cauce "
                 "(5 aguas arriba · punto · 5 aguas abajo)", fontsize=10.5)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    return _guardar(fig, archivo, bbox="tight")


def plot_alcantarilla_curva(alc, archivo):
    """Curva de funcionamiento de la alcantarilla: HW/D vs Q (y velocidad de
    salida), con marcas del Q de diseño y de verificación y del criterio HW/D."""
    filas = getattr(alc, "curva_funcionamiento", None)
    if not filas:
        return None
    Q = [f["Q_m3s"] for f in filas]
    hwd = [f["HW_D"] for f in filas]
    V = [f["V_ms"] for f in filas]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    ax.plot(Q, hwd, "-o", color="#1f3a68", lw=1.8, ms=4, label="HW/D")
    ax.axhline(alc.criterio_hw_d, color="#c0392b", ls="--", lw=1.2,
               label=f"Criterio HW/D = {alc.criterio_hw_d:.1f}")
    ax.axhline(1.5, color="#e67e22", ls=":", lw=1.0, label="HW/D = 1.5 (desborde)")
    if alc.Q_diseno_m3s:
        ax.axvline(alc.Q_diseno_m3s, color="#27ae60", ls="-", lw=1.0,
                   label=f"Q diseño = {alc.Q_diseno_m3s:.1f} m³/s")
    if alc.Q_verif_m3s:
        ax.axvline(alc.Q_verif_m3s, color="#8e44ad", ls="-", lw=1.0,
                   label=f"Q verif = {alc.Q_verif_m3s:.1f} m³/s")
    ax.set_xlabel("Caudal Q (m³/s)")
    ax.set_ylabel("HW/D  (carga a la entrada / alto)")
    _des = alc.recomendada.designacion if alc.recomendada else ""
    ax.set_title(f"Curva de funcionamiento — {_des}", fontsize=11)
    ax.grid(True, alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(Q, V, "-s", color="#7f8c8d", lw=1.0, ms=3, alpha=0.8,
             label="V salida")
    ax2.set_ylabel("Velocidad de salida (m/s)", color="#7f8c8d")
    ax2.tick_params(axis="y", labelcolor="#7f8c8d")
    ax.legend(fontsize=7.5, loc="upper left")
    fig.tight_layout()
    return _guardar(fig, archivo, bbox="tight")


def plot_alcantarilla_perfil(alc, archivo):
    """Perfil (curva de remanso) esquemático: tirantes antes, a la entrada, en
    el barril y a la salida de la alcantarilla, más el nivel aguas abajo."""
    p = getattr(alc, "perfil", None)
    if not p:
        return None
    So = alc.pendiente_pct / 100.0
    L = alc.long_m
    alto = (alc.recomendada.H_m or alc.recomendada.D_m or 1.0
            ) if alc.recomendada else 1.0
    # Estaciones: pozo aguas arriba (-0.3L), entrada (0), salida (L), TW (1.3L).
    x0, xi, xo, xt = -0.3 * L, 0.0, L, 1.3 * L
    # Cota de fondo: horizontal aguas arriba, pendiente en el barril, horiz. abajo.
    z_i = 0.0
    z_o = z_i - L * So
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    # Fondo / conducto.
    ax.plot([x0, xi], [z_i, z_i], color="#5b4636", lw=2)
    ax.plot([xi, xo], [z_i, z_o], color="#5b4636", lw=2)
    ax.plot([xo, xt], [z_o, z_o], color="#5b4636", lw=2)
    # Techo del barril.
    ax.plot([xi, xo], [z_i + alto, z_o + alto], color="#5b4636", lw=1.5, ls="--")
    # Lámina de agua (WSE) en los puntos de control.
    wse = [z_i + p["hw_pozo_m"], z_i + p["y_entrada_m"],
           z_o + p["y_salida_m"], z_o + p["tw_m"]]
    ax.plot([x0, xi, xo, xt], wse, "-o", color="#2980b9", lw=2, ms=5,
            label="Lámina de agua")
    etiquetas = [f"Antes\n{p['hw_pozo_m']:.2f} m", f"Entrada\n{p['y_entrada_m']:.2f} m",
                 f"Salida\n{p['y_salida_m']:.2f} m", f"Aguas abajo\n{p['tw_m']:.2f} m"]
    for x, y, txt in zip([x0, xi, xo, xt], wse, etiquetas):
        ax.annotate(txt, (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=7.5, color="#1f3a68")
    ax.set_xlabel("Distancia (m)")
    ax.set_ylabel("Cota relativa (m)")
    _des = alc.recomendada.designacion if alc.recomendada else ""
    ax.set_title(f"Perfil hidráulico (remanso) — {_des} · control de "
                 f"{p['control']}", fontsize=10.5)
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    return _guardar(fig, archivo, bbox="tight")
