"""Supabase data-access layer for the HELITEB agent.

All HELITEB tables are prefixed with ``heliteb_`` to coexist with other
projects in the same Supabase project. The service-role key is used because
the agent runs server-side and needs full read/write access.

Required env vars
-----------------
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import os
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a process-wide Supabase client (singleton)."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def search_products_text(query: str, limit: int = 5):
    """Text search over ``heliteb_productos`` using ILIKE on relevant fields.
    
    Falls back to ILIKE search when no embeddings are available. Searches
    across marca, modelo, descripcion, and categoria fields.
    """
    sb = get_supabase()
    # Build OR filter across searchable fields
    pattern = f"%{query}%"
    return (
        sb.table("heliteb_productos")
        .select("*, heliteb_precios(*)")
        .or_(
            f"marca.ilike.{pattern},"
            f"modelo.ilike.{pattern},"
            f"descripcion.ilike.{pattern},"
            f"categoria.ilike.{pattern},"
            f"linea.ilike.{pattern},"
            f"codigo_sap.ilike.{pattern}"
        )
        .limit(limit)
        .execute()
    )


def search_products(query_embedding: list[float], limit: int = 5):
    """Vector search via match_products RPC (pgvector cosine similarity).

    Backwards-compat wrapper for callers not yet migrated to the
    hybrid search RPC ``buscar_productos_hibrido``. New code should
    prefer ``buscar_productos_hibrido_rpc`` instead.
    """
    sb = get_supabase()
    return sb.rpc(
        "match_products",
        {"query_embedding": query_embedding, "match_limit": limit},
    ).execute()


def buscar_productos_hibrido_rpc(
    query_text: str,
    query_embedding: list[float],
    match_count: int = 10,
    categoria: str | None = None,
    linea: str | None = None,
    marca: str | None = None,
    bodega_id: int | None = None,
    stock_min: int | None = None,
    sort: str | None = None,
    rrf_k: int = 60,
):
    """Hybrid search (tsvector + pgvector + RRF) via the
    ``buscar_productos_hibrido`` RPC created in Paso 2 of the migration.

    Combines full-text search over ``heliteb_productos.fts`` (Spanish
    unaccent + stemming) with cosine similarity over
    ``heliteb_producto_embeddings`` (tipo='descripcion'), fused by
    Reciprocal Rank Fusion (k=60).

    Hard filters (categoria / linea / marca / bodega_id / stock_min) are
    applied via EXISTS against ``heliteb_inventario`` so 1-N bodega rows
    never duplicate product rows.

    Args:
        query_text: free-text query in Spanish (e.g., "cámara wifi audio
            bidireccional"). Used for the FTS branch.
        query_embedding: 1024-dim BGE-M3 embedding of the same query.
            Used for the semantic branch. Pass ``None`` to disable the
            semantic branch (caller should rarely do this; the RPC
            expects a vector).
        match_count: max rows returned (capped at 30 by the RPC).
        categoria / linea / marca: optional substring filters on the
            matching columns. None = no filter.
        bodega_id: optional filter on ``heliteb_inventario.id_bodega``.
            None = no filter.
        stock_min: optional minimum ``cantidad_disponible``. None = no
            filter. Pass ``0`` to require any stock.
        sort: ``'price_asc'`` / ``'price_desc'`` to override RRF order;
            any other value (including None) keeps RRF ranking.
        rrf_k: RRF smoothing constant. Default 60 is the literature
            stable value; do not tune per-corpus.

    Returns:
        Supabase APIResponse with rows of (codigo_sap, marca, modelo,
        descripcion, linea, categoria, serie, precio_msrp_cop,
        rrf_score, similarity).
    """
    sb = get_supabase()
    params = {
        "p_query_text": query_text,
        "p_query_embedding": query_embedding,
        "p_match_count": match_count,
        "p_categoria": categoria,
        "p_linea": linea,
        "p_marca": marca,
        "p_bodega_id": bodega_id,
        "p_stock_min": stock_min,
        "p_sort": sort,
        "p_rrf_k": rrf_k,
    }
    return sb.rpc("buscar_productos_hibrido", params).execute()


def search_similar_text(query: str, exclude_sap: str, limit: int = 3):
    """Find similar products using text search on category/linea."""
    sb = get_supabase()
    return (
        sb.table("heliteb_productos")
        .select("*, heliteb_precios(*)")
        .or_(f"categoria.ilike.%{query}%,linea.ilike.%{query}%,marca.ilike.%{query}%")
        .neq("codigo_sap", exclude_sap)
        .limit(limit)
        .execute()
    )


def get_product_by_sap(codigo_sap: str):
    """Fetch a product by its SAP code, joined with ``heliteb_precios``."""
    sb = get_supabase()
    return (
        sb.table("heliteb_productos")
        .select("*, heliteb_precios(*)")
        .eq("codigo_sap", codigo_sap)
        .maybe_single()
        .execute()
    )


def get_stock(codigo_sap: str):
    """List stock rows for a product, joined with ``heliteb_bodegas``.

    Only returns rows with ``cantidad_disponible > 0``.
    """
    sb = get_supabase()
    return (
        sb.table("heliteb_inventario")
        .select("cantidad_disponible, heliteb_bodegas(nombre_sucursal, ciudad)")
        .eq("codigo_sap", codigo_sap)
        .gt("cantidad_disponible", 0)
        .execute()
    )


def search_similar_products(
    embedding: list[float],
    exclude_sap: str,
    limit: int = 3,
):
    """Vector search via the ``match_similar_products`` RPC.

    Excludes the product identified by ``exclude_sap`` from the results.
    """
    sb = get_supabase()
    return sb.rpc(
        "match_similar_products",
        {
            "query_embedding": embedding,
            "exclude_sap": exclude_sap,
            "match_limit": limit,
        },
    ).execute()


def get_competition_prices(codigo_sap: str):
    """Return the 5 most recent competitor prices for a product."""
    sb = get_supabase()
    return (
        sb.table("heliteb_precios_competencia")
        .select("*")
        .eq("codigo_sap", codigo_sap)
        .order("fecha_consulta", desc=True)
        .limit(5)
        .execute()
    )


def save_conversation(
    cliente_id: str,
    canal: str,
    msg_usuario: str,
    msg_agente: str,
    intent: str,
):
    """Persist a single conversation turn to ``heliteb_conversaciones``."""
    sb = get_supabase()
    return (
        sb.table("heliteb_conversaciones")
        .insert(
            {
                "cliente_id": cliente_id,
                "canal": canal,
                "mensaje_usuario": msg_usuario,
                "mensaje_agente": msg_agente,
                "intent_detectado": intent,
            }
        )
        .execute()
    )


def search_variants_by_model_prefix(modelo_prefix: str, limit: int = 20):
    """Find all products whose ``modelo`` starts with the given prefix.

    Used by the agent to detect model variants (e.g., when a user asks for
    ``DS-2CE16D0T-IRF``, this returns both the 2.8mm and 3.6mm lens variants).

    The prefix is used as-is with a ``%`` wildcard appended for ILIKE matching,
    so ``DS-2CE16D0T-IRF`` matches ``DS-2CE16D0T-IRF(2.8mm)(C)`` and
    ``DS-2CE16D0T-IRF(3.6mm)(C)``.

    Returns:
        List of dicts with ``codigo_sap``, ``modelo``, ``marca``, ``categoria``,
        ``descripcion``, and nested ``heliteb_precios`` data.
    """
    sb = get_supabase()
    pattern = f"{modelo_prefix}%"
    return (
        sb.table("heliteb_productos")
        .select("codigo_sap, modelo, marca, categoria, descripcion, heliteb_precios(precio_msrp_cop)")
        .ilike("modelo", pattern)
        .limit(limit)
        .execute()
    )
