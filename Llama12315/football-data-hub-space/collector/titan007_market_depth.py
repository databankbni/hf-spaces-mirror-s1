#!/usr/bin/env python3
"""Capture Crown main and adjacent Titan007 AH/OU board evidence.

A change-detail history is not adjacent-line evidence. This collector requires the
main board pages and preserves Crown's own main-plus-adjacent board only. Other
companies' adjacent rows must never be mislabelled as Crown evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import titan007_relay_transport as relay_transport
from html.parser import HTMLParser

ROOT = Path(os.getenv('HF_COLLECTOR_ROOT') or Path(__file__).resolve().parents[1])
SNAPSHOTS = ROOT / "market_depth_snapshots"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://vip.titan007.com/", "Accept-Language": "zh-CN,zh;q=0.9"}
ATTEMPTS = 3
PAGES = {"AH": "AsianOdds_n.aspx", "OU": "OverDown_n.aspx"}


def atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(raw)
    temp.replace(path)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def fetch(url: str) -> tuple[bytes, int]:
    """Direct egress first, read-only relay fallback (see titan007_relay_transport)."""
    return relay_transport.fetch(url, HEADERS, timeout=30, attempts=ATTEMPTS)


def decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        elif tag in ("td", "th") and self.row is not None: self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

def compact_lines(text: str, market: str) -> list[dict]:
    parser = Rows()
    parser.feed(text)
    rows = []
    crown_seen = False
    for row in parser.rows:
        if len(row) < 9:
            continue
        company = row[1] if len(row) > 1 else ""
        multi = row[2] if len(row) > 2 else ""
        is_crown = company in ("Crow*", "皇冠")
        if is_crown:
            crown_seen = True
        elif company:
            crown_seen = False
            continue
        elif not (crown_seen and multi in ("盘2", "盤2", "盘3", "盤3", "盘4", "盤4")):
            continue
        try:
            rows.append({
                "company": company or "Crow*",
                "depth": multi or "main",
                "opening_water": float(row[3]),
                "opening_line": row[4],
                "opening_opponent_water": float(row[5]),
                "current_water": float(row[6]),
                "current_line": row[7],
                "current_opponent_water": float(row[8]),
            })
        except (ValueError, IndexError):
            continue
    return rows[:16]

def summary(text: str, market: str) -> dict:
    company_markers = ("Crow", "皇冠", "Pinnacle", "Bet365", "William")
    lines = compact_lines(text, market)
    adjacent = [line for line in lines if line["depth"] in ("盘2", "盤2", "盘3", "盤3", "盘4", "盤4")]
    return {
        "market": market,
        "crow_present": "Crow" in text or "皇冠" in text,
        "company_marker_count": sum(1 for marker in company_markers if marker.lower() in text.lower()),
        "adjacent_line_count": len(adjacent),
        "adjacent_lines_present": bool(adjacent),
        "crown_lines": lines,
    }


def depth_readiness(records: list[dict]) -> dict:
    """Allow exact Crown main-line analysis when adjacent boards are not offered."""
    markets = {record.get("market"): record for record in records}
    required = [markets.get("AH", {}), markets.get("OU", {})]
    main_ready = all(
        record.get("ok")
        and record.get("crow_present")
        and any(line.get("depth") == "main" for line in record.get("crown_lines", []))
        for record in required
    )
    adjacent_available = all(record.get("adjacent_lines_present") for record in required)
    return {
        "directional_eligible": main_ready,
        "adjacent_lines_available": adjacent_available,
        "candidate_scope": "main_plus_adjacent" if adjacent_available else "exact_main_only",
    }


def capture(match_id: str) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    records = []
    for market, page in PAGES.items():
        url = f"https://vip.titan007.com/{page}?id={match_id}"
        try:
            raw, attempts = fetch(url)
            digest = hashlib.sha256(raw).hexdigest()
            raw_path = SNAPSHOTS / str(match_id) / "raw" / f"{stamp}_{market}_{digest[:12]}.html"
            atomic(raw_path, raw)
            records.append({"ok": True, "url": url, "attempts": attempts, "raw_sha256": digest, "raw_path": str(raw_path), **summary(decode(raw), market)})
        except Exception as exc:
            records.append({"ok": False, "market": market, "url": url, "attempts": ATTEMPTS, "error": f"{type(exc).__name__}:{str(exc)[:180]}", "adjacent_lines_present": False})
    readiness = depth_readiness(records)
    ready = readiness["directional_eligible"]
    artifact = {
        "ok": ready,
        "code": "MARKET_DEPTH_READY" if ready else "MARKET_DEPTH_INCOMPLETE",
        "match_id": str(match_id),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "markets": records,
        "directional_eligible": ready,
        "adjacent_lines_available": readiness["adjacent_lines_available"],
        "candidate_scope": readiness["candidate_scope"],
    }
    target = SNAPSHOTS / str(match_id) / f"{stamp}.json"
    atomic_json(target, artifact)
    artifact["artifact_path"] = str(target)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    args = parser.parse_args()
    result = capture(args.match_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 20


if __name__ == "__main__":
    sys.exit(main())
