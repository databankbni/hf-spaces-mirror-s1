"""Mapa nacional de Bolivia con el punto de estudio y las estaciones cercanas.

Genera un PNG con el contorno aproximado de Bolivia, el punto de análisis
y dos capas de estaciones:

- Meteorológicas (catálogo SENAMHI, src/idf/data.py).
- Hidrométricas / aforos (catálogo BHN+GRDC, src/idf/estaciones_hidro.py).

Cada punto se representa con marcador y color según su estado (activa,
pasiva, intermitente) y se rotula con el código. Las N más cercanas al
punto de estudio se resaltan y se conectan con una línea fina.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


# Contorno simplificado de Bolivia (polígono cerrado lon, lat).
# Coordenadas aproximadas extraídas de límites departamentales públicos.
_BOLIVIA_CONTORNO = np.array([
    (-69.65, -11.00), (-68.95, -11.45), (-67.45, -11.05), (-66.10, -10.65),
    (-65.40, -10.20), (-64.80, -10.55), (-63.90, -11.45), (-62.55, -11.25),
    (-61.55, -11.70), (-60.55, -12.10), (-60.20, -13.20), (-59.85, -14.40),
    (-60.20, -15.55), (-60.20, -16.50), (-58.20, -16.40), (-57.70, -17.40),
    (-58.30, -18.25), (-58.80, -19.45), (-59.50, -20.10), (-60.05, -20.65),
    (-60.75, -21.20), (-61.50, -21.95), (-62.30, -22.60), (-62.85, -22.90),
    (-63.85, -22.05), (-64.45, -22.85), (-64.95, -22.10), (-65.50, -22.10),
    (-66.30, -22.80), (-66.95, -22.30), (-67.85, -22.85), (-68.45, -22.10),
    (-68.55, -20.95), (-68.20, -19.30), (-69.10, -18.30), (-69.00, -17.50),
    (-69.50, -17.20), (-69.60, -16.20), (-68.95, -15.90), (-69.00, -15.30),
    (-69.45, -14.05), (-69.20, -13.40), (-69.50, -12.50), (-69.65, -11.00),
])


def _agregar_decoracion(ax, titulo: str = ""):
    """Marco, ejes, título y leyenda básica."""
    ax.set_xlim(-70.5, -57.0)
    ax.set_ylim(-23.5, -9.5)
    ax.set_aspect(1.07)
    ax.set_xlabel("Longitud (°)", fontsize=9)
    ax.set_ylabel("Latitud (°)", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.25, lw=0.4)
    if titulo:
        ax.set_title(titulo, fontsize=11, fontweight="bold",
                     color="#1f3a68", pad=12)


_COLOR_ESTADO = {
    "activa": "#27ae60",         # verde
    "pasiva": "#7f8c8d",         # gris
    "intermitente": "#e67e22",   # naranja
}
_MARKER_TIPO = {
    "met": ("s", 38, "Estación meteorológica SENAMHI"),
    "hidro": ("^", 54, "Estación hidrométrica / aforo"),
    "punto": ("*", 280, "Punto de estudio"),
}


def mapa_bolivia(lat: float, lon: float, archivo,
                  estaciones_met: list = None,
                  estaciones_hidro: list = None,
                  n_destacar: int = 5,
                  nombre_sitio: str = "Punto de estudio") -> Path:
    """Dibuja el mapa nacional con el punto y todas las estaciones.

    `estaciones_met` y `estaciones_hidro` son listas de tuplas
    (Estacion, distancia_km) ya ordenadas por proximidad. Las primeras
    `n_destacar` de cada lista se conectan con una línea al punto y se
    rotulan con su código.
    """
    fig, ax = plt.subplots(figsize=(10.5, 9))
    _agregar_decoracion(ax, titulo="Punto de estudio y estaciones disponibles en Bolivia")

    # Contorno de Bolivia.
    poli = _BOLIVIA_CONTORNO
    ax.fill(poli[:, 0], poli[:, 1], color="#f4f7fb", edgecolor="none", zorder=1)
    ax.plot(poli[:, 0], poli[:, 1], color="#1f3a68", lw=1.2, zorder=2)

    # Estaciones meteorológicas.
    for e, d in (estaciones_met or []):
        col = _COLOR_ESTADO.get(getattr(e, "estado", "activa"), "#27ae60")
        marker, size, _ = _MARKER_TIPO["met"]
        ax.scatter(e.longitud, e.latitud, marker=marker, s=size,
                   color=col, edgecolor="black", lw=0.4,
                   alpha=0.85, zorder=4)
    # Estaciones hidrométricas.
    for e, d in (estaciones_hidro or []):
        col = _COLOR_ESTADO.get(e.estado, "#27ae60")
        marker, size, _ = _MARKER_TIPO["hidro"]
        ax.scatter(e.longitud, e.latitud, marker=marker, s=size,
                   color=col, edgecolor="black", lw=0.4,
                   alpha=0.9, zorder=5)

    # Líneas + etiquetas a las más cercanas.
    def _resaltar(pares, tope, label_color):
        for i, (e, d) in enumerate(pares[:tope]):
            ax.plot([lon, e.longitud], [lat, e.latitud],
                    color=label_color, lw=0.6, alpha=0.4,
                    linestyle="--", zorder=3)
            ax.annotate(f"{e.codigo}\n{d:.0f} km",
                        (e.longitud, e.latitud),
                        xytext=(7, 7), textcoords="offset points",
                        fontsize=6.5, color=label_color,
                        fontweight="bold")
    _resaltar(estaciones_met or [], n_destacar, "#1f3a68")
    _resaltar(estaciones_hidro or [], n_destacar, "#1e6638")

    # Punto de estudio.
    ax.scatter([lon], [lat], marker="*", s=380, color="#d7191c",
               edgecolor="black", lw=1.0, zorder=8, label=nombre_sitio)
    ax.annotate(nombre_sitio, (lon, lat), xytext=(10, -14),
                textcoords="offset points", fontsize=9,
                fontweight="bold", color="#d7191c")

    # Leyenda combinada (tipos + estados).
    from matplotlib.lines import Line2D
    leyenda = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#d7191c",
               markeredgecolor="black", markersize=14, label="Punto de estudio"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#27ae60",
               markeredgecolor="black", markersize=8, label="Met. SENAMHI activa"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#7f8c8d",
               markeredgecolor="black", markersize=8, label="Met. pasiva"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#27ae60",
               markeredgecolor="black", markersize=10, label="Hidrométrica activa"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#e67e22",
               markeredgecolor="black", markersize=10, label="Hidrom. intermitente"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#7f8c8d",
               markeredgecolor="black", markersize=10, label="Hidrométrica pasiva"),
    ]
    ax.legend(handles=leyenda, loc="lower left", fontsize=7.5,
              framealpha=0.92, title="Leyenda",
              title_fontsize=8.5)

    # Etiqueta cartográfica simple.
    ax.text(-70.3, -23.2, "WGS 84 / lat-lon", fontsize=6.5,
            color="#555", style="italic")
    ax.text(-57.3, -23.2, "Fuente: SENAMHI + BHN + GRDC + HydroBASINS",
            fontsize=6.5, color="#555", style="italic", ha="right")

    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return out
