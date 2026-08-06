#!/usr/bin/env python3
"""Answer GET on a paid POST route with the x402 challenge instead of 405.

WHY THIS EXISTS (measured 2026-07-29, tokenguard access log, 10h window)
-----------------------------------------------------------------------
  402 (POST, paywall shown) ...... 7,254
  405 (GET/HEAD, "Method Not Allowed") 2,174   <-- 22% of all traffic
  200 (GET, discovery docs) .......... 508
  200 (POST, actually paid) .............. 1

The 405s are not junk. Two of the busiest clients GET a route first and only
then POST it (167.233.212.44: 514 GET + 514 POST; 149.28.91.153: 213 + 213) —
GET-then-POST is a real x402 client probe pattern. The clients that only ever
GET are the ones we lose: 13.140.139.31 issued 435 GETs, received 435x
`{"detail":"Method Not Allowed"}`, and never came back. Roughly a thousand
requests per 10h fall in that bucket.

`{"detail":"Method Not Allowed"}` carries no price, no payTo, no x402 version
and no hint that a payment would have been accepted — an indexer or agent
probing this way concludes the path is not a purchasable resource. That is a
plausible mechanical cause of our headline number: 127 unique payers who each
called exactly 1.1 times. We are discovered constantly and then dismissed.

WHAT THIS DOES
--------------
For every path that is paywalled for POST and has no GET handler of its own,
register a GET that returns the SAME 402 challenge the POST returns — the
`payment-required` header (base64 JSON, x402 v2) plus, unlike the POST, a
readable JSON body carrying the same object. The POST path is not touched.

Two deliberate differences from the SDK's POST 402:
  * the body is populated. The SDK answers POST with `{}` because a v2 client
    reads the header; a v1-era client, a browser, or a human reads the body and
    would otherwise still learn nothing.
  * `accepts[].method` and a `hint` state that payment must be presented on a
    POST, so nothing here can be mistaken for a purchasable GET.

SAFETY
------
The amount is derived from the same RouteConfig the middleware compiled, so the
advertised price cannot drift from the enforced one. Nothing here mutates the
paywall: it only adds GET handlers, and the payment middleware keys on
"POST <path>", so these responses never pass through it. Callers must install
this OUTSIDE the x402 try/except — an exception raised while poking SDK objects
inside that block silently serves every paid route for free.
"""
from __future__ import annotations

import base64
import json
from typing import Any

# Imported at MODULE level on purpose. FastAPI resolves a handler's annotations against
# the module globals of the function that defines it, so a `Request` imported inside
# install() is invisible there and `request` gets treated as a required query parameter —
# every advertisement then answers 422 instead of 402. Guarded so importing this module
# can never be what breaks a build.
try:
    from fastapi import Request as _Request
    from fastapi.responses import JSONResponse as _JSONResponse
    from fastapi.routing import APIRoute as _APIRoute
    _FASTAPI_OK = True
except Exception:  # pragma: no cover
    _Request = _JSONResponse = _APIRoute = None
    _FASTAPI_OK = False

# USDC per CAIP-2 network. Used only to fill the `asset` field of the advertised
# challenge; the enforced one comes from the SDK.
_ASSET = {
    "eip155:8453": ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "USD Coin", "2"),
    "eip155:84532": ("0x036CbD53842c5426634e7929541eC2318f3dCF7e", "USDC", "2"),
}
_DEFAULT_ASSET = _ASSET["eip155:8453"]


def _amount(price: Any) -> str:
    """'$0.02' -> '20000' (USDC, 6 decimals). Ints/strings of raw units pass through."""
    if price is None:
        return "0"
    s = str(price).strip()
    if s.startswith("$"):
        return str(int(round(float(s[1:]) * 1_000_000)))
    if s.replace("_", "").isdigit():
        return s.replace("_", "")
    try:
        return str(int(round(float(s) * 1_000_000)))
    except ValueError:
        return "0"


def _accepts_of(cfg: Any) -> list[dict]:
    out = []
    for opt in (getattr(cfg, "accepts", None) or []):
        network = getattr(opt, "network", None) or "eip155:8453"
        asset, name, version = _ASSET.get(network, _DEFAULT_ASSET)
        out.append({
            "scheme": getattr(opt, "scheme", "exact"),
            "network": network,
            "asset": asset,
            "amount": _amount(getattr(opt, "price", None)),
            "payTo": getattr(opt, "pay_to", None),
            "maxTimeoutSeconds": 300,
            "extra": {"name": name, "version": version},
            # Not part of the v2 accept object, but harmless to carry and it is the
            # single fact a GET-probing client is missing.
            "method": "POST",
        })
    return out


def _challenge(url: str, cfg: Any) -> dict:
    body = {
        "x402Version": 2,
        "error": "Payment required",
        "resource": {
            "url": url,
            "description": getattr(cfg, "description", "") or "",
            "mimeType": getattr(cfg, "mime_type", None) or "application/json",
            "serviceName": getattr(cfg, "service_name", None),
            "tags": list(getattr(cfg, "tags", None) or []),
        },
        "accepts": _accepts_of(cfg),
        "hint": "This resource is purchasable. Send the same request as POST with an "
                "X-PAYMENT header built from `accepts`; GET only advertises the price.",
    }
    ext = getattr(cfg, "extensions", None)
    if ext:
        body["extensions"] = ext if isinstance(ext, dict) else getattr(ext, "__dict__", {}) or {}
    return body


def install(app, routes: dict, *, log=print) -> int:
    """Add a GET 402-advertisement for every paywalled POST path lacking a GET.

    Returns the number of paths wired. Never raises: a failure here must not be
    able to affect the paywall.
    """
    if not _FASTAPI_OK:  # pragma: no cover
        log("  x402 GET-advertise skipped: fastapi unavailable")
        return 0

    try:
        taken = {
            r.path for r in app.routes
            if isinstance(r, _APIRoute) and ({"GET"} & (r.methods or set()))
        }
        paid = {k.split(" ", 1)[1]: v for k, v in routes.items() if k.startswith("POST ")}

        def _make(path: str, cfg: Any):
            async def advertise(request: _Request):
                # Rebuild the resource URL from the live request so it matches what the
                # SDK advertises on POST (HF terminates TLS at its proxy -> uvicorn is
                # started with --proxy-headers, so request.url is already https there).
                url = str(request.url).split("?")[0]
                doc = _challenge(url, cfg)
                blob = base64.b64encode(
                    json.dumps(doc, separators=(",", ":")).encode()
                ).decode()
                return _JSONResponse(
                    doc, status_code=402,
                    headers={"payment-required": blob, "allow": "POST"},
                )
            advertise.__name__ = f"advertise_{path.strip('/').replace('/', '_') or 'root'}"
            return advertise

        n = 0
        for path, cfg in paid.items():
            if path in taken:
                continue
            # HEAD is listed explicitly: Starlette matches methods strictly and does not
            # synthesise HEAD from GET here, and the log carried 50 HEAD probes per 10h.
            app.add_api_route(
                path, _make(path, cfg), methods=["GET", "HEAD"], include_in_schema=False,
                summary=f"x402 price advertisement for POST {path}",
            )
            n += 1
        log(f"  x402: {n} paid paths now answer GET with a 402 challenge (was 405)")
        return n
    except Exception as e:  # pragma: no cover
        log(f"  x402 GET-advertise FAILED (paywall unaffected): {type(e).__name__}: {e}")
        return 0
