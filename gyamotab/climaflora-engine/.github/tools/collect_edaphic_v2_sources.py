from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

USDA_BASE = "https://plantsservices.sc.egov.usda.gov/api"
USER_AGENT = "ClimaFlora/2.0 scientific edaphic enrichment (source audit; contact via shugoan.com)"
RANK_MARKERS = {"subsp.", "ssp.", "var.", "forma", "f.", "subvar.", "nothosubsp.", "nothovar."}
THREAD_LOCAL = threading.local()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_session() -> requests.Session:
    session = getattr(THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        THREAD_LOCAL.session = session
    return session


def get_json(url: str, *, timeout: int = 40, tries: int = 5) -> tuple[Any | None, dict[str, Any]]:
    last: str | None = None
    for attempt in range(tries):
        try:
            r = get_session().get(url, timeout=(min(timeout, 15), timeout))
            if r.status_code == 404:
                return None, {"status": 404, "bytes": len(r.content), "attempts": attempt + 1}
            r.raise_for_status()
            return r.json(), {
                "status": r.status_code,
                "bytes": len(r.content),
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "attempts": attempt + 1,
            }
        except Exception as exc:
            last = repr(exc)
            if attempt + 1 < tries:
                time.sleep(min(8.0, 0.5 * (2**attempt)))
    return None, {"status": None, "error": last, "attempts": tries}


def canonical_species_name(scientific_name_with_author: str) -> str | None:
    text = re.sub(r"<[^>]+>", "", scientific_name_with_author or "").strip()
    tokens = text.replace("× ", "×").split()
    if len(tokens) < 2:
        return None
    lowered = {t.lower() for t in tokens}
    if lowered & RANK_MARKERS:
        return None
    genus, epithet = tokens[0].strip(), tokens[1].strip().rstrip(",;")
    if not genus or not epithet or epithet.endswith("."):
        return None
    return f"{genus} {epithet}"


def load_climaflora_names(db: Path) -> tuple[dict[str, str], set[str]]:
    by_name: dict[str, list[str]] = defaultdict(list)
    with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as con:
        for name, taxon_id in con.execute("SELECT scientific_name,taxon_id FROM plant_index"):
            if name:
                by_name[str(name).strip()].append(str(taxon_id))
    unique = {name: ids[0] for name, ids in by_name.items() if len(ids) == 1}
    ambiguous = {name for name, ids in by_name.items() if len(ids) > 1}
    return unique, ambiguous


def load_usda_candidates(plant_list: Path, name_to_taxon: dict[str, str], ambiguous: set[str]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    candidates: list[dict[str, str]] = []
    accepted_rows = 0
    exact_names = 0
    seen_symbol: set[str] = set()
    with plant_list.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Synonym Symbol") or "").strip():
                continue
            accepted_rows += 1
            symbol = (row.get("Symbol") or "").strip()
            canonical = canonical_species_name(row.get("Scientific Name with Author") or "")
            if not symbol or symbol in seen_symbol or not canonical or canonical in ambiguous:
                continue
            taxon_id = name_to_taxon.get(canonical)
            if not taxon_id:
                continue
            exact_names += 1
            seen_symbol.add(symbol)
            candidates.append({
                "symbol": symbol,
                "scientific_name": canonical,
                "taxon_id": taxon_id,
                "family": (row.get("Family") or "").strip(),
                "source_name": (row.get("Scientific Name with Author") or "").strip(),
            })
    return candidates, {
        "accepted_rows": accepted_rows,
        "exact_unambiguous_candidates": len(candidates),
        "exact_name_rows": exact_names,
        "ambiguous_climaflora_names_skipped": len(ambiguous),
    }


def collect_one(candidate: dict[str, str], *, timeout: int = 40, tries: int = 5) -> dict[str, Any]:
    symbol = candidate["symbol"]
    profile, pmeta = get_json(f"{USDA_BASE}/PlantProfile?symbol={symbol}", timeout=timeout, tries=tries)
    result: dict[str, Any] = {**candidate, "profile_http": pmeta}
    if not isinstance(profile, dict):
        result["outcome"] = "PROFILE_UNAVAILABLE"
        return result
    result.update({
        "usda_id": profile.get("Id"),
        "rank": profile.get("Rank"),
        "has_characteristics": bool(profile.get("HasCharacteristics")),
        "profile_scientific_name": re.sub(r"<[^>]+>", "", str(profile.get("ScientificName") or "")).strip(),
    })
    if str(profile.get("Rank") or "").lower() != "species":
        result["outcome"] = "NON_SPECIES_PROFILE"
        return result
    if not profile.get("HasCharacteristics") or not profile.get("Id"):
        result["outcome"] = "NO_CHARACTERISTICS"
        return result
    chars, cmeta = get_json(f"{USDA_BASE}/PlantCharacteristics/{profile['Id']}", timeout=timeout, tries=tries)
    result["characteristics_http"] = cmeta
    if not isinstance(chars, list):
        result["outcome"] = "CHARACTERISTICS_UNAVAILABLE"
        return result
    growth: list[dict[str, Any]] = []
    dropped_cultivar = 0
    dropped_synonym = 0
    for row in chars:
        if not isinstance(row, dict) or row.get("PlantCharacteristicCategory") != "Growth Requirements":
            continue
        if row.get("CultivarName") not in (None, ""):
            dropped_cultivar += 1
            continue
        if row.get("SynonymName") not in (None, ""):
            dropped_synonym += 1
            continue
        name = str(row.get("PlantCharacteristicName") or "").strip()
        value = row.get("PlantCharacteristicValue")
        if name and value not in (None, ""):
            growth.append({"name": name, "value": str(value).strip()})
    dedup: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in growth:
        key = (item["name"], item["value"])
        if key not in seen:
            seen.add(key)
            dedup.append(item)
    result.update({
        "growth_requirements": dedup,
        "growth_requirement_count": len(dedup),
        "cultivar_rows_excluded": dropped_cultivar,
        "synonym_rows_excluded": dropped_synonym,
        "outcome": "GROWTH_REQUIREMENTS" if dedup else "NO_GROWTH_REQUIREMENTS",
    })
    return result


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def summarize(records: list[dict[str, Any]], candidate_stats: dict[str, Any]) -> dict[str, Any]:
    outcomes = Counter(str(r.get("outcome")) for r in records)
    characteristic_names: Counter[str] = Counter()
    taxa_by_characteristic: Counter[str] = Counter()
    ph_complete = ph_any = texture_any = salinity_any = root_depth_any = 0
    for rec in records:
        names = {str(x.get("name")) for x in rec.get("growth_requirements", []) if isinstance(x, dict)}
        for item in rec.get("growth_requirements", []):
            if isinstance(item, dict):
                characteristic_names[str(item.get("name"))] += 1
        for name in names:
            taxa_by_characteristic[name] += 1
        has_min = "pH, Minimum" in names
        has_max = "pH, Maximum" in names
        ph_complete += int(has_min and has_max)
        ph_any += int(has_min or has_max)
        texture_any += int(bool(names & {"Adapted to Coarse Textured Soils", "Adapted to Medium Textured Soils", "Adapted to Fine Textured Soils"}))
        salinity_any += int("Salinity Tolerance" in names)
        root_depth_any += int(bool(names & {"Root Depth, Minimum", "Root Depth, Minimum (inches)"}))
    return {
        **candidate_stats,
        "profiles_attempted": len(records),
        "outcomes": dict(outcomes),
        "taxa_with_growth_requirements": outcomes.get("GROWTH_REQUIREMENTS", 0),
        "taxa_with_complete_ph_range": ph_complete,
        "taxa_with_any_ph_bound": ph_any,
        "taxa_with_texture_adaptation": texture_any,
        "taxa_with_salinity_tolerance": salinity_any,
        "taxa_with_minimum_root_depth": root_depth_any,
        "top_growth_requirements": taxa_by_characteristic.most_common(80),
        "raw_characteristic_row_counts": characteristic_names.most_common(80),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--plant-list", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    catalog = Path(args.catalog)
    plant_list = Path(args.plant_list)
    output = Path(args.output)
    report_path = Path(args.report)
    name_to_taxon, ambiguous = load_climaflora_names(catalog)
    candidates, candidate_stats = load_usda_candidates(plant_list, name_to_taxon, ambiguous)

    started = time.monotonic()
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(collect_one, c): c for c in candidates}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                records.append(future.result())
            except Exception as exc:
                c = futures[future]
                records.append({**c, "outcome": "UNHANDLED_ERROR", "error": repr(exc)})
            if i % 1000 == 0:
                print(f"USDA profiles {i}/{len(candidates)} elapsed={time.monotonic()-started:.1f}s", flush=True)

    records.sort(key=lambda r: (str(r.get("scientific_name")), str(r.get("symbol"))))
    write_jsonl(output, records)
    summary = summarize(records, candidate_stats)
    report = {
        "status": "ready",
        "source": "USDA_PLANTS",
        "source_api": USDA_BASE,
        "accessed_at": utcnow(),
        "catalog_sha256": sha256_file(catalog),
        "plant_list_sha256": sha256_file(plant_list),
        "output_sha256": sha256_file(output),
        "workers": args.workers,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "stats": summary,
        "matching_policy": "exact unambiguous ClimaFlora/WCVP accepted species binomial; USDA accepted symbols; profile Rank=Species; no fuzzy matching",
        "row_policy": "Growth Requirements only; cultivar-specific and synonym-specific characteristic rows excluded",
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
