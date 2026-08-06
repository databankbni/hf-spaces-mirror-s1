#!/usr/bin/env python3
"""Example only: seed a hot-match pool manually or from your keepalive job.

This does NOT scrape Titan007 hot list. Phase 1 uses externally supplied hot pool
because the exported hot/crow path depends on Playwright and is not migrated.
"""
import argparse, json, requests, os

ap = argparse.ArgumentParser()
ap.add_argument("--base-url", required=True)
ap.add_argument("--api-key", default=os.getenv("HF_DATA_HUB_API_KEY"))
ap.add_argument("--date", required=True)
ap.add_argument("--input-json", required=True, help="JSON file with {'date':..., 'matches':[...]} or list of matches")
args = ap.parse_args()

data = json.load(open(args.input_json, "r", encoding="utf-8"))
if isinstance(data, list):
    data = {"date": args.date, "source": "manual_seed", "matches": data}
data["date"] = args.date
headers = {"X-API-Key": args.api_key} if args.api_key else {}
r = requests.post(args.base_url.rstrip()+"/hot-matches", json=data, headers=headers, timeout=60)
print(r.status_code, r.text)
