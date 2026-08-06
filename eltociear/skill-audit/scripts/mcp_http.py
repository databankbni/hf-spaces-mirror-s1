#!/usr/bin/env python3
"""MCP over Streamable HTTP, mounted on the same FastAPI app that serves the paid routes.

Why this exists: today's measurement says x402 is not a marketplace. Across the top 18
buyers, 13 pay exactly ONE seller and the largest sends 5,876 transfers a day to a single
provider. Nothing on that network is bought because it was discovered in a catalog — every
large flow is one buyer wired into one provider. Our own 127 payers averaging 1.1 calls is
the signature of being CRAWLED, not of being bought from.

MCP is the one channel we own that produces the other shape. A human adds a server to their
client once and it is then used repeatedly, by them, for as long as it is useful. That is
the integration shape, arrived at deliberately rather than by discovery.

We already had five servers in the official MCP registry — and all five listed ONLY an
`ghcr.io` OCI image with `remotes: null`, i.e. Docker-or-nothing, while we run live HTTP
Spaces that advertised no MCP endpoint at all (`/mcp`, `/sse`, `/messages` were all 404).
This closes that gap so the registry entries can carry a URL.

The tools here are deliberately the FREE-UPSTREAM ones. Every backend behind them
(Open-Meteo, USGS, Nager.Date, World Bank, the multi-engine search) costs nothing per call,
so giving them away has no marginal cost, and adoption is the thing we do not have. The
crypto, security and LLM routes stay paid on the x402 side.

⚠ MOUNTING TRAP: `tokenguard_api/main.py` sweeps EVERY POST route into the paywall with no
exclusion list — deliberately, because 45 routes once escaped it by being forgotten. A
paywalled `/mcp` cannot work: MCP clients do not speak x402 and would get 402 on every
JSON-RPC frame. The mount MUST add these paths to the sweep's exclusion set.
"""
import json
from typing import Any

from fastapi import APIRouter, Request, Response

router = APIRouter()

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "tokenguard"
SERVER_VERSION = "1.2.0"

# Paths the x402 sweep must NOT paywall. Imported by main.py rather than duplicated there,
# so adding a route here cannot silently become a paid route over there.
FREE_PATHS = {"POST /mcp", "GET /mcp"}


def _tool(name, description, properties, required):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


TOOLS = [
    _tool("air_quality",
          "Current air quality for a place: PM2.5, PM10, ozone, NO2, SO2, CO and dust, plus "
          "the US and European AQI and the US AQI band ('Good', 'Unhealthy'). Takes a place "
          "name — no coordinates needed.",
          {"location": {"type": "string", "description": "Place name, e.g. 'Tokyo'"}},
          ["location"]),
    _tool("geocode",
          "Resolve a place name to coordinates, country, admin region, timezone, elevation "
          "and population.",
          {"name": {"type": "string", "description": "Place name to resolve"},
           "count": {"type": "integer", "description": "1-20 candidates (default 5)"}},
          ["name"]),
    _tool("earthquakes",
          "Recent earthquakes from the USGS feed — worldwide, or within a radius of a named "
          "place. Returns magnitude, depth, tsunami flag and felt reports.",
          {"min_magnitude": {"type": "number", "description": "Lower bound (default 4.5)"},
           "days": {"type": "integer", "description": "1-30 days back (default 1)"},
           "limit": {"type": "integer", "description": "1-100 events (default 20)"},
           "location": {"type": "string", "description": "Centre on a place name"},
           "radius_km": {"type": "number", "description": "Radius around location (default 500)"}},
          []),
    _tool("public_holidays",
          "Public holidays for a country and year, with local names and a past/upcoming flag.",
          {"country": {"type": "string", "description": "ISO 2-letter country code, e.g. JP"},
           "year": {"type": "integer", "description": "Calendar year (defaults to current)"}},
          ["country"]),
    _tool("country_indicator",
          "World Bank time series for a country: gdp, gdp_per_capita, population, inflation, "
          "unemployment, life_expectancy, co2_per_capita or internet_users.",
          {"country": {"type": "string", "description": "ISO 2- or 3-letter country code"},
           "indicator": {"type": "string", "description": "Alias above, or a World Bank code"},
           "years": {"type": "integer", "description": "1-60 most recent years (default 5)"}},
          ["country"]),
    _tool("elevation",
          "Ground elevation in metres for a place name.",
          {"location": {"type": "string", "description": "Place name"}},
          ["location"]),
    _tool("web_search",
          "Search the live web and return ranked title/url/snippet results, through an "
          "automatic multi-engine failover chain.",
          {"query": {"type": "string", "description": "Search query"},
           "max_results": {"type": "integer", "description": "1-25 (default 10)"}},
          ["query"]),
    _tool("read_url",
          "Fetch a URL and return its main content as clean Markdown, boilerplate stripped.",
          {"url": {"type": "string", "description": "Page to fetch"}},
          ["url"]),
]


# Host-specific tools. Both Spaces mount this module, and serving the same eight tools twice
# would just be two URLs for one product. skill-audit's distinctive asset is the malicious-
# pattern scanner, which is also the tool a human has an actual reason to install — so it
# registers that here rather than duplicating the data tools.
_EXTRA_TOOLS: list = []
_EXTRA_DISPATCH: list = []


def register_extra(tools, dispatch):
    """Add host-specific tools. `dispatch(name, args)` may be sync or async; it is only
    consulted for names it declared, so a failure here cannot shadow the built-ins."""
    _EXTRA_TOOLS.extend(tools)
    _EXTRA_DISPATCH.append((frozenset(t["name"] for t in tools), dispatch))


def set_identity(name, version=None):
    """Declare which server this host IS.

    This router is shared, so `SERVER_NAME` defaulting to "tokenguard" meant the
    skill-audit Space answered `initialize` with `serverInfo.name = "tokenguard"`
    (measured 2026-07-29 against the live remote). The MCP registry lists that URL as
    `skill-audit-mcp`, so a developer installing the scanner saw it announce itself as a
    different product — in the one funnel that the buyer-monogamy finding says actually
    wins customers. Every host that mounts this router should call it.
    """
    global SERVER_NAME, SERVER_VERSION
    SERVER_NAME = name
    if version:
        SERVER_VERSION = version


def _all_tools():
    return TOOLS + _EXTRA_TOOLS


async def _dispatch(name: str, args: dict) -> Any:
    """Run a tool by reusing the route handlers in-process — no HTTP round trip to ourselves."""
    import inspect
    for names, fn in _EXTRA_DISPATCH:
        if name in names:
            out = fn(name, args)
            return await out if inspect.isawaitable(out) else out
    if name in ("air_quality", "elevation"):
        import worlddata_routes as W
        req = W.PointRequest(location=args.get("location"))
        return await (W.air_quality(req) if name == "air_quality" else W.elevation(req))
    if name == "geocode":
        import worlddata_routes as W
        return await W.geocode(W.GeocodeRequest(name=args.get("name"), count=args.get("count") or 5))
    if name == "earthquakes":
        import worlddata_routes as W
        return await W.earthquakes(W.QuakeRequest(
            min_magnitude=args.get("min_magnitude"), days=args.get("days"),
            limit=args.get("limit"), location=args.get("location"),
            radius_km=args.get("radius_km")))
    if name == "public_holidays":
        import worlddata_routes as W
        return await W.holidays(W.HolidayRequest(country=args.get("country"), year=args.get("year")))
    if name == "country_indicator":
        import worlddata_routes as W
        return await W.indicators(W.IndicatorRequest(
            country=args.get("country"), indicator=args.get("indicator") or "gdp",
            years=args.get("years") or 5))
    if name == "web_search":
        import webdata_routes as D
        return await D.web_search(D.SearchRequest(
            query=args.get("query"), max_results=args.get("max_results") or 10))
    if name == "read_url":
        import webdata_routes as D
        return await D.read_url(D.ReadRequest(url=args.get("url")))
    raise ValueError(f"unknown tool: {name}")


def _result(rid, payload):
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    """MCP Streamable HTTP endpoint (JSON-RPC 2.0). FREE — never behind the x402 paywall."""
    try:
        body = await request.json()
    except Exception:
        return Response(json.dumps(_error(None, -32700, "parse error")),
                        media_type="application/json", status_code=400)

    # Batches are legal JSON-RPC; handle them so a compliant client is not rejected.
    single = not isinstance(body, list)
    frames = [body] if single else body
    out = []
    for frame in frames:
        rid = frame.get("id") if isinstance(frame, dict) else None
        method = (frame or {}).get("method")
        params = (frame or {}).get("params") or {}

        if method == "initialize":
            out.append(_result(rid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Real-world reference data and web reading, free. Air quality, geocoding, "
                    "earthquakes, public holidays, World Bank indicators, elevation, web search "
                    "and URL-to-Markdown. Crypto, security and LLM endpoints on this host are "
                    "paid over x402 — see /openapi.json."),
            }))
        elif method in ("notifications/initialized", "notifications/cancelled"):
            continue  # notifications carry no id and MUST NOT get a response
        elif method == "ping":
            out.append(_result(rid, {}))
        elif method == "tools/list":
            out.append(_result(rid, {"tools": _all_tools()}))
        elif method == "tools/call":
            tname = params.get("name")
            targs = params.get("arguments") or {}
            try:
                data = await _dispatch(tname, targs)
                out.append(_result(rid, {
                    "content": [{"type": "text", "text": json.dumps(data, default=str)}],
                    "isError": False}))
            except Exception as e:
                # Tool failures are reported INSIDE the result, not as a JSON-RPC error —
                # a protocol-level error tells the client the server is broken, when in fact
                # one upstream refused one query and the model should see why and retry.
                out.append(_result(rid, {
                    "content": [{"type": "text",
                                 "text": f"{type(e).__name__}: {getattr(e, 'detail', e)}"}],
                    "isError": True}))
        else:
            out.append(_error(rid, -32601, f"method not found: {method}"))

    if not out:
        return Response(status_code=202)  # notification-only frame
    return Response(json.dumps(out[0] if single else out), media_type="application/json")


@router.get("/mcp")
async def mcp_info():
    """Human/browser-facing description. Clients POST here; GET just explains what this is."""
    return {"protocol": "mcp", "transport": "streamable-http",
            "protocolVersion": PROTOCOL_VERSION,
            "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "tools": [t["name"] for t in _all_tools()],
            "usage": {"method": "POST", "content_type": "application/json",
                      "example": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}},
            "cost": "free; the crypto/security/LLM routes on this host are x402-paid"}
