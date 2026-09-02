#!/usr/bin/env python3
"""Parse Titan007 H2H from one already-captured fundamentals page.

This module is data-only.  It returns structured rows and never returns the raw
HTML, so its result can be embedded in a portable packet without leaking a
Space-local filesystem path.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join(unescape("".join(self._cell)).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _decode(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", "replace"), "utf-8-sig"
    head = raw[:4096].decode("ascii", "ignore").lower()
    declared = re.search(r"charset\s*=\s*[\"']?([\w-]+)", head)
    candidates = [declared.group(1)] if declared else []
    candidates.extend(["utf-8", "gb18030", "gbk"])
    for encoding in candidates:
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8-replace"


def parse_h2h(raw: bytes) -> dict:
    text, encoding = _decode(raw)
    markers = ("對賽往績", "历史交锋", "歷史交鋒", "交锋往绩", "交鋒往績", "H2H")
    marker = next((item for item in markers if item in text), None)
    js_matches: list[dict] = []
    js_match = re.search(r"\bvar\s+v_data\s*=\s*(\[.*?\]);", text, re.S)
    if js_match:
        try:
            rows = ast.literal_eval(js_match.group(1))
            for row in rows:
                if not isinstance(row, list) or len(row) < 10:
                    continue
                home = re.sub(r"<[^>]+>", "", str(row[5])).strip()
                away = re.sub(r"<[^>]+>", "", str(row[7])).strip()
                js_matches.append({
                    "date": str(row[0]),
                    "league": str(row[2]),
                    "home": unescape(home),
                    "score": f"{row[8]}-{row[9]}",
                    "away": unescape(away),
                    "match_id": str(row[15]) if len(row) > 15 else None,
                })
        except (SyntaxError, ValueError, TypeError):
            js_matches = []
    if js_matches:
        return {
            "encoding": encoding,
            "h2h_marker": marker,
            "h2h_table_rows": len(js_matches),
            "h2h_available": True,
            "matches": js_matches,
            "status": "H2H_AVAILABLE",
            "source_structure": "v_data",
        }
    window = text[text.find(marker):text.find(marker) + 48000] if marker else ""
    parser = _TableParser()
    parser.feed(window)
    candidate: list[list[str]] = []
    matches: list[dict] = []
    for table in parser.tables:
        table_matches = []
        for row in table:
            row_date = row[0] if row and re.fullmatch(r"(?:20\d{2}[-/.])?\d{1,2}[-/.]\d{1,2}", row[0]) else None
            score = next((value for value in row[1:] if row_date and re.fullmatch(r"(?:[0-9]|1[0-9]|20)\s*[-:]\s*(?:[0-9]|1[0-9]|20)", value)), None)
            if not score:
                continue
            score_index = row.index(score)
            table_matches.append({
                "date": row[0] if row else None,
                "home": row[score_index - 1] if score_index >= 1 else None,
                "score": score.replace(":", "-"),
                "away": row[score_index + 1] if score_index + 1 < len(row) else None,
            })
        if len(table_matches) > len(matches):
            candidate, matches = table, table_matches
    available = bool(marker and matches)
    return {
        "encoding": encoding,
        "h2h_marker": marker,
        "h2h_table_rows": len(candidate),
        "h2h_available": available,
        "matches": matches,
        "status": "H2H_AVAILABLE" if available else "H2H_NO_SAMPLE",
        "source_structure": "rendered_table_fallback",
    }


def build_portable_evidence(fundamentals: dict) -> dict:
    """Build packet-safe H2H evidence from one fundamentals artifact."""
    match_id = str(fundamentals.get("match_id") or "")
    raw_path = Path(str(fundamentals.get("raw_path") or ""))
    claimed_sha = str(fundamentals.get("raw_sha256") or "")
    base = {
        "schema_version": 1,
        "match_id": match_id,
        "source": "packet_fundamentals_raw_reuse",
        "source_url": fundamentals.get("source_url"),
        "source_captured_at": fundamentals.get("captured_at"),
        "source_sha256": claimed_sha,
        "parser": "titan007_h2h.parse_h2h",
    }
    try:
        raw = raw_path.read_bytes()
    except OSError as exc:
        value = {**base, "ok": False, "status": "H2H_PORTABLE_SOURCE_UNAVAILABLE",
                 "code": "H2H_RAW_PATH_UNREADABLE", "error_type": type(exc).__name__}
    else:
        actual_sha = hashlib.sha256(raw).hexdigest()
        if len(claimed_sha) != 64 or actual_sha != claimed_sha:
            value = {**base, "ok": False, "status": "H2H_PORTABLE_SOURCE_INVALID",
                     "code": "H2H_RAW_SHA256_MISMATCH", "actual_sha256": actual_sha}
        else:
            value = {**base, "ok": True, "parsed": parse_h2h(raw)}
    value["evidence_sha256"] = hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return value


__all__ = ["build_portable_evidence", "parse_h2h"]