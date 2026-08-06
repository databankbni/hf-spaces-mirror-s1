"""
server.py — MCP server exposing semantic Bible search.

Runs in two modes:
  stdio (default)  — for Claude Desktop local use
  SSE              — for remote/hosted use (pass --sse or set PORT env var)

Environment variables:
    CHROMA_PATH      Path to ChromaDB built by the indexer (default: ./bible_chroma_db)
    PORT             If set, enables SSE mode on this port (HuggingFace Spaces uses 7860)
"""

import os
import sys
from pathlib import Path
from typing import Any

import chromadb
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .constants import _BOOK_LOOKUP, ALL_TRANSLATIONS, TRANSLATION_META

MODEL_NAME = "intfloat/multilingual-e5-small"


def resolve_book_number(book: str) -> int | None:
    """Resolve German or English book name (case-insensitive) to book number."""
    return _BOOK_LOOKUP.get(book.strip().lower())


def score_from_distance(distance: float) -> float:
    """Convert cosine distance to similarity score [0, 1]."""
    return round(max(0.0, 1.0 - distance), 4)


def _extract_text(doc: str) -> str:
    """Extract verse text from a stored document string ('Ref — text' format)."""
    return doc.split(" — ", 1)[-1] if " — " in doc else doc


# ---------------------------------------------------------------------------
# Server state (initialized once at startup)
# ---------------------------------------------------------------------------

_model = None        # SentenceTransformer
_chroma_client = None


def get_collection(name: str):
    try:
        return _chroma_client.get_collection(name, embedding_function=None)
    except Exception as e:
        print(f"Warning: collection '{name}' unavailable: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_search_bible(
    query: str,
    translation: str = "GerBoLut",
    n_results: int = 10,
    testament: str | None = None,
) -> list[dict]:
    # E5 models use "query: " prefix for queries
    query_embedding = _model.encode(f"query: {query}", normalize_embeddings=True).tolist()

    where_filter = {"testament": testament} if testament in ("OT", "NT") else None

    translations_to_search = ALL_TRANSLATIONS if translation == "all" else [translation]
    raw_results: list[dict] = []

    for tname in translations_to_search:
        col = get_collection(tname)
        if col is None:
            continue
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where_filter:
            kwargs["where"] = where_filter
        try:
            results = col.query(**kwargs)
        except Exception as e:
            print(f"Warning: query failed for '{tname}': {e}", file=sys.stderr)
            continue

        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            raw_results.append({
                "reference": f"{meta['book']} {meta['chapter']}:{meta['verse']}",
                "reference_en": f"{meta['book_en']} {meta['chapter']}:{meta['verse']}",
                "text": _extract_text(doc),
                "translation": meta["translation"],
                "score": score_from_distance(dist),
                "_canon_key": f"{meta['book_number']}_{meta['chapter']}_{meta['verse']}",
                "_doc": doc,
            })

    if translation == "all":
        best: dict[str, dict] = {}
        for r in raw_results:
            key = r["_canon_key"]
            if key not in best or r["score"] > best[key]["score"]:
                best[key] = r
        raw_results = sorted(best.values(), key=lambda x: x["score"], reverse=True)[:n_results]
    else:
        raw_results.sort(key=lambda x: x["score"], reverse=True)

    return [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in raw_results
    ]


def tool_get_verse(
    book: str,
    chapter: int,
    verse: int,
    translation: str = "GerBoLut",
) -> dict | list[dict]:
    book_number = resolve_book_number(book)
    if book_number is None:
        return {"error": f"Unknown book name: '{book}'"}

    translations_to_query = ALL_TRANSLATIONS if translation == "all" else [translation]
    results = []

    for tname in translations_to_query:
        col = get_collection(tname)
        if col is None:
            continue
        doc_id = f"{tname}_{book_number}_{chapter}_{verse}"
        try:
            res = col.get(ids=[doc_id], include=["documents", "metadatas"])
        except Exception as e:
            print(f"Warning: get failed for '{tname}': {e}", file=sys.stderr)
            continue
        if not res["ids"]:
            continue
        meta = res["metadatas"][0]
        doc = res["documents"][0]
        results.append({
            "reference": f"{meta['book']} {chapter}:{verse}",
            "reference_en": f"{meta['book_en']} {chapter}:{verse}",
            "text": _extract_text(doc),
            "translation": tname,
        })

    if translation != "all":
        return results[0] if results else {"error": f"Verse not found: {book} {chapter}:{verse} in {translation}"}
    return results


MAX_N_RESULTS = 50
_VALID_TRANSLATIONS = set(ALL_TRANSLATIONS) | {"all"}


async def handle_search(request):
    """REST wrapper around ``tool_search_bible``.

    ``GET /search?query=...&translation=GerBoLut&n_results=10&testament=NT``

    Returns ``{query, translation, count, results: [...]}`` where each result
    has the same shape as the ``search_bible`` MCP tool. Provided so plain HTTP
    clients (e.g. an edge Worker) can use semantic search without an MCP/SSE
    handshake. Errors return an ``{"error": ...}`` body with a 4xx status.
    """
    from starlette.responses import JSONResponse

    params = request.query_params

    query = (params.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "Missing required 'query' parameter."}, status_code=400)

    translation = params.get("translation", "GerBoLut")
    if translation not in _VALID_TRANSLATIONS:
        valid = ", ".join(sorted(_VALID_TRANSLATIONS))
        return JSONResponse(
            {"error": f"Unknown translation '{translation}'. Valid values: {valid}."},
            status_code=400,
        )

    raw_n = params.get("n_results", "10")
    try:
        n_results = int(raw_n)
    except (TypeError, ValueError):
        return JSONResponse({"error": "'n_results' must be an integer."}, status_code=400)
    n_results = max(1, min(MAX_N_RESULTS, n_results))

    testament = params.get("testament")
    if testament is not None and testament not in ("OT", "NT"):
        return JSONResponse(
            {"error": "'testament' must be 'OT' or 'NT' when provided."},
            status_code=400,
        )

    results = tool_search_bible(
        query=query,
        translation=translation,
        n_results=n_results,
        testament=testament,
    )
    return JSONResponse(
        {
            "query": query,
            "translation": translation,
            "count": len(results),
            "results": results,
        }
    )


def tool_list_translations() -> list[dict]:
    output = []
    for tname, meta in TRANSLATION_META.items():
        col = get_collection(tname)
        verse_count = col.count() if col else 0
        output.append({
            "id": tname,
            "language": meta["language"],
            "description": meta["description"],
            "verse_count": verse_count,
            "indexed": col is not None,
        })
    return output


# ---------------------------------------------------------------------------
# MCP server definition
# ---------------------------------------------------------------------------

server = Server("luther-bible")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_bible",
            description=(
                "Semantic search over the Bible. Supports German and English queries. "
                "Returns the most relevant verses by meaning, not just keyword match."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (any language — German or English both work)",
                    },
                    "translation": {
                        "type": "string",
                        "enum": ["GerBoLut", "KJV", "web", "all"],
                        "default": "GerBoLut",
                        "description": "Which translation to search. Use 'all' to search all and deduplicate.",
                    },
                    "n_results": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                        "description": "Number of results to return.",
                    },
                    "testament": {
                        "type": "string",
                        "enum": ["OT", "NT"],
                        "description": "Optional filter: 'OT' (Old Testament) or 'NT' (New Testament).",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_verse",
            description=(
                "Retrieve an exact Bible verse by reference. "
                "Accepts German or English book names (case-insensitive)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "book": {
                        "type": "string",
                        "description": "Book name in German or English, e.g. 'Johannes' or 'John'.",
                    },
                    "chapter": {
                        "type": "integer",
                        "description": "Chapter number.",
                    },
                    "verse": {
                        "type": "integer",
                        "description": "Verse number.",
                    },
                    "translation": {
                        "type": "string",
                        "enum": ["GerBoLut", "KJV", "web", "all"],
                        "default": "GerBoLut",
                        "description": "Translation. Use 'all' to get the verse from every available translation.",
                    },
                },
                "required": ["book", "chapter", "verse"],
            },
        ),
        Tool(
            name="list_translations",
            description="List available Bible translations with metadata and verse counts.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    import json

    if name == "search_bible":
        result = tool_search_bible(
            query=arguments["query"],
            translation=arguments.get("translation", "GerBoLut"),
            n_results=arguments.get("n_results", 10),
            testament=arguments.get("testament"),
        )
    elif name == "get_verse":
        result = tool_get_verse(
            book=arguments["book"],
            chapter=int(arguments["chapter"]),
            verse=int(arguments["verse"]),
            translation=arguments.get("translation", "GerBoLut"),
        )
    elif name == "list_translations":
        result = tool_list_translations()
    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


# ---------------------------------------------------------------------------
# Entry points (called from __main__.py)
# ---------------------------------------------------------------------------

def _init_globals(chroma_path: str) -> None:
    global _model, _chroma_client

    chroma_dir = Path(chroma_path)
    if not chroma_dir.exists():
        print(f"Error: CHROMA_PATH '{chroma_dir}' does not exist. Run: python -m luther_mcp index", file=sys.stderr)
        sys.exit(1)

    print(f"Loading embedding model '{MODEL_NAME}' ...", file=sys.stderr)
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer(MODEL_NAME)

    _chroma_client = chromadb.PersistentClient(path=str(chroma_dir))


async def main():
    """stdio transport — for local Claude Desktop use."""
    chroma_path = os.environ.get("CHROMA_PATH", "./bible_chroma_db")
    _init_globals(chroma_path)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def main_sse(port: int = 7860):
    """SSE transport — for remote/hosted use (HuggingFace Spaces etc.)."""
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    chroma_path = os.environ.get("CHROMA_PATH", "./bible_chroma_db")
    _init_globals(chroma_path)

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        from starlette.responses import Response
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    async def handle_health(request):
        from starlette.responses import JSONResponse
        return JSONResponse({"status": "ok", "service": "luther-bible-mcp"})

    app = Starlette(routes=[
        Route("/", handle_health, methods=["GET"]),
        Route("/search", handle_search, methods=["GET"]),
        Route("/sse", handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ])

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    await uvicorn.Server(config).serve()
