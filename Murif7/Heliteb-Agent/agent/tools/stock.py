"""Stock tool: consult product availability across HELITEB warehouses.

The four warehouses are:
- Bodega Obrero   — Medellín
- Bodega Centro   — Medellín
- Bodega Montería — Montería
- Bodega Bogotá   — Bogotá

Only rows with ``cantidad_disponible > 0`` are returned by the data layer.
"""
from __future__ import annotations

import logging
from langchain_core.tools import tool

from db.supabase import get_product_by_sap, get_stock

logger = logging.getLogger("heliteb.tools.stock")


@tool
def consultar_stock(codigo_sap: str) -> str:
    """Consulta la disponibilidad de un producto en las 4 bodegas de HELITEB.

    Busca en Bodega Obrero (Medellín), Bodega Centro (Medellín),
    Bodega Montería (Montería) y Bodega Bogotá (Bogotá). Solo lista
    bodegas con cantidad disponible mayor a cero.

    USA cuando: el asesor pregunta por disponibilidad, existencias,
    inventario, "hay stock", "qué bodega tiene", "para entrega inmediata",
    "en stock en Bogotá/Medellín/Montería". NO USA cuando: el asesor
    solo describe un producto sin mencionar disponibilidad (usa
    ``buscar_producto`` primero para obtener el SAP, luego
    ``consultar_stock`` con ese SAP).

    Args:
        codigo_sap: Código SAP de 9 dígitos del producto (ej: '311315990').
            Si el asesor solo describe el producto sin SAP, llama primero
            a ``buscar_producto`` para obtener el SAP y luego llámame con
            ese código.

    Returns:
        Lista de bodegas con cantidad disponible, o "SIN STOCK en ninguna
        bodega" si ninguna tiene existencias. El encabezado incluye la
        marca y el modelo del producto.
    """
    logger.info("consultar_stock invoked: codigo_sap=%r", codigo_sap)
    try:
        product_resp = get_product_by_sap(codigo_sap)
    except Exception as exc:  # noqa: BLE001
        return f"❌ Error consultando el producto: {exc}"

    product = product_resp.data if product_resp else None
    if not product:
        return f"❌ No encontré el producto con SAP {codigo_sap}."

    marca = product.get("marca", "")
    modelo = product.get("modelo", "")
    header = f"📦 STOCK — {marca} {modelo} (SAP: {codigo_sap})".strip()

    try:
        stock_resp = get_stock(codigo_sap)
    except Exception as exc:  # noqa: BLE001
        return f"{header}\n\n❌ Error consultando inventario: {exc}"

    rows = stock_resp.data or []
    if not rows:
        return f"{header}\n\n⚠️  SIN STOCK en ninguna bodega."

    lines = [header, "\nDisponibilidad por bodega:"]
    total = 0
    for row in rows:
        bodega = row.get("heliteb_bodegas") or {}
        nombre = bodega.get("nombre_sucursal", "Bodega")
        ciudad = bodega.get("ciudad", "")
        try:
            cantidad = int(row.get("cantidad_disponible", 0) or 0)
        except (TypeError, ValueError):
            cantidad = 0
        total += cantidad
        lines.append(f"  • {nombre} ({ciudad}): {cantidad} unidades")

    lines.append(f"\nTotal disponible: {total} unidades")
    return "\n".join(lines)
