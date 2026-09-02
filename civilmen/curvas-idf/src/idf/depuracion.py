"""Depuración de outliers en la serie de máximos anuales de P24.

Para análisis de MÁXIMOS no se completan ni inventan datos: se usa la
serie observada tal cual, pero se descartan los valores físicamente
imposibles (errores de digitación / fuente), que de otro modo inflan
los cuantiles P24(T) y, en cascada, los caudales de diseño.

Caso real que motivó esto: una serie satelital/GHCN-D con un P24max anual
de 307 mm en una zona (Tarija) cuya climatología oficial SENAMHI da una
P24 media de ~45 mm y máximos observados de ~65 mm. 307 mm en un día es
físicamente imposible para ese régimen — es un error de dato.

Criterio (conservador, solo descarta errores groseros, NUNCA extremos
naturales legítimos):

  Un P24max anual es ERROR si supera el umbral físico derivado de la
  climatología oficial de la estación de referencia:

      umbral = P24_media_estación + K · P24_desv_estación      (K = 6)

  Para una distribución de Gumbel, el cuantil de T = 10 000 años está
  en ~media + 5·desv. Un valor observado por encima de media + 6·desv
  en una serie de pocas décadas corresponde a T ≫ 10 000 → no es un
  extremo natural, es un error.

  Si no hay climatología de referencia, se usa un criterio robusto por
  MAD (mediana ± 8·MAD) y un tope absoluto de 400 mm (por encima del
  cual ningún registro diario boliviano es creíble, incluso en el
  trópico húmedo).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Tope absoluto de seguridad (mm/día). Por encima es error seguro en el
# territorio boliviano (el récord nacional ronda 200-250 mm/día en el
# Chapare; nada se acerca a 400).
TOPE_ABSOLUTO_MM = 400.0


def depurar_serie_maximos(serie: pd.DataFrame,
                            p24_media_ref: float | None = None,
                            p24_desv_ref: float | None = None,
                            k_desv: float = 6.0
                            ) -> tuple[pd.DataFrame, list[dict]]:
    """Descarta P24max anuales físicamente imposibles.

    `serie` debe tener columnas 'anio' y 'p24_mm'. Devuelve
    (serie_depurada, descartados) donde `descartados` es una lista de
    dicts {anio, p24_mm, motivo} para reportar en el informe.

    NO completa ni rellena: solo elimina los años con valor aberrante.
    """
    if "p24_mm" not in serie.columns or len(serie) < 5:
        return serie.reset_index(drop=True), []

    p = serie["p24_mm"].to_numpy(float)
    mediana = float(np.median(p))
    mad = float(np.median(np.abs(p - mediana))) * 1.4826  # MAD normalizado

    # Umbral físico desde la estación de referencia (preferido)
    if p24_media_ref and p24_desv_ref and p24_desv_ref > 0:
        umbral_fisico = p24_media_ref + k_desv * p24_desv_ref
    else:
        umbral_fisico = np.inf

    # Umbral robusto por MAD (fallback / refuerzo)
    umbral_mad = mediana + 8.0 * max(mad, 0.10 * mediana) if mad > 0 else np.inf

    # Umbral efectivo: el MÁS PERMISIVO entre físico y MAD, acotado por el
    # tope absoluto. Ser permisivo evita descartar extremos legítimos; el
    # tope absoluto garantiza que los errores groseros (307, 500…) caigan.
    umbral = min(max(umbral_fisico, umbral_mad), TOPE_ABSOLUTO_MM)
    if not np.isfinite(umbral):
        umbral = TOPE_ABSOLUTO_MM

    mask_ok = p <= umbral
    descartados = []
    for anio, val, ok in zip(serie["anio"].to_numpy(), p, mask_ok):
        if not ok:
            descartados.append({
                "anio": int(anio),
                "p24_mm": round(float(val), 1),
                "motivo": (f"P24max {val:.0f} mm supera el umbral físico "
                             f"{umbral:.0f} mm "
                             + (f"(media {p24_media_ref:.0f} + {k_desv:.0f}·desv "
                                f"{p24_desv_ref:.0f} mm de la estación SENAMHI)"
                                if np.isfinite(umbral_fisico) else
                                f"(mediana {mediana:.0f} + 8·MAD)")
                             + " — error de dato, no es un extremo natural."),
            })

    if not descartados:
        return serie.reset_index(drop=True), []

    serie_dep = serie[mask_ok].reset_index(drop=True)
    return serie_dep, descartados


# Rangos físicos de Pmax24h para T = 100 años por región climática de Bolivia
# (skill «estudio-hidrologico-bolivia», curvas-idf.md §2.7, valores por
# estación agrupados por piso). Sirven de sanity-check del cuantil P24(100):
# si el valor calculado cae muy fuera, hay un problema en la serie o el ajuste.
RANGO_P24_T100_REGION = {   # (mín, máx) mm
    "nival":         (25, 70),
    "puna":          (25, 70),
    "altiplano":     (25, 70),
    "prepuna":       (50, 95),
    "valles":        (55, 95),
    "yungas":        (110, 200),
    "tierras_bajas": (100, 220),
}


def validar_p24_regional(p24_t100: float, lat: float, lon: float,
                            altitud_m: float | None = None) -> dict | None:
    """Compara el cuantil P24(T=100) con el rango físico de la región.

    Devuelve None si está dentro del rango esperado, o un dict de
    advertencia {region, rango, valor, mensaje} si cae fuera. No modifica
    el cálculo — solo alerta en el informe para revisión del ingeniero.
    """
    try:
        from .pisos_ecologicos import clasificar
        piso = clasificar(lat, lon, altitud_m)
        rango = RANGO_P24_T100_REGION.get(piso.clave)
        if rango is None:
            return None
        lo, hi = rango
        # Margen de tolerancia ±40 % (la regionalización es orientativa).
        lo_t, hi_t = lo * 0.6, hi * 1.4
        if lo_t <= p24_t100 <= hi_t:
            return None
        if p24_t100 > hi_t:
            sentido = (f"SUPERA ampliamente el rango regional ({lo}–{hi} mm). "
                         f"Revisar la serie por posibles outliers de la fuente "
                         f"o un ajuste de frecuencia distorsionado por la cola.")
        else:
            sentido = (f"está por DEBAJO del rango regional ({lo}–{hi} mm). "
                         f"Puede indicar que la fuente satelital subestima los "
                         f"extremos (CHIRPS/ERA5 suelen suavizarlos).")
        return {
            "region": piso.nombre,
            "rango_mm": [lo, hi],
            "valor_mm": round(float(p24_t100), 1),
            "mensaje": (f"El P24 para T=100 años calculado "
                          f"({p24_t100:.0f} mm) {sentido}"),
        }
    except Exception:  # noqa: BLE001
        return None
