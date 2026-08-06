"""Catalog tools: hybrid search (tsvector + pgvector + RRF) for ``heliteb_productos``.

The previous dual-mode implementation (vector-only vs ILIKE-with-post-filter,
switched by the presence of categoria/linea/marca kwargs) is replaced by a
single call to the ``buscar_productos_hibrido`` RPC (see ``db.supabase``).
The RPC fuses full-text (Spanish unaccent + stemming) and cosine similarity
(BGE-M3 embeddings) via Reciprocal Rank Fusion and applies hard filters
(categoria / linea / marca / bodega_id / stock_min) via EXISTS so the 1-N
inventario relationship never duplicates product rows.

The BGE-M3 model is loaded once at module level (~2 GB RAM, ~30s first load)
to generate the query embedding passed to the RPC.
"""
from __future__ import annotations

import logging
from langchain_core.tools import tool
from sentence_transformers import SentenceTransformer

from db.supabase import (
    buscar_productos_hibrido_rpc,
    get_product_by_sap,
)

logger = logging.getLogger("heliteb.tools.catalog")

# Load BGE-M3 once at module level (cached across requests).
# On HF Spaces CPU Basic (16 GB RAM): ~2 GB RAM usage, ~30s first load.
_model = SentenceTransformer("BAAI/bge-m3")


def _fmt_cop(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "Consultar"
    return f"$ {n:,.0f}".replace(",", ".")


def _extract_price(product: dict) -> float:
    precios = product.get("heliteb_precios") or product.get("precios")
    if isinstance(precios, list) and precios:
        p0 = precios[0] or {}
        return float(p0.get("precio_msrp_cop") or 0)
    if isinstance(precios, dict):
        return float(precios.get("precio_msrp_cop") or 0)
    return float(product.get("precio_msrp_cop") or 0)


@tool
def buscar_producto(
    query: str,
    categoria: str = "",
    linea: str = "",
    marca: str = "",
    sort: str = "",
) -> str:
    """Busca productos en HELITEB usando búsqueda híbrida (FTS + vector + RRF).

    Combina full-text search (tsvector con unaccent + stemming español) y
    similitud semántica (BGE-M3 + pgvector coseno) fusionadas por Reciprocal
    Rank Fusion (k=60). Los filtros exactos (categoria, linea, marca) se
    aplican dentro de la RPC con EXISTS, no como post-filtro en Python —
    así no se duplican filas por el JOIN 1-N con ``heliteb_inventario``.

    La descripción de cada argumento (esto es lo que ve el LLM vía
    ``bind_tools``) reemplaza el diccionario hardcodeado
    ``_CATEGORIA_KEYWORDS``/``_LINEA_KEYWORDS``/``_MARCA_KEYWORDS`` del
    ``graph.py`` original. El LLM rellena los argumentos a partir del
    lenguaje natural del asesor.

    Args:
        query: texto libre en español. Ej: 'cámara wifi audio bidireccional',
            'NVR 16 canales', 'switch PoE 24 puertos'. La misma cadena se usa
            para el FTS y se embebe con BGE-M3 para el camino semántico.
        categoria: categoría del catálogo. Ej: 'Cameras Products', 'NVR',
            'Switches', 'Cables', 'Power Supplies', 'Cabinets', 'Tools',
            'Accessories'. Vacío = cualquier categoría. Substring match.
        linea: línea del producto. Ej: 'Network Cameras', 'Pro Series',
            'EasyIP', 'Value Series', 'AcuViz', 'DeepinView', 'DarkFighter',
            'ColorVu', 'Monitors'. Vacío = cualquier línea. Substring match.
        marca: marca exacta. Ej: 'Hikvision', 'HiLook', 'HIKMICRO', 'EZVIZ',
            'Dahua', 'Outsource'. Vacío = cualquier marca. Substring match.
        sort: 'price_asc' para más baratos primero, 'price_desc' para más
            caros primero. Cualquier otro valor (o vacío) = ranking RRF.
    """
    has_filters = bool(categoria or linea or marca)
    sort_param = sort if sort in ("price_asc", "price_desc") else None

    logger.info(
        "buscar_producto invoked: query=%r categoria=%r linea=%r marca=%r sort=%r",
        query, categoria, linea, marca, sort,
    )

    # 1) Generar embedding BGE-M3 de la query (camino semántico de la RPC).
    try:
        embedding = _model.encode(query, normalize_embeddings=True).tolist()
    except Exception as exc:
        # Si no podemos embedir, no podemos llamar a la RPC híbrida (requiere
        # el vector como argumento no nulo). Devolvemos error honesto.
        return f"Error generando embedding de búsqueda: {exc}"

    # 2) Llamar a la RPC híbrida (tsvector + pgvector + RRF + filtros duros).
    try:
        result = buscar_productos_hibrido_rpc(
            query_text=query,
            query_embedding=embedding,
            match_count=10,
            categoria=categoria or None,
            linea=linea or None,
            marca=marca or None,
            sort=sort_param,
        )
    except Exception as exc:
        return f"Error consultando el catálogo: {exc}"

    rows = result.data or []
    if not rows:
        if has_filters:
            filtros = []
            if categoria:
                filtros.append(f"categoría '{categoria}'")
            if linea:
                filtros.append(f"línea '{linea}'")
            if marca:
                filtros.append(f"marca '{marca}'")
            filtro_str = " y ".join(filtros)
            return (
                f"No encontré productos con {filtro_str} para: {query}. "
                "¿Intentaste con otros filtros o palabras clave?"
            )
        return (
            f"No encontré productos para: {query}. "
            "¿Intentaste con otras palabras clave?"
        )

    # 3) Formatear la salida igual que la versión anterior para no romper
    #    el contrato texto del tool (los tests y callers esperan el formato
    #    "Resultados para: ..." con "  Marca Modelo (SAP: X) — $ Y COP (Z%)").
    lines = [f"Resultados para: {query}"]
    for r in rows:
        marca_val = r.get("marca") or "N/A"
        modelo_val = r.get("modelo") or "N/A"
        sap = r.get("codigo_sap") or ""
        precio = _extract_price(r)
        sim = r.get("similarity")
        sim_str = f" ({sim:.0%})" if sim is not None else ""
        lines.append(
            f"  {marca_val} {modelo_val} (SAP: {sap}) — {_fmt_cop(precio)} COP{sim_str}"
        )
    return "\n".join(lines)


@tool
def ficha_producto(codigo_sap: str) -> str:
    """Ficha técnica completa de un producto por código SAP.

    USA cuando: el asesor pide especificaciones, ficha técnica, detalles,
    características de un producto específico cuyo SAP ya conoces. Si
    no tienes el SAP, llama primero a ``buscar_producto`` para
    encontrarlo (puede devolverlo en "(SAP: XXXXXXXXX)").

    Args:
        codigo_sap: código SAP de 9 dígitos del producto (ej: '311315990').
            Si no lo tienes, usa ``buscar_producto`` primero.
    """
    try:
        result = get_product_by_sap(codigo_sap)
    except Exception as exc:
        return f"Error consultando el producto: {exc}"

    product = result.data if result else None
    if not product:
        logger.warning("ficha_producto: SAP %s no encontrado en catálogo", codigo_sap)
        return f"No encontre el producto con SAP {codigo_sap}."

    logger.info("ficha_producto: SAP=%s modelo=%s marca=%s",
                codigo_sap, product.get("modelo", "?"), product.get("marca", "?"))

    lines = [
        "FICHA TECNICA",
        "=============",
        f"SAP:       {product.get('codigo_sap', codigo_sap)}",
        f"Marca:     {product.get('marca', 'N/A')}",
        f"Modelo:    {product.get('modelo', 'N/A')}",
        f"Categoria: {product.get('categoria', 'N/A')}",
        f"Linea:     {product.get('linea', 'N/A')}",
        f"Serie:     {product.get('serie', 'N/A')}",
    ]

    descripcion = product.get("descripcion")
    if descripcion:
        lines.append(f"\nDescripcion:\n{descripcion}")

    specs = []
    for key, label in [
        ("parametro_1", "Param 1"),
        ("parametro_2", "Param 2"),
        ("parametro_3", "Param 3"),
    ]:
        val = product.get(key)
        if val:
            specs.append(f"  {label}: {val}")
    if specs:
        lines.append("\nEspecificaciones:\n" + "\n".join(specs))

    precio = _extract_price(product)
    lines.append(f"\nPrecio MSRP: {_fmt_cop(precio)} COP")
    return "\n".join(lines)
