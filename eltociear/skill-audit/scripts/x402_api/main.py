#!/usr/bin/env python3
"""skill-audit x402 API — Security audit as a paid service (x402 protocol v2).

Deploy: uvicorn scripts.x402_api.main:app --host 0.0.0.0 --port $PORT
Local:  uvicorn scripts.x402_api.main:app --port 8402

Endpoints:
  GET  /          — Service info (free)
  GET  /health    — Health check (free)
  POST /audit     — Text audit $0.005/call (x402)
  POST /audit/url — URL fetch + audit $0.005/call (x402)
  POST /read      — URL → clean Markdown $0.005/call (x402)

Payment: USDC on Base mainnet (eip155:8453) via the official x402 v2 SDK.
Facilitator default = Dexter (https://x402.dexter.cash): zero-gate, 0% seller fee,
gas-sponsored for buyers, v2-native, and auto-lists this endpoint on the discovery
layer (Bazaar) once the first payment settles.

v2 migration note: the legacy fastapi-x402 (v0.1.x) only spoke x402 v1, which the new
discovery ecosystem (x402scan / CDP Bazaar v2) rejects ("migrate to v2 spec"). This
file uses the official `x402` SDK so the 402 challenge is valid v2 and discoverable.
The old USDC-name hack is gone: the SDK uses the correct on-chain EIP-712 domain.
"""
import os
import sys
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# -- the 402 body is a distribution channel ---------------------------------------------
# Every 402 we return is delivered to someone who just tried to call a paid route: the most
# qualified audience this operation has, arriving free, and in volume: one pre-fix log buffer alone held 7,657 of them.
# Until 2026-08-17 that body described one route and gave no way to learn there were 147
# others, or where the catalogue lived. `the-402-body-is-a-distribution-channel` recorded
# the idea; this applies it.
#
# contract-guard is the sharpest case: the most trafficked thing we own by a wide
# margin -- 7,657 of the 37,501 lines in one pre-fix buffer were its 402s -- and it
# sells a SINGLE route, while tokenguard holds the shelf and sees far less traffic.
# (No per-minute figure: /logs/run replays a history buffer, so dividing it by the
# listen window inflates the rate ~160x. See top_caller_profile.py's docstring.)
#
# WARNING: self-contained ON PURPOSE. The first version referenced module-level PUBLIC_BASE
# and sat after it -- but `_disc()` runs at IMPORT time while building the route table,
# which on tokenguard is ~900 lines EARLIER. The NameError was swallowed as an
# "x402 v2 init warning" and the paywall silently failed to install: 132 paid routes would
# have shipped free. Nothing here may depend on definition order.
#
# Carries NO route counts. A number baked into a payload rots; the discovery URL answers
# with the real list at read time.
_SERVICE_NAME = "skill-audit"
_CATALOGUE_BASE = "https://eltociear-skill-audit.hf.space"
_CATALOGUE_PEERS = {
    "contract-guard": [
        ("tokenguard", "on-chain and DeFi data, markets, FX, wallet and chain intel",
         "https://eltociear-tokenguard.hf.space/.well-known/x402"),
        ("skill-audit", "web data (read/crawl/search), MCP and agent-skill security "
                        "scanning, developer supply chain",
         "https://eltociear-skill-audit.hf.space/.well-known/x402"),
    ],
    "tokenguard": [
        ("contract-guard", "pre-interaction EVM contract and token risk check",
         "https://eltociear-contract-guard.hf.space/.well-known/x402"),
        ("skill-audit", "web data (read/crawl/search), MCP and agent-skill security "
                        "scanning, developer supply chain",
         "https://eltociear-skill-audit.hf.space/.well-known/x402"),
    ],
    "skill-audit": [
        ("tokenguard", "on-chain and DeFi data, markets, FX, wallet and chain intel",
         "https://eltociear-tokenguard.hf.space/.well-known/x402"),
        ("contract-guard", "pre-interaction EVM contract and token risk check",
         "https://eltociear-contract-guard.hf.space/.well-known/x402"),
    ],
}


def _catalogue():
    """Where the rest of the shelf is. Same rail, same wallet, no signup."""
    import os as _os
    base = _os.environ.get("PUBLIC_BASE_URL", _CATALOGUE_BASE).rstrip("/")
    return {
        "discovery": base + "/.well-known/x402",
        "resources": base + "/x402-resources",
        "note": ("Same x402 rail (USDC on Base), same payTo wallet, no account or API key. "
                 "GET the discovery URL for the full route list and prices."),
        "related": [{"service": s, "covers": c, "discovery": u}
                    for s, c, u in _CATALOGUE_PEERS[_SERVICE_NAME]],
    }





# Import scan engine from skill-audit MCP server
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mcp_servers", "skill-audit"))
from server import scan, PATTERNS  # noqa: E402

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Config
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WALLET = os.environ.get("BASE_WALLET_ADDRESS", "0x5bCDA55247B238a573A968B234F788a2D35664Dd")
BASE_MAINNET = "eip155:8453"  # CAIP-2 network id for Base mainnet
# Facilitator selection mirrors tokenguard: with CDP API keys present, settle through
# Coinbase's CDP facilitator so payments auto-list this Space on the buyer-facing CDP
# Bazaar (the discovery layer with the real demand; sibling tokenguard proved it). Without
# keys, fall back to Dexter — zero-gate but a separate, low-traffic bazaar.
CDP_KEY_ID = os.environ.get("CDP_API_KEY_ID", "")
CDP_KEY_SECRET = os.environ.get("CDP_API_KEY_SECRET", "")
CDP_FACILITATOR = "https://api.cdp.coinbase.com/platform/v2/x402"
USE_CDP = bool(CDP_KEY_ID and CDP_KEY_SECRET)
FACILITATOR_URL = os.environ.get("FACILITATOR_URL", CDP_FACILITATOR if USE_CDP else "https://x402.dexter.cash")


def _cdp_auth_headers():
    """Ed25519 JWT per CDP facilitator operation. The x402 SDK's CreateHeadersAuthProvider
    calls this and attaches the right header per verify/settle/supported/bazaar call.
    Verified working 2026-07-22: /supported returns 200 with these headers."""
    import base64, json as _json, secrets, time
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    seed = base64.b64decode(CDP_KEY_SECRET)[:32]
    pk = Ed25519PrivateKey.from_private_bytes(seed)
    b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    host = "api.cdp.coinbase.com"
    base = "/platform/v2/x402"

    def jwt(method, path):
        now = int(time.time())
        h = {"alg": "EdDSA", "kid": CDP_KEY_ID, "typ": "JWT", "nonce": secrets.token_hex(16)}
        p = {"sub": CDP_KEY_ID, "iss": "cdp", "aud": ["cdp_service"], "nbf": now, "exp": now + 120,
             "uris": [f"{method} {host}{path}"]}
        s = f"{b64u(_json.dumps(h, separators=(',', ':')).encode())}.{b64u(_json.dumps(p, separators=(',', ':')).encode())}"
        return f"{s}.{b64u(pk.sign(s.encode()))}"

    def hdr(method, path):
        return {"Authorization": f"Bearer {jwt(method, path)}"}
    return {
        "verify": hdr("POST", f"{base}/verify"),
        "settle": hdr("POST", f"{base}/settle"),
        "supported": hdr("GET", f"{base}/supported"),
        "bazaar": hdr("GET", f"{base}/discovery/resources"),
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# App
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Discovery and service-descriptor endpoints answer EVERY verb a crawler might use, not
# just GET. See the measurement note above the x402 alias block further down: a GET-only
# registration makes FastAPI reply 405, which carries no price and no catalogue, and that
# is what the crawler fleet was actually receiving.
_DISCOVERY_VERBS = _DISCOVERY_VERBS_ROOT = ["GET", "POST", "HEAD"]


app = FastAPI(
    title="skill-audit API",
    description="Detect malicious patterns in AI agent skills/plugins. x402 v2 micropayments on Base.",
    version="2.0.0",
    contact={
        "name": "eltociear",
        "url": "https://github.com/eltociear",
        "email": "ashimine_ikko_bp@netprice.com",
    },
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sellable inventory on an already heavily-indexed surface
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# This Space is crawled HARDER than tokenguard — one 60s sample held 1,331
# GET /openapi.json and 1,163 GET /.well-known/x402 — and has still never earned a cent:
# its 14 audit/web routes drew 3,714 challenges and converted zero. So the problem here was
# never discovery, it is that nothing on offer is what buyers pay for. Per-route revenue on
# tokenguard says that is general-purpose real-world data (/weather and /stocks are the two
# best sellers there). Mount those families here too — same free upstreams, no new
# credentials, no marginal cost.
#
# Prices are deliberately NOT copied from tokenguard. There, /llm/answer went out at $0.02
# and /llm/chat at $0.05, which is backwards — answer runs a search, reads pages AND infers.
# Those are already settled, and Bazaar metadata freezes at first settlement, so correcting
# them there would leave the catalog advertising $0.02 while the live route demanded $0.05 —
# the direction that makes a buyer under-sign and get rejected. These paths are new and have
# never settled, so they get the coherent pricing from the start.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# MCP over Streamable HTTP, FREE. See mcp_http.py for why this channel rather than more
# x402 routes. This host registers the malicious-pattern scanner on top of the shared data
# tools — serving the same eight tools as tokenguard would just be two URLs for one product,
# and the scanner is the tool a human has an actual reason to install: it answers "is this
# MCP server / agent skill safe to load?" before they load it.
try:
    from mcp_http import (router as _mcp_router, register_extra as _mcp_register_extra,
                          set_identity as _mcp_set_identity)
    from server import scan as _sa_scan, PATTERNS as _SA_PATTERNS

    def _sa_tools():
        groups = sum(len(v) for v in _SA_PATTERNS.values())
        sigs = sum(len(pg["regexes"]) for v in _SA_PATTERNS.values() for pg in v)
        # Counted from PATTERNS, never written as prose: the hardcoded copies of this number
        # were wrong in 18 files while the live API computed it correctly.
        blurb = (f"{groups} attack patterns / {sigs} regex signatures across 4 severity "
                 f"levels — credential exfiltration, download-and-execute, prompt injection, "
                 f"command execution, seed-phrase harvesting and more.")
        return [
            {"name": "audit_skill_text",
             "description": f"Scan text — an agent skill, MCP server source, or plugin — for "
                            f"malicious behaviour before loading it. {blurb}",
             "inputSchema": {"type": "object", "properties": {
                 "content": {"type": "string", "description": "File or snippet to scan"}},
                 "required": ["content"]}},
            {"name": "audit_skill_url",
             "description": f"Fetch a URL and scan what it serves for malicious behaviour. "
                            f"{blurb}",
             "inputSchema": {"type": "object", "properties": {
                 "url": {"type": "string", "description": "Raw file URL to fetch and scan"}},
                 "required": ["url"]}},
        ]

    async def _sa_dispatch(name, args):
        # A missing or empty argument used to fall through to `or ""`, so the scanner scanned
        # nothing and answered "SAFE, no issues found". A caller that mistypes the parameter name
        # -- `text` instead of `content`, which is exactly what happened while probing this
        # endpoint -- got a clean bill of health for a file it never sent. A verdict over zero
        # bytes is a failed call, not a result.
        if name == "audit_skill_text":
            content = args.get("content") or ""
            if not content.strip():
                return {"error": "content is required and must be non-empty",
                        "hint": "pass {\"content\": \"<file or snippet>\"}; this is NOT a SAFE verdict",
                        "scanned_bytes": 0}
            return _sa_scan(content[:1_000_000])
        url = args.get("url") or ""
        if not url.strip():
            return {"error": "url is required and must be non-empty",
                    "hint": "pass {\"url\": \"https://...\"}; this is NOT a SAFE verdict",
                    "scanned_bytes": 0}
        import webdata_routes as _D
        text, final = await _D._fetch_text(url, 1_000_000, timeout=20.0)
        if not (text or "").strip():
            return {"url": final, "error": "the URL returned no readable text",
                    "hint": "this is NOT a SAFE verdict", "scanned_bytes": 0}
        return {"url": final, **_sa_scan(text[:1_000_000])}

    # Must match the name this URL is published under in the MCP registry
    # (io.github.eltociear/skill-audit-mcp), not the shared router's default.
    _mcp_set_identity("skill-audit", "1.1.0")
    _mcp_register_extra(_sa_tools(), _sa_dispatch)
    app.include_router(_mcp_router)
except Exception as _e:  # pragma: no cover
    print(f"  mcp http unavailable: {type(_e).__name__}: {_e}")

_extra_specs = []
try:
    from worlddata_routes import router as _world_router, route_specs as _world_route_specs
    app.include_router(_world_router, prefix="/world")
    # $0.01, deliberately half of tokenguard's $0.02 for the SAME routes. The Bazaar's
    # per-resource median price is $0.02, but weighting by calls — i.e. asking where money
    # actually moves rather than what people list at — the median is $0.01 and p25 is
    # $0.004. We sit at the top of the paying range for commodity data. Identical product
    # on two hosts at two prices is the cheapest way to find out whether that matters.
    # Safe against stale Bazaar metadata: those entries froze at $0.02, and advertising
    # ABOVE the live price only makes a buyer over-budget, never under-sign.
    _extra_specs += _world_route_specs(prefix="/world", price="$0.01")
except Exception as _e:  # pragma: no cover
    print(f"  world-data routes unavailable: {type(_e).__name__}: {_e}")
try:
    from llm_routes import router as _llm_router, route_specs as _llm_route_specs
    app.include_router(_llm_router, prefix="/llm")
    _extra_specs += _llm_route_specs(prefix="/llm", cheap="$0.02", answer="$0.05")
except Exception as _e:  # pragma: no cover
    print(f"  llm routes unavailable: {type(_e).__name__}: {_e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# x402 v2 payment middleware (official SDK)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_x402_available = False
try:
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption, CreateHeadersAuthProvider
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer
    from x402.extensions.bazaar import declare_discovery_extension, OutputConfig

    if USE_CDP:
        _fac_cfg = FacilitatorConfig(url=FACILITATOR_URL, auth_provider=CreateHeadersAuthProvider(_cdp_auth_headers))
    else:
        _fac_cfg = FacilitatorConfig(url=FACILITATOR_URL)
    facilitator = HTTPFacilitatorClient(_fac_cfg)
    server = x402ResourceServer(facilitator)
    server.register(BASE_MAINNET, ExactEvmServerScheme())

    def _disc(input_example, input_schema, output_example):
        # Bazaar discovery extension for a POST/JSON endpoint. declare_discovery_extension
        # leaves info.input.method for runtime enrichment, but the schema marks it required;
        # inject "POST" so the extension validates at registration and CDP Bazaar can catalog it.
        ext = declare_discovery_extension(
            input=input_example, input_schema=input_schema,
            body_type="json", output=OutputConfig(example=output_example),
        )
        ext["bazaar"]["info"]["input"]["method"] = "POST"
        ext["catalogue"] = _catalogue()
        return ext

    # ━━━ PRICE EXPERIMENT, 2026-08-10: every audit route down to $0.005 ━━━━━━━━━━━━━━━━━━
    # Measured from the Space access logs, with `POST /mcp 200` excluded (it is transport, not
    # revenue — counting it had this operation's revenue report 20x too high):
    #
    #     price      route                       challenges -> paid
    #     $0.005     /stocks /lido /weather …          many -> 57-68 each
    #     $0.005     /check                           5,608 -> 1
    #     $0.010     /audit                          ~2,700 -> 0
    #     $0.020     /btc_rates                       4,364 -> 5
    #     $0.050     /audit/repo                     ~2,700 -> 0
    #
    # Two lines fall out. Nothing above $0.005 converts at any meaningful rate, and even at
    # $0.005 the security/verification category barely converts while market and chain data
    # does. Those are different explanations and the data cannot separate them, because the
    # audit routes have only ever been offered at a price no one pays.
    #
    # So: hold the category, change the price. All three audit routes go to $0.005. The
    # downside is bounded at zero — they earn nothing today — and the upside is a definitive
    # answer. If they still convert 0 after a few thousand challenges at the one price that
    # demonstrably works, the constraint is the CATEGORY, and no pricing will fix it.
    # Read the result with `python scripts/x402_route_stats.py --report`.
    #
    # Safe against frozen Bazaar metadata: a catalog advertising ABOVE the live price makes a
    # buyer over-budget, never under-sign. Lowering is always the safe direction.
    routes = {
        "POST /audit": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            # ⚠ The 402 body carries `resource.description` verbatim — verified live. These three
            # routes have served ~8,100 challenges and converted zero, because the caller is a
            # crawler with no content, URL or repo of ours to send. The refusal is the one moment
            # we know the buyer is reading, so it now names the way through instead of just a
            # price for something they cannot invoke. tokenguard runs the controlled version of
            # this (two routes treated, two left alone); here it is simply applied.
            description="Audit text for malicious AI-skill patterns. Requires `content`. "
                        "Nothing to audit — crawling, or discovering this endpoint cold? "
                        "POST /audit/registry runs the same scanner over the newest servers "
                        "in the official MCP registry: no input required, $0.005.",
            extensions=_disc(
                {"content": "skill or plugin text to scan"},
                {"properties": {"content": {"type": "string", "description": "Text to audit"}}, "required": ["content"]},
                {"risk_score": 0, "risk_level": "clean", "total_findings": 0, "findings": []},
            ),
        ),
        "POST /audit/url": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Fetch a URL and audit its content. Requires `url`. No URL to hand? "
                        "POST /audit/registry runs the same scanner over the newest servers "
                        "in the official MCP registry: no input required, $0.005.",
            extensions=_disc(
                {"url": "https://example.com/skill.md"},
                {"properties": {"url": {"type": "string", "format": "uri", "description": "URL to fetch + audit"}}, "required": ["url"]},
                {"url": "https://example.com/skill.md", "risk_score": 0, "risk_level": "clean", "total_findings": 0, "findings": []},
            ),
        ),
        "POST /read": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Fetch a URL and return its main content as clean Markdown (boilerplate stripped)",
            extensions=_disc(
                {"url": "https://example.com/article"},
                {"properties": {
                    "url": {"type": "string", "format": "uri", "description": "Page to fetch and clean"},
                    "include_links": {"type": "boolean", "description": "Keep hyperlinks in the Markdown (default true)"},
                 }, "required": ["url"]},
                {"url": "https://example.com/article", "title": "Article title",
                 "markdown": "# Article title\n\nMain content…", "word_count": 1234},
            ),
        ),
        "POST /read/batch": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.02", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Fetch up to 10 URLs concurrently and return each as clean Markdown (bulk rate)",
            extensions=_disc(
                {"urls": ["https://example.com/a", "https://example.com/b"]},
                {"properties": {
                    "urls": {"type": "array", "items": {"type": "string", "format": "uri"},
                             "description": "1-10 pages to fetch and clean"},
                    "include_links": {"type": "boolean", "description": "Keep hyperlinks (default true)"},
                 }, "required": ["urls"]},
                {"count": 2, "ok": 2, "results": [
                    {"url": "https://example.com/a", "title": "A", "markdown": "# A…", "word_count": 120},
                ]},
            ),
        ),
        "POST /extract": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.008", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Extract structured metadata from a page: title, description, OpenGraph, JSON-LD, headings, links",
            extensions=_disc(
                {"url": "https://example.com/product"},
                {"properties": {"url": {"type": "string", "format": "uri", "description": "Page to extract structured data from"}},
                 "required": ["url"]},
                {"url": "https://example.com/product", "title": "Product", "description": "…",
                 "opengraph": {"og:title": "Product"}, "jsonld": [{"@type": "Product"}],
                 "headings": [{"level": 1, "text": "Product"}], "links": ["https://example.com/buy"]},
            ),
        ),
        "POST /pdf": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.01", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Fetch a PDF by URL and return its text as Markdown-ish plain text, page by page",
            extensions=_disc(
                {"url": "https://example.com/paper.pdf"},
                {"properties": {
                    "url": {"type": "string", "format": "uri", "description": "PDF to fetch and extract"},
                    "max_pages": {"type": "integer", "description": "Page cap (default 50)"},
                 }, "required": ["url"]},
                {"url": "https://example.com/paper.pdf", "pages": 12, "extracted_pages": 12,
                 "text": "# Page 1\n\n…", "word_count": 4200},
            ),
        ),
        "POST /trust": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.02", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Vet an x402 server or any URL for scam/phishing/trust in ONE call: transport, content-safety, domain, metadata + x402-compliance sub-scores, each with transparent evidence",
            extensions=_disc(
                {"url": "https://some-x402-api.example.com"},
                {"properties": {
                    "url": {"type": "string", "format": "uri", "description": "x402 server or URL to vet before trusting/paying it"},
                    "check_x402": {"type": "boolean", "description": "Probe for a valid x402 402 challenge (default true)"},
                 }, "required": ["url"]},
                {"url": "https://some-x402-api.example.com", "trust_score": 82, "risk_level": "low",
                 "is_scam": False, "verdict": "Reachable HTTPS endpoint with strong headers, valid x402 challenge, no malicious patterns.",
                 "sub_scores": {"transport": 90, "content_safety": 100, "domain": 70, "metadata": 80, "x402": 100},
                 "x402": {"is_x402": True, "valid_challenge": True, "pay_to": "0x…", "network": "eip155:8453", "asset": "USDC"},
                 "evidence": {"missing_headers": ["content-security-policy"], "malicious_findings": 0,
                              "spf": True, "dmarc": True, "latency_ms": 210}},
            ),
        ),
        "POST /headers": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Fetch a URL and grade its HTTP security headers (HSTS, CSP, X-Frame-Options, etc.)",
            extensions=_disc(
                {"url": "https://example.com"},
                {"properties": {"url": {"type": "string", "format": "uri", "description": "URL to inspect"}},
                 "required": ["url"]},
                {"url": "https://example.com", "status": 200, "grade": "B", "score": 70,
                 "headers": {"strict-transport-security": "max-age=63072000"},
                 "present": ["strict-transport-security"], "missing": ["content-security-policy"]},
            ),
        ),
        "POST /dns": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.006", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Resolve a domain's DNS records (A/AAAA/MX/NS/TXT/CNAME) and flag basic email/security posture",
            extensions=_disc(
                {"domain": "example.com"},
                {"properties": {"domain": {"type": "string", "description": "Domain to resolve (or a full URL)"}},
                 "required": ["domain"]},
                {"domain": "example.com", "records": {"A": ["93.184.216.34"], "MX": [], "TXT": []},
                 "flags": {"has_spf": False, "has_dmarc": False, "has_mx": False}},
            ),
        ),
        "POST /search": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.01", network=BASE_MAINNET)],
            mime_type="application/json",
            description="What does the open web say about this query? Ranked title/url/snippet results for agents, served through an automatic multi-engine failover chain so a single call still answers when any one backend is blocked, rate-limited or timing out from a datacenter IP.",
            extensions=_disc(
                {"query": "x402 protocol spec"},
                {"properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "1-25 results (default 10)"},
                 }, "required": ["query"]},
                {"query": "x402 protocol spec", "engine": "duckduckgo", "count": 10,
                 "results": [{"rank": 1, "title": "x402 spec", "url": "https://example.com/spec",
                              "snippet": "The x402 protocol defines…"}]},
            ),
        ),
        "POST /crawl": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.02", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Crawl a site from a start URL (same-domain, breadth-first) and return each page as clean Markdown",
            extensions=_disc(
                {"url": "https://example.com/docs", "max_pages": 5},
                {"properties": {
                    "url": {"type": "string", "format": "uri", "description": "Start URL"},
                    "max_pages": {"type": "integer", "description": "1-10 pages to fetch (default 5)"},
                    "include_links": {"type": "boolean", "description": "Keep hyperlinks (default true)"},
                 }, "required": ["url"]},
                {"start_url": "https://example.com/docs", "pages_fetched": 5, "ok": 5,
                 "pages": [{"url": "https://example.com/docs", "title": "Docs",
                            "markdown": "# Docs…", "word_count": 800, "depth": 0}]},
            ),
        ),
        "POST /sitemap": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Enumerate a site's URLs from robots.txt + sitemap.xml (sitemap-index aware) — map a domain before crawling it",
            extensions=_disc(
                {"url": "https://example.com"},
                {"properties": {
                    "url": {"type": "string", "description": "Site URL or bare domain"},
                    "max_urls": {"type": "integer", "description": "Cap on returned URLs (default 500, max 2000)"},
                 }, "required": ["url"]},
                {"site": "https://example.com", "sitemaps": ["https://example.com/sitemap.xml"],
                 "count": 120, "urls": [{"loc": "https://example.com/a", "lastmod": "2026-07-01"}]},
            ),
        ),
        "POST /rss": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Parse an RSS/Atom feed into structured items (title, link, published, summary) — or auto-discover the feed from a site URL",
            extensions=_disc(
                {"url": "https://example.com/feed.xml"},
                {"properties": {
                    "url": {"type": "string", "description": "Feed URL, or a site URL to auto-discover its feed"},
                    "max_items": {"type": "integer", "description": "Cap on items (default 50)"},
                 }, "required": ["url"]},
                {"feed_url": "https://example.com/feed.xml", "title": "Example Blog", "format": "rss",
                 "count": 2, "items": [{"title": "Post", "link": "https://example.com/post",
                                        "published": "2026-07-20T10:00:00Z", "summary": "…"}]},
            ),
        ),
        "POST /audit/repo": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Scan an entire public GitHub repo for malicious AI-skill/supply-chain "
                        "patterns. Requires `repo`. No repo in mind? POST /audit/registry runs "
                        "this same scanner over the newest servers in the official MCP "
                        "registry: no input required, $0.005.",
            extensions=_disc(
                {"repo": "owner/name"},
                {"properties": {
                    "repo": {"type": "string", "description": "GitHub repo as 'owner/name' or full URL"},
                    "ref": {"type": "string", "description": "Branch/tag/sha (default: HEAD)"},
                 }, "required": ["repo"]},
                {"repo": "owner/name", "files_scanned": 84, "risk_score": 0, "risk_level": "clean",
                 "total_findings": 0, "flagged_files": []},
            ),
        ),
        # The zero-input security route. `required` is deliberately EMPTY — a crawler that
        # calls this with `{}` still gets a real answer, which the measurements say is the
        # difference between converting and not. See RegistryAuditRequest.
        "POST /audit/registry": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price="$0.005", network=BASE_MAINNET)],
            mime_type="application/json",
            description="Scan the newest servers in the official MCP registry for "
                        "supply-chain risk — no input required",
            extensions=_disc(
                {},
                {"properties": {
                    "limit": {"type": "integer", "description":
                              "How many of the newest registry servers to scan (1-15, default 5)"},
                 }, "required": []},
                {"source": "registry.modelcontextprotocol.io/v0/servers", "scanned": 5,
                 "flagged": 1, "unreadable": 2,
                 "results": [{"server": "io.github.owner/name", "repo": "owner/name",
                              "risk_level": "HIGH", "risk_score": 30, "finding_count": 1,
                              "files_scanned": ["package.json"], "top_finding": {}}]},
            ),
        ),
    }

    # Merge the mounted families in. Same RouteConfig shape as the literal above; the
    # per-route price comes from each module's spec rather than being fixed here.
    routes.update({f"POST {path}": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=WALLET, price=price, network=BASE_MAINNET)],
        mime_type="application/json",
        description=desc,
        extensions=_disc(in_ex, in_schema, out_ex),
    ) for path, price, desc, in_ex, in_schema, out_ex in _extra_specs})

    # Bazaar discovery metadata — see the same block in tokenguard_api/main.py. A
    # 14,271-resource scan on 2026-07-27 showed all of our listings with
    # serviceName=None and tags=[], i.e. absent from every tag-filtered buyer query.
    # Caps: service_name <= 32 chars, <= 5 tags of <= 32 chars each.
    _TAGS = (
        ("/read",   ["web", "scraping", "content", "data", "ai-agents"]),
        ("/search", ["search", "web", "data", "ai-agents", "tools"]),
        ("/crawl",  ["web", "scraping", "search", "data", "ai-agents"]),
        ("/sitemap", ["web", "scraping", "search", "data", "ai-agents"]),
        ("/rss",    ["web", "feeds", "content", "data", "ai-agents"]),
        ("/extract", ["web", "scraping", "content", "data", "ai-agents"]),
        ("/pdf",    ["web", "documents", "content", "data", "ai-agents"]),
        ("/dns",    ["web", "infrastructure", "data", "ai-agents", "tools"]),
        ("/headers", ["web", "infrastructure", "data", "ai-agents", "tools"]),
        ("/trust",  ["verification", "security", "web", "data", "ai-agents"]),
        ("/audit",  ["verification", "security", "developer", "data", "ai-agents"]),
    )
    for _key, _cfg in routes.items():
        _path = _key.split(" ", 1)[-1]
        if not getattr(_cfg, "tags", None):
            for _prefix, _tags in _TAGS:
                if _path.startswith(_prefix):
                    _cfg.tags = _tags
                    break
            else:
                _cfg.tags = ["web", "data", "ai-agents", "tools", "api"]
        if not getattr(_cfg, "service_name", None):
            _cfg.service_name = "skill-audit"

    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    # `/.well-known/x402` publishes bare URL strings, so the free `paid_catalogue` MCP tool
    # cannot tell an agent which routes need no input — the property that predicts conversion.
    try:
        import mcp_http
        mcp_http.set_routes(routes)
    except Exception as _e:                                            # noqa: BLE001
        print(f"mcp_http.set_routes skipped: {type(_e).__name__}: {_e}")
    _x402_available = True
except Exception as e:  # pragma: no cover
    print(f"  x402 v2 init warning: {type(e).__name__}: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Models
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RegistryAuditRequest(BaseModel):
    """Deliberately has NO required field — that is the entire point of the route.

    Measured 2026-08-10 across ~14,000 paywall challenges, with `POST /mcp 200` excluded:

        routes callable with NO required input : 12 routes, 397 paid,  mean 33.1
        routes REQUIRING an argument           :  9 routes,  12 paid,  mean  1.3

    A 25x gap that cuts cleanly across price AND category. /btc_rates at $0.020 with no
    argument converts; /check at $0.005 needing an `address` converted once in 5,608. The
    buyers are crawlers walking a directory of x402 endpoints and calling them blind: they can
    pay for /stocks because `{}` returns something worth $0.005, and they cannot pay for
    /audit because they have no text of ours to audit.

    So the security capability was never unsellable — it was the wrong SHAPE. This is the same
    scanner behind /audit, pointed at a target the caller does not have to supply.
    """
    limit: Optional[int] = 5          # newest N registry servers; capped at 15 below

class AuditRequest(BaseModel):
    content: str

class AuditUrlRequest(BaseModel):
    url: str
    max_size: Optional[int] = 500_000  # 500KB default limit

class ReadRequest(BaseModel):
    url: str
    include_links: Optional[bool] = True
    max_size: Optional[int] = 2_000_000  # 2MB raw HTML cap

class ReadBatchRequest(BaseModel):
    urls: list[str]
    include_links: Optional[bool] = True

class ExtractRequest(BaseModel):
    url: str

class PdfRequest(BaseModel):
    url: str
    max_pages: Optional[int] = 50

class RepoAuditRequest(BaseModel):
    repo: str
    ref: Optional[str] = None
    include_tests: Optional[bool] = False  # test/doc/changelog files are false-positive factories

class TrustRequest(BaseModel):
    url: str
    check_x402: Optional[bool] = True

class SearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 10

class CrawlRequest(BaseModel):
    url: str
    max_pages: Optional[int] = 5
    include_links: Optional[bool] = True

class SitemapRequest(BaseModel):
    url: str
    max_urls: Optional[int] = 500

class RssRequest(BaseModel):
    url: str
    max_items: Optional[int] = 50

class HeadersRequest(BaseModel):
    url: str

class DnsRequest(BaseModel):
    domain: str

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.api_route("/", methods=_DISCOVERY_VERBS_ROOT)
async def root():
    pattern_count = sum(len(pgs) for pgs in PATTERNS.values())
    signature_count = sum(len(pg["regexes"]) for pgs in PATTERNS.values() for pg in pgs)
    return {
        "service": "skill-audit API",
        "version": "2.1.0",
        "description": "Detect malicious patterns in AI agent skills, plugins, and prompts.",
        "signature_count": signature_count,
        "detects": [
            "download-and-execute", "credential exfiltration", "key generation",
            "prompt injection", "privilege escalation", "code execution",
            "identity impersonation", "seed phrase harvesting",
        ],
        "pattern_count": pattern_count,
        "endpoints": {
            "GET /": "Service info (free)",
            "GET /health": "Health check (free)",
            "POST /audit": "Audit text content ($0.005 USDC)",
            "POST /audit/url": "Fetch URL + audit ($0.005 USDC)",
            "POST /read": "Fetch URL → clean Markdown ($0.005 USDC)",
            "POST /read/batch": "Up to 10 URLs → clean Markdown, concurrent ($0.02 USDC)",
            "POST /search": "Web search → ranked title/url/snippet results, no API key ($0.01 USDC)",
            "POST /crawl": "Crawl a site same-domain BFS → each page as clean Markdown ($0.02 USDC)",
            "POST /sitemap": "robots.txt + sitemap.xml → full URL map of a domain ($0.005 USDC)",
            "POST /rss": "RSS/Atom feed (or auto-discovered from a site) → structured items ($0.005 USDC)",
            "POST /extract": "URL → structured metadata / OpenGraph / JSON-LD / links ($0.008 USDC)",
            "POST /pdf": "PDF URL → extracted text ($0.01 USDC)",
            "POST /audit/repo": "Public GitHub repo → full malicious-pattern scan ($0.005 USDC)",
            "POST /audit/registry": "Newest MCP-registry servers → supply-chain risk feed, no input required ($0.005 USDC)",
            "POST /trust": "Vet any URL / x402 server for scam+trust in one call (5 sub-scores + evidence + x402 check) ($0.02 USDC)",
            "POST /headers": "URL → HTTP security-header grade ($0.005 USDC)",
            "POST /dns": "Domain → DNS records + email/security posture ($0.006 USDC)",
        },
        "payment": {
            "method": "x402",
            "x402_version": 2,
            "currency": "USDC",
            "network": "Base (eip155:8453)",
            "facilitator": FACILITATOR_URL,
            "wallet": WALLET,
            "x402_enabled": _x402_available,
        },
    }

@app.api_route("/health", methods=_DISCOVERY_VERBS_ROOT)
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "x402_enabled": _x402_available,
    }

# Public base URL of this origin (for the x402 discovery document). Override per-Space.
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://eltociear-skill-audit.hf.space").rstrip("/")


# Paid resources advertised in /.well-known/x402 so on-chain explorers (x402scan,
# CDP Bazaar) can auto-discover and index this origin's endpoints.
_PAID_PATHS = [
    "/audit", "/audit/url", "/audit/repo", "/audit/registry", "/trust", "/read", "/read/batch",
    "/extract", "/pdf", "/headers", "/dns", "/search", "/crawl", "/sitemap", "/rss",
]

# Same measured-demand story as /llms.txt below, one sample later: a 90s access-log read on
# 2026-08-07 caught this Space 404ing GET /x402-resources, /api and /api/v1 — and the other
# two Spaces already served the resources shape. Every path added here is one real traffic
# asked for and did not get.
#
# ⚠ GET/POST/HEAD, not GET, and `.json` is here too. Measured 2026-08-17 on contract-guard:
# one access-log buffer carried 8,689 405s against 7,657 402s, all of them discovery probes
# from 262 distinct IPs POSTing to these paths. GET-only registration turned every one into
# a bare "405 Method Not Allowed" — no price, no catalogue. That is
# `x402-405-hides-the-paywall` again with the verbs swapped, and this Space was missing four
# of the aliases the other two already served on top of it.
@app.api_route("/x402", methods=_DISCOVERY_VERBS)
@app.api_route("/.well-known/x402", methods=_DISCOVERY_VERBS)
@app.api_route("/.well-known/x402.json", methods=_DISCOVERY_VERBS)
async def well_known_x402():
    """x402 discovery document (x402scan/Bazaar auto-index). version-1 schema:
    {version, resources[], instructions}. ownershipProofs omitted (listed as
    unverified) — a wallet-signed proof can be added later for the verified badge."""
    return {
        "version": 1,
        "resources": [PUBLIC_BASE + p for p in _PAID_PATHS],
        "instructions": (
            "# skill-audit x402 API\n\n"
            "Security + web-data API suite for AI agents. Pay-per-call in USDC on Base "
            "(eip155:8453) via x402 v2 — no signup, no API key.\n\n"
            "| Endpoint | Price | Description |\n|---|---|---|\n"
            "| `POST /audit` | $0.005 | Scan text for malicious AI-skill / prompt-injection patterns |\n"
            "| `POST /audit/url` | $0.005 | Fetch a URL and audit it |\n"
            "| `POST /audit/repo` | $0.005 | Scan a whole public GitHub repo (tests/docs excluded) |\n"
            "| `POST /audit/registry` | $0.005 | Newest MCP-registry servers scanned for supply-chain risk — **no input required** |\n"
            "| `POST /trust` | $0.02 | Vet any URL / x402 server for scam+trust — 5 sub-scores + evidence + x402 check, one call |\n"
            "| `POST /search` | $0.01 | Web search → ranked title/url/snippet, no API key or signup |\n"
            "| `POST /read` | $0.005 | URL → clean Markdown |\n"
            "| `POST /crawl` | $0.02 | Crawl a site same-domain (BFS) → every page as clean Markdown |\n"
            "| `POST /sitemap` | $0.005 | robots.txt + sitemap.xml → full URL map of a domain |\n"
            "| `POST /rss` | $0.005 | RSS/Atom feed (auto-discovered from a site URL) → structured items |\n"
            "| `POST /read/batch` | $0.02 | Up to 10 URLs → clean Markdown, concurrent |\n"
            "| `POST /extract` | $0.008 | URL → OpenGraph / JSON-LD / headings / links |\n"
            "| `POST /pdf` | $0.01 | PDF URL → extracted text |\n"
            "| `POST /headers` | $0.005 | URL → HTTP security-header grade A–F |\n"
            "| `POST /dns` | $0.006 | Domain → DNS records + SPF/DMARC posture |\n\n"
            f"Payments settle to `{WALLET}`. Facilitator: {FACILITATOR_URL}."
        ),
        "payTo": [WALLET],
        "network": BASE_MAINNET,
    }

# ── discovery files agents ACTUALLY request here and 404'd on (measured 2026-08-02:
# this Space is the highest-traffic of the three yet was the only one missing them —
# /llms.txt and the A2A agent-card, which a real population of distinct agents probes).
# tokenguard + contract-guard already serve these; skill-audit did not. Serving them
# is answering demand whose audience is already attached.
# Prices for /pricing and /x402-resources. These MUST stay in step with the Markdown table
# in `instructions` above and with the paywall itself -- a price list that disagrees with
# what is actually charged is worse than no price list. Asserted at import below.
_PRICE_TABLE = {
    # audit* moved to $0.005 on 2026-08-10 — see the price-experiment note above `routes`.
    "/audit": "$0.005", "/audit/url": "$0.005", "/audit/repo": "$0.005",
    "/audit/registry": "$0.005", "/trust": "$0.02",
    "/search": "$0.01", "/read": "$0.005", "/crawl": "$0.02", "/sitemap": "$0.005",
    "/rss": "$0.005", "/read/batch": "$0.02", "/extract": "$0.008", "/pdf": "$0.01",
    "/headers": "$0.005", "/dns": "$0.006",
}

# Every advertised paid path must carry a price. Without this, adding a route to
# _PAID_PATHS and forgetting the price ships a resource quoting `""` to the indexers.
assert set(_PRICE_TABLE) == set(_PAID_PATHS), (
    f"price table and paid paths disagree: "
    f"missing={sorted(set(_PAID_PATHS) - set(_PRICE_TABLE))} "
    f"extra={sorted(set(_PRICE_TABLE) - set(_PAID_PATHS))}")


# -- what a discovering agent actually READS --------------------------------------------
# The description is the only text an indexing crawler stores about a route, and the only
# thing an agent has when choosing between ours and an incumbent's. Measured 2026-08-17:
# this Space served 15 resources with NO description field at all -- 15 nameless URLs --
# while tokenguard and contract-guard both carried one. The text already existed, in the
# `endpoints` map of the service-info payload; it was simply never attached per resource.
#
# Asserted against _PAID_PATHS for the same reason the price table is: adding a route and
# forgetting its description ships an anonymous resource to every indexer.
_DESC_TABLE = {
    "/audit": "Scan text for malicious AI-skill and prompt-injection patterns; returns the "
              "matched signatures with evidence, not just a verdict.",
    "/audit/url": "Fetch a URL and audit its content for malicious AI-skill and "
                  "prompt-injection patterns.",
    "/audit/repo": "Scan a whole public GitHub repo for malicious patterns, with coverage "
                   "reported so a clean result carries its own denominator.",
    "/audit/registry": "Newest MCP-registry servers scanned for supply-chain risk -- a "
                       "feed, and it needs no input at all.",
    "/trust": "Vet any URL or x402 server for scam and trust risk in one call: five "
              "sub-scores, the evidence behind each, and an x402 liveness check.",
    "/read": "URL to clean Markdown, boilerplate stripped, ready to feed a model.",
    "/read/batch": "Up to 10 URLs to clean Markdown, fetched concurrently.",
    "/extract": "URL to structured metadata: OpenGraph, JSON-LD, canonical links.",
    "/pdf": "PDF URL to its extracted text, page by page, with the page count.",
    "/headers": "URL to an HTTP security-header grade, with the per-header findings.",
    "/dns": "Domain to DNS records plus its email and security posture (SPF, DMARC, DNSSEC).",
    "/search": "Web search to ranked title/url/snippet results. No API key, no signup.",
    "/crawl": "Crawl a site same-domain breadth-first, every page as clean Markdown.",
    "/sitemap": "robots.txt and sitemap.xml to a full URL map of a domain.",
    "/rss": "RSS or Atom feed, auto-discovered from a site URL, to structured items.",
}
assert set(_DESC_TABLE) == set(_PAID_PATHS), (
    f"description table and paid paths disagree: "
    f"missing={sorted(set(_PAID_PATHS) - set(_DESC_TABLE))} "
    f"extra={sorted(set(_DESC_TABLE) - set(_PAID_PATHS))}")


@app.api_route("/x402-resources", methods=_DISCOVERY_VERBS)
@app.api_route("/.well-known/x402-resources", methods=_DISCOVERY_VERBS)
@app.api_route("/discovery/resources", methods=_DISCOVERY_VERBS)
@app.api_route("/x402/discovery/resources", methods=_DISCOVERY_VERBS)
@app.api_route("/v1/x402/discovery/resources", methods=_DISCOVERY_VERBS)
@app.api_route("/v2/x402/discovery/resources", methods=_DISCOVERY_VERBS)
@app.api_route("/.well-known/x402/discovery/resources", methods=_DISCOVERY_VERBS)
async def x402_resources():
    """Expanded resource list. Indexers ask for this shape (full `accepts` per resource)
    rather than the bare URL array in /.well-known/x402, and this Space was the only one of
    the three not serving it — its own access log shows the path being requested."""
    items = [{
        "resource": PUBLIC_BASE + p,
        "url": PUBLIC_BASE + p,
        "method": "POST",
        "type": "http",
        "x402Version": 2,
        "mimeType": "application/json",
        "description": _DESC_TABLE.get(p, ""),
        "accepts": [{
            "scheme": "exact",
            "network": BASE_MAINNET,
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
            "payTo": WALLET,
            "price": _PRICE_TABLE.get(p, ""),
        }],
    } for p in _PAID_PATHS]
    return {"x402Version": 2, "count": len(items), "resources": items, "items": items}


@app.api_route("/api", methods=_DISCOVERY_VERBS_ROOT)
@app.api_route("/api/v1", methods=_DISCOVERY_VERBS_ROOT)
@app.api_route("/v1", methods=_DISCOVERY_VERBS_ROOT)
async def api_index():
    return {
        "service": "skill-audit",
        "description": "Security + web-data API suite for AI agents.",
        "paid_endpoint_count": len(_PAID_PATHS),
        "payment": {"protocol": "x402", "asset": "USDC", "network": BASE_MAINNET,
                    "payTo": WALLET},
        "discovery": {
            "x402": PUBLIC_BASE + "/.well-known/x402",
            "resources": PUBLIC_BASE + "/x402-resources",
            "pricing": PUBLIC_BASE + "/pricing",
            "terms": PUBLIC_BASE + "/terms",
            "agent_card": PUBLIC_BASE + "/.well-known/agent-card.json",
            "openapi": PUBLIC_BASE + "/openapi.json",
        },
    }


@app.api_route("/pricing", methods=_DISCOVERY_VERBS_ROOT)
async def pricing():
    return {
        "currency": "USDC", "network": BASE_MAINNET, "payTo": WALLET,
        "protocol": "x402", "unit": "per request", "count": len(_PAID_PATHS),
        "paid": [{"method": "POST", "path": p, "price": _PRICE_TABLE.get(p, "")}
                 for p in _PAID_PATHS],
    }


@app.api_route("/terms", methods=_DISCOVERY_VERBS_ROOT)
@app.api_route("/tos", methods=_DISCOVERY_VERBS_ROOT)
@app.api_route("/privacy", methods=_DISCOVERY_VERBS_ROOT)
async def terms():
    """Terms an autonomous buyer can read before spending."""
    return {
        "service": "skill-audit",
        "operator": "eltociear",
        "payment": {"protocol": "x402", "asset": "USDC", "network": BASE_MAINNET,
                    "payTo": WALLET,
                    "refunds": "none — each call is priced and settled per request"},
        "data": {
            "inputs_logged": "request path and parameters, for rate limiting only",
            "personal_data_collected": "none — there is no account and no API key",
            "retention": "access logs only, as retained by the hosting platform",
        },
        "warranty": "none. Audit output is a heuristic signal from static pattern "
                    "matching, not a security guarantee.",
        "acceptable_use": "scan only targets you are authorised to scan",
    }


@app.api_route("/sitemap.xml", methods=_DISCOVERY_VERBS_ROOT)
async def sitemap():
    paths = ["/", "/pricing", "/terms", "/llms.txt", "/openapi.json",
             "/.well-known/x402", "/x402-resources", "/.well-known/agent-card.json"]
    urls = "".join(f"<url><loc>{PUBLIC_BASE}{p}</loc></url>" for p in paths)
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>",
        media_type="application/xml")


@app.api_route("/m2m-openapi.json", methods=_DISCOVERY_VERBS_ROOT)
async def m2m_openapi():
    """Alias: something in the wild probes this name for a machine-readable spec."""
    return app.openapi()


@app.api_route("/llms.txt", methods=_DISCOVERY_VERBS_ROOT)
async def llms_txt():
    """llms.txt — the machine-readable site summary crawlers/agents probe for."""
    lines = ["# skill-audit", "",
             "> Security + web-data API suite for AI agents. Pay-per-call in USDC on "
             "Base (eip155:8453) via x402 v2 — no signup, no API key.", "",
             "## Paid endpoints (x402)"]
    lines += [f"- POST {PUBLIC_BASE}{p}" for p in _PAID_PATHS]
    lines += ["", f"x402 discovery: {PUBLIC_BASE}/.well-known/x402",
              f"Agent card: {PUBLIC_BASE}/.well-known/agent-card.json",
              f"Payments settle to {WALLET}."]
    return Response("\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")


@app.api_route("/.well-known/agent.json", methods=_DISCOVERY_VERBS_ROOT)
@app.api_route("/.well-known/agent-card.json", methods=_DISCOVERY_VERBS_ROOT)
@app.api_route("/.well-known/agent-card", methods=_DISCOVERY_VERBS_ROOT)
async def agent_card():
    """A2A agent card — how agent directories and peers introspect a service. Measured
    2026-08-02: distinct A2A agents probe these exact paths on this Space and got 404,
    i.e. they are trying to discover us as a peer and failing."""
    return {
        "protocolVersion": "0.3.0",
        "name": "skill-audit",
        "description": ("Pay-per-call security + web-data API for AI agents: malicious-skill / "
                        "prompt-injection scanning, URL trust/scam vetting, web search, and "
                        "URL-to-Markdown reading. USDC on Base via x402 — no signup."),
        "url": PUBLIC_BASE,
        "provider": {"organization": "eltociear", "url": "https://github.com/eltociear"},
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{
            "id": p.strip("/").replace("/", "_"),
            "name": p,
            "description": f"POST {p} — x402 paid",
            "tags": ["x402", "paid", "security", "web-data"],
        } for p in _PAID_PATHS],
        "payment": {"protocol": "x402", "version": 2, "network": BASE_MAINNET,
                    "currency": "USDC", "payTo": WALLET},
    }

@app.post("/audit")
async def audit_text(req: AuditRequest):
    content = req.content
    if not content or not content.strip():
        raise HTTPException(400, "content is required and must not be empty")
    if len(content) > 1_000_000:
        raise HTTPException(413, "content too large (max 1MB)")
    result = scan(content)
    return {
        "risk_score": result["risk_score"],
        "risk_level": result["risk_level"],
        "summary": result["summary"],
        "total_findings": result["total_findings"],
        "findings": result["findings"],
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OKX AI Agent Marketplace variant — X Layer (eip155:196) 402 challenge.
# OKX's task system settles via its own escrow and only accepts USDT/USDG on X Layer, so
# this route advertises a hand-built X-Layer challenge (OKX reads it during review and pays
# via escrow). It is DELIBERATELY outside the x402 middleware `routes` dict so it does not
# touch the live Base/USDC settlement path — Base earners are unaffected. On a request that
# already carries an X-PAYMENT header (OKX escrow settled), it runs the real audit.
import base64 as _b64
import json as _json
# USDT0 on X Layer, 6 dec — the ONLY payment token OKX review accepts (rejection 2026-07-26:
# "Please make sure the token for payment is USDT0"). EIP-712 domain verified on-chain against
# DOMAIN_SEPARATOR 0xd591d9ba…: name="USD₮0", version="1", chainId 196.
# (The older 0x1E4a5963… "Tether USD" is a different X Layer token and gets the listing rejected.)
_XLAYER_USDT = "0x779DEd0c9e1022225f8E0630b35a9b54bE713736"
_OKX_WALLET = os.environ.get("OKX_WALLET", "0xf8ea161baa8dbb47d6c8744c718e29a9d83609b6")

# OKX's 3rd review (2026-07-27) demands the payment go through THEIR broker, not a challenge we
# hand-write. `okx_payments` does that with our own SDK (their "official SDK" is a repackaged,
# older copy of the same library and would collide with the Base earners). It needs OKX Developer
# Portal API keys; without them this stays False and the hand-built challenge below still serves,
# so the listing is never worse off than it is today.
try:
    # okx_payments.py sits one level up (scripts/) in both the repo and the deployed build;
    # main.py is imported as scripts.x402_api.main, so neither dir is on sys.path by default.
    for _p in (os.path.dirname(os.path.abspath(__file__)),
               os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import okx_payments as _okx_pay
    _OKX_SDK_ACTIVE = _okx_pay.install(app, _OKX_WALLET)
except Exception as _e:  # pragma: no cover
    _OKX_SDK_ACTIVE = False
    print(f"  okx payment SDK not installed: {type(_e).__name__}: {_e}")
print(f"  okx broker paywall: {'ACTIVE' if _OKX_SDK_ACTIVE else 'inactive (no OKX_* credentials)'}")


def _okx_unpaid(request: Request) -> bool:
    """True only when WE still have to emit the challenge. Once the OKX middleware is active it
    owns the whole handshake — including its own header names — so the handler must not re-gate."""
    if _OKX_SDK_ACTIVE:
        return False
    return not (request.headers.get("X-PAYMENT") or request.headers.get("x-payment")
                or request.headers.get("PAYMENT-SIGNATURE"))


def _okx_challenge(amount_usdt6: int, resource: str):
    doc = {
        "x402Version": 2,
        "error": "payment required",
        "accepts": [{
            "scheme": "exact",
            "network": "eip155:196",
            "asset": _XLAYER_USDT,
            "payTo": _OKX_WALLET,
            "amount": str(amount_usdt6),
            "maxAmountRequired": str(amount_usdt6),
            "resource": resource,
            "maxTimeoutSeconds": 300,
            "extra": {"name": "USD₮0", "version": "1", "decimals": 6},
        }],
    }
    return _b64.b64encode(_json.dumps(doc, separators=(",", ":")).encode()).decode()


# GET/POST/HEAD: this is a free diagnostic and the crawler fleet POSTs it. Registered
# GET-only it answered 405, which tells a prober the path is not there at all. Its
# full path is also in mcp_http.FREE_PATHS so tokenguard's blanket POST sweep cannot
# turn a diagnostic into a paid route.
@app.api_route("/okx/status", methods=["GET", "POST", "HEAD"])
async def okx_status():
    """FREE diagnostic: is the OKX broker paywall live, or are we still on the fallback challenge?
    Reports whether credentials are present, never their values."""
    creds = False
    try:
        creds = bool(_okx_pay.credentials())
    except Exception:
        pass
    return {"broker_paywall_active": _OKX_SDK_ACTIVE,
            "credentials_present": creds,
            "mode": "okx-broker" if _OKX_SDK_ACTIVE else "fallback-challenge",
            "network": "eip155:196", "asset": _XLAYER_USDT, "pay_to": _OKX_WALLET,
            "routes": sorted(["/okx/audit", "/okx/read", "/okx/search", "/okx/extract"])}


@app.get("/okx/{service}")
async def okx_discover(service: str):
    """Discovery probe: a bare GET on any /okx/* service returns the same 402 challenge the POST
    does. Without this a reviewer (or `onchainos agent x402-check` with no --body) sees 405 and
    reads the service as 'not a valid x402 endpoint'."""
    if service not in ("audit", "read", "search", "extract"):
        raise HTTPException(404, "unknown service")
    return Response(
        status_code=402,
        headers={"payment-required": _okx_challenge(10000, f"/okx/{service}")},
        media_type="application/json",
        content=_json.dumps({"x402Version": 2, "error": "payment required",
                             "accepts_network": "eip155:196"}),
    )


@app.post("/okx/audit")
async def okx_audit(req: AuditRequest, request: Request):
    """OKX-marketplace audit endpoint (X Layer / USDT via OKX escrow). Same scan engine as
    /audit; only the payment rail differs (eip155:196 + USDT, settled by OKX)."""
    if _okx_unpaid(request):
        return Response(
            status_code=402,
            headers={"payment-required": _okx_challenge(10000, "/okx/audit")},  # $0.01 USDT
            media_type="application/json",
            content=_json.dumps({"x402Version": 2, "error": "payment required",
                                "accepts_network": "eip155:196"}),
        )
    content = (req.content or "")
    if not content.strip():
        raise HTTPException(400, "content is required")
    result = scan(content[:1_000_000])
    return {"risk_score": result["risk_score"], "risk_level": result["risk_level"],
            "summary": result["summary"], "total_findings": result["total_findings"],
            "findings": result["findings"]}


@app.post("/okx/search")
async def okx_search(req: SearchRequest, request: Request):
    """OKX-marketplace web search (X Layer / USDT via OKX escrow). Delegates to /search."""
    if _okx_unpaid(request):
        return Response(
            status_code=402,
            headers={"payment-required": _okx_challenge(10000, "/okx/search")},  # $0.01 USDT
            media_type="application/json",
            content=_json.dumps({"x402Version": 2, "error": "payment required",
                                 "accepts_network": "eip155:196"}),
        )
    return await web_search(req)


@app.post("/okx/extract")
async def okx_extract(req: ExtractRequest, request: Request):
    """OKX-marketplace structured extract (X Layer / USDT via OKX escrow). Delegates to /extract."""
    if _okx_unpaid(request):
        return Response(
            status_code=402,
            headers={"payment-required": _okx_challenge(10000, "/okx/extract")},  # $0.01 USDT
            media_type="application/json",
            content=_json.dumps({"x402Version": 2, "error": "payment required",
                                 "accepts_network": "eip155:196"}),
        )
    return await extract_structured(req)


@app.post("/okx/read")
async def okx_read(req: ReadRequest, request: Request):
    """OKX-marketplace clean-read (X Layer / USDT via OKX escrow). Delegates to /read."""
    if _okx_unpaid(request):
        return Response(
            status_code=402,
            headers={"payment-required": _okx_challenge(10000, "/okx/read")},  # $0.01 USDT
            media_type="application/json",
            content=_json.dumps({"x402Version": 2, "error": "payment required",
                                 "accepts_network": "eip155:196"}),
        )
    return await read_url(req)


@app.post("/audit/url")
async def audit_url(req: AuditUrlRequest):
    url = req.url
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")

    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client:
            resp = await _safe_get(client, url, ua="skill-audit/1.0")
            resp.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"upstream returned {e.response.status_code}")
    except Exception as e:
        raise HTTPException(502, f"fetch failed: {type(e).__name__}")

    content = resp.text
    if len(content) > req.max_size:
        content = content[:req.max_size]

    result = scan(content)
    return {
        "url": url,
        "content_length": len(content),
        "risk_score": result["risk_score"],
        "risk_level": result["risk_level"],
        "summary": result["summary"],
        "total_findings": result["total_findings"],
        "findings": result["findings"],
    }

@app.post("/read")
async def read_url(req: ReadRequest):
    url = req.url
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")

    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
            resp = await _safe_get(client, url, ua="Mozilla/5.0 (compatible; clean-read/1.0)")
            resp.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"upstream returned {e.response.status_code}")
    except Exception as e:
        raise HTTPException(502, f"fetch failed: {type(e).__name__}")

    html = resp.text
    if len(html) > req.max_size:
        html = html[: req.max_size]

    try:
        import trafilatura
    except ImportError:
        raise HTTPException(503, "extraction engine unavailable")

    markdown = trafilatura.extract(
        html, output_format="markdown",
        include_links=bool(req.include_links), include_tables=True, favor_recall=True,
    )
    if not markdown:
        raise HTTPException(422, "could not extract main content from this page")

    title = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta:
            title = meta.title
    except Exception:
        pass

    return {
        "url": str(resp.url),
        "title": title,
        "markdown": markdown,
        "word_count": len(markdown.split()),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SSRF guard — these endpoints fetch caller-supplied URLs server-side, so they must
# refuse loopback / private / link-local / reserved targets (incl. cloud metadata at
# 169.254.169.254) and re-validate on every redirect hop. Public URLs are unaffected.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _host_is_blocked(host: str) -> bool:
    """True if `host` (name or literal) resolves to any non-public IP."""
    import ipaddress, socket
    host = host.strip("[]")  # strip IPv6 literal brackets
    try:  # already a literal?
        ip = ipaddress.ip_address(host)
        return not ip.is_global
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True  # unresolvable → refuse
    for info in infos:
        ip_str = info[4][0].split("%")[0]  # drop scope id
        try:
            if not ipaddress.ip_address(ip_str).is_global:
                return True
        except ValueError:
            return True
    return False


def _validate_public_url(url: str):
    """Raise HTTPException(400) unless url is http(s) with a public host."""
    from urllib.parse import urlparse
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "valid http/https URL required")
    if _host_is_blocked(p.hostname):
        raise HTTPException(400, "URL host is not a public address (private/loopback/link-local blocked)")


async def _safe_get(client, url: str, *, ua: str, max_redirects: int = 5):
    """GET with manual, SSRF-validated redirect following (each hop re-checked)."""
    _validate_public_url(url)
    current = url
    for _ in range(max_redirects + 1):
        resp = await client.get(current, headers={"User-Agent": ua})
        if resp.is_redirect and resp.headers.get("location"):
            from urllib.parse import urljoin
            current = urljoin(current, resp.headers["location"])
            _validate_public_url(current)  # block redirect-to-internal
            continue
        return resp
    raise HTTPException(400, "too many redirects")


async def _fetch_text(url: str, max_size: int, timeout: float = 20.0, ua: str = "Mozilla/5.0 (compatible; clean-read/1.0)"):
    """Fetch a URL and return its decoded body, truncated to max_size (SSRF-guarded)."""
    import httpx
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        resp = await _safe_get(client, url, ua=ua)
        resp.raise_for_status()
    html = resp.text
    return (html[:max_size] if len(html) > max_size else html), str(resp.url)


def _to_markdown(html: str, include_links: bool):
    """trafilatura extraction shared by /read and /read/batch. Returns (markdown, title)."""
    import trafilatura
    markdown = trafilatura.extract(
        html, output_format="markdown",
        include_links=include_links, include_tables=True, favor_recall=True,
    )
    title = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta:
            title = meta.title
    except Exception:
        pass
    return markdown, title


@app.post("/read/batch")
async def read_batch(req: ReadBatchRequest):
    urls = [u for u in (req.urls or []) if u]
    if not urls:
        raise HTTPException(400, "urls is required and must not be empty")
    if len(urls) > 10:
        raise HTTPException(413, "max 10 urls per batch")
    for u in urls:
        if not u.startswith(("http://", "https://")):
            raise HTTPException(400, f"valid http/https URL required: {u}")

    import asyncio

    async def one(u: str):
        try:
            html, final = await _fetch_text(u, 2_000_000)
            markdown, title = _to_markdown(html, bool(req.include_links))
            if not markdown:
                return {"url": u, "error": "could not extract main content"}
            return {"url": final, "title": title, "markdown": markdown,
                    "word_count": len(markdown.split())}
        except Exception as e:
            return {"url": u, "error": f"{type(e).__name__}: {e}"}

    results = await asyncio.gather(*[one(u) for u in urls])
    return {
        "count": len(results),
        "ok": sum(1 for r in results if "markdown" in r),
        "results": results,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agent web-data tier: /search /crawl /sitemap /rss
# These extend the proven /read product (fetch → structured text for agents).
# All outbound fetches go through _safe_get/_fetch_text, so the SSRF guard applies.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SEARCH_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _unwrap_ddg(href: str) -> str:
    """DDG html wraps results as //duckduckgo.com/l/?uddg=<urlencoded target>."""
    from urllib.parse import urlparse, parse_qs, unquote
    if "uddg=" in href:
        q = parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)
        if q.get("uddg"):
            return unquote(q["uddg"][0])
    return href


def _parse_ddg(html: str, limit: int):
    from lxml import html as lh
    doc = lh.fromstring(html)
    out = []
    # Anchor-first: DDG nests several `result*`-classed divs per hit, so selecting
    # containers double-counts. One anchor == one hit; snippet lives in its ancestor.
    seen = set()
    for a in doc.xpath("//a[contains(@class,'result__a')]"):
        url = _unwrap_ddg(a.get("href") or "")
        if not url.startswith("http") or url in seen:
            continue
        if "duckduckgo.com/y.js" in url or "ad_provider" in url:  # sponsored
            continue
        seen.add(url)
        snip = a.xpath("ancestor::div[contains(@class,'result')][1]"
                       "//*[contains(@class,'result__snippet')]")
        out.append({"rank": len(out) + 1,
                    "title": " ".join(a.text_content().split()),
                    "url": url,
                    "snippet": " ".join(snip[0].text_content().split()) if snip else None})
        if len(out) >= limit:
            break
    return out


def _parse_ddg_lite(html: str, limit: int):
    """lite.duckduckgo.com/lite — table layout: a.result-link + td.result-snippet."""
    from lxml import html as lh
    doc = lh.fromstring(html)
    out, seen = [], set()
    for a in doc.xpath("//a[contains(@class,'result-link')]"):
        url = _unwrap_ddg(a.get("href") or "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        snip = a.xpath("ancestor::tr[1]/following-sibling::tr[1]//td[contains(@class,'result-snippet')]")
        out.append({"rank": len(out) + 1,
                    "title": " ".join(a.text_content().split()),
                    "url": url,
                    "snippet": " ".join(snip[0].text_content().split()) if snip else None})
        if len(out) >= limit:
            break
    return out


def _parse_mojeek(html: str, limit: int):
    from lxml import html as lh
    doc = lh.fromstring(html)
    out = []
    for li in doc.xpath("//ul[contains(@class,'results-standard')]/li"):
        a = li.xpath(".//a[contains(@class,'title')] | .//h2/a")
        if not a:
            continue
        url = a[0].get("href") or ""
        if not url.startswith("http"):
            continue
        p = li.xpath(".//p[@class='s']")
        out.append({"rank": len(out) + 1,
                    "title": " ".join(a[0].text_content().split()),
                    "url": url,
                    "snippet": " ".join(p[0].text_content().split()) if p else None})
        if len(out) >= limit:
            break
    return out


@app.post("/search")
async def web_search(req: SearchRequest):
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    limit = max(1, min(int(req.max_results or 10), 25))

    from urllib.parse import quote_plus
    engines = [
        ("duckduckgo", f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", _parse_ddg),
        ("duckduckgo-lite", f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}", _parse_ddg_lite),
        ("mojeek", f"https://www.mojeek.com/search?q={quote_plus(query)}", _parse_mojeek),
    ]
    errors = {}
    for name, url, parse in engines:
        try:
            html, _ = await _fetch_text(url, 3_000_000, timeout=20.0, ua=_SEARCH_UA)
            results = parse(html, limit)
            if results:
                return {"query": query, "engine": name, "count": len(results),
                        "results": results,
                        "fetched_at": datetime.utcnow().isoformat() + "Z"}
            errors[name] = "no results parsed"
        except Exception as e:
            # Class only: the message can carry our upstream URLs and transport detail, and
            # these backends are OUR infrastructure, not something the caller supplied.
            errors[name] = type(e).__name__
            print(f"  search backend {name} failed: {type(e).__name__}: {e}")
    # Nothing usable — 502 so the payment middleware does not settle a useless call.
    raise HTTPException(502, f"all search backends failed or returned nothing: {errors}")


@app.post("/crawl")
async def crawl_site(req: CrawlRequest):
    start = (req.url or "").strip()
    if not start.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")
    max_pages = max(1, min(int(req.max_pages or 5), 10))

    from urllib.parse import urljoin, urldefrag, urlparse
    from lxml import html as lh

    origin_host = urlparse(start).hostname or ""
    seen = {urldefrag(start)[0]}
    queue = [(urldefrag(start)[0], 0)]
    pages, failures = [], []

    while queue and len(pages) < max_pages:
        current, depth = queue.pop(0)
        try:
            raw, final = await _fetch_text(current, 2_000_000)
        except Exception as e:
            failures.append({"url": current, "error": f"{type(e).__name__}: {e}"})
            continue

        markdown, title = _to_markdown(raw, bool(req.include_links))
        if markdown:
            pages.append({"url": final, "title": title, "markdown": markdown,
                          "word_count": len(markdown.split()), "depth": depth})
        else:
            failures.append({"url": final, "error": "could not extract main content"})

        if len(pages) + len(queue) >= max_pages:
            continue
        try:  # enqueue same-domain children
            doc = lh.fromstring(raw)
            for a in doc.xpath("//a[@href]"):
                link = urldefrag(urljoin(final, a.get("href")))[0]
                if not link.startswith(("http://", "https://")) or link in seen:
                    continue
                if (urlparse(link).hostname or "") != origin_host:
                    continue
                seen.add(link)
                queue.append((link, depth + 1))
                if len(seen) > max_pages * 20:
                    break
        except Exception:
            pass

    if not pages:
        raise HTTPException(502, f"no page could be crawled from {start}")
    return {"start_url": start, "pages_fetched": len(pages), "ok": len(pages),
            "failed": failures[:10], "pages": pages,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@app.post("/sitemap")
async def site_map(req: SitemapRequest):
    raw_url = (req.url or "").strip()
    if not raw_url:
        raise HTTPException(400, "url is required")
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    max_urls = max(1, min(int(req.max_urls or 500), 2000))

    from urllib.parse import urlparse
    from lxml import etree
    p = urlparse(raw_url)
    site = f"{p.scheme}://{p.netloc}"

    # Cloudflare-fronted origins 403 the default "compatible; clean-read/1.0" UA from a
    # datacenter IP, which used to surface as a misleading "no sitemap found" 404 — the
    # buyer paid and was told the site has no sitemap when really we were blocked.
    # Ask as a browser; sitemaps are public documents.
    SITEMAP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

    # 1. robots.txt Sitemap: lines, then the conventional locations.
    candidates = []
    blocked: list = []

    async def _get(url: str, cap: int, timeout: float):
        """Fetch, recording upstream refusals so they can be reported rather than
        silently collapsing into 'no sitemap'."""
        try:
            return await _fetch_text(url, cap, timeout=timeout, ua=SITEMAP_UA)
        except Exception as ex:
            status = getattr(getattr(ex, "response", None), "status_code", None)
            if status in (401, 403, 405, 406, 429) or status is None:
                blocked.append({"url": url, "status": status, "error": type(ex).__name__})
            raise

    try:
        robots, _ = await _get(site + "/robots.txt", 500_000, 15.0)
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                loc = line.split(":", 1)[1].strip()
                if loc.startswith("http") and loc not in candidates:
                    candidates.append(loc)
    except Exception:
        pass
    for guess in (site + "/sitemap.xml", site + "/sitemap_index.xml"):
        if guess not in candidates:
            candidates.append(guess)

    urls, used, index_expansions = [], [], 0

    async def load(loc: str, depth: int = 0):
        nonlocal index_expansions
        if len(urls) >= max_urls or depth > 2:
            return
        try:
            body, final = await _get(loc, 5_000_000, 20.0)
        except Exception:
            return
        try:
            root = etree.fromstring(body.encode("utf-8", "replace"),
                                    etree.XMLParser(recover=True, resolve_entities=False))
        except Exception:
            return
        if root is None:
            return
        used.append(final)
        tag = etree.QName(root).localname if root.tag is not etree.Comment else ""

        # Match on local names instead of a hardcoded namespace URI. Plenty of real
        # sitemaps declare no namespace, or the http vs https form of the schema URL;
        # a fixed prefix silently yields 0 URLs on those, i.e. "this site has no
        # sitemap" for a site that plainly does. Same failure mode as the OFAC parser.
        def _find(el, name):
            return [e for e in el.iter() if isinstance(e.tag, str)
                    and etree.QName(e).localname == name]

        def _child_text(el, name):
            for e in el:
                if isinstance(e.tag, str) and etree.QName(e).localname == name and e.text:
                    return e.text.strip()
            return None

        if tag == "sitemapindex":
            children = [t for t in (_child_text(e, "loc") for e in _find(root, "sitemap")) if t]
            for child in children[:20]:
                index_expansions += 1
                await load(child, depth + 1)
            return
        for u in _find(root, "url"):
            loc_text = _child_text(u, "loc")
            if loc_text:
                urls.append({"loc": loc_text, "lastmod": _child_text(u, "lastmod")})
                if len(urls) >= max_urls:
                    return

    for c in candidates:
        await load(c)
        if len(urls) >= max_urls:
            break

    if not urls:
        # Tell the buyer which of the two it is. 404 means "this site has no sitemap";
        # 502 means "the origin refused us" — a paid call must not report the second
        # as the first.
        if blocked:
            raise HTTPException(502, {
                "error": f"origin refused our requests for {site}; no sitemap could be read",
                "blocked": blocked[:6],
                "hint": "the site is likely behind a bot filter that rejects datacenter IPs",
            })
        raise HTTPException(404, f"no sitemap URLs found for {site} (tried {candidates})")
    return {"site": site, "sitemaps": used, "sitemap_index_expansions": index_expansions,
            "count": len(urls), "urls": urls,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@app.post("/rss")
async def parse_feed(req: RssRequest):
    raw_url = (req.url or "").strip()
    if not raw_url:
        raise HTTPException(400, "url is required")
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    max_items = max(1, min(int(req.max_items or 50), 200))

    from lxml import etree, html as lh
    from urllib.parse import urljoin

    body, final = await _fetch_text(raw_url, 5_000_000, timeout=20.0)

    def as_xml(text: str):
        try:
            root = etree.fromstring(text.encode("utf-8", "replace"),
                                    etree.XMLParser(recover=True, resolve_entities=False))
        except Exception:
            return None
        if root is None:
            return None
        name = etree.QName(root).localname.lower() if isinstance(root.tag, str) else ""
        return root if name in ("rss", "feed", "rdf") else None

    root = as_xml(body)
    if root is None:  # looked like a site page → auto-discover its feed link
        try:
            doc = lh.fromstring(body)
            links = doc.xpath("//link[@type='application/rss+xml' or @type='application/atom+xml']")
            hrefs = [urljoin(final, l.get("href")) for l in links if l.get("href")]
        except Exception:
            hrefs = []
        for h in hrefs[:3]:
            try:
                body2, final2 = await _fetch_text(h, 5_000_000, timeout=20.0)
            except Exception:
                continue
            root = as_xml(body2)
            if root is not None:
                final = final2
                break
    if root is None:
        raise HTTPException(422, "not an RSS/Atom feed and no feed link could be discovered")

    ATOM = "http://www.w3.org/2005/Atom"

    def txt(el):
        return " ".join(el.text_content().split()) if hasattr(el, "text_content") else (
            " ".join(el.text.split()) if el is not None and el.text else None)

    kind = etree.QName(root).localname.lower()
    items, feed_title = [], None
    if kind == "feed":  # Atom
        t = root.find(f"{{{ATOM}}}title")
        feed_title = txt(t)
        for e in root.findall(f"{{{ATOM}}}entry")[:max_items]:
            link_el = e.find(f"{{{ATOM}}}link")
            summary = e.find(f"{{{ATOM}}}summary")
            if summary is None:
                summary = e.find(f"{{{ATOM}}}content")
            items.append({
                "title": txt(e.find(f"{{{ATOM}}}title")),
                "link": link_el.get("href") if link_el is not None else None,
                "published": txt(e.find(f"{{{ATOM}}}updated")) or txt(e.find(f"{{{ATOM}}}published")),
                "summary": (txt(summary) or "")[:2000] or None,
            })
        fmt = "atom"
    else:  # RSS 2.0 / RDF — namespace-agnostic local-name search
        feed_title = txt(root.find(".//channel/title")) or txt(root.find(".//title"))
        entries = root.findall(".//item") or root.findall(".//{*}item")
        for e in entries[:max_items]:
            def sub(name):
                el = e.find(name)
                return el if el is not None else e.find("{*}" + name)
            items.append({
                "title": txt(sub("title")),
                "link": txt(sub("link")) or (sub("guid") is not None and txt(sub("guid"))) or None,
                "published": txt(sub("pubDate")) or txt(sub("date")),
                "summary": (txt(sub("description")) or "")[:2000] or None,
            })
        fmt = "rss"

    if not items:
        raise HTTPException(422, "feed parsed but contained no items")
    return {"feed_url": final, "title": feed_title, "format": fmt,
            "count": len(items), "items": items,
            "fetched_at": datetime.utcnow().isoformat() + "Z"}


@app.post("/extract")
async def extract_structured(req: ExtractRequest):
    if not req.url or not req.url.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")
    try:
        html, final = await _fetch_text(req.url, 2_000_000)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"fetch failed: {type(e).__name__}")

    import json as _json
    from lxml import html as lhtml

    try:
        tree = lhtml.fromstring(html)
    except Exception as e:
        raise HTTPException(422, f"could not parse HTML: {type(e).__name__}")

    def _txt(nodes):
        return [" ".join(n.text_content().split()) for n in nodes]

    opengraph = {}
    meta_desc = None
    for m in tree.xpath("//meta"):
        prop = m.get("property") or m.get("name") or ""
        content = m.get("content")
        if not content:
            continue
        if prop.startswith(("og:", "twitter:")):
            opengraph[prop] = content
        elif prop.lower() == "description":
            meta_desc = content

    jsonld = []
    for s in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            jsonld.append(_json.loads(s.text_content()))
        except Exception:
            continue

    headings = [
        {"level": int(h.tag[1]), "text": t}
        for h, t in zip(tree.xpath("//h1|//h2|//h3"), _txt(tree.xpath("//h1|//h2|//h3")))
        if t
    ][:100]

    from urllib.parse import urljoin
    links, seen = [], set()
    for a in tree.xpath("//a[@href]"):
        href = urljoin(final, a.get("href"))
        if href.startswith(("http://", "https://")) and href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= 200:
            break

    titles = tree.xpath("//title/text()")
    return {
        "url": final,
        "title": (titles[0].strip() if titles else None),
        "description": meta_desc or opengraph.get("og:description"),
        "opengraph": opengraph,
        "jsonld": jsonld[:20],
        "headings": headings,
        "links": links,
        "link_count": len(links),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/pdf")
async def pdf_to_text(req: PdfRequest):
    if not req.url or not req.url.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise HTTPException(503, "pdf engine unavailable")

    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            resp = await _safe_get(client, req.url, ua="clean-read/1.0")
            resp.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"upstream returned {e.response.status_code}")
    except Exception as e:
        raise HTTPException(502, f"fetch failed: {type(e).__name__}")

    raw = resp.content
    if len(raw) > 25_000_000:
        raise HTTPException(413, "pdf too large (max 25MB)")
    if not raw[:5].startswith(b"%PDF"):
        raise HTTPException(415, "url did not return a PDF")

    import io
    try:
        reader = PdfReader(io.BytesIO(raw))
        total = len(reader.pages)
        cap = max(1, min(int(req.max_pages or 50), 200))
        parts = []
        for i, page in enumerate(reader.pages[:cap], 1):
            try:
                body = (page.extract_text() or "").strip()
            except Exception:
                body = ""
            parts.append(f"# Page {i}\n\n{body}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"could not read pdf: {type(e).__name__}: {e}")

    text = "\n\n".join(parts)
    return {
        "url": str(resp.url),
        "pages": total,
        "extracted_pages": min(total, cap),
        "text": text,
        "word_count": len(text.split()),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }


# HTTP response headers that reduce attack surface, with weight toward the security grade.
_SEC_HEADERS = {
    "strict-transport-security": 25,
    "content-security-policy": 25,
    "x-content-type-options": 15,
    "x-frame-options": 15,
    "referrer-policy": 10,
    "permissions-policy": 10,
}


import re as _re

# High-precision web-scam / phishing / wallet-drainer signals. Tuned to NOT fire on
# normal sites (github, docs, blogs) — unlike the AI-skill scanner, which over-matches
# on ordinary HTML. Each hit carries a severity weight subtracted from content_safety.
_SCAM_RULES = [
    ("seed_phrase_harvest", 60, _re.compile(
        r"(seed phrase|recovery phrase|mnemonic|private key|secret recovery)", _re.I)),
    ("wallet_drainer", 55, _re.compile(
        r"(setApprovalForAll|permit2|signTypedData_v4[^a-z]|eth_sign\b|sweepToken|drainer|_transferFrom.*unlimited)", _re.I)),
    ("fake_airdrop", 30, _re.compile(
        r"(claim (your )?(free )?(airdrop|reward|token|nft)|you'?ve won|verify (your )?wallet to (claim|continue|unlock)|connect wallet to claim)", _re.I)),
    ("credential_phish", 35, _re.compile(
        r"<input[^>]+type=[\"']?password", _re.I)),
    ("obfuscated_js", 25, _re.compile(
        r"(eval\(\s*(atob|unescape|String\.fromCharCode)|document\.write\(\s*unescape|Function\(\s*[\"']return|\\x[0-9a-f]{2}\\x[0-9a-f]{2}\\x[0-9a-f]{2})", _re.I)),
    ("meta_redirect", 15, _re.compile(
        r"<meta[^>]+http-equiv=[\"']?refresh[\"']?[^>]+url=https?://", _re.I)),
]


def _web_scam_scan(html: str, final_url: str):
    """Return (score 0-100, [signals]) — high-precision web-scam detection for /trust."""
    signals, penalty = [], 0
    for name, weight, rx in _SCAM_RULES:
        m = rx.search(html)
        if not m:
            continue
        # seed/private-key phrasing only counts as harvesting if there's an input to type into
        if name == "seed_phrase_harvest" and "<input" not in html.lower() and "<textarea" not in html.lower():
            continue
        # a password field over plaintext http is the real phishing tell; over https it's normal login
        if name == "credential_phish" and final_url.startswith("https://"):
            weight = 10
        signals.append({"signal": name, "severity": "high" if weight >= 45 else ("medium" if weight >= 25 else "low"),
                        "match": (m.group(0)[:60])})
        penalty += weight
    return max(0, 100 - penalty), signals


def _parse_x402_challenge(resp):
    """Extract the x402 payment requirements from a 402 response. v2 puts a base64 JSON
    in the `payment-required` header; v1 used `www-authenticate`; some servers use the body."""
    import base64, json as _json
    raw = None
    for h in ("payment-required", "www-authenticate", "x-payment-required"):
        v = resp.headers.get(h)
        if v:
            token = v.split(" ", 1)[-1].strip() if " " in v and not v.strip().startswith("ey") else v.strip()
            try:
                raw = _json.loads(base64.b64decode(token + "==="))
                break
            except Exception:
                try:
                    raw = _json.loads(token)
                    break
                except Exception:
                    continue
    if raw is None:
        try:
            b = resp.json()
            if isinstance(b, dict) and (b.get("accepts") or b.get("x402Version")):
                raw = b
        except Exception:
            raw = None
    return raw


async def _doh_query(client, name: str, rtype: str):
    """One DNS-over-HTTPS query via Cloudflare. Returns list of record data strings."""
    try:
        r = await client.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": name, "type": rtype},
            headers={"accept": "application/dns-json"},
        )
        if r.status_code != 200:
            return []
        return [a["data"].strip('"') for a in r.json().get("Answer", []) if a.get("data")]
    except Exception:
        return []


@app.post("/trust")
async def trust_score(req: TrustRequest):
    """Composite, transparent, x402-native trust score for an arbitrary URL / x402 server.
    Beats single-signal scorers: one call returns transport + content-safety + domain +
    metadata + x402-compliance sub-scores, each backed by real evidence."""
    _validate_public_url(req.url)  # SSRF guard
    import httpx, time
    from urllib.parse import urlparse

    evidence, subs = {}, {}
    reachable = False
    body, final_url, hdrs = "", req.url, {}

    # ── reachability + transport (timed GET) ──
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client:
            t0 = time.perf_counter()
            resp = await _safe_get(client, req.url, ua="skill-audit/2.2 (+trust-scan)")
            evidence["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            reachable = resp.status_code < 500
            final_url = str(resp.url)
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.text[:1_000_000]
            evidence["status"] = resp.status_code
    except HTTPException:
        raise
    except Exception as e:
        evidence["fetch_error"] = f"{type(e).__name__}: {e}"

    # transport: HTTPS + security headers
    https = final_url.startswith("https://")
    present = [h for h in _SEC_HEADERS if h in hdrs]
    missing = [h for h in _SEC_HEADERS if h not in hdrs]
    hdr_pts = sum(_SEC_HEADERS[h] for h in present)  # 0..100
    subs["transport"] = (60 if https else 0) + int(hdr_pts * 0.4) if reachable else 0
    evidence["https"] = https
    evidence["present_headers"] = present
    evidence["missing_headers"] = missing

    # ── content safety (high-precision web-scam/phishing/drainer scan) ──
    if body:
        cs_score, scam_signals = _web_scam_scan(body, final_url)
        subs["content_safety"] = cs_score
        evidence["scam_signals"] = scam_signals
        evidence["malicious_findings"] = len(scam_signals)
    else:
        subs["content_safety"] = 0 if not reachable else 100
        evidence["malicious_findings"] = 0

    # ── metadata quality (real content vs parked/empty) ──
    title = None
    word_count = 0
    try:
        from lxml import html as lhtml
        tree = lhtml.fromstring(body) if body else None
        if tree is not None:
            t = tree.xpath("//title/text()")
            title = t[0].strip() if t else None
            og = any((m.get("property") or "").startswith("og:") for m in tree.xpath("//meta"))
            word_count = len(tree.text_content().split())
            q = 0
            if title:
                q += 40
            if og:
                q += 25
            if word_count >= 50:
                q += 35
            elif word_count >= 10:
                q += 15
            subs["metadata"] = min(100, q)
            evidence["title"] = title
            evidence["word_count"] = word_count
        else:
            subs["metadata"] = 0
    except Exception:
        subs["metadata"] = 30 if body else 0

    # ── domain trust (DNS + SPF/DMARC) ──
    host = urlparse(final_url).hostname or ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            a = await _doh_query(client, host, "A")
            aaaa = await _doh_query(client, host, "AAAA")
            mx = await _doh_query(client, host, "MX")
            txt = await _doh_query(client, host, "TXT")
            dmarc = await _doh_query(client, f"_dmarc.{host}", "TXT")
        has_spf = any("v=spf1" in t.lower() for t in txt)
        has_dmarc = any("v=dmarc1" in t.lower() for t in dmarc)
        d = 0
        if a or aaaa:
            d += 45
        if mx:
            d += 15
        if has_spf:
            d += 20
        if has_dmarc:
            d += 20
        subs["domain"] = min(100, d)
        evidence.update({"has_a": bool(a or aaaa), "has_mx": bool(mx), "spf": has_spf, "dmarc": has_dmarc})
    except Exception:
        subs["domain"] = 40

    # ── x402 compliance (the question buyer-agents actually have) ──
    x402_info = {"is_x402": False, "valid_challenge": False}
    if req.check_x402:
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=12.0) as client:
                _validate_public_url(req.url)
                pr = await client.post(req.url, json={}, headers={"User-Agent": "skill-audit/2.2"})
                if pr.status_code == 402:
                    x402_info["is_x402"] = True
                    ch = _parse_x402_challenge(pr)
                    if ch:
                        accepts = ch.get("accepts") or (ch.get("error", {}) if isinstance(ch.get("error"), dict) else {}).get("accepts") or []
                        opt = accepts[0] if accepts else {}
                        pay_to = opt.get("payTo") or opt.get("pay_to")
                        network = opt.get("network")
                        asset = (opt.get("extra") or {}).get("name") or opt.get("asset")
                        x402_info["valid_challenge"] = bool(pay_to and network)
                        x402_info.update({"pay_to": pay_to, "network": network, "asset": asset,
                                          "amount": opt.get("amount"),
                                          "x402_version": ch.get("x402Version") or ch.get("x402_version")})
            subs["x402"] = 100 if x402_info["valid_challenge"] else (50 if x402_info["is_x402"] else 0)
        except Exception:
            subs["x402"] = 0
    else:
        subs.pop("x402", None)

    # ── aggregate (weighted) ──
    weights = {"transport": 0.20, "content_safety": 0.30, "domain": 0.20, "metadata": 0.10, "x402": 0.20}
    active = {k: v for k, v in subs.items() if k in weights}
    wsum = sum(weights[k] for k in active) or 1
    trust = round(sum(active[k] * weights[k] for k in active) / wsum)

    critical_content = evidence.get("malicious_findings", 0) > 0 and subs.get("content_safety", 100) < 50
    is_scam = (not reachable) or critical_content or (trust < 30)
    if trust >= 80:
        level = "low"
    elif trust >= 60:
        level = "medium"
    elif trust >= 35:
        level = "high"
    else:
        level = "critical"

    bits = []
    bits.append("reachable" if reachable else "UNREACHABLE")
    bits.append("HTTPS" if https else "no-HTTPS")
    bits.append(f"{evidence.get('malicious_findings', 0)} malicious pattern(s)")
    if req.check_x402:
        bits.append("valid x402 challenge" if x402_info["valid_challenge"]
                    else ("x402 402 but malformed" if x402_info["is_x402"] else "not an x402 endpoint"))
    verdict = ", ".join(bits) + "."

    return {
        "url": final_url,
        "trust_score": trust,
        "risk_level": level,
        "is_scam": is_scam,
        "verdict": verdict,
        "sub_scores": active,
        "x402": x402_info if req.check_x402 else None,
        "evidence": evidence,
        "scored_at": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/headers")
async def security_headers(req: HeadersRequest):
    if not req.url or not req.url.startswith(("http://", "https://")):
        raise HTTPException(400, "valid http/https URL required")
    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client:
            resp = await _safe_get(client, req.url, ua="skill-audit/2.1 (+security-headers)")
    except Exception as e:
        raise HTTPException(502, f"fetch failed: {type(e).__name__}")

    hdrs = {k.lower(): v for k, v in resp.headers.items()}
    present, missing, score = [], [], 0
    for h, w in _SEC_HEADERS.items():
        if h in hdrs:
            present.append(h)
            score += w
        else:
            missing.append(h)
    grade = ("A" if score >= 90 else "B" if score >= 70 else "C" if score >= 50
             else "D" if score >= 25 else "F")
    return {
        "url": str(resp.url),
        "status": resp.status_code,
        "score": score,
        "grade": grade,
        "present": present,
        "missing": missing,
        "headers": {h: hdrs[h] for h in present},
        "server": hdrs.get("server"),
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/dns")
async def dns_lookup(req: DnsRequest):
    domain = (req.domain or "").strip()
    if domain.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        domain = urlparse(domain).hostname or domain
    domain = domain.rstrip(".").lower()
    if not domain or "." not in domain or " " in domain:
        raise HTTPException(400, "valid domain required")

    import httpx
    types = ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]
    records = {}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            for rt in types:
                r = await client.get(
                    "https://cloudflare-dns.com/dns-query",
                    params={"name": domain, "type": rt},
                    headers={"accept": "application/dns-json"},
                )
                ans = r.json().get("Answer", []) if r.status_code == 200 else []
                vals = [a["data"].strip('"') for a in ans if a.get("type") is not None]
                records[rt] = vals
    except Exception as e:
        raise HTTPException(502, f"dns query failed: {type(e).__name__}")

    txt = " ".join(records.get("TXT", []))
    flags = {
        "has_a": bool(records.get("A") or records.get("AAAA")),
        "has_mx": bool(records.get("MX")),
        "has_spf": "v=spf1" in txt.lower(),
        "has_dmarc": False,  # filled below
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://cloudflare-dns.com/dns-query",
                                  params={"name": f"_dmarc.{domain}", "type": "TXT"},
                                  headers={"accept": "application/dns-json"})
            dmarc = " ".join(a["data"].strip('"') for a in r.json().get("Answer", [])) if r.status_code == 200 else ""
            flags["has_dmarc"] = "v=dmarc1" in dmarc.lower()
    except Exception:
        pass

    return {
        "domain": domain,
        "records": records,
        "flags": flags,
        "resolved_at": datetime.utcnow().isoformat() + "Z",
    }


# Text-ish files worth scanning inside a repo tarball; everything else is skipped.
_SCAN_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".sh", ".bash", ".zsh",
    ".rb", ".go", ".rs", ".php", ".pl", ".ps1", ".md", ".txt", ".json", ".yaml",
    ".yml", ".toml", ".cfg", ".ini", ".env", ".sql", ".java", ".c", ".cpp", ".h",
}

# Tests, docs and changelogs quote attack strings on purpose, so scanning them
# buries the real signal (psf/requests scored 100/high entirely on test fixtures).
_NOISE_DIRS = ("test/", "tests/", "docs/", "doc/", "examples/", "example/",
               "fixtures/", "testdata/", "spec/", "__tests__/", "benchmarks/")
_NOISE_NAMES = ("changelog", "history", "news", "releases", "release-notes")


def _is_noise(path: str) -> bool:
    low = path.lower()
    if any(seg in low for seg in _NOISE_DIRS) or low.startswith(_NOISE_DIRS):
        return True
    base = low.rsplit("/", 1)[-1]
    if base.startswith("test_") or base.startswith("test.") or "_test." in base or ".spec." in base:
        return True
    return any(base.startswith(n) for n in _NOISE_NAMES)


_LEVEL_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "SAFE": 0, "UNKNOWN": 0}
# The three entry points that actually exist on a live MCP-server repo. Probed concurrently
# first, so a delisted repo costs three parallel requests rather than fourteen serial 404s.
_REG_PROBE = ("package.json", "README.md", "src/index.ts")


async def _reg_fetch(client, owner, name, path):
    """One raw.githubusercontent read; returns the body or None. Never raises."""
    try:
        r = await client.get(f"https://raw.githubusercontent.com/{owner}/{name}/HEAD/{path}")
    except Exception:  # noqa: BLE001
        return None
    return r.text if r.status_code == 200 and len(r.text) >= 40 else None


_REG_CANDIDATES = ("package.json", "setup.py", "pyproject.toml", "install.sh",
                   "postinstall.js", "src/index.ts", "index.ts", "src/index.js", "index.js",
                   "server.py", "src/main.py", "main.py", "app.py", "README.md")


@app.post("/audit/registry")
async def audit_registry(req: RegistryAuditRequest):
    """Scan the newest servers in the official MCP registry. No input required.

    See RegistryAuditRequest for why this exists: every route that needs an argument from the
    caller converts ~25x worse than one that can be called blind, because the buyers are
    crawlers. This gives a blind caller a real answer — a fresh supply-chain risk feed over
    servers somebody just published — using the same pattern engine as /audit.
    """
    import asyncio
    from datetime import timedelta, timezone

    import httpx
    n = max(1, min(int(req.limit or 5), 15))
    # ⚠ `sort=newest` is accepted and SILENTLY IGNORED — it returns the same alphabetical
    # first page. `updated_since` genuinely filters, so recency comes from that. Without it
    # the first page is dominated by long-dead entries: a plain limit=5 scan returned four
    # UNKNOWNs out of five, which is not worth $0.005 to anybody.
    since = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient(follow_redirects=True, timeout=25.0,
                                 headers={"User-Agent": "x402-registry-audit"}) as client:
        try:
            r = await client.get("https://registry.modelcontextprotocol.io/v0/servers",
                                 params={"limit": 100, "updated_since": since})
            servers = (r.json() or {}).get("servers", [])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"registry unreachable: {type(e).__name__}") from None

        seen, targets = set(), []
        for entry in servers:
            srv = entry.get("server", entry)
            official = (entry.get("_meta") or {}).get(
                "io.modelcontextprotocol.registry/official") or {}
            if official.get("status") not in (None, "active"):
                continue
            url = ((srv.get("repository") or {}).get("url") or "")
            if "github.com/" not in url:
                continue
            parts = [p for p in url.split("github.com/", 1)[1].split("/") if p][:2]
            if len(parts) != 2:
                continue
            key = (parts[0].lower(), parts[1].removesuffix(".git").lower())
            if key in seen:
                continue
            seen.add(key)
            targets.append((parts[0], parts[1].removesuffix(".git"), srv.get("name", ""),
                            official.get("publishedAt")))
            # Over-fetch: roughly half the registry's repos are 404 (measured), and a buyer
            # paying per call wants N READABLE rows, not N rows of "gone".
            if len(targets) >= n * 4:
                break

        rows, delisted = [], 0
        for owner, name, sname, published in targets:
            if len(rows) >= n:
                break
            worst, score, findings, files = "SAFE", 0, [], []

            def _absorb(path, text):
                nonlocal worst, score
                files.append(path)
                res = scan(text[:200_000])
                score = max(score, res.get("risk_score") or 0)
                for f in res.get("findings", []):
                    findings.append({**f, "file": path})
                if _LEVEL_ORDER.get(res["risk_level"], 0) > _LEVEL_ORDER.get(worst, 0):
                    worst = res["risk_level"]

            # About half of these repos are 404. Walking all 14 candidates on a dead one costs
            # 14 round trips and dominated the call — five results took 37s. Probe the three
            # most common entry points CONCURRENTLY and abandon the repo if none answers:
            # a dead repo now costs 3 parallel requests instead of 14 serial ones.
            probed = await asyncio.gather(*[_reg_fetch(client, owner, name, p)
                                            for p in _REG_PROBE])
            alive = [(p, t) for p, t in zip(_REG_PROBE, probed) if t]
            if not alive:
                # "we could not read it" is never "it is safe" — but it is also not worth a
                # paid row. Counted, named, and skipped so the buyer gets N real answers.
                delisted += 1
                continue
            for path, text in alive:
                _absorb(path, text)
            for path in _REG_CANDIDATES:
                if len(files) >= 4:      # budget: 4 files a repo keeps the call responsive
                    break
                if path in _REG_PROBE:
                    continue
                text = await _reg_fetch(client, owner, name, path)
                if text:
                    _absorb(path, text)
            rows.append({
                "server": sname, "repo": f"{owner}/{name}",
                "repo_url": f"https://github.com/{owner}/{name}",
                "published_at": published,
                "risk_level": worst, "risk_score": score,
                "finding_count": len(findings),
                "files_scanned": files,
                "top_finding": (max(findings, key=lambda f: _LEVEL_ORDER.get(f["severity"], 0))
                                if findings else None),
            })

    rows.sort(key=lambda r: -_LEVEL_ORDER.get(r["risk_level"], 0))
    return {
        "source": "registry.modelcontextprotocol.io/v0/servers",
        "window": f"servers updated since {since}",
        "scanned": len(rows),
        "flagged": sum(1 for r in rows if r["risk_level"] != "SAFE"),
        # Not padding, and not hidden: about half the registry's repositories 404, and how many
        # were skipped to reach N readable ones is itself a fact about the registry.
        "delisted_skipped": delisted,
        "results": rows,
    }


@app.post("/audit/repo")
async def audit_repo(req: RepoAuditRequest):
    slug = (req.repo or "").strip()
    if slug.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        slug = urlparse(slug).path.strip("/")
    slug = slug.removesuffix(".git")
    parts = [p for p in slug.split("/") if p]
    if len(parts) != 2:
        raise HTTPException(400, "repo must be 'owner/name' or a github.com repo URL")
    owner, name = parts

    import httpx
    refs = [req.ref] if req.ref else ["HEAD", "main", "master"]
    raw = used_ref = None
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
        for ref in refs:
            url = f"https://codeload.github.com/{owner}/{name}/tar.gz/{ref}"
            try:
                resp = await client.get(url, headers={"User-Agent": "skill-audit/2.1"})
            except Exception as e:
                raise HTTPException(502, f"fetch failed: {type(e).__name__}")
            if resp.status_code == 200:
                raw, used_ref = resp.content, ref
                break
    if raw is None:
        raise HTTPException(404, f"could not download {owner}/{name} (private, missing, or bad ref)")
    if len(raw) > 60_000_000:
        raise HTTPException(413, "repo tarball too large (max 60MB)")

    import io, tarfile
    flagged, scanned, skipped, worst, findings_total, noise_skipped = [], 0, 0, 0, 0, 0
    try:
        tar = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
    except Exception as e:
        raise HTTPException(422, f"could not open tarball: {type(e).__name__}")

    for member in tar:
        if not member.isfile() or member.size > 1_000_000:
            skipped += 1
            continue
        path = member.name.split("/", 1)[-1]  # strip the '{name}-{ref}/' prefix
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
        if ext not in _SCAN_EXT:
            skipped += 1
            continue
        if not req.include_tests and _is_noise(path):
            noise_skipped += 1
            continue
        if scanned >= 1500:
            skipped += 1
            continue
        try:
            data = tar.extractfile(member).read().decode("utf-8", "replace")
        except Exception:
            skipped += 1
            continue
        scanned += 1
        result = scan(data)
        if result["total_findings"]:
            findings_total += result["total_findings"]
            worst = max(worst, result["risk_score"])
            flagged.append({
                "file": path,
                "risk_score": result["risk_score"],
                "risk_level": result["risk_level"],
                "total_findings": result["total_findings"],
                "findings": result["findings"][:10],
            })
    tar.close()

    flagged.sort(key=lambda f: -f["risk_score"])
    level = "clean" if worst == 0 else ("low" if worst < 30 else ("medium" if worst < 60 else "high"))
    return {
        "repo": f"{owner}/{name}",
        "ref": used_ref,
        "files_scanned": scanned,
        "files_skipped": skipped,
        "test_doc_files_excluded": noise_skipped,
        "note": ("tests/docs/changelogs excluded (they quote attack strings deliberately); "
                 "pass include_tests=true to scan them"),
        "risk_score": worst,
        "risk_level": level,
        "total_findings": findings_total,
        "flagged_files": flagged[:50],
        "scanned_at": datetime.utcnow().isoformat() + "Z",
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET on a paid route: advertise the price instead of 405
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Measured on tokenguard's access log 2026-07-29: 22% of all traffic was a GET or
# HEAD on a paid POST path answered with `{"detail":"Method Not Allowed"}`, which
# tells a probing agent nothing about price, payTo or x402 support. Runs LAST so it
# sees every route, and outside the x402 init block so it can never disable payments.
if _x402_available:
    try:
        import x402_get_challenge as _getadv
        _getadv.install(app, routes)
    except Exception as _e:  # pragma: no cover
        print(f"  x402 GET-advertise unavailable: {type(_e).__name__}: {_e}")

    # Same gap as contract-guard: the 402 body is `{}` and the challenge lives only in the
    # header, so a body-reading client sees nothing to buy. Added LAST so it wraps the
    # payment middleware and sees the final response.
    try:
        import x402_402_body as _fillbody
        _fillbody.install(app)
    except Exception as _e:  # pragma: no cover
        print(f"  x402 GET-advertise unavailable: {type(_e).__name__}: {_e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8402))
    print(f"\n  skill-audit API (x402 v2) starting on :{port}")
    print(f"  x402: {'ENABLED' if _x402_available else 'DISABLED (pip install x402[fastapi,evm,extensions])'}")
    print(f"  Facilitator: {FACILITATOR_URL}")
    print(f"  Wallet: {WALLET}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
