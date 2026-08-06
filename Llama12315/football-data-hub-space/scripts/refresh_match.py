#!/usr/bin/env python3
from hf_football_data_hub.packet_builder import build_match_packet
import argparse, json

ap = argparse.ArgumentParser()
ap.add_argument("--match-id", required=True)
ap.add_argument("--date")
ap.add_argument("--company-ids")
args = ap.parse_args()
packet = build_match_packet(args.match_id, day=args.date, company_ids=args.company_ids, save=True)
print(json.dumps({"ok": True, "packet_meta": packet.get("packet_meta"), "recommendation_allowed": packet.get("recommendation_allowed")}, ensure_ascii=False, indent=2))
