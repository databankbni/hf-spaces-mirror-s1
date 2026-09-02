#!/usr/bin/env python3
"""HTTP smoke test for the v2 demo stack. Run while uvicorn is on :8000."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
TENANT = "demo-smoke"
PASSWORD = "demo-smoke-pass"


def req(
    method: str, path: str, *, body: dict | None = None, token: str | None = None
) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main() -> int:
    print("1. Health")
    code, raw = req("GET", "/health")
    if code != 200:
        print(f"   FAIL health {code}: {raw[:200]}")
        return 1
    health = json.loads(raw)
    print(
        f"   OK status={health.get('status')} reference={health.get('reference_faiss_count')}"
    )

    print("2. UI")
    code, _ = req("GET", "/v2.html")
    if code != 200:
        print(f"   FAIL v2.html {code}")
        return 1
    print("   OK /v2.html served")

    print("3. Register / login")
    code, raw = req(
        "POST", "/auth/register", body={"tenant_id": TENANT, "password": PASSWORD}
    )
    if code not in (201, 409):
        print(f"   FAIL register {code}: {raw[:200]}")
        return 1
    code, raw = req(
        "POST", "/auth/login", body={"tenant_id": TENANT, "password": PASSWORD}
    )
    if code != 200:
        print(f"   FAIL login {code}: {raw[:200]}")
        return 1
    token = json.loads(raw)["access_token"]
    print("   OK JWT received")

    print("4. Auth me")
    code, raw = req("GET", "/auth/me", token=token)
    if code != 200 or json.loads(raw).get("tenant_id") != TENANT:
        print(f"   FAIL /auth/me {code}")
        return 1
    print("   OK")

    print("5. Schema")
    code, raw = req("GET", "/api/schema", token=token)
    if code != 200:
        print(f"   FAIL schema {code}: {raw[:200]}")
        return 1
    sections = json.loads(raw).get("sections") or []
    print(f"   OK {len(sections)} sections")

    print("6. Reference status")
    code, raw = req("GET", "/api/upload/reference/status", token=token)
    ref = json.loads(raw)
    if code != 200:
        print(f"   FAIL reference status {code}")
        return 1
    print(
        f"   OK chunks={ref.get('reference_chunk_count')} ready={ref.get('ready_for_generation')}"
    )

    if not ref.get("ready_for_generation"):
        print("   SKIP preview — no reference docs (upload past reports for full test)")
        return 0

    print("7. Preview")
    payload = {
        "raw_notes": "E2: roof tile slipped on south slope",
        "property_type": "semi-detached house",
        "tenure": "freehold",
        "interference_level": "minimum",
    }
    code, raw = req("POST", "/api/report/preview", body=payload, token=token)
    if code != 200:
        print(f"   FAIL preview {code}: {raw[:300]}")
        return 1
    preview = json.loads(raw)
    print(
        f"   OK mapped={preview.get('sections_mapped')} review={preview.get('sections_needing_review')}"
    )

    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
