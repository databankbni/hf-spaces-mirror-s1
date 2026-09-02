#!/usr/bin/env python3
"""Collect individually licensed Dryades / Flora d'Italia media metadata.

The collector downloads HTML metadata only, never image bytes. It reads the
single accepted-taxa index, maps labels deterministically to exact ClimaFlora
scientific names, skips taxa already covered by a supplied Media sidecar, then
visits only remaining taxon pages. Every selected image must carry an explicit
open licence in its own page markup.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

INDEX_URL = "https://dryades.units.it/floritaly/index.php?fami=&procedure=simple_new1&taxon=&tipo=all&volgo="
SOURCE = "dryades_flora_italia"
DATASET_ID = "Dryades:Flora-d-Italia"


def clean(value) -> str:
    return " ".join(str(value or "").strip().split())


class TaxaIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.rows: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        a = dict(attrs)
        href = clean(a.get("href"))
        if href and "procedure=taxon_page" in href and "id=" in href:
            self.current_href = urljoin(INDEX_URL, href)
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_href:
            label = clean(unescape("".join(self.current_text)))
            if label:
                self.rows.append((label, self.current_href))
            self.current_href = None
            self.current_text = []


class TaxonPageParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.current: dict | None = None
        self.media: list[dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        a = dict(attrs)
        if tag == "a":
            klass = clean(a.get("class"))
            href = clean(a.get("href"))
            if href and "pirobox_gall" in klass and re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", href, re.I):
                self.current = {
                    "image_url": urljoin(self.page_url, href),
                    "alt": clean(a.get("alt")),
                    "thumbnail_url": None,
                }
        elif tag == "img" and self.current is not None:
            src = clean(a.get("src"))
            if src:
                self.current["thumbnail_url"] = urljoin(self.page_url, src)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current is not None:
            self.media.append(self.current)
            self.current = None


def fetch_text(url: str, retries: int = 8) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "ClimaFlora-MediaV2/2.2 (+https://shugoan.com/climaflora/)"},
            )
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else 0.0
            except ValueError:
                delay = 0.0
            time.sleep(delay if delay > 0 else min(2 ** attempt, 30))
        except Exception as exc:
            last = exc
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"Dryades request failed after {retries} attempts: {last}; url={url}")


def load_catalog(path: Path) -> tuple[dict[str, str | None], dict[str, list[str]], int]:
    by_name: dict[str, str | None] = {}
    names_by_genus: dict[str, list[str]] = defaultdict(list)
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0])
        for tid, raw_name in conn.execute("SELECT taxon_id,scientific_name FROM plant_index"):
            name = clean(raw_name)
            if not name:
                continue
            tid = str(tid)
            if name in by_name and by_name[name] != tid:
                by_name[name] = None
            elif name not in by_name:
                by_name[name] = tid
            genus = name.split(" ", 1)[0]
            names_by_genus[genus].append(name)
    for genus in names_by_genus:
        names_by_genus[genus].sort(key=lambda x: (-len(x), x))
    return by_name, names_by_genus, total


def load_baseline(path: Path | None) -> set[str]:
    if path is None:
        return set()
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        return {str(row[0]) for row in conn.execute("SELECT DISTINCT taxon_id FROM plant_image_asset")}


def canonical_from_label(label: str, names_by_genus: dict[str, list[str]]) -> str | None:
    """Resolve a Dryades accepted label without fuzzy matching.

    A candidate must be an exact catalog name prefix; the only tolerated suffix
    is botanical authorship. Extra lower-case epithets or infraspecific ranks
    are rejected instead of guessed.
    """
    label = clean(label)
    genus = label.split(" ", 1)[0]
    for name in names_by_genus.get(genus, []):
        if label == name:
            return name
        if not label.startswith(name + " "):
            continue
        remainder = label[len(name):].strip()
        low = remainder.lower()
        if re.match(r"^(?:subsp\.|ssp\.|var\.|subvar\.|f\.|forma\s)\b", low):
            continue
        first = remainder.split(" ", 1)[0]
        if first and first[0].islower() and not first.startswith("ex"):
            continue
        return name
    return None


def parse_license(alt: str) -> tuple[str | None, str | None]:
    text = clean(unescape(alt)).replace("<br>", " | ")
    low = text.lower()
    if any(token in low for token in ("by-nc", "by-nd", "noncommercial", "no derivatives", "all rights reserved")):
        return None, None
    if "public domain" in low or "pubblico dominio" in low or "copyright expired" in low:
        return "Public domain", extract_author(text)
    if re.search(r"cc[- ]?by[- ]?sa\s*4\.0", low):
        return "CC BY-SA 4.0", extract_author(text)
    if re.search(r"cc[- ]?by[- ]?sa\s*3\.0", low):
        return "CC BY-SA 3.0", extract_author(text)
    if re.search(r"cc[- ]?by\s*4\.0", low):
        return "CC BY 4.0", extract_author(text)
    if re.search(r"cc[- ]?by\s*3\.0", low):
        return "CC BY 3.0", extract_author(text)
    return None, None


def extract_author(text: str) -> str | None:
    match = re.search(r"(?:^|\|)\s*by\s+([^|]+)", text, re.I)
    if match:
        author = clean(match.group(1))
        if author:
            return author
    if "public domain" in text.lower():
        prefix = clean(text.split("-", 1)[0])
        if prefix and len(prefix) < 160:
            return prefix
    return None


def taxon_page_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return clean((query.get("id") or [""])[0])


def collect_candidate(candidate: tuple[str, str, str, str], settle_delay: float) -> tuple[dict | None, Counter]:
    taxon_id, canonical, page_url, _label = candidate
    local = Counter(taxon_pages_requested=1)
    parser = TaxonPageParser(page_url)
    parser.feed(fetch_text(page_url))
    if settle_delay:
        time.sleep(settle_delay)
    for media in parser.media:
        local["media_rows_seen"] += 1
        licence, author = parse_license(media.get("alt") or "")
        if not licence:
            local["rejected_license_media"] += 1
            continue
        image_url = clean(media.get("image_url"))
        thumb = clean(media.get("thumbnail_url")) or image_url
        if not image_url.startswith("https://") or not thumb.startswith("https://"):
            local["rejected_url_media"] += 1
            continue
        local["eligible_media"] += 1
        local["eligible_taxa"] += 1
        return {
            "asset_id": f"dryades:{taxon_page_id(page_url)}:{Path(urlparse(image_url).path).name}",
            "taxon_id": taxon_id,
            "thumbnail_url": thumb,
            "image_url": image_url,
            "source": SOURCE,
            "source_record_id": taxon_page_id(page_url),
            "source_dataset_id": DATASET_ID,
            "license": licence,
            "license_raw": clean(media.get("alt")),
            "author": author,
            "attribution_url": page_url,
            "is_primary": 0,
            "quality_rank": 140.0 + (5.0 if author else 0.0),
            "verified_taxon_name": canonical,
            "local_filename": None,
            "materialized": 0,
            "materialization_error": None,
        }, local
    local["taxa_without_open_media"] += 1
    return None, local


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=0, help="Limit uncovered taxon-page requests for probes; 0 = all")
    ap.add_argument("--workers", type=int, default=4, help="Bounded concurrent Dryades taxon-page requests (1-8)")
    ap.add_argument("--sleep", type=float, default=0.05, help="Per-request settling delay after a successful response")
    args = ap.parse_args()
    if not 1 <= args.workers <= 8:
        raise SystemExit("--workers must be between 1 and 8")
    if args.sleep < 0:
        raise SystemExit("--sleep must be >= 0")

    catalog, names_by_genus, catalog_total = load_catalog(args.catalog)
    baseline = load_baseline(args.baseline)
    stats = Counter()
    index = TaxaIndexParser()
    index.feed(fetch_text(INDEX_URL))
    stats["accepted_index_links"] = len(index.rows)

    candidates: list[tuple[str, str, str, str]] = []
    seen_taxa: set[str] = set()
    for label, page_url in index.rows:
        canonical = canonical_from_label(label, names_by_genus)
        if not canonical:
            stats["index_unmatched_catalog"] += 1
            continue
        taxon_id = catalog.get(canonical)
        if not taxon_id:
            stats["index_ambiguous_catalog"] += 1
            continue
        stats["index_exact_catalog"] += 1
        if taxon_id in seen_taxa:
            stats["index_duplicate_taxa"] += 1
            continue
        seen_taxa.add(taxon_id)
        if taxon_id in baseline:
            stats["already_covered_taxa"] += 1
            continue
        candidates.append((taxon_id, canonical, page_url, label))

    if args.limit:
        candidates = candidates[: args.limit]

    assets: list[dict] = []
    licenses = Counter()
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="dryades") as executor:
        for selected, local in executor.map(
            lambda candidate: collect_candidate(candidate, args.sleep),
            candidates,
        ):
            stats.update(local)
            if selected:
                assets.append(selected)
                licenses[selected["license"]] += 1

    assets.sort(key=lambda row: (str(row["taxon_id"]), str(row["asset_id"])))
    payload = {
        "schema_version": "1.0",
        "source": SOURCE,
        "dataset_id": DATASET_ID,
        "matching_policy": "exact_catalog_name_after_authorship_stripping_no_fuzzy",
        "license_policy": "explicit per-image CC BY/CC BY-SA/Public Domain only; reject blank/restricted",
        "catalog_taxa_total": catalog_total,
        "baseline_taxa": len(baseline),
        "workers": args.workers,
        "assets": assets,
    }
    report = {
        "status": "ready",
        "source": SOURCE,
        "catalog_taxa_total": catalog_total,
        "baseline_taxa": len(baseline),
        "accepted_index_links": stats["accepted_index_links"],
        "index_exact_catalog": stats["index_exact_catalog"],
        "index_unmatched_catalog": stats["index_unmatched_catalog"],
        "index_ambiguous_catalog": stats["index_ambiguous_catalog"],
        "already_covered_taxa": stats["already_covered_taxa"],
        "uncovered_candidates_considered": len(candidates),
        "workers": args.workers,
        "taxon_pages_requested": stats["taxon_pages_requested"],
        "media_rows_seen": stats["media_rows_seen"],
        "eligible_media": stats["eligible_media"],
        "rejected_license_media": stats["rejected_license_media"],
        "rejected_url_media": stats["rejected_url_media"],
        "eligible_unique_taxa": stats["eligible_taxa"],
        "taxa_without_open_media": stats["taxa_without_open_media"],
        "license_counts": dict(licenses.most_common()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
