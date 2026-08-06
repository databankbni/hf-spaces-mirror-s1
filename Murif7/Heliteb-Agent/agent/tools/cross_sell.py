"""Tool: venta cruzada técnica — productos complementarios via BGE-M3 + pgvector."""
from langchain_core.tools import tool
from sentence_transformers import SentenceTransformer
from db.supabase import search_similar_products, search_similar_text, get_product_by_sap

# Reuse BGE-M3 (SentenceTransformer caches internally, so loading twice
# from different modules is harmless but we keep it explicit here).
_model = SentenceTransformer("BAAI/bge-m3")


@tool
def sugerir_complementos(codigo_sap: str) -> str:
    """Sugiere productos complementarios técnicamente compatibles usando BGE-M3.

    Genera un embedding del producto base y busca los más cercanos en el
    espacio vectorial via match_similar_products RPC (pgvector cosine similarity).
    Si el vector search falla, cae a ILIKE por categoría/marca.

    USA cuando: el asesor pregunta "qué accesorios necesito para X",
    "complementos para", "qué más necesito para instalar este equipo",
    "venta cruzada". NO USA cuando: el asesor solo quiere buscar productos
    (usa ``buscar_producto``).

    Args:
        codigo_sap: código SAP de 9 dígitos del producto base. Si el asesor
            describe el producto sin SAP, llama primero a ``buscar_producto``
            para obtener el SAP.
    """
    producto = get_product_by_sap(codigo_sap)
    if not producto:
        return f"Producto {codigo_sap} no encontrado."

    pdata = producto.data if hasattr(producto, 'data') else producto
    marca = pdata.get('marca', '')
    modelo = pdata.get('modelo', '')
    categoria = pdata.get('categoria', '')
    descripcion = pdata.get('descripcion', '')

    lines = [f"🔄 Para {marca} {modelo}:"]

    # Determinar tipo de producto para sugerencias específicas
    es_camara = 'camara' in (categoria or '').lower() or 'camera' in (categoria or '').lower()

    if es_camara:
        lines.append("\n📦 Complementos necesarios para instalación:")
        lines.append("  • NVR compatible con la marca y resolución")
        lines.append("  • Switch PoE con puertos suficientes")
        lines.append("  • Cable UTP categoría 6 para exterior")
        lines.append("  • Fuente de poder / UPS de respaldo")

    # 1) Vector search: generate embedding for the base product
    sdata: list[dict] = []
    try:
        texto = f"{marca} {modelo} {categoria} {descripcion}"
        embedding = _model.encode(texto, normalize_embeddings=True).tolist()
        similares = search_similar_products(embedding, codigo_sap, limit=4)
        sdata = similares.data if hasattr(similares, 'data') else (similares or [])
    except Exception:
        pass

    # 2) Fallback to ILIKE if no vector results
    if not sdata:
        similares = search_similar_text(categoria or marca, codigo_sap, limit=4)
        sdata = similares.data if hasattr(similares, 'data') else (similares or [])

    if sdata:
        lines.append("\n🔗 Productos complementarios en catálogo:")
        for s in sdata:
            smarca = s.get('marca', '?')
            smodelo = s.get('modelo', '?')
            sprecio = 0
            precios = s.get('heliteb_precios', [])
            if isinstance(precios, list) and precios:
                sprecio = float(precios[0].get('precio_msrp_cop', 0))
            sim = s.get("similarity")
            sim_str = f" ({sim:.0%})" if sim is not None else ""
            lines.append(f"  • {smarca} {smodelo} — ${sprecio:,.0f} COP{sim_str}")

    return "\n".join(lines)
