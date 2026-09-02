"""Integración opcional con Google Earth Engine (GEE).

Si el entorno tiene credenciales válidas (variables `GEE_SERVICE_ACCOUNT_JSON`
y `GEE_PROJECT_ID`), reemplazamos la morfología y la cartografía sintéticas
por valores derivados de productos globales reales:

- HydroSHEDS HydroBASINS nivel 12 → polígono aproximado de la cuenca de aporte.
- COP-DEM GLO-30 (Copernicus, 30 m) → elevaciones (min/max) y pendiente media de la cuenca.
- ESA WorldCover v200 (10 m) → clase predominante de cobertura → CN orientativo.

Si la inicialización o cualquier consulta falla (sin credencial, sin red, error
de la API…), las funciones devuelven `None` y el llamador debe caer a la
estimación sintética. Nunca lanza excepciones al exterior.
"""

from __future__ import annotations

import json
import logging
import math
import os
import socket
import sys
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, urlretrieve  # noqa: F401

_log = logging.getLogger(__name__)

_INICIALIZADO: Optional[bool] = None  # None = no intentado aún
_ERROR_INIT: Optional[str] = None     # último mensaje de error de init


def _msg(texto: str) -> None:
    """Log a stderr para que sea visible en los Container logs de HF."""
    print(f"[GEE] {texto}", file=sys.stderr, flush=True)


def descargar_con_timeout(url: str, dest: Path, timeout: float = 90.0) -> None:
    """`urlretrieve` con timeout duro — la versión stdlib se cuelga si GEE se traba.

    Lanza `socket.timeout` o `URLError` si excede el timeout. El caller debe
    capturarlo y reportar el error en lugar de colgar el thread del worker.
    """
    with urlopen(url, timeout=timeout) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)


def _intentar_inicializar() -> bool:
    """Inicializa GEE una sola vez. Idempotente y silencioso ante fallos."""
    global _INICIALIZADO, _ERROR_INIT
    if _INICIALIZADO is not None:
        return _INICIALIZADO
    try:
        sa_json = os.environ.get("GEE_SERVICE_ACCOUNT_JSON")
        project = os.environ.get("GEE_PROJECT_ID")
        if not sa_json or not project:
            _ERROR_INIT = (
                f"Faltan secrets: "
                f"GEE_PROJECT_ID={'OK' if project else 'FALTA'}, "
                f"GEE_SERVICE_ACCOUNT_JSON={'OK' if sa_json else 'FALTA'}"
            )
            _msg(_ERROR_INIT)
            _INICIALIZADO = False
            return False
        import ee  # import diferido: paquete grande
        from google.oauth2 import service_account

        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/earthengine"]
        )
        ee.Initialize(
            credentials=creds, project=project,
            opt_url="https://earthengine-highvolume.googleapis.com",
        )
        _msg(f"Inicializado OK (project={project})")
        _INICIALIZADO = True
    except Exception as e:  # noqa: BLE001
        _ERROR_INIT = f"{type(e).__name__}: {e}"
        _msg(f"Init failed: {_ERROR_INIT}")
        _INICIALIZADO = False
    return _INICIALIZADO


def disponible() -> bool:
    return _intentar_inicializar()


def estado() -> dict:
    """Diagnóstico exposed por /gee_status."""
    ok = _intentar_inicializar()
    sa_json = os.environ.get("GEE_SERVICE_ACCOUNT_JSON", "")
    return {
        "disponible": ok,
        "error_init": _ERROR_INIT,
        "secrets": {
            "GEE_PROJECT_ID_set": bool(os.environ.get("GEE_PROJECT_ID")),
            "GEE_PROJECT_ID_value": os.environ.get("GEE_PROJECT_ID"),
            "GEE_SERVICE_ACCOUNT_JSON_set": bool(sa_json),
            "GEE_SERVICE_ACCOUNT_JSON_chars": len(sa_json),
        },
    }


# Mapeo MapBiomas Bolivia LULC v1 (clases nativas) → CN SCS orientativo
# (grupo hidrológico B, condición media AMC II). El usuario puede sobreescribir
# el CN si conoce el grupo de suelos real (checkbox "Tengo CN verificado").
# MapBiomas Bolivia es específico para el país: incluye formaciones andinas,
# salares, glaciares y soja con clases dedicadas (mejor que datasets globales).
_CN_POR_COBERTURA = {
    0:   75,   # Sin clasificar (default)
    1:   60,   # Forest Formation
    3:   60,   # Forest
    4:   65,   # Open Forest
    6:   70,   # Flooded Forest
    10:  70,   # Grassland and shrubland
    11:  78,   # Flooded grassland/shrubland
    12:  70,   # Grassland/shrubland
    13:  73,   # Other non-forest natural formation
    14:  78,   # Farming
    15:  79,   # Pasture
    18:  78,   # Agriculture
    21:  78,   # Mosaic of Uses
    22:  86,   # Non-vegetated area
    23:  79,   # Beach, dune and sandbank
    24:  92,   # Urban Infrastructure
    25:  90,   # Other non-vegetated anthropic area
    26: 100,   # Water
    27:  75,   # Not observed
    29:  95,   # Rocky outcrop
    30:  89,   # Mining (suelo disturbado)
    31: 100,   # Aquaculture
    33: 100,   # River and lake
    34: 100,   # Glacier
    39:  78,   # Soybean
    61:  90,   # Salt flat (salar)
    66:  65,   # Scrubland
    68:  86,   # Other non-vegetated natural area
    72:  78,   # Other crops
    81:  70,   # Andean grassland and shrubland (pajonal andino)
    82:  78,   # Flooded Andean grassland and shrubland (bofedal)
}


def poligono_hidrobasins_l12(lat: float, lon: float):
    """Devuelve el polígono de la sub-cuenca HydroBASINS L12 que contiene
    el punto, como array Nx2 [lon, lat]. None si GEE no responde.

    Usado como fallback cuando `delinear_cuenca_merit` falla — es menos
    preciso (sub-cuenca preexistente, no aporte estricto al punto) pero
    es un polígono REAL en lugar de la estimación sintética por Hack.
    """
    if not _intentar_inicializar():
        return None
    try:
        import ee
        import numpy as np
        punto = ee.Geometry.Point([lon, lat])
        fc = (ee.FeatureCollection("WWF/HydroSHEDS/v1/Basins/hybas_12")
                  .filterBounds(punto))
        if fc.size().getInfo() == 0:
            _msg("HydroBASINS L12 no contiene este punto")
            return None
        geom = ee.Feature(fc.first()).geometry()
        # Extraemos los vértices del contorno exterior
        coords = geom.coordinates().getInfo()
        # GEE puede devolver MultiPolygon o Polygon — sacamos el outer ring del primero
        if not coords:
            return None
        if isinstance(coords[0][0][0], list):  # MultiPolygon
            outer = coords[0][0]
        else:
            outer = coords[0]
        pol = np.array(outer, dtype=float)  # (N, 2) [lon, lat]
        if pol.ndim != 2 or pol.shape[1] != 2 or len(pol) < 4:
            return None
        # Simplificar: si tiene > 200 vértices, samplear cada k para acelerar
        if len(pol) > 200:
            step = max(1, len(pol) // 200)
            pol = np.vstack([pol[::step], pol[-1]])
        _msg(f"HydroBASINS L12: {len(pol)} vértices, área aprox del "
               f"feature: {ee.Number(geom.area(maxError=10)).divide(1e6).getInfo():.2f} km²")
        return pol
    except Exception as e:  # noqa: BLE001
        _msg(f"HydroBASINS fallback falló: {type(e).__name__}: {e}")
        return None


def cuenca_upstream_hidrobasins(lat: float, lon: float,
                                max_iter: int = 150,
                                max_subcuencas: int = 6000):
    """Delinea la cuenca de aporte FUSIONANDO las sub-cuencas HydroBASINS L12
    aguas arriba del punto, y las disuelve en UN solo polígono.

    Resuelve el caso de cuencas grandes (Mamoré, Bermejo, escala amazónica)
    donde la delineación pixel a pixel de MERIT Hydro se trunca en el borde
    del tile descargado y «no fusiona» la cuenca completa. Aquí el trazado
    aguas arriba se hace 100 % en el servidor de GEE siguiendo la topología
    `NEXT_DOWN` de HydroBASINS y luego se hace `union()/dissolve()`.

    Estrategia:
      1. Sub-cuenca L12 que contiene el punto → HYBAS_ID semilla y MAIN_BAS.
      2. Se acota la colección al sistema fluvial (mismo MAIN_BAS) para que
         los filtros `NEXT_DOWN` no escaneen el millón de polígonos globales.
      3. Trazado iterativo aguas arriba (frontera = sub-cuencas cuyo
         NEXT_DOWN ∈ frontera previa) acumulando HYBAS_IDs, hasta `max_iter`
         saltos o hasta que la frontera quede vacía.
      4. `union()` de las sub-cuencas trazadas → polígono fusionado.

    Devuelve dict con: poligono (Nx2 [lon,lat]), area_km2, perimetro_km,
    n_subcuencas, truncada (True si se alcanzó el tope sin agotar la red).
    None si GEE no responde o el punto no cae en HydroBASINS.
    """
    if not _intentar_inicializar():
        return None
    try:
        import ee
        import numpy as np
        punto = ee.Geometry.Point([lon, lat])
        hb = ee.FeatureCollection("WWF/HydroSHEDS/v1/Basins/hybas_12")
        seed = hb.filterBounds(punto)
        if seed.size().getInfo() == 0:
            _msg("upstream-merge: punto fuera de HydroBASINS L12")
            return None
        sem = ee.Feature(seed.first())
        seed_id = ee.Number(sem.get("HYBAS_ID"))
        main_bas = sem.get("MAIN_BAS")
        # Acotar al sistema fluvial del punto: baja el coste de cada filtro
        # NEXT_DOWN de ~1e6 a los polígonos de ese sistema.
        sistema = hb.filter(ee.Filter.eq("MAIN_BAS", main_bas))

        def _step(_i, acc):
            acc = ee.Dictionary(acc)
            frontier = ee.List(acc.get("frontier"))
            allids = ee.List(acc.get("all"))
            up = (sistema.filter(ee.Filter.inList("NEXT_DOWN", frontier))
                         .aggregate_array("HYBAS_ID"))
            nuevos = up.removeAll(allids)        # evita revisitar
            return ee.Dictionary({
                "frontier": nuevos,
                "all": allids.cat(nuevos),
            })

        init = ee.Dictionary({"frontier": ee.List([seed_id]),
                              "all": ee.List([seed_id])})
        res = ee.Dictionary(
            ee.List.sequence(1, max_iter).iterate(_step, init))
        all_ids = ee.List(res.get("all"))
        frontera_final = ee.List(res.get("frontier"))
        n_sub = int(all_ids.size().getInfo())
        # truncada = quedó frontera pendiente al agotar las iteraciones, o el
        # nº de sub-cuencas excede el tope que podemos unir sin saturar GEE.
        truncada = bool(int(frontera_final.size().getInfo()) > 0) or \
            n_sub > max_subcuencas
        if n_sub > max_subcuencas:
            _msg(f"upstream-merge: {n_sub} sub-cuencas > tope "
                 f"{max_subcuencas} (escala continental) — se omite el union")
            return {"poligono": None, "area_km2": None, "perimetro_km": None,
                    "n_subcuencas": n_sub, "truncada": True}

        basin = sistema.filter(ee.Filter.inList("HYBAS_ID", all_ids))
        # Disolver en un solo polígono. maxError generoso (30 m) y simplify
        # para mantener los vértices manejables en cuencas grandes.
        geom = basin.geometry(maxError=30).dissolve(maxError=30)
        info = ee.Dictionary({
            "area_m2": geom.area(maxError=30),
            "perim_m": geom.perimeter(maxError=30),
            "coords": geom.simplify(maxError=90).coordinates(),
        }).getInfo()
        area_km2 = float(info["area_m2"]) / 1e6
        perimetro_km = float(info["perim_m"]) / 1000.0
        coords = info["coords"]
        if not coords:
            return None
        # Tras dissolve puede ser Polygon o MultiPolygon: tomar el anillo
        # exterior del polígono de mayor área (la cuenca principal).
        if isinstance(coords[0][0][0], list):  # MultiPolygon
            anillos = [np.array(p[0], dtype=float) for p in coords]
            outer = max(anillos, key=len)
        else:                                   # Polygon
            outer = np.array(coords[0], dtype=float)
        pol = np.asarray(outer, dtype=float)
        if pol.ndim != 2 or pol.shape[1] != 2 or len(pol) < 4:
            return None
        if len(pol) > 400:                      # samplear para acelerar dibujo
            step = max(1, len(pol) // 400)
            pol = np.vstack([pol[::step], pol[-1]])
        _msg(f"upstream-merge OK: {n_sub} sub-cuencas L12 fusionadas, "
             f"A={area_km2:.1f} km², {len(pol)} vértices"
             + (" (TRUNCADA)" if truncada else ""))
        return {"poligono": pol, "area_km2": round(area_km2, 2),
                "perimetro_km": round(perimetro_km, 3),
                "n_subcuencas": n_sub, "truncada": truncada}
    except Exception as e:  # noqa: BLE001
        _msg(f"upstream-merge falló: {type(e).__name__}: {e}")
        return None


def morfologia_desde_gee(lat: float, lon: float,
                         altitud_salida_m: Optional[float] = None):
    """Devuelve `MorfologiaCuenca` real o `None` si GEE no está disponible.

    Estrategia: HydroBASINS nivel 12 → polígono de la sub-cuenca que contiene
    el punto. Sobre ese polígono se calculan: área y perímetro (geometría),
    elevación min/max/media (COP-DEM GLO-30), pendiente media (Terrain.slope), clase
    de cobertura predominante (ESA WorldCover) → CN.

    La longitud del cauce sigue siendo una estimación por ley de Hack con el
    área real; extraerla por flow-accumulation es trabajo aparte.
    """
    if not _intentar_inicializar():
        return None
    try:
        import ee
        from .morfologia import MorfologiaCuenca

        _msg(f"morfologia_desde_gee(lat={lat}, lon={lon}) → consultando…")
        punto = ee.Geometry.Point([lon, lat])
        fc = ee.FeatureCollection("WWF/HydroSHEDS/v1/Basins/hybas_12") \
                .filterBounds(punto)
        if fc.size().getInfo() == 0:
            _msg("HydroBASINS: no encontró cuenca para el punto.")
            return None
        cuenca = ee.Feature(fc.first())
        geom = cuenca.geometry()

        # COP-DEM GLO-30 (Copernicus): mejor calidad y cobertura global
        # completa que SRTM. Single-band float32 en metros sobre WGS84.
        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"]))
        slope = ee.Terrain.slope(dem)
        # MapBiomas Bolivia LULC v1 (30 m, Landsat) — año más reciente.
        # Asset público; cobertura solo Bolivia.
        wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
                .sort("year", False)
                .first()
                .select(0).rename("clase"))
        red_dem = (ee.Reducer.min()
                   .combine(ee.Reducer.max(), sharedInputs=True)
                   .combine(ee.Reducer.mean(), sharedInputs=True))

        # Un único getInfo() para minimizar round-trips a GEE.
        combinado = ee.Feature(None, {
            "area_m2": geom.area(maxError=1),
            "perim_m": geom.perimeter(maxError=1),
            "dem": dem.reduceRegion(red_dem, geom, scale=30,
                                    maxPixels=1e9, bestEffort=True),
            "slope": slope.reduceRegion(ee.Reducer.mean(), geom, scale=30,
                                        maxPixels=1e9, bestEffort=True),
            "cobertura": wc.reduceRegion(ee.Reducer.mode(), geom, scale=30,
                                          maxPixels=1e9, bestEffort=True),
        })
        data = combinado.getInfo()["properties"]

        area_km2 = float(data["area_m2"]) / 1e6
        perimetro_km = float(data["perim_m"]) / 1000.0
        dem_stats = data.get("dem") or {}
        slope_stats = data.get("slope") or {}
        elev_min = dem_stats.get("elevation_min")
        elev_max = dem_stats.get("elevation_max")
        slope_deg = slope_stats.get("slope")
        if elev_min is None or elev_max is None or slope_deg is None:
            return None

        pendiente_mm = math.tan(math.radians(float(slope_deg)))
        long_cauce = 1.4 * area_km2 ** 0.6  # ley de Hack con A real

        cota_menor = float(altitud_salida_m) if altitud_salida_m else float(elev_min)
        cota_mayor = float(elev_max)
        desnivel = cota_mayor - cota_menor

        cobertura = (data.get("cobertura") or {})
        clase = int(cobertura.get("clase") or 0)
        cn = float(_CN_POR_COBERTURA.get(clase, 75))
        _msg(f"cobertura MapBiomas clase={clase} → CN={cn:.0f}")

        _msg(f"morfologia OK: A={area_km2:.2f} km², S={pendiente_mm*100:.1f}%, "
             f"H_max={cota_mayor:.0f}, H_min={cota_menor:.0f}, CN={cn:.0f}")
        return MorfologiaCuenca(
            area_km2=round(area_km2, 2),
            long_cauce_km=round(long_cauce, 3),
            cota_mayor_m=round(cota_mayor, 1),
            cota_menor_m=round(cota_menor, 1),
            desnivel_m=round(desnivel, 1),
            pendiente_media_mm=round(pendiente_mm, 4),
            perimetro_km=round(perimetro_km, 3),
            cn=cn,
            sintetica=False,
        )
    except Exception as e:  # noqa: BLE001
        _msg(f"morfologia_desde_gee falló: {type(e).__name__}: {e}")
        return None


def mapa_cuenca_gee(lat: float, lon: float, out_path: Path,
                    autor: str = "",
                    poligono_externo=None,
                    entradas_leyenda=None) -> Optional[Path]:
    """Descarga un PNG con hillshade COP-DEM GLO-30 + polígono de cuenca superpuesto.

    Si `poligono_externo` (array Nx2 de [lon, lat]) viene, usa ese polígono
    para el contorno y el encuadre (proviene del watershed MERIT Hydro real).
    Si no, cae al polígono HydroBASINS L12 que contiene al punto.

    Devuelve el path al PNG o `None` si GEE no está disponible / falla.
    El PNG queda decorado con flecha de norte, barra de escala, proyección
    y autor.
    """
    if not _intentar_inicializar():
        return None
    try:
        import ee
        if poligono_externo is not None:
            coords = [[float(c[0]), float(c[1])] for c in poligono_externo]
            cuenca_fc = ee.FeatureCollection(
                [ee.Feature(ee.Geometry.Polygon([coords]))])
            geom = cuenca_fc.geometry()
        else:
            punto = ee.Geometry.Point([lon, lat])
            fc = ee.FeatureCollection("WWF/HydroSHEDS/v1/Basins/hybas_12") \
                    .filterBounds(punto)
            if fc.size().getInfo() == 0:
                return None
            cuenca_fc = ee.FeatureCollection([ee.Feature(fc.first())])
            geom = cuenca_fc.geometry()
        # Encuadre con un margen del 8% alrededor de la cuenca.
        bounds = geom.bounds(maxError=1).buffer(
            ee.Number(geom.area(maxError=1)).sqrt().multiply(0.08)
        )

        dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                  .select(["DEM"]).mosaic().rename(["elevation"]))
        # Hillshade gris (relieve) y elevación coloreada combinados.
        hill = ee.Terrain.hillshade(dem).visualize(min=0, max=255,
                                                    palette=["#000000", "#ffffff"])
        # Paleta solicitada por el usuario (SRTM 0-6000 m).
        elev_vis = dem.visualize(min=0, max=6000,
                                  palette=["#7f9f65", "#0f160b", "#bad77d",
                                           "#f0eea6", "#f0d38e", "#deada5",
                                           "#f5e1e9", "#ffffff"])
        composite = elev_vis.blend(hill.updateMask(ee.Image(0.35)))

        # Cauce principal: MERIT Hydro upa con umbral alto (acumulación
        # ≥ 5 km²) clipeado a la cuenca. Pintado en azul oscuro grueso
        # para que sea claramente identificable. Si MERIT no responde,
        # esta capa queda transparente — el contorno se sigue dibujando.
        try:
            upa = ee.Image("MERIT/Hydro/v1_0_1").select("upa")
            cauce = (upa.gte(5.0).updateMask(upa.gte(5.0))
                          .clip(geom).visualize(palette=["#1f3a68"]))
            composite = composite.blend(cauce.updateMask(ee.Image(0.95)))
        except Exception:  # noqa: BLE001
            pass

        # Contorno de la cuenca en rojo.
        contorno = ee.Image().byte().paint(
            featureCollection=cuenca_fc,
            color=1, width=3,
        ).visualize(palette=["#e53935"])
        salida = composite.blend(contorno)

        # Área de la cuenca (km²) para la leyenda
        try:
            area_km2 = (ee.Number(geom.area(maxError=10))
                            .divide(1e6).getInfo())
        except Exception:  # noqa: BLE001
            area_km2 = None

        # bbox real (rect envolvente del encuadre) para barra de escala.
        bbox_coords = bounds.bounds(maxError=1).coordinates().getInfo()[0]
        xs = [c[0] for c in bbox_coords]
        ys = [c[1] for c in bbox_coords]
        bbox = {"oeste": min(xs), "este": max(xs),
                "sur": min(ys), "norte": max(ys)}

        crs = epsg_utm((bbox["sur"] + bbox["norte"]) / 2,
                       (bbox["oeste"] + bbox["este"]) / 2)
        url = salida.getThumbURL({
            "region": bounds,
            "dimensions": "900",
            "crs": crs,
            "format": "png",
        })
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _msg(f"descargando thumbnail cuenca ({crs})…")
        descargar_con_timeout(url, out_path, timeout=90)
        # Construir leyenda combinada: bandas de elevación (si vienen) +
        # entrada cauce principal + entrada cuenca con área.
        leyenda_final = list(entradas_leyenda or [])
        leyenda_final.append({
            "etiqueta": "Cauce principal (MERIT upa ≥ 5 km²)",
            "color": "#1f3a68", "pct": None,
        })
        if area_km2 is not None:
            leyenda_final.append({
                "etiqueta": f"Contorno de cuenca — A = {area_km2:.2f} km²",
                "color": "#e53935", "pct": None,
            })
        else:
            leyenda_final.append({
                "etiqueta": "Contorno de cuenca",
                "color": "#e53935", "pct": None,
            })
        resumen_9_1 = (f"Área de cuenca: {area_km2:.2f} km²"
                          if area_km2 is not None else "")
        _decorar_mapa_cartografico(out_path, bbox, autor,
                                    titulo="9.1 Cuenca y cauce principal",
                                    entradas_leyenda=leyenda_final,
                                    resumen=resumen_9_1)
        _msg(f"mapa_cuenca_gee OK: {out_path}")
        return out_path
    except Exception as e:  # noqa: BLE001
        _msg(f"mapa_cuenca_gee falló: {type(e).__name__}: {e}")
        return None


def cn_desde_poligono(poligono_lonlat) -> Optional[float]:
    """Calcula CN SCS sobre un polígono externo (Nx2 [lon, lat]) usando MapBiomas.

    Usado cuando el polígono viene del watershed MERIT Hydro real (no de
    HydroBASINS). Devuelve un CN orientativo (grupo hidrológico B, AMC II)
    o `None` si GEE/MapBiomas no responden.
    """
    if not _intentar_inicializar():
        return None
    try:
        import ee
        coords = [[float(c[0]), float(c[1])] for c in poligono_lonlat]
        geom = ee.Geometry.Polygon([coords])
        wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
                .sort("year", False)
                .first()
                .select(0).rename("clase"))
        data = wc.reduceRegion(ee.Reducer.mode(), geom, scale=30,
                                maxPixels=1e9, bestEffort=True).getInfo()
        clase = int(data.get("clase") or 0)
        cn = float(_CN_POR_COBERTURA.get(clase, 75))
        _msg(f"cn_desde_poligono: clase MapBiomas={clase} → CN={cn:.0f}")
        return cn
    except Exception as e:  # noqa: BLE001
        _msg(f"cn_desde_poligono falló: {type(e).__name__}: {e}")
        return None


def cn_ponderado_desde_poligono(poligono_lonlat) -> Optional[float]:
    """CN SCS ponderado por área sobre el polígono (media de MapBiomas → CN).

    Idéntico al CN ponderado del mapa 9.5, pero sin renderizar el thumbnail.
    Se usa en el pipeline ANTES del §10 para que el Tc se calcule con el CN
    real ponderado de la cuenca, no con el de la clase predominante.
    """
    if not _intentar_inicializar():
        return None
    try:
        import ee
        coords = [[float(c[0]), float(c[1])] for c in poligono_lonlat]
        geom = ee.Geometry.Polygon([coords])
        wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
                .sort("year", False).first().select(0))
        clases = sorted(_CN_POR_COBERTURA.keys())
        valores_cn = [int(_CN_POR_COBERTURA[c]) for c in clases]
        cn_img = wc.remap(clases, valores_cn, 75).toFloat()
        d = cn_img.reduceRegion(ee.Reducer.mean(), geom, scale=30,
                                 maxPixels=1e9, bestEffort=True).getInfo()
        if not d:
            return None
        cn = float(list(d.values())[0])
        _msg(f"cn_ponderado_desde_poligono: CN={cn:.1f}")
        return cn
    except Exception as e:  # noqa: BLE001
        _msg(f"cn_ponderado_desde_poligono falló: {type(e).__name__}: {e}")
        return None


# Mapeo MapBiomas Bolivia LULC v1 (clases nativas) → n de Manning orientativo
# para el CORREDOR fluvial (cauce + llanura). Valores de Chow (1959),
# "Open-Channel Hydraulics", tablas 5-6 (canales naturales) y overbank/planicie
# de inundación. Se usa un n compuesto ponderado por área del corredor — una
# simplificación de v1 respecto a la variación horizontal de n de HEC-RAS.
_N_MANNING_POR_COBERTURA = {
    0:  0.035,   # Sin clasificar (cauce natural limpio, default)
    1:  0.100,   # Forest Formation (planicie arbolada densa)
    3:  0.100,   # Forest
    4:  0.080,   # Open Forest
    6:  0.100,   # Flooded Forest
    10: 0.045,   # Grassland and shrubland
    11: 0.050,   # Flooded grassland/shrubland
    12: 0.045,   # Grassland/shrubland
    13: 0.040,   # Other non-forest natural formation
    14: 0.040,   # Farming
    15: 0.035,   # Pasture
    18: 0.040,   # Agriculture
    21: 0.040,   # Mosaic of Uses
    22: 0.030,   # Non-vegetated area (suelo desnudo)
    23: 0.028,   # Beach, dune and sandbank (arena)
    24: 0.025,   # Urban Infrastructure (cauce canalizado/urbano)
    25: 0.028,   # Other non-vegetated anthropic area
    26: 0.033,   # Water (canal natural limpio)
    27: 0.035,   # Not observed
    29: 0.040,   # Rocky outcrop
    30: 0.035,   # Mining
    31: 0.033,   # Aquaculture
    33: 0.033,   # River and lake
    34: 0.030,   # Glacier
    39: 0.040,   # Soybean
    61: 0.025,   # Salt flat (salar)
    66: 0.055,   # Scrubland (matorral)
    68: 0.030,   # Other non-vegetated natural area
    72: 0.040,   # Other crops
    81: 0.045,   # Andean grassland and shrubland (pajonal andino)
    82: 0.050,   # Flooded Andean grassland and shrubland (bofedal)
}


def n_manning_ponderado_desde_poligono(poligono_lonlat) -> Optional[float]:
    """n de Manning ponderado por área sobre el polígono (cobertura MapBiomas).

    Análogo a `cn_ponderado_desde_poligono` pero para la rugosidad de Manning.
    Como MapBiomas remap requiere enteros, se escala n×1000, se promedia y se
    divide. Usado por `hidraulica_fluvial` para el cálculo del tirante normal.
    `None` si GEE/MapBiomas no responden.
    """
    if not _intentar_inicializar():
        return None
    try:
        import ee
        coords = [[float(c[0]), float(c[1])] for c in poligono_lonlat]
        geom = ee.Geometry.Polygon([coords])
        wc = (ee.ImageCollection("projects/mapbiomas-public/assets/bolivia/lulc/v1")
                .sort("year", False).first().select(0))
        clases = sorted(_N_MANNING_POR_COBERTURA.keys())
        # n×1000 como entero para el remap (0.035 → 35).
        valores_n = [int(round(_N_MANNING_POR_COBERTURA[c] * 1000)) for c in clases]
        n_img = wc.remap(clases, valores_n, 35).toFloat()
        d = n_img.reduceRegion(ee.Reducer.mean(), geom, scale=30,
                               maxPixels=1e9, bestEffort=True).getInfo()
        if not d:
            return None
        n = float(list(d.values())[0]) / 1000.0
        _msg(f"n_manning_ponderado_desde_poligono: n={n:.3f}")
        return n
    except Exception as e:  # noqa: BLE001
        _msg(f"n_manning_ponderado_desde_poligono falló: {type(e).__name__}: {e}")
        return None


def zona_utm(lon: float) -> int:
    return int((lon + 180) // 6) + 1


def epsg_utm(lat: float, lon: float) -> str:
    z = zona_utm(lon)
    return f"EPSG:{(32700 if lat < 0 else 32600) + z}"


def latlon_a_utm(lat: float, lon: float):
    """WGS84 lat/lon → UTM (easting, northing, zona). Fórmula de Snyder/USGS."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    k0 = 0.9996
    z = zona_utm(lon)
    lon0 = math.radians((z - 1) * 6 - 180 + 3)
    latr, lonr = math.radians(lat), math.radians(lon)
    ep2 = e2 / (1 - e2)
    N = a / math.sqrt(1 - e2 * math.sin(latr) ** 2)
    T = math.tan(latr) ** 2
    C = ep2 * math.cos(latr) ** 2
    A_ = (lonr - lon0) * math.cos(latr)
    M = a * ((1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * latr
             - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * latr)
             + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * latr)
             - (35 * e2**3 / 3072) * math.sin(6 * latr))
    easting = (k0 * N * (A_ + (1 - T + C) * A_**3 / 6
               + (5 - 18 * T + T**2 + 72 * C - 58 * ep2) * A_**5 / 120) + 500000)
    northing = (k0 * (M + N * math.tan(latr) * (A_**2 / 2
                + (5 - T + 9 * C + 4 * C**2) * A_**4 / 24
                + (61 - 58 * T + T**2 + 600 * C - 330 * ep2) * A_**6 / 720)))
    if lat < 0:
        northing += 10000000.0
    return easting, northing, z


def _utm_bbox_desde_latlon(bbox: dict):
    """Extensión UTM (E_min,E_max,N_min,N_max,zona) muestreando los bordes lat/lon."""
    o, e, s, n = bbox["oeste"], bbox["este"], bbox["sur"], bbox["norte"]
    pts = []
    for t in range(0, 21):
        fr = t / 20.0
        pts += [(s, o + fr * (e - o)), (n, o + fr * (e - o)),
                (s + fr * (n - s), o), (s + fr * (n - s), e)]
    zona = zona_utm((o + e) / 2)
    es, ns = [], []
    for la, lo in pts:
        E, N, _ = latlon_a_utm(la, lo)
        es.append(E)
        ns.append(N)
    return min(es), max(es), min(ns), max(ns), zona


def _barra_redonda(ancho_m: float) -> float:
    objetivo = ancho_m / 4
    exp = math.floor(math.log10(objetivo))
    base = objetivo / (10 ** exp)
    if base < 1.5:
        return 1 * (10 ** exp)
    if base < 3.5:
        return 2 * (10 ** exp)
    if base < 7.5:
        return 5 * (10 ** exp)
    return 10 * (10 ** exp)


def _wrap_texto(texto: str, max_chars: int = 38) -> list[str]:
    """Parte un texto en líneas de ≤ max_chars sin cortar palabras."""
    if not texto:
        return []
    palabras = texto.split()
    lineas, actual = [], ""
    for p in palabras:
        if actual and len(actual) + 1 + len(p) > max_chars:
            lineas.append(actual)
            actual = p
        else:
            actual = f"{actual} {p}".strip()
    if actual:
        lineas.append(actual)
    return lineas


def _decorar_mapa_cartografico(png_path: Path, bbox: dict, autor: str = "",
                                entradas_leyenda=None, resumen: str = "",
                                titulo: str = "") -> None:
    """Compone el PNG final con marco cartográfico estilo profesional.

    Añade: marco con grilla UTM cada 2500 m rotulada a la IZQUIERDA (norte) e
    INFERIOR (este), panel derecho con flecha de norte, leyenda (clases con %),
    barra de escala graduada, proyección (zona UTM) y autor.

    `bbox` en grados (oeste/este/sur/norte). `entradas_leyenda` es una lista de
    dicts {etiqueta, color, pct} (pct opcional). `resumen` es texto extra para
    la leyenda (p. ej. "CN ponderado = 78").
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrow, Rectangle

    img = plt.imread(str(png_path))
    H, W = img.shape[0], img.shape[1]

    E_min, E_max, N_min, N_max, zona = _utm_bbox_desde_latlon(bbox)
    ancho_m = max(E_max - E_min, 1.0)

    # Márgenes (px) para el marco. mb amplio para las etiquetas verticales
    # rotadas 90° con la nueva fuente más grande. mr expandido para que la
    # leyenda con texto + 1pt no se corte. mt reducido porque ya no
    # dibujamos título DENTRO del PNG (el título de §9.X lo lleva el
    # informe arriba del mapa).
    # mb reducido: los rótulos del eje Este ahora son horizontales (ocupan
    # ~14 px de alto en vez de ~50 px verticales) + el título del eje.
    ml, mb, mt = 88, 50, 14
    mr = 250 if entradas_leyenda else 180
    CW = W + ml + mr

    # Altura del panel derecho calculada dinámicamente para que la leyenda
    # (que puede tener hasta 6 clases) + resumen + escala + proyección NUNCA
    # se sobrepongan. Antes la escala/proyección estaban ancladas al fondo
    # con altura fija → se amontonaban en mapas anchos/bajos.
    n_ent = len(entradas_leyenda) if entradas_leyenda else 0
    # Resumen partido en líneas que quepan en el ancho del panel (~36 chars)
    resumen_lineas = _wrap_texto(resumen, 38) if resumen else []
    alto_panel = (mt + 70                       # flecha norte + «N»
                  + (22 + 16 * n_ent if n_ent else 0)   # LEYENDA + clases
                  + (8 + 13 * len(resumen_lineas) if resumen_lineas else 0)
                  + 22 + 30                      # gap + barra de escala
                  + 34 + mb)                     # proyección + autor
    CH = max(H + mt + mb, alto_panel)

    fig = plt.figure(figsize=(CW / 100, CH / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, CW)
    ax.set_ylim(CH, 0)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), CW, CH, facecolor="white", edgecolor="none"))
    # Imagen del mapa.
    ax.imshow(img, extent=(ml, ml + W, mt + H, mt), zorder=1)
    # Marco negro alrededor del mapa.
    ax.add_patch(Rectangle((ml, mt), W, H, fill=False, edgecolor="black",
                           lw=1.2, zorder=4))

    def col_de_E(E):
        return ml + (E - E_min) / (E_max - E_min) * W

    def row_de_N(N):
        return mt + (N_max - N) / (N_max - N_min) * H

    # Grilla UTM cada 2500 m.
    paso = 2500.0
    e0 = math.ceil(E_min / paso) * paso
    Es = []
    e = e0
    while e <= E_max:
        Es.append(e)
        e += paso
    n0 = math.ceil(N_min / paso) * paso
    Ns = []
    nn = n0
    while nn <= N_max:
        Ns.append(nn)
        nn += paso
    # Etiquetas inferiores (Este): HORIZONTALES (pedido del usuario). Como
    # los valores tienen 6 dígitos, si los ticks quedan muy juntos los
    # números se sobreponen → mostramos el rótulo solo en ticks alternos
    # cuando el espaciado en píxeles es menor al ancho del texto. Las líneas
    # de grilla se dibujan siempre (cada 2500 m).
    px_por_tick = (2500.0 / max(E_max - E_min, 1.0)) * W
    paso_rotulo = 1 if px_por_tick >= 46 else 2
    for k_e, E in enumerate(Es):
        x = col_de_E(E)
        ax.plot([x, x], [mt, mt + H], color="#888888", lw=0.4, alpha=0.6, zorder=3)
        if k_e % paso_rotulo == 0:
            ax.text(x, mt + H + 4, f"{int(E)}", ha="center", va="top",
                    fontsize=7.0, zorder=5)
    for N in Ns:
        y = row_de_N(N)
        ax.plot([ml, ml + W], [y, y], color="#888888", lw=0.4, alpha=0.6, zorder=3)
        ax.text(ml - 4, y, f"{int(N)}", ha="right", va="center",
                fontsize=7.5, rotation=90, zorder=5)
    # Títulos de eje. «UTM Norte (m)» (eje izquierdo) rotado 90° por su
    # orientación vertical natural. «UTM Este (m)» (eje inferior) HORIZONTAL
    # (pedido del usuario). Posicionado relativo al mapa (mt + H + offset),
    # NO a CH, porque el canvas puede expandirse por el panel derecho y el
    # título quedaría flotando lejos del eje.
    ax.text(13, mt + H / 2, "UTM Norte (m)", ha="center", va="center",
            rotation=90, fontsize=7.5, style="italic", color="#555")
    ax.text(ml + W / 2, mt + H + 24, "UTM Este (m)", ha="center", va="top",
            fontsize=7.5, style="italic", color="#555")

    # ---- Panel derecho (TODO en flujo vertical: nunca se sobrepone) ----
    px = ml + W + 12
    py = mt + 6

    # Flecha de norte.
    ax.add_patch(FancyArrow(px + 18, py + 34, 0, -30, width=3.5, head_width=12,
                            head_length=11, length_includes_head=True,
                            facecolor="black", edgecolor="black", zorder=6))
    ax.text(px + 18, py + 42, "N", ha="center", va="bottom", fontsize=14,
            fontweight="bold")
    py += 70

    # Leyenda.
    if entradas_leyenda:
        ax.text(px, py, "LEYENDA", fontsize=9, fontweight="bold")
        py += 18
        for ent in entradas_leyenda:
            ax.add_patch(Rectangle((px, py), 13, 10, facecolor=ent.get("color", "#ccc"),
                                   edgecolor="black", lw=0.4, zorder=6))
            etq = ent.get("etiqueta", "")
            pct = ent.get("pct")
            txt = f"{etq}" if pct is None else f"{etq} ({pct:.1f}%)"
            ax.text(px + 18, py + 5, txt, fontsize=7.2, va="center")
            py += 16

    # Resumen (multilínea, en flujo debajo de la leyenda).
    if resumen_lineas:
        py += 8
        for ln in resumen_lineas:
            ax.text(px, py, ln, fontsize=7.5, fontweight="bold",
                    color="#1f3a68", va="top")
            py += 13

    # Barra de escala graduada (en flujo, debajo del resumen).
    py += 16
    barra_m = _barra_redonda(ancho_m)
    barra_px = (barra_m / ancho_m) * W
    barra_px = min(barra_px, mr - 24)
    by = py
    bx = px
    nseg = 4
    seg = barra_px / nseg
    seg_m = barra_m / nseg
    unidad = "km" if barra_m >= 1000 else "m"
    ax.text(bx, by, f"Escala ({unidad})", fontsize=7.5, va="bottom",
            fontweight="bold")
    by += 5
    for k in range(nseg):
        color = "black" if k % 2 == 0 else "white"
        ax.add_patch(Rectangle((bx + k * seg, by), seg, 6, facecolor=color,
                               edgecolor="black", lw=0.5, zorder=6))
    for k in range(nseg + 1):
        val = seg_m * k
        et = f"{val/1000:g}" if barra_m >= 1000 else f"{val:g}"
        ax.text(bx + k * seg, by + 8, et, ha="center", va="top", fontsize=7)
    py = by + 24

    # Proyección + autor (en flujo, debajo de la escala).
    ax.text(px, py, f"WGS 84 / UTM {zona}S", fontsize=8, va="top",
            fontweight="bold")
    py += 13
    if autor and autor.strip() and autor.strip() != "—":
        ax.text(px, py, f"Autor: {autor.strip()}", fontsize=7, va="top")

    # NOTA: El título dentro del mapa fue eliminado por pedido del usuario.
    # El título de la sección (9.X) lo lleva el informe en su h3 arriba del
    # mapa, con tamaño y estilo del PDF.

    fig.savefig(str(png_path), dpi=100)
    plt.close(fig)
