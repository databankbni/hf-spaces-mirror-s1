"""Tool: inteligencia competitiva — comparativa vs mercado."""
from langchain_core.tools import tool
from db.supabase import get_competition_prices, get_product_by_sap


@tool
def comparar_competencia(codigo_sap: str) -> str:
    """Compara el precio HELITEB vs competencia (MercadoLibre, Alkosto, etc.)
    y genera argumentos de venta.

    Args:
        codigo_sap: código SAP del producto a comparar
    """
    producto_resp = get_product_by_sap(codigo_sap)
    producto = producto_resp.data if producto_resp and producto_resp.data else None
    if not producto:
        return f"Producto {codigo_sap} no encontrado."

    precios_resp = get_competition_prices(codigo_sap)
    competencia = precios_resp.data if precios_resp and precios_resp.data else []

    # Precio HELITEB: el join del DAO viene bajo la key 'heliteb_precios'
    precios_hb = producto.get("heliteb_precios") or []
    if isinstance(precios_hb, list) and precios_hb:
        precio_heliteb = float(precios_hb[0].get("precio_msrp_cop") or 0)
    else:
        precio_heliteb = 0.0

    marca = producto.get("marca", "")
    modelo = producto.get("modelo", "")

    lines = [f"📊 Comparativa: {marca} {modelo}"]
    lines.append(f"\n💰 Nuestro precio: ${precio_heliteb:,.0f} COP\n")

    if competencia:
        lines.append("🏪 Precios en el mercado:")
        for pc in competencia:
            diff = float(pc.get("precio_competencia_cop") or 0) - precio_heliteb
            signo = "+" if diff > 0 else ""
            lines.append(
                f"  • {pc.get('fuente', '?')}: "
                f"${float(pc.get('precio_competencia_cop') or 0):,.0f} COP "
                f"({signo}{diff:,.0f} vs HELITEB)"
            )
    else:
        lines.append(
            "🏪 No hay datos de competencia para este producto aún. "
            "Nuestro precio es competitivo como distribuidor oficial."
        )

    lines.append(
        "\n💪 ARGUMENTOS DE VENTA HELITEB:\n"
        f"• Garantía oficial {marca} Colombia (3 años)\n"
        "• Soporte técnico especializado post-venta\n"
        "• Factura electrónica\n"
        "• Producto homologado para Colombia (no mercado gris)\n"
        "• Disponibilidad inmediata en nuestras bodegas"
    )
    return "\n".join(lines)
