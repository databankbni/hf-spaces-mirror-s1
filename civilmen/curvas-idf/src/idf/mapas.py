"""Mapas esquemáticos de la cuenca (procedurales).

IMPORTANTE: estos mapas son ESQUEMÁTICOS, generados de forma sintética y
determinística a partir de la coordenada y la morfología estimada. NO provienen
de un DEM ni de delineación SIG real. Sirven para ilustrar el tipo de cartografía
requerida (cuenca, red de drenaje, uso de suelo, cobertura vegetal, CN, isoyetas).
Para diseño definitivo deben reemplazarse por mapas derivados de DEM (ALOS PALSAR)
y coberturas oficiales (CORINE/ESA WorldCover) en QGIS/ArcGIS/GEE.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.path import Path as MplPath

_DPI = 70
_NOTA = "ESQUEMÁTICO — no es delineación DEM real (ver §10.1)"


@dataclass
class GeometriaCuenca:
    poligono: np.ndarray        # (N,2) en km relativos al exutorio
    cauce: np.ndarray           # (M,2) cauce principal
    tributarios: list           # lista de (K,2)
    extent: tuple               # (xmin, xmax, ymin, ymax)


def construir_geometria(lat, lon, morf) -> GeometriaCuenca:
    """Genera un polígono de cuenca irregular + red de drenaje (determinístico)."""
    rng = np.random.default_rng(abs(hash((round(lat, 4), round(lon, 4)))) % (2**32))
    # Dimensiones desde morfología: largo Lb, ancho W
    Lb = morf.long_cauce_km
    W = max(morf.area_km2 / Lb, Lb * 0.15)
    # Polígono: elipse perturbada, eje mayor vertical (norte-sur)
    th = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    rad = 1.0 + 0.18 * rng.standard_normal(len(th))
    rad = np.clip(rad, 0.6, 1.5)
    # suavizar
    rad = np.convolve(np.r_[rad[-3:], rad, rad[:3]], np.ones(5) / 5, "same")[3:-3]
    x = (W / 2) * rad * np.cos(th)
    y = (Lb / 2) * rad * np.sin(th)
    poligono = np.column_stack([x, y])
    poligono = np.vstack([poligono, poligono[0]])

    # Exutorio en el extremo inferior; cabecera arriba
    exutorio = np.array([0.0, -Lb / 2 * 0.92])
    cabecera = np.array([rng.uniform(-W * 0.15, W * 0.15), Lb / 2 * 0.85])
    n = 14
    t = np.linspace(0, 1, n)
    serp = 0.12 * W * np.sin(np.linspace(0, 3 * np.pi, n)) * (1 - t)
    cauce = np.column_stack([
        exutorio[0] + (cabecera[0] - exutorio[0]) * t + serp,
        exutorio[1] + (cabecera[1] - exutorio[1]) * t,
    ])

    # Tributarios: desde puntos del cauce hacia los flancos
    tributarios = []
    for frac in (0.3, 0.5, 0.7):
        idx = int(frac * (n - 1))
        base = cauce[idx]
        lado = 1 if rng.random() > 0.5 else -1
        fin = np.array([lado * W * rng.uniform(0.3, 0.48),
                        base[1] + rng.uniform(-0.1, 0.2) * Lb])
        k = 8
        tt = np.linspace(0, 1, k)
        trib = np.column_stack([base[0] + (fin[0] - base[0]) * tt,
                                base[1] + (fin[1] - base[1]) * tt
                                + 0.04 * W * np.sin(np.linspace(0, 2 * np.pi, k))])
        tributarios.append(trib)

    m = 0.15
    extent = (x.min() - m * W, x.max() + m * W, y.min() - m * Lb, y.max() + m * Lb)
    return GeometriaCuenca(poligono, cauce, tributarios, extent)


def _base_ax(geo, titulo, ax):
    ax.plot(geo.poligono[:, 0], geo.poligono[:, 1], color="black", lw=1.8)
    ax.set_aspect("equal")
    ax.set_xlabel("Este relativo (km)")
    ax.set_ylabel("Norte relativo (km)")
    ax.set_title(titulo)
    ax.text(0.5, -0.12, _NOTA, transform=ax.transAxes, ha="center",
            fontsize=7, style="italic", color="#777")


def _clip(artista, geo, ax):
    path = MplPath(geo.poligono)
    artista.set_clip_path(path, transform=ax.transData)


def _malla(geo, nx=70, ny=90):
    x0, x1, y0, y1 = geo.extent
    gx = np.linspace(x0, x1, nx)
    gy = np.linspace(y0, y1, ny)
    return np.meshgrid(gx, gy)


def _ruido_suave(X, Y, rng, escala=0.6):
    """Campo de valor-ruido suave en [0,1] (suma de senoides aleatorias)."""
    Z = np.zeros_like(X)
    for _ in range(5):
        fx, fy = rng.uniform(0.3, 1.2, 2) / escala
        ph = rng.uniform(0, 2 * np.pi)
        amp = rng.uniform(0.5, 1.0)
        Z += amp * np.sin(fx * X + ph) * np.cos(fy * Y + ph)
    Z = (Z - Z.min()) / (Z.max() - Z.min() + 1e-9)
    return Z


def _guardar(fig, archivo):
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    plt.close("all")
    gc.collect()
    return out


def mapa_cuenca(geo, morf, archivo):
    fig, ax = plt.subplots(figsize=(5.2, 6.0))
    ax.fill(geo.poligono[:, 0], geo.poligono[:, 1], color="#cfe3f7", alpha=0.6)
    _base_ax(geo, "Mapa de la cuenca y cauce principal", ax)
    ax.plot(geo.cauce[:, 0], geo.cauce[:, 1], color="#1f5fa8", lw=2.2, label="Cauce principal")
    for tr in geo.tributarios:
        ax.plot(tr[:, 0], tr[:, 1], color="#3a86c8", lw=1.2)
    ax.plot(geo.cauce[0, 0], geo.cauce[0, 1], "rv", ms=10, label="Exutorio")
    ax.legend(fontsize=8, loc="upper right")
    ax.text(0.02, 0.02, f"A = {morf.area_km2:.1f} km²  L = {morf.long_cauce_km:.1f} km\n"
            f"Ff = {morf.ff_horton:.2f}  Kc = {morf.kc_gravelius:.2f}",
            transform=ax.transAxes, fontsize=8,
            bbox=dict(boxstyle="round", fc="white", ec="#999", alpha=0.9))
    return _guardar(fig, archivo)


def mapa_red_drenaje(geo, archivo):
    fig, ax = plt.subplots(figsize=(5.2, 6.0))
    _base_ax(geo, "Mapa de red de drenaje", ax)
    ax.plot(geo.cauce[:, 0], geo.cauce[:, 1], color="#08519c", lw=2.6, label="Orden mayor")
    for tr in geo.tributarios:
        ax.plot(tr[:, 0], tr[:, 1], color="#3182bd", lw=1.4)
        # sub-tributarios
        mid = tr[len(tr) // 2]
        ax.plot([mid[0], mid[0] + 0.4], [mid[1], mid[1] + 0.5], color="#6baed6", lw=0.9)
    ax.plot(geo.cauce[0, 0], geo.cauce[0, 1], "rv", ms=10, label="Punto de cierre")
    ax.legend(fontsize=8, loc="upper right")
    return _guardar(fig, archivo)


def _mapa_categorico(geo, archivo, titulo, categorias, colores, semilla):
    rng = np.random.default_rng(semilla)
    X, Y = _malla(geo)
    Z = _ruido_suave(X, Y, rng)
    n = len(categorias)
    bordes = np.linspace(0, 1, n + 1)
    clases = np.digitize(Z, bordes[1:-1])
    cmap = ListedColormap(colores)
    norm = BoundaryNorm(np.arange(-0.5, n + 0.5), cmap.N)
    fig, ax = plt.subplots(figsize=(5.2, 6.0))
    pc = ax.pcolormesh(X, Y, clases, cmap=cmap, norm=norm, shading="auto")
    _clip(pc, geo, ax)
    _base_ax(geo, titulo, ax)
    ax.plot(geo.cauce[:, 0], geo.cauce[:, 1], color="navy", lw=1.2)
    cbar = fig.colorbar(pc, ax=ax, ticks=range(n), shrink=0.7)
    cbar.ax.set_yticklabels(categorias, fontsize=7)
    return _guardar(fig, archivo)


def mapa_uso_suelo(geo, archivo):
    cats = ["Agrícola", "Pastizal", "Urbano", "Bosque", "Suelo desnudo"]
    cols = ["#f4e285", "#a3c75d", "#d1495b", "#2e7d32", "#bcaaa4"]
    return _mapa_categorico(geo, archivo, "Mapa de uso de suelo", cats, cols, 101)


def mapa_cobertura_vegetal(geo, archivo):
    cats = ["Vegetación densa", "Vegetación media", "Vegetación rala", "Sin vegetación"]
    cols = ["#006837", "#66bd63", "#d9ef8b", "#d9d9d9"]
    return _mapa_categorico(geo, archivo, "Mapa de cobertura vegetal", cats, cols, 202)


def mapa_cn(geo, morf, archivo):
    rng = np.random.default_rng(303)
    X, Y = _malla(geo)
    base = morf.cn
    Z = base + (_ruido_suave(X, Y, rng) - 0.5) * 24.0  # CN ± 12
    Z = np.clip(Z, 40, 98)
    fig, ax = plt.subplots(figsize=(5.2, 6.0))
    pc = ax.pcolormesh(X, Y, Z, cmap="YlOrRd", shading="auto")
    _clip(pc, geo, ax)
    _base_ax(geo, f"Mapa de número de curva CN (SCS) — CN medio ≈ {base:.0f}", ax)
    ax.plot(geo.cauce[:, 0], geo.cauce[:, 1], color="navy", lw=1.2)
    fig.colorbar(pc, ax=ax, shrink=0.7, label="CN")
    return _guardar(fig, archivo)


def mapa_isoyetas(geo, archivo, p_media=45.0):
    rng = np.random.default_rng(404)
    X, Y = _malla(geo)
    # Gradiente con la altitud (norte más alto/lluvioso) + bump
    Z = p_media * (1 + 0.25 * (Y - Y.mean()) / (np.ptp(Y) + 1e-9)) \
        + 6.0 * _ruido_suave(X, Y, rng)
    fig, ax = plt.subplots(figsize=(5.2, 6.0))
    cf = ax.contourf(X, Y, Z, levels=12, cmap="Blues")
    cs = ax.contour(X, Y, Z, levels=12, colors="navy", linewidths=0.6)
    ax.clabel(cs, inline=True, fontsize=6, fmt="%.0f")
    try:
        _clip(cf, geo, ax)
        _clip(cs, geo, ax)
    except Exception:
        pass  # clipping de contornos opcional según versión de matplotlib
    _base_ax(geo, "Mapa de isoyetas (mm)", ax)
    fig.colorbar(cf, ax=ax, shrink=0.7, label="P (mm)")
    return _guardar(fig, archivo)


def mapa_pendientes(geo, morf, archivo):
    rng = np.random.default_rng(505)
    X, Y = _malla(geo)
    Z = morf.pendiente_pct * (0.5 + _ruido_suave(X, Y, rng))
    fig, ax = plt.subplots(figsize=(5.2, 6.0))
    pc = ax.pcolormesh(X, Y, Z, cmap="terrain_r", shading="auto")
    _clip(pc, geo, ax)
    _base_ax(geo, f"Mapa de pendientes (%) — media ≈ {morf.pendiente_pct:.1f}%", ax)
    ax.plot(geo.cauce[:, 0], geo.cauce[:, 1], color="navy", lw=1.2)
    fig.colorbar(pc, ax=ax, shrink=0.7, label="Pendiente (%)")
    return _guardar(fig, archivo)


def generar_todos_los_mapas(lat, lon, morf, out_dir, p_media=45.0) -> dict:
    """Genera todos los mapas esquemáticos y devuelve {clave: ruta}."""
    out = Path(out_dir)
    geo = construir_geometria(lat, lon, morf)
    return {
        "mapa_cuenca": mapa_cuenca(geo, morf, out / "mapa_01_cuenca.png"),
        "mapa_red_drenaje": mapa_red_drenaje(geo, out / "mapa_02_red_drenaje.png"),
        "mapa_uso_suelo": mapa_uso_suelo(geo, out / "mapa_03_uso_suelo.png"),
        "mapa_cobertura": mapa_cobertura_vegetal(geo, out / "mapa_04_cobertura.png"),
        "mapa_cn": mapa_cn(geo, morf, out / "mapa_05_cn.png"),
        "mapa_pendientes": mapa_pendientes(geo, morf, out / "mapa_06_pendientes.png"),
        "mapa_isoyetas": mapa_isoyetas(geo, out / "mapa_07_isoyetas.png", p_media),
    }
