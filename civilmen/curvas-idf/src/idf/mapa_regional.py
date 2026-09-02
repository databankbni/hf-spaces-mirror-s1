"""Mapa regional centrado en el punto de estudio con fondo satelital.

A diferencia de `mapa_bolivia.mapa_bolivia` (que muestra el contorno nacional
completo), esta vista zoomea a un radio fijo (por defecto 100 km) alrededor
del punto y, si GEE está disponible, descarga un thumbnail Sentinel-2 RGB
cloud-free como fondo. Sobre el fondo se superponen:

- El punto de estudio (estrella roja).
- Las estaciones meteorológicas e hidrométricas dentro del radio,
  diferenciadas por marcador y coloreadas por estado.
- Las ciudades principales de Bolivia que caen dentro del marco, con
  etiqueta para que el lector pueda ubicarse geoespacialmente.
- Un círculo punteado al radio de búsqueda y una grilla lat/lon.

Sin GEE el fondo cae a hillshade SRTM o, en última instancia, a un fondo
liso con el contorno nacional aproximado.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .gee import _intentar_inicializar, descargar_con_timeout, _msg


# Ciudades principales de Bolivia con población ≳ 30 000 hab.
# (lon, lat, nombre, importancia 1=capital depto / 2=ciudad media / 3=pueblo)
CIUDADES_BOLIVIA = [
    (-68.1500, -16.5000, "La Paz",          1),
    (-68.1633, -16.5000, "El Alto",         1),
    (-66.1747, -17.3935, "Cochabamba",      1),
    (-63.1830, -17.7833, "Santa Cruz",      1),
    (-65.2627, -19.0476, "Sucre",           1),
    (-64.7325, -21.5355, "Tarija",          1),
    (-67.1067, -17.9836, "Oruro",           1),
    (-65.7531, -19.5836, "Potosí",          1),
    (-64.9000, -14.8333, "Trinidad",        1),
    (-68.7392, -11.0267, "Cobija",          1),
    (-63.6919, -22.0167, "Yacuiba",         2),
    (-64.3422, -22.7322, "Bermejo",         2),
    (-66.0667, -10.9833, "Riberalta",       2),
    (-63.4072, -21.2553, "Villa Montes",    2),
    (-65.7194, -21.4392, "Tupiza",          2),
    (-63.5167, -20.0411, "Camiri",          2),
    (-63.2500, -17.3422, "Montero",         2),
    (-66.2767, -17.3917, "Quillacollo",     2),
    (-66.0400, -17.4081, "Sacaba",          2),
    (-65.4000, -10.4833, "Guayaramerín",    2),
    (-65.5000, -22.7833, "Villazón",        2),
    (-65.7833, -16.1500, "Caranavi",        2),
    (-67.1500, -21.5333, "Uyuni",           2),
    (-66.7500, -16.6500, "Coroico",         3),
    (-67.5333, -14.4400, "Rurrenabaque",    3),
    (-64.7900, -16.8400, "Puerto Villarroel", 3),
    (-65.7340, -17.7666, "Aiquile",         3),
    (-65.0200, -16.7000, "Chimoré",         3),
    (-64.9100, -14.8300, "Trinidad-Aforo",  3),
    (-66.7833, -16.3833, "Achocalla",       3),
    (-67.7500, -17.6833, "Eucaliptus",      3),
    (-68.3333, -17.7833, "Patacamaya",      3),
    (-65.7833, -18.4000, "Padilla",         3),
    (-65.3000, -19.0500, "Yotala",          3),
    (-64.7500, -21.2167, "San Lorenzo",     3),
    (-64.6500, -21.6000, "Padcaya",         3),
    (-64.3500, -22.4200, "Aguairenda",      3),
    (-63.4000, -18.7700, "Abapó",           3),
    (-62.5300, -22.3700, "Misión La Paz",   3),
    (-64.9000, -19.0500, "Sucre-Aforo",     3),
    (-66.4500, -19.0500, "Tarapaya",        3),
    (-65.2000, -22.8000, "La Quiaca-frontera", 3),
]


# Contorno nacional simplificado (fallback cuando no hay fondo satelital).
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


def _bbox_radio(lat: float, lon: float, radio_km: float) -> tuple:
    """Bounding box geográfico (oeste, sur, este, norte) a radio_km del punto."""
    dlat = radio_km / 111.0
    dlon = radio_km / (111.0 * max(math.cos(math.radians(lat)), 0.2))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _descargar_sentinel2_rgb(lat: float, lon: float, radio_km: float,
                                out_path: Path) -> bool:
    """Descarga thumbnail Sentinel-2 RGB cloud-free como PNG. True si OK."""
    if not _intentar_inicializar():
        return False
    try:
        import ee
        bbox = _bbox_radio(lat, lon, radio_km)
        region = ee.Geometry.Rectangle(bbox)
        # Composite mediana cloud-free últimos 18 meses.
        from datetime import datetime, timedelta
        fin = datetime.utcnow()
        ini = fin - timedelta(days=540)
        col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                 .filterBounds(region)
                 .filterDate(ini.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"))
                 .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20)))
        composite = col.median().select(["B4", "B3", "B2"])
        vis = composite.visualize(min=300, max=3000, gamma=1.2)
        url = vis.getThumbURL({
            "region": region,
            "dimensions": 900,
            "crs": "EPSG:4326",
            "format": "png",
        })
        _msg(f"descargando Sentinel-2 RGB ({bbox})…")
        descargar_con_timeout(url, out_path, timeout=60)
        return out_path.exists() and out_path.stat().st_size > 5000
    except Exception as e:  # noqa: BLE001
        _msg(f"Sentinel-2 thumbnail falló: {type(e).__name__}: {e}")
        return False


def _descargar_hillshade(lat: float, lon: float, radio_km: float,
                          out_path: Path) -> bool:
    """Fallback: hillshade SRTM coloreado como fondo cuando Sentinel-2 falla."""
    if not _intentar_inicializar():
        return False
    try:
        import ee
        bbox = _bbox_radio(lat, lon, radio_km)
        region = ee.Geometry.Rectangle(bbox)
        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"]))
        hill = ee.Terrain.hillshade(dem)
        elev_vis = dem.visualize(min=0, max=6000,
                                   palette=["#7f9f65", "#bad77d", "#f0eea6",
                                            "#deada5", "#f5e1e9", "#ffffff"])
        hill_vis = hill.visualize(min=0, max=255,
                                    palette=["#000000", "#ffffff"])
        composite = elev_vis.blend(hill_vis.updateMask(ee.Image(0.4)))
        url = composite.getThumbURL({
            "region": region,
            "dimensions": 900,
            "crs": "EPSG:4326",
            "format": "png",
        })
        _msg(f"descargando hillshade SRTM ({bbox})…")
        descargar_con_timeout(url, out_path, timeout=45)
        return out_path.exists() and out_path.stat().st_size > 5000
    except Exception as e:  # noqa: BLE001
        _msg(f"hillshade fallback falló: {type(e).__name__}: {e}")
        return False


_COLOR_ESTADO = {
    "activa":       "#27ae60",
    "pasiva":       "#7f8c8d",
    "intermitente": "#e67e22",
}


def mapa_regional(lat: float, lon: float, archivo,
                    estaciones_met: list = None,
                    estaciones_hidro: list = None,
                    radio_km: float = 100.0,
                    nombre_sitio: str = "Punto de estudio",
                    fondo_satelital: bool = True,
                    catalogo_contexto: bool = True) -> Path:
    """Mapa regional centrado en el punto, con fondo satelital opcional.

    `estaciones_met` y `estaciones_hidro` son listas de tuplas
    (Estacion, distancia_km) ya filtradas al radio operativo y se dibujan
    destacadas con su código. Si `catalogo_contexto` es True, además se pinta
    como capa de fondo cada estación del catálogo oficial SENAMHI (1 861)
    que caiga dentro del marco, como punto pequeño semitransparente coloreado
    por estado — da la densidad real de la red sin saturar la lectura.
    Devuelve la ruta al PNG generado.
    """
    out = Path(archivo)
    out.parent.mkdir(parents=True, exist_ok=True)
    bbox = _bbox_radio(lat, lon, radio_km)
    oeste, sur, este, norte = bbox

    # Intenta descargar el fondo satelital o hillshade.
    fondo = None
    if fondo_satelital:
        tmp_fondo = out.parent / f".fondo_{out.stem}.png"
        if _descargar_sentinel2_rgb(lat, lon, radio_km, tmp_fondo):
            fondo = tmp_fondo
        elif _descargar_hillshade(lat, lon, radio_km, tmp_fondo):
            fondo = tmp_fondo

    fig, ax = plt.subplots(figsize=(11, 9))
    ax.set_xlim(oeste, este)
    ax.set_ylim(sur, norte)
    ax.set_aspect(1.0 / max(math.cos(math.radians(lat)), 0.2))
    ax.set_xlabel("Longitud (°)", fontsize=9)
    ax.set_ylabel("Latitud (°)", fontsize=9)
    ax.tick_params(labelsize=8)

    if fondo is not None:
        try:
            img = plt.imread(str(fondo))
            ax.imshow(img, extent=[oeste, este, sur, norte],
                       aspect="auto", zorder=0, alpha=0.95)
        except Exception as e:  # noqa: BLE001
            _msg(f"render del fondo falló: {e}")
            fondo = None

    if fondo is None:
        # Fondo neutro + contorno nacional dentro del marco.
        ax.set_facecolor("#f4f7fb")
        ax.fill(_BOLIVIA_CONTORNO[:, 0], _BOLIVIA_CONTORNO[:, 1],
                 color="#ffffff", edgecolor="#1f3a68", lw=1.0, zorder=1)

    # Grilla.
    ax.grid(True, alpha=0.32, lw=0.4, color="#ffffff" if fondo else "#aaa",
             zorder=2)

    # Círculo de radio operativo.
    angles = np.linspace(0, 2 * np.pi, 200)
    cos_lat = max(math.cos(math.radians(lat)), 0.2)
    rl = radio_km / 111.0
    rlon = rl / cos_lat
    ax.plot(lon + rlon * np.cos(angles), lat + rl * np.sin(angles),
             color="#d7191c", lw=1.0, ls="--", alpha=0.85, zorder=3,
             label=f"Radio {radio_km:.0f} km")

    # Ciudades dentro del marco — solo prioridad 1 y 2 si quedan dentro.
    for clon, clat, nombre, prio in CIUDADES_BOLIVIA:
        if not (oeste <= clon <= este and sur <= clat <= norte):
            continue
        if prio == 1:
            ax.plot(clon, clat, "s", markersize=8, color="#fff200",
                     markeredgecolor="black", lw=0.8, zorder=6)
            ax.annotate(nombre, (clon, clat), xytext=(7, 6),
                          textcoords="offset points", fontsize=8.5,
                          fontweight="bold", color="#222",
                          path_effects=_efectos_texto())
        elif prio == 2:
            ax.plot(clon, clat, "s", markersize=5, color="#ffd633",
                     markeredgecolor="black", lw=0.5, zorder=6)
            ax.annotate(nombre, (clon, clat), xytext=(6, 3),
                          textcoords="offset points", fontsize=7,
                          color="#222",
                          path_effects=_efectos_texto())

    # Capa de contexto: todas las estaciones del catálogo oficial dentro del
    # marco, como puntitos tenues. Da la densidad real de la red SENAMHI.
    n_contexto = 0
    if catalogo_contexto:
        try:
            from .catalogo_senamhi import CATALOGO
            ya_destacadas = {(round(e.longitud, 4), round(e.latitud, 4))
                              for e, _ in (estaciones_met or [])}
            ya_destacadas |= {(round(e.longitud, 4), round(e.latitud, 4))
                               for e, _ in (estaciones_hidro or [])}
            for c in CATALOGO:
                if not (oeste <= c.longitud <= este
                          and sur <= c.latitud <= norte):
                    continue
                if (round(c.longitud, 4), round(c.latitud, 4)) in ya_destacadas:
                    continue
                col = _COLOR_ESTADO.get(
                    {"Activo": "activa", "Mantenimiento": "intermitente",
                      "Inactivo": "pasiva"}.get(c.estado, "activa"),
                    "#27ae60")
                es_hidro = (c.categoria or "").startswith("Hidro")
                ax.scatter(c.longitud, c.latitud,
                            marker="^" if es_hidro else "o",
                            s=14, color=col, edgecolor="none",
                            alpha=0.45, zorder=5)
                n_contexto += 1
        except Exception as e:  # noqa: BLE001
            _msg(f"capa de contexto del catálogo falló: {e}")

    # Estaciones meteorológicas (cuadrado).
    for e, d in (estaciones_met or []):
        col = _COLOR_ESTADO.get(getattr(e, "estado", "activa"), "#27ae60")
        ax.scatter(e.longitud, e.latitud, marker="s", s=70,
                    color=col, edgecolor="black", lw=0.6, zorder=7,
                    alpha=0.95)
        ax.annotate(e.codigo, (e.longitud, e.latitud), xytext=(6, -10),
                      textcoords="offset points", fontsize=6.5,
                      color="#1f3a68", fontweight="bold",
                      path_effects=_efectos_texto(borde=2))
    # Estaciones hidrométricas (triángulo).
    for e, d in (estaciones_hidro or []):
        col = _COLOR_ESTADO.get(getattr(e, "estado", "activa"), "#27ae60")
        ax.scatter(e.longitud, e.latitud, marker="^", s=110,
                    color=col, edgecolor="black", lw=0.7, zorder=8,
                    alpha=0.95)
        ax.annotate(e.codigo, (e.longitud, e.latitud), xytext=(7, 7),
                      textcoords="offset points", fontsize=6.8,
                      color="#1e6638", fontweight="bold",
                      path_effects=_efectos_texto(borde=2))

    # Punto de estudio (estrella grande).
    ax.scatter([lon], [lat], marker="*", s=500, color="#d7191c",
                edgecolor="black", lw=1.4, zorder=10)
    ax.annotate(nombre_sitio, (lon, lat), xytext=(12, -16),
                  textcoords="offset points", fontsize=11,
                  fontweight="bold", color="#d7191c",
                  path_effects=_efectos_texto(borde=3))

    # Barra de escala simple (10% del ancho).
    barra_km = 10 if radio_km <= 30 else 25 if radio_km <= 80 else 50
    barra_lon = barra_km / 111.0 / cos_lat
    x0 = oeste + 0.06 * (este - oeste)
    y0 = sur + 0.06 * (norte - sur)
    ax.plot([x0, x0 + barra_lon], [y0, y0], color="white" if fondo else "black",
             lw=4.0, solid_capstyle="butt", zorder=11,
             path_effects=_efectos_linea())
    ax.text(x0 + barra_lon / 2, y0 + 0.012 * (norte - sur),
             f"{barra_km} km",
             ha="center", fontsize=9, color="white" if fondo else "black",
             fontweight="bold", path_effects=_efectos_texto(borde=3))

    # Leyenda.
    from matplotlib.lines import Line2D
    legend = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#d7191c",
                markeredgecolor="black", markersize=15, label=nombre_sitio),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#fff200",
                markeredgecolor="black", markersize=9, label="Capital depto."),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#ffd633",
                markeredgecolor="black", markersize=7, label="Ciudad media"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#27ae60",
                markeredgecolor="black", markersize=8, label="Met. activa"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#7f8c8d",
                markeredgecolor="black", markersize=8, label="Met. pasiva"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#27ae60",
                markeredgecolor="black", markersize=11, label="Hidrom. activa"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#e67e22",
                markeredgecolor="black", markersize=11, label="Hidrom. interm."),
        Line2D([0], [0], color="#d7191c", ls="--", lw=1.2,
                label=f"Radio {radio_km:.0f} km"),
    ]
    ax.legend(handles=legend, loc="lower right", fontsize=7.8,
                framealpha=0.92, facecolor="white",
                title=("Vista regional · fondo Sentinel-2"
                        if fondo else "Vista regional"),
                title_fontsize=8.5)

    # Atribución.
    ax.text(oeste + 0.985 * (este - oeste), norte - 0.018 * (norte - sur),
             ("Imagen © Copernicus Sentinel-2  ·  EPSG:4326"
              if fondo else "Fondo esquemático  ·  EPSG:4326"),
             fontsize=6.8, ha="right", va="top",
             color="white" if fondo else "#555",
             style="italic", path_effects=_efectos_texto(borde=2))

    sub = (f"  ·  {n_contexto} estaciones del catálogo en el marco"
            if n_contexto else "")
    ax.set_title(f"Mapa regional — {nombre_sitio}  ·  radio {radio_km:.0f} km{sub}",
                  fontsize=11.5, fontweight="bold", color="#1f3a68", pad=10)

    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    # Limpia el fondo temporal.
    if fondo is not None:
        try:
            fondo.unlink()
        except Exception:  # noqa: BLE001
            pass
    return out


def _efectos_texto(borde: int = 2):
    """Path effects para que el texto sea legible sobre cualquier fondo."""
    try:
        from matplotlib.patheffects import Stroke, Normal
        return [Stroke(linewidth=borde, foreground="white"), Normal()]
    except Exception:  # noqa: BLE001
        return []


def _efectos_linea():
    try:
        from matplotlib.patheffects import Stroke, Normal
        return [Stroke(linewidth=6.5, foreground="black"), Normal()]
    except Exception:  # noqa: BLE001
        return []
