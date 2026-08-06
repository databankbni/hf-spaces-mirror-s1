"""Tool: generación de cotizaciones PDF."""
from langchain_core.tools import tool
from db.supabase import get_product_by_sap


@tool
def generar_cotizacion(
    codigos_sap: str,
    cliente_nombre: str,
    cliente_whatsapp: str = "",
) -> str:
    """Genera una cotización en PDF y la registra en el sistema.

    USA cuando: el asesor solicita explícitamente una cotización, proforma,
    presupuesto o PDF formal. NO USA cuando: solo pregunta por precios
    (usa ``ficha_producto`` para el MSRP).

    FLUJO OBLIGATORIO (no saltes pasos):
      1. Si el asesor describe productos sin SAP, llama primero
         ``buscar_producto`` para obtener los códigos SAP.
      2. Pide al asesor que confirme los SAPs si hubo múltiples resultados.
      3. Pregunta: "¿A nombre de qué cliente se genera la cotización?"
         y espera la respuesta. NO generes la cotización sin un nombre
         completo de cliente.
      4. Recién entonces llama a esta herramienta con los SAPs (separados
         por coma) y el nombre del cliente.

    Args:
        codigos_sap: códigos SAP separados por coma (ej: '311315990,311315672').
            Cada código debe ser de 9 dígitos. Si el asesor mencionó un
            modelo pero no el SAP, obtén el SAP primero con ``buscar_producto``.
        cliente_nombre: nombre completo del cliente (NO nombre del asesor
            HELITEB, sino del cliente final para quien se cotiza). Obligatorio.
        cliente_whatsapp: número WhatsApp del cliente (opcional, para
            follow-up). Vacío si no se proporciona.

    Returns:
        Resumen de la cotización con ID y total.
    """
    codigos = [c.strip() for c in codigos_sap.split(",")]
    items = []
    total = 0

    for codigo in codigos:
        p_resp = get_product_by_sap(codigo)
        p = p_resp.data if p_resp and p_resp.data else None
        if p:
            precios_hb = p.get("heliteb_precios") or []
            if isinstance(precios_hb, list) and precios_hb:
                precio = float(precios_hb[0].get("precio_msrp_cop") or 0)
            else:
                precio = 0.0
            marca = p.get("marca", "")
            modelo = p.get("modelo", "")
            items.append({
                "codigo_sap": codigo,
                "modelo": f"{marca} {modelo}",
                "precio": precio,
            })
            total += precio

    lines = [f"📄 COTIZACIÓN — {cliente_nombre}"]
    lines.append(f"Total productos: {len(items)}")
    lines.append("")
    for item in items:
        lines.append(
            f"  • {item['modelo']} — ${item['precio']:,.0f} COP"
        )
    lines.append(f"\n💰 TOTAL: ${total:,.0f} COP")

    if cliente_whatsapp:
        lines.append(f"\n📱 Se enviará al WhatsApp {cliente_whatsapp}")
        lines.append("⏰ Follow-up programado en 3 días si no hay respuesta")

    return "\n".join(lines)
