#!/usr/bin/env python3
"""Put the x402 challenge in the 402 response BODY as well as the header.

WHY THIS EXISTS (measured 2026-08-05)
-------------------------------------
Every paid POST route we serve answers 402 with `payment-required: <base64 JSON>` and a body
of exactly `{}` — 2 bytes. That is legal x402 v2: the spec says the client reads the header.

But it locks out every client that reads the body, and that is not a hypothetical shape — it
is *our own* client. Running `scripts/x402_pay.py` against contract-guard's busiest route:

    [1] unpaid -> HTTP 402
      no accepts in 402

Our own payer could not buy from our own endpoint. A v1-era client, a browser, a human with
curl, or any agent that inspects JSON before headers sees `{}` and concludes there is nothing
to buy. Against a route drawing thousands of 402s in a minute, that is the difference between
being discovered and being purchasable.

`x402_get_challenge.py` already made this call for GET, and for the same reason. This closes
the same gap on POST, which is the path payment actually happens on.

WHAT THIS DOES
--------------
An ASGI wrapper that, when a response is 402 with an empty JSON body and a
`payment-required` header, replaces the body with the decoded header contents. Nothing else
is touched: same status, same headers, same challenge. It is purely additive — a v2 client
still reads the header and never looks at the body.

SAFETY
------
Install it OUTSIDE the payment middleware so it sees the final response. It never raises: any
failure to decode leaves the original response untouched, so the worst case is the `{}` we
already send. It only ever rewrites a 402 — a 200 (the paid answer) is passed through
byte-for-byte, so it can never leak a paid response or alter one.

    python scripts/x402_402_body.py --selftest
"""

from __future__ import annotations

import base64
import json
import sys


class Fill402Body:
    """ASGI middleware: fill an empty 402 body from the payment-required header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        held = {}

        async def send_wrapper(message):
            mt = message.get("type")

            if mt == "http.response.start":
                if message.get("status") == 402:
                    held["start"] = message  # hold it: content-length may need rewriting
                    return
                return await send(message)

            if mt == "http.response.body" and held.get("start"):
                start = held.pop("start")
                body = message.get("body", b"") or b""
                # Only touch a complete, empty JSON body. A streamed or already-populated
                # 402 is left exactly as it is.
                if not message.get("more_body") and body.strip() in (b"", b"{}"):
                    filled = self._decode(start.get("headers") or [])
                    if filled is not None:
                        body = filled
                        headers = [(k, v) for k, v in (start.get("headers") or [])
                                   if k.lower() not in (b"content-length", b"content-type")]
                        headers.append((b"content-length", str(len(body)).encode()))
                        headers.append((b"content-type", b"application/json"))
                        start = dict(start, headers=headers)
                await send(start)
                return await send({"type": "http.response.body", "body": body})

            return await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _decode(headers):
        """Return the challenge JSON bytes from the payment-required header, or None."""
        try:
            for k, v in headers:
                if k.lower() == b"payment-required":
                    raw = base64.b64decode(v)
                    json.loads(raw)  # must be valid JSON or we leave the response alone
                    return raw
        except Exception:  # noqa: BLE001 - a malformed header must not break the 402
            return None
        return None


def install(app, log=print) -> bool:
    """Wrap `app` so empty 402 bodies get filled. Never raises."""
    try:
        app.add_middleware(Fill402Body)
        log("  x402: 402 responses now carry the challenge in the body as well as the header")
        return True
    except Exception as e:  # pragma: no cover
        log(f"  x402 402-body fill unavailable (paywall unaffected): {type(e).__name__}: {e}")
        return False


# --------------------------------------------------------------------------- selftest


async def _selftest() -> int:
    """Drive the middleware over a fake 402 app, with no server and no network."""
    challenge = {"x402Version": 2, "accepts": [{"scheme": "exact", "amount": "5000",
                                                "payTo": "0x5bCDA", "network": "eip155:8453"}]}
    blob = base64.b64encode(json.dumps(challenge).encode())

    async def fake_app(scope, receive, send):
        if scope["path"] == "/paid":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"result":"ok"}'})
            return
        await send({"type": "http.response.start", "status": 402,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", b"2"),
                                (b"payment-required", blob)]})
        await send({"type": "http.response.body", "body": b"{}"})

    wrapped = Fill402Body(fake_app)
    failures = 0

    async def drive(path):
        out = {}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
                out["headers"] = {k.lower(): v for k, v in msg["headers"]}
            else:
                out["body"] = out.get("body", b"") + msg.get("body", b"")

        async def receive():
            return {"type": "http.request", "body": b""}

        await wrapped({"type": "http", "path": path}, receive, send)
        return out

    print("[1/3] empty 402 body gets filled from the header")
    r = await drive("/check")
    ok = r["status"] == 402 and json.loads(r["body"]) == challenge
    print(f"   {'ok  ' if ok else 'FAIL'} status={r['status']} body={r['body'][:60]!r}")
    failures += 0 if ok else 1

    print("[2/3] content-length is corrected, header still present")
    cl = int(r["headers"].get(b"content-length", b"0"))
    ok = cl == len(r["body"]) and b"payment-required" in r["headers"]
    print(f"   {'ok  ' if ok else 'FAIL'} content-length={cl} actual={len(r['body'])} "
          f"header_kept={b'payment-required' in r['headers']}")
    failures += 0 if ok else 1

    print("[3/3] a paid 200 response is passed through untouched")
    r2 = await drive("/paid")
    ok = r2["status"] == 200 and r2["body"] == b'{"result":"ok"}'
    print(f"   {'ok  ' if ok else 'FAIL'} status={r2['status']} body={r2['body']!r}")
    failures += 0 if ok else 1

    print(f"\nSELFTEST {'PASS' if failures == 0 else f'FAIL ({failures})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    import asyncio
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if "--selftest" in sys.argv:
        sys.exit(asyncio.run(_selftest()))
    print(__doc__)
