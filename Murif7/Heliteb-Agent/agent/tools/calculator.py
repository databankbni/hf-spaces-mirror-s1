"""Tool: calculadora de instalación CCTV."""
from langchain_core.tools import tool

# Reglas heurísticas de instalación
CAMARA_POR_METRO_PERIMETRO = 20     # 1 cámara bullet cada 20m lineales
CAMARA_POR_ENTRADA = 1              # 1 cámara dome por entrada
MARGEN_NVR = 0.25                   # 25% margen canales extras
CABLE_POR_CAMARA_METROS = 20        # ~20m de cable por cámara


def _redondear_canales_nvr(total_camaras: int) -> int:
    """Redondea a la potencia de 4 más cercana: 4, 8, 16, 32."""
    canales = round(total_camaras * (1 + MARGEN_NVR))
    return min([4, 8, 16, 32], key=lambda x: abs(x - canales))


def _redondear_puertos_switch(total_camaras: int) -> int:
    """Redondea al puerto PoE estándar más cercano: 4, 8, 16, 24."""
    return min([4, 8, 16, 24], key=lambda x: abs(x - total_camaras))


@tool
def calcular_instalacion(
    ancho_metros: float,
    largo_metros: float,
    entradas: int,
    tipo_espacio: str = "bodega",
) -> str:
    """Calcula equipos CCTV necesarios según dimensiones del espacio.

    Args:
        ancho_metros: ancho del espacio en metros
        largo_metros: largo del espacio en metros
        entradas: número de accesos/entradas a cubrir
        tipo_espacio: 'bodega', 'oficina', 'local_comercial', 'casa'
    """
    perimetro = 2 * (ancho_metros + largo_metros)
    camaras_perimetro = max(1, round(perimetro / CAMARA_POR_METRO_PERIMETRO))
    camaras_entradas = entradas * CAMARA_POR_ENTRADA
    total_camaras = camaras_perimetro + camaras_entradas
    canales_nvr = _redondear_canales_nvr(total_camaras)
    puertos_switch = _redondear_puertos_switch(total_camaras)
    cable_metros = total_camaras * CABLE_POR_CAMARA_METROS

    return (
        f"📐 CÁLCULO DE INSTALACIÓN — {tipo_espacio.upper()}\n\n"
        f"📏 Dimensiones: {ancho_metros}×{largo_metros}m | "
        f"Perímetro: {perimetro}m | Entradas: {entradas}\n\n"
        f"🔧 EQUIPOS RECOMENDADOS:\n"
        f"• {camaras_perimetro} cámaras bullet (perímetro, IR 30-50m)\n"
        f"• {camaras_entradas} cámaras dome (entradas, con WDR para contraluz)\n"
        f"• 1 NVR de {canales_nvr} canales\n"
        f"• 1 switch PoE de {puertos_switch} puertos\n"
        f"• ~{cable_metros}m cable UTP categoría 6\n\n"
        f"💡 Las cámaras exactas dependen de la marca y resolución deseada.\n"
        f"   Para Hikvision Value Series: ~$350.000-450.000 COP por cámara.\n"
        f"   ¿Quieres que busque modelos específicos en el catálogo?"
    )
