#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hermes client for HF Football Data Hub Phase 1.

Usage:
  python3 hermes_hf_client.py health --base-url https://xxx.hf.space
  python3 hermes_hf_client.py match-packet --base-url https://xxx.hf.space --match-id 2929650
  python3 hermes_hf_client.py refresh --base-url https://xxx.hf.space --match-id 2929650

Auth:
  For private spaces, set HF_DATA_HUB_TOKEN env var or pass --token.
  Token is sent as: Authorization: Bearer <token>
  Write endpoints also need X-API-Key (set via --api-key or HF_DATA_HUB_API_KEY env var).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests


def _print(obj: Any):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def request_json(method: str, url: str, api_key: str | None = None, bearer_token: str | None = None, **kwargs):
    headers = kwargs.pop("headers", {})
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        r = requests.request(method, url, headers=headers, timeout=120, **kwargs)
    except requests.exceptions.ConnectionError as e:
        return {"ok": False, "error": "connection_failed", "detail": str(e)[:200]}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "timeout"}
    try:
        data = r.json()
    except Exception:
        data = {"raw_text": r.text[:2000]}
    if r.status_code >= 400:
        return {"ok": False, "status_code": r.status_code, "response": data}
    return data


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--base-url", required=True, help="HF Space base URL")
        p.add_argument("--api-key", default=os.getenv("HF_DATA_HUB_API_KEY"))
        p.add_argument("--token", default=os.getenv("HF_DATA_HUB_TOKEN"), help="Bearer token for private Space auth")

    p = sub.add_parser("health")
    common(p)

    p = sub.add_parser("hot-matches")
    common(p)
    p.add_argument("--date")

    p = sub.add_parser("match-packet")
    common(p)
    p.add_argument("--match-id", required=True)
    p.add_argument("--date")

    p = sub.add_parser("refresh")
    common(p)
    p.add_argument("--match-id", required=True)
    p.add_argument("--date")
    p.add_argument("--company-ids", default=os.getenv("DEFAULT_COMPANY_IDS", "3,24,8"))

    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    if args.cmd == "health":
        _print(request_json("GET", f"{base}/health", api_key=args.api_key, bearer_token=args.token))
    elif args.cmd == "hot-matches":
        params = {"date_": args.date} if args.date else {}
        _print(request_json("GET", f"{base}/hot-matches", api_key=args.api_key, bearer_token=args.token, params=params))
    elif args.cmd == "match-packet":
        params = {"match_id": args.match_id}
        if args.date:
            params["date_"] = args.date
        data = request_json("GET", f"{base}/match-packet", api_key=args.api_key, bearer_token=args.token, params=params)
        # Enrich with semantic field analysis
        if data.get("ok"):
            p = data.get("packet", {})
            usage = p.get("packet_usage", {})
            boundary = p.get("hf_decision_boundary", {})
            data["_hermes_analysis"] = {
                "usable_for_analysis": usage.get("usable_for_hermes_analysis", False),
                "block_reason": usage.get("block_reason"),
                "hf_final_pick_allowed": boundary.get("hf_final_pick_allowed", False),
                "hermes_local_decision_required": boundary.get("hermes_local_decision_required", True),
                "note": "usable_for_hermes_analysis determines if Hermes can analyze; hf_final_pick_allowed=false is NOT a block",
            }
        _print(data)
    elif args.cmd == "refresh":
        payload = {"match_id": args.match_id, "date": args.date, "company_ids": args.company_ids}
        _print(request_json("POST", f"{base}/refresh-match", api_key=args.api_key, bearer_token=args.token, json=payload))


if __name__ == "__main__":
    main()
