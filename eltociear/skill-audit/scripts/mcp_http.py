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
import os
from typing import Any

from fastapi import APIRouter, Request, Response

router = APIRouter()

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "tokenguard"
SERVER_VERSION = "1.2.0"

# Paths the x402 sweep must NOT paywall. Imported by main.py rather than duplicated there,
# so adding a route here cannot silently become a paid route over there.
#
# The discovery aliases below are here for the same reason MCP is: paywalling the CATALOGUE
# would be self-defeating. A crawler that must pay to learn our prices does not pay, it
# leaves. They need POST because that is the verb crawlers actually use — measured on
# contract-guard 2026-08-17, one access-log buffer carried 8,689 405s (more than its 7,657 402s) and
# every one was a discovery probe from a fleet of 262 distinct IPs POSTing to these exact
# paths. The routes already existed; they were registered GET-only, so FastAPI answered
# "405 Method Not Allowed" — a response that carries no price and no catalogue, which is the
# same failure as `x402-405-hides-the-paywall`, inverted. That fix taught "answer GET with
# the 402" and this is its mirror: answer POST with the catalogue.
# `/` and `/apis.json` are in here for the same measured reason as the x402 paths: that
# same buffer carried 924 `POST /` and 650 `HEAD /`, and `/apis.json` (the APIs.json discovery
# standard) has 128 lifetime `POST … 405` on contract-guard while its GET answers 200. Both
# only ever return a service descriptor, so answering them on every verb gives nothing away.
#
# The list below is the CLASS, not the instances that happened to be measured. Every entry
# is a descriptor endpoint: it takes no input, gives away no product, and exists to tell a
# machine what this service is and what it costs. There is no verb on which refusing one of
# them helps us, and `/pricing` or `/llms.txt` behind a paywall would be self-defeating in
# the same way a paywalled catalogue is.
_DISCOVERY_ALIASES = (
    "/", "/apis.json",
    # x402 catalogue, the paths the crawler fleet was measured POSTing to
    "/x402", "/x402-resources", "/discovery/resources", "/x402/discovery/resources",
    "/v1/x402/discovery/resources", "/v2/x402/discovery/resources",
    "/.well-known/x402", "/.well-known/x402.json", "/.well-known/x402-resources",
    "/.well-known/x402/discovery/resources",
    # generic API roots — also measured 405ing (POST /v1 x356, POST /api/v1 x355)
    "/api", "/api/v1", "/v1",
    # agent + LLM descriptors
    "/.well-known/agent.json", "/.well-known/agent-card.json", "/.well-known/agent-card",
    "/.well-known/api-catalog", "/.well-known/llms.txt",
    "/llms.txt", "/llms-full.txt", "/m2m-openapi.json",
    # commercial + operational descriptors
    "/pricing", "/terms", "/tos", "/privacy", "/health", "/selftest",
    "/robots.txt", "/sitemap.xml",
    # ⚠ Second pass, 2026-08-17. The first sweep covered the three main.py files and
    # missed the same class living in the mounted route MODULES. The prober fleet found
    # them immediately: over ~2.2h of log history, skill-audit still answered 17 405s and
    # tokenguard 29, every one of them a POST to a free diagnostic or descriptor below.
    # Fixing the class inside the files you happen to be reading is not fixing the class.
    "/world/selftest", "/llm/selftest", "/web/selftest", "/web/sitemap/selftest",
    "/sanctions/status", "/intel/x402/preview", "/upstreams", "/attestation/key",
    "/okx/status",
)
FREE_PATHS = ({"POST /mcp", "GET /mcp"}
              | {f"POST {p}" for p in _DISCOVERY_ALIASES}
              | {f"GET {p}" for p in _DISCOVERY_ALIASES})


def _tool(name, description, properties, required):
    # ⚠ Every tool description is text an agent reads while deciding what to call, on the one
    # channel we know is used: POST /mcp has carried 8,135 frames and a tool call is free.
    # `paid_catalogue` exists but an agent has to go looking for it; THESE are the tools that
    # actually get invoked. One sentence, on the tools that are already being used, is the
    # cheapest distribution we own — and unlike exposing paid routes as tools, it gives away
    # no product. Skipped on the catalogue tool itself, which already says all of this.
    if name != "paid_catalogue":
        description = (description.rstrip()
                       + " (Free. This server also sells a paid API — call `paid_catalogue`"
                         " for the routes and prices; x402 over USDC on Base, no signup.)")
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required}}


TOOLS = [
    _tool("paid_catalogue",
          "List the paid API routes this same server offers, with prices and which ones need "
          "no input. The MCP tools here are free and general-purpose; the paid routes are "
          "specialised (on-chain token safety, live DEX prices, wallet intel, supply-chain "
          "scans). Payment is x402 over USDC on Base — no account or API key. Takes no "
          "arguments.",
          {}, []),
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


_ROUTE_FACTS: dict = {}


def _find_required(node, _depth=0):
    """Recursively look for the input `required` list inside a bazaar discovery extension.

    Returns (found, list). **The two halves matter separately**: a route that declares
    `required: []` is genuinely callable blind, while a route we simply could not read is not
    an answer at all. Collapsing those two into one empty list is what made the first version
    of the catalogue tell buyers all 131 routes needed no input.
    """
    if _depth > 8 or not isinstance(node, (dict, list)):
        return False, []
    if isinstance(node, dict):
        # ⚠ Must be the `required` belonging to the INPUT, not the first one anywhere in the
        # tree. The first version took whichever it met first — an outer schema's own
        # `required` — and reported 0 zero-input routes out of 131 when twelve of them take
        # nothing. Anchor on the "input" key instead of trusting depth-first order.
        # Dumped `declare_discovery_extension` rather than guessing a third time. The caller's
        # own fields live at bazaar.schema.properties.input.properties.BODY.required. The two
        # earlier attempts anchored one level too high, on the input ENVELOPE, whose required
        # list is ["type","bodyType","body"] — never empty, which is precisely why every route
        # came back "requires input". Anchor on `body`.
        body = (node.get("properties") or {}).get("body")
        # ⚠ Do NOT gate on body.get("type") == "object" — the SDK does not emit a `type` here.
        # That guess cost two live deploys. It was settled in one call by unit-testing the
        # extractor offline against a built extension, which is what should have happened
        # first: iterating on a live buyer-facing service is slow, and every cycle risks
        # shipping a confident wrong answer.
        if isinstance(body, dict) and ("properties" in body or "required" in body):
            r = body.get("required")
            # No `required` key on the body means no required fields — an ANSWER, not a miss.
            return True, [x for x in (r or []) if isinstance(x, str)]
        for v in node.values():
            found, out = _find_required(v, _depth + 1)
            if found:
                return True, out
    else:
        for v in node:
            found, out = _find_required(v, _depth + 1)
            if found:
                return True, out
    return False, []


def set_routes(routes: dict) -> None:
    """Let the app hand us its own x402 routes dict at startup.

    `/.well-known/x402` lists **bare URL strings** — no schema, no extensions — so the
    catalogue tool could never say which routes are callable with no input, which is exactly
    the fact that predicts conversion (25x, measured). The app already holds the real
    structure; this is the only place it can come from without probing 131 challenges inside
    a single tool call.
    """
    facts = {}
    for key, cfg in (routes or {}).items():
        path = key.split(" ", 1)[-1] if " " in key else key
        found, req = _find_required(getattr(cfg, "extensions", None))
        facts[path] = {"known": found, "required": req,
                       "description": getattr(cfg, "description", None)}
    _ROUTE_FACTS.clear()
    _ROUTE_FACTS.update(facts)


def _all_tools():
    return TOOLS + _EXTRA_TOOLS


async def _paid_catalogue() -> dict:
    """What this server also sells, read from its own live x402 manifest.

    Measured 2026-08-10: `POST /mcp` has carried **8,135 frames** — by far the largest
    engagement this operation has anywhere — and a tool call is FREE (verified: tools/call →
    geocode → HTTP 200, real data, no payment challenge). It converts nothing, because nothing
    an agent can see here mentions that a paid, differentiated API exists on the same host.

    The instinct was to expose the paid routes AS tools. That is backwards: it would hand over
    the priced product for free. This does the opposite — it hands over the *catalogue*, which
    is the one thing an agent needs in order to become a buyer and the one thing that costs us
    nothing. Same lesson as spending the 402 body: the text is the channel, not the payload.

    Read from `/.well-known/x402` at call time rather than hardcoded, so a route added over
    there cannot silently go unadvertised here.
    """
    # ⚠ MUST be async, and this is not a style point. The first version used a synchronous
    # urllib call, which blocks the event loop — so the server was waiting on a request only
    # it could serve, and deadlocked itself until the timeout. It shipped and every call came
    # back "could not read … TimeoutError". A server fetching itself has to yield the loop.
    import httpx
    base = os.environ.get("PUBLIC_BASE_URL") or f"https://eltociear-{SERVER_NAME}.hf.space"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            res = (await c.get(base + "/.well-known/x402")).json().get("resources") or []
    except Exception as e:                                             # noqa: BLE001
        # Never fake a catalogue. An empty list would read as "nothing for sale".
        return {"error": f"could not read {base}/.well-known/x402: {type(e).__name__}",
                "hint": "fetch it directly; this tool only mirrors it"}
    rows = []
    for r_ in res:
        u = r_.get("resource") or r_.get("url") if isinstance(r_, dict) else r_
        if not isinstance(u, str):
            continue
        path = "/" + u.split("/", 3)[-1] if "//" in u else u
        f = _ROUTE_FACTS.get(path) or {}
        row = {"route": path, "url": u,
               "description": f.get("description")
               or (r_.get("description") if isinstance(r_, dict) else None)}
        if f.get("known"):
            row["requires_input"] = bool(f["required"])
            if f["required"]:
                row["required_fields"] = f["required"]
        else:
            row["requires_input"] = "unknown"
        rows.append(row)
    # ⚠ The first live run claimed `callable_with_no_input: 131 of 131`. It is not — nine of
    # them demand an argument. The nested path this reads is wrong for this manifest shape, so
    # every route came back with no required fields and that read as a definite "needs
    # nothing". Telling a buyer they can call /scan blind is worse than telling them nothing:
    # they try, they fail, they leave. If NOTHING resolves, we could not read it — say so.
    # ⚠ And it is NOT a parse bug to be fixed later: `resources` in this manifest is a list of
    # bare URL STRINGS — 131 of them, no description, no schema, no extensions. The richer
    # shape (bazaar info/schema) exists only in the 402 challenge itself, one route at a time.
    # So the requirement genuinely cannot be derived here, and the branch below is the correct
    # permanent answer rather than a stopgap. To do better, main.py has to hand its routes dict
    # to this module at startup; probing 131 challenges inside a tool call is not an option.
    # ⚠ Sanity-check the EXTRACTOR, not just the data. We know from measurement that both
    # kinds of route exist here — twelve take no input at all. So if every route it resolved
    # landed on the same side, the extractor is not discriminating; it is pattern-matching
    # something else and its confident answers are worthless. Two live deploys reported
    # "0 callable with no input" out of 86 resolved, which is how this was caught.
    #
    # Falling back to "unknown" loses a feature. Publishing "requires input" for a route that
    # takes none loses a buyer, who tries, fails and never returns. Fail to the honest side.
    resolved = [r_["requires_input"] for r_ in rows if r_["requires_input"] != "unknown"]
    readable = bool(resolved) and (True in resolved) and (False in resolved)
    if not readable:
        for r_ in rows:
            r_["requires_input"] = "unknown"
            r_.pop("required_fields", None)
    if not readable:
        return {
            "server": SERVER_NAME,
            "payment": "x402 v2, USDC on Base (eip155:8453). Send the payment header the 402 "
                       "challenge asks for; no account, no signup, no API key.",
            "note": "MCP tools on this server are free. The routes below are paid and are a "
                    "different, more specialised product.",
            "input_requirements": "could not be read from this manifest — GET any route's 402 "
                                  "challenge for its exact input schema before calling",
            "total": len(rows),
            "routes": rows,
        }
    blind = [r_ for r_ in rows if r_["requires_input"] is False]
    unknown = [r_ for r_ in rows if r_["requires_input"] == "unknown"]
    return {
        "server": SERVER_NAME,
        "payment": "x402 v2, USDC on Base (eip155:8453). Send the payment header the 402 "
                   "challenge asks for; no account, no signup, no API key.",
        "note": "MCP tools on this server are free. The routes below are paid and are a "
                "different, more specialised product.",
        "callable_with_no_input": len(blind),
        "requirements_unreadable": len(unknown),
        "total": len(rows),
        "start_here": [r_["url"] for r_ in blind[:8]],
        "routes": rows,
    }


async def _dispatch(name: str, args: dict) -> Any:
    """Run a tool by reusing the route handlers in-process — no HTTP round trip to ourselves."""
    import inspect
    # ⚠ Every MCP call is `POST /mcp 200` in the access log, so 8,135 frames of our largest
    # engagement are indistinguishable from each other. The question that matters — is the
    # FREE `audit_skill_text` cannibalising the PAID `/audit`, which has 2,709 challenges and
    # zero conversions? — cannot be answered from a log where both look the same.
    #
    # Name only. Never the arguments: they carry caller content, and a demand meter is not a
    # reason to start recording what people send us. The Space log stream is already read as
    # a demand oracle, so one line per call makes this channel measurable with no new tooling.
    print(f"MCPTOOL {name}", flush=True)
    if name == "paid_catalogue":
        return await _paid_catalogue()
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
