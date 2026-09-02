#!/usr/bin/env python3
"""Build ClimaFlora Wikimedia media sidecar v1.1.

Policy:
- exact scientific-name linkage through Wikidata P225 only;
- Wikimedia P18 is the first source;
- exact Wikidata P373 Commons categories are the second source;
- legally admissible media only (CC0/Public domain/CC BY/CC BY-SA);
- visually doubtful media are retained but flagged for blurred display;
- unresolved taxonomic homonyms are still rejected because attachment is unsafe;
- images are illustrative only and never affect ClimaFlora scoring.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.media import (  # noqa: E402
    canonical_open_license,
    media_quality_rank,
    safe_image_url,
    safe_license_url,
    safe_source_url,
)

INGESTER_VERSION = "1.1.0"
SOURCE_NAME = "wikimedia_commons"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "ClimaFlora/0.9.44 (https://shugoan.com/climaflora; media metadata ingestion)"
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
TAG_RE = re.compile(r"<[^>]+>")
AMBIGUOUS_MEDIA_LABEL_RE = re.compile(
    r"(?:\bor\b|\bpossibly\b|\bprobable\b|\bprobably\b|\bcf\.?\b|\baff\.?\b|\bunknown\b|\buncertain\b|\?)",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: str | None, limit: int = 1000) -> str | None:
    raw = html.unescape(TAG_RE.sub(" ", str(value or "")))
    raw = " ".join(raw.split()).strip()
    return raw[:limit] if raw else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sparql_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def filename_from_p18(uri: str) -> str | None:
    parsed = urlparse(uri)
    marker = "/Special:FilePath/"
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"commons.wikimedia.org", "www.wikidata.org"}
        or parsed.username
        or parsed.password
        or marker not in parsed.path
    ):
        return None
    name = unquote(parsed.path.split(marker, 1)[1]).replace("_", " ").strip()
    return name or None


def media_label_is_ambiguous(filename: str) -> bool:
    normalized = unquote(str(filename or "")).replace("_", " ").strip()
    return bool(normalized and AMBIGUOUS_MEDIA_LABEL_RE.search(normalized))


def filename_mentions_taxon(filename: str, scientific_name: str) -> bool:
    haystack = re.sub(r"[^a-z0-9]+", " ", unquote(filename).lower()).split()
    tokens = [token for token in re.sub(r"[^a-z0-9]+", " ", scientific_name.lower()).split() if len(token) > 2]
    return bool(tokens) and all(token in haystack for token in tokens[:2])


def display_uncertainty(filename: str, scientific_name: str, source_method: str) -> tuple[bool, str | None]:
    if media_label_is_ambiguous(filename):
        return True, "ambiguous_media_label"
    if source_method == "wikidata_p373_category" and not filename_mentions_taxon(filename, scientific_name):
        return True, "category_member_without_explicit_taxon_name"
    return False, None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS plant_image_asset(
          taxon_id TEXT NOT NULL,
          asset_id TEXT PRIMARY KEY,
          source_name TEXT NOT NULL,
          source_page_url TEXT NOT NULL,
          image_url TEXT,
          thumbnail_url TEXT NOT NULL,
          license TEXT NOT NULL,
          license_url TEXT,
          author TEXT,
          attribution TEXT,
          width INTEGER,
          height INTEGER,
          mime_type TEXT,
          is_primary INTEGER NOT NULL DEFAULT 0,
          materialized INTEGER NOT NULL DEFAULT 0,
          display_blurred INTEGER NOT NULL DEFAULT 0,
          ambiguity_reason TEXT,
          match_method TEXT NOT NULL,
          match_confidence REAL NOT NULL,
          quality_rank REAL NOT NULL DEFAULT 0,
          retrieved_at TEXT NOT NULL,
          last_checked_at TEXT,
          source_metadata_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_media_taxon ON plant_image_asset(taxon_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_media_primary ON plant_image_asset(taxon_id) WHERE is_primary=1;
        CREATE TABLE IF NOT EXISTS media_ingest_attempt(
          taxon_id TEXT PRIMARY KEY,
          scientific_name TEXT NOT NULL,
          result TEXT NOT NULL,
          reason TEXT,
          source_asset_id TEXT,
          license TEXT,
          duration_ms INTEGER NOT NULL DEFAULT 0,
          checked_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS media_metadata(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )


def set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO media_metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def catalog_version(conn: sqlite3.Connection) -> str | None:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "climaflora_catalog_metadata" not in tables:
        return None
    row = conn.execute("SELECT value FROM climaflora_catalog_metadata WHERE key='catalog_version'").fetchone()
    return str(row[0]) if row else None


def select_taxa(catalog: Path, taxon: str | None, limit: int, offset: int) -> list[tuple[str, str]]:
    uri = f"file:{catalog.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        if taxon:
            rows = conn.execute(
                "SELECT taxon_id,scientific_name FROM plant_index WHERE scientific_name=?",
                (taxon.strip(),),
            ).fetchall()
            if len(rows) != 1:
                raise RuntimeError(f"exact taxon lookup must resolve once, got {len(rows)} for {taxon!r}")
            return [(str(rows[0]["taxon_id"]), str(rows[0]["scientific_name"]))]
        rows = conn.execute(
            """
            SELECT MIN(taxon_id) AS taxon_id, scientific_name
            FROM plant_index
            WHERE scientific_name IS NOT NULL AND trim(scientific_name)<>''
            GROUP BY scientific_name
            HAVING COUNT(*)=1
            ORDER BY scientific_name COLLATE NOCASE, scientific_name
            LIMIT ? OFFSET ?
            """,
            (max(1, int(limit)), max(0, int(offset))),
        ).fetchall()
        return [(str(row["taxon_id"]), str(row["scientific_name"])) for row in rows]


class WikimediaClient:
    def __init__(self, *, timeout: float, max_retries: int, request_delay_ms: int):
        self.max_retries = max_retries
        self.delay = max(0, request_delay_ms) / 1000.0
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, url: str, **kwargs) -> dict:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.request(method, url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    retry = response.headers.get("Retry-After")
                    delay = float(retry) if retry and retry.isdigit() else min(30.0, 2.0 ** attempt)
                    if attempt < self.max_retries:
                        time.sleep(delay)
                        continue
                response.raise_for_status()
                data = response.json()
                if self.delay:
                    time.sleep(self.delay)
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(min(30.0, 2.0 ** attempt))
        raise RuntimeError(f"Wikimedia request failed after retries: {last}")

    def exact_assets(self, names: list[str]) -> tuple[dict[str, dict], set[str]]:
        if not names:
            return {}, set()
        values = " ".join(sparql_string(name) for name in names)
        query = f"""
        SELECT ?taxon ?name ?image ?commonsCategory WHERE {{
          VALUES ?name {{ {values} }}
          ?taxon wdt:P225 ?name .
          OPTIONAL {{ ?taxon wdt:P18 ?image . }}
          OPTIONAL {{ ?taxon wdt:P373 ?commonsCategory . }}
        }}
        """
        data = self._request(
            "POST",
            WIKIDATA_SPARQL,
            data={"query": query, "format": "json"},
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/sparql-results+json"},
        )
        out: dict[str, dict] = defaultdict(lambda: {"qids": set(), "p18": set(), "categories": set()})
        for binding in data.get("results", {}).get("bindings", []):
            name = str(binding.get("name", {}).get("value", ""))
            taxon_uri = str(binding.get("taxon", {}).get("value", ""))
            if name not in names or not taxon_uri:
                continue
            qid = taxon_uri.rsplit("/", 1)[-1]
            out[name]["qids"].add(qid)
            image_uri = str(binding.get("image", {}).get("value", ""))
            filename = filename_from_p18(image_uri) if image_uri else None
            if filename:
                out[name]["p18"].add(filename)
            category = clean_text(binding.get("commonsCategory", {}).get("value"), 300)
            if category:
                out[name]["categories"].add(category)
        ambiguous = {name for name, item in out.items() if len(item["qids"]) != 1}
        return out, ambiguous

    def category_files(self, category: str, limit: int = 8) -> list[str]:
        data = self._request(
            "GET",
            COMMONS_API,
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmtype": "file",
                "cmlimit": str(max(1, min(int(limit), 20))),
            },
        )
        files: list[str] = []
        for item in data.get("query", {}).get("categorymembers", []):
            title = str(item.get("title", ""))
            if title.startswith("File:"):
                files.append(title[5:])
        return files

    def commons_info(self, filenames: list[str], width: int) -> dict[str, dict]:
        out: dict[str, dict] = {}
        unique = list(dict.fromkeys(filenames))
        for start in range(0, len(unique), 50):
            batch = unique[start:start + 50]
            titles = "|".join(f"File:{name}" for name in batch)
            data = self._request(
                "GET",
                COMMONS_API,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "prop": "imageinfo",
                    "titles": titles,
                    "iiprop": "url|size|mime|extmetadata",
                    "iiurlwidth": str(width),
                },
            )
            for page in data.get("query", {}).get("pages", []):
                title = str(page.get("title", ""))
                filename = title[5:] if title.startswith("File:") else title
                info = (page.get("imageinfo") or [None])[0]
                if isinstance(info, dict):
                    out[filename] = info
        return out


def candidate_from_info(
    filename: str,
    info480: dict,
    info960: dict | None,
    retrieved_at: str,
    scientific_name: str,
    source_method: str,
    category: str | None = None,
) -> dict | None:
    ext = info480.get("extmetadata") or {}
    licence = canonical_open_license(clean_text((ext.get("LicenseShortName") or {}).get("value"), 120))
    mime = str(info480.get("mime") or "").lower()
    if not licence or mime not in ALLOWED_MIME:
        return None
    thumb = safe_image_url(info480.get("thumburl"))
    detail = safe_image_url((info960 or {}).get("thumburl")) or thumb
    page = safe_source_url(
        "https://commons.wikimedia.org/wiki/File:" + quote(filename.replace(" ", "_"), safe="()_,-.")
    )
    if not thumb or not detail or not page:
        return None
    author = clean_text((ext.get("Artist") or {}).get("value"), 500) or clean_text(
        (ext.get("Credit") or {}).get("value"), 500
    )
    licence_url = safe_license_url(clean_text((ext.get("LicenseUrl") or {}).get("value"), 500))
    width = int(info480.get("width") or 0) or None
    height = int(info480.get("height") or 0) or None
    blurred, reason = display_uncertainty(filename, scientific_name, source_method)
    rank = media_quality_rank(
        exact_scientific_name=True,
        width=width,
        height=height,
        author=author,
        license_url=licence_url,
        mime_type=mime,
    ) + (12 if source_method == "wikidata_p18" else 0)
    upper = licence.upper()
    permissive = 0 if upper.startswith("CC0") or upper == "PUBLIC DOMAIN" else 1 if upper.startswith("CC BY ") else 2
    asset_id = "commons-" + hashlib.sha256(page.encode("utf-8")).hexdigest()[:24]
    return {
        "asset_id": asset_id,
        "source_name": SOURCE_NAME,
        "source_page_url": page,
        "image_url": detail,
        "thumbnail_url": thumb,
        "license": licence,
        "license_url": licence_url,
        "author": author,
        "attribution": " · ".join(v for v in (author, licence, "Wikimedia Commons") if v),
        "width": width,
        "height": height,
        "mime_type": mime,
        "materialized": 0,
        "display_blurred": int(blurred),
        "ambiguity_reason": reason,
        "match_method": "exact_scientific_name",
        "match_confidence": 0.95 if source_method == "wikidata_p18" else 0.90,
        "quality_rank": rank,
        "retrieved_at": retrieved_at,
        "last_checked_at": retrieved_at,
        "permissive_rank": permissive,
        "filename": filename,
        "source_method": source_method,
        "category": category,
    }


def upsert_attempt(conn: sqlite3.Connection, **values) -> None:
    conn.execute(
        """
        INSERT INTO media_ingest_attempt(
          taxon_id,scientific_name,result,reason,source_asset_id,license,duration_ms,checked_at
        ) VALUES(:taxon_id,:scientific_name,:result,:reason,:asset_id,:licence,:duration_ms,:checked_at)
        ON CONFLICT(taxon_id) DO UPDATE SET
          scientific_name=excluded.scientific_name,result=excluded.result,reason=excluded.reason,
          source_asset_id=excluded.source_asset_id,license=excluded.license,
          duration_ms=excluded.duration_ms,checked_at=excluded.checked_at
        """,
        values,
    )


def build(args: argparse.Namespace) -> dict:
    catalog = Path(args.catalog)
    if not catalog.exists():
        raise RuntimeError(f"catalog not found: {catalog}")
    started = now_iso()
    catalog_sha = args.catalog_sha256 or sha256_file(catalog)
    taxa = select_taxa(catalog, args.taxon, args.limit, args.offset)
    if not taxa:
        raise RuntimeError("no exact unique taxa selected")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(":memory:" if args.dry_run else output)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    if not args.dry_run and not args.retry_missing:
        ids = [taxon_id for taxon_id, _ in taxa]
        for start in range(0, len(ids), 800):
            batch = ids[start:start + 800]
            marks = ",".join("?" for _ in batch)
            conn.execute(f"DELETE FROM plant_image_asset WHERE taxon_id IN ({marks})", batch)
            conn.execute(f"DELETE FROM media_ingest_attempt WHERE taxon_id IN ({marks})", batch)
    elif not args.dry_run and args.retry_missing:
        selected = {str(row[0]) for row in conn.execute("SELECT taxon_id FROM media_ingest_attempt WHERE result IN ('selected','selected_blurred')")}
        taxa = [(taxon_id, name) for taxon_id, name in taxa if taxon_id not in selected]

    client = WikimediaClient(
        timeout=float(args.timeout_seconds),
        max_retries=int(args.max_retries),
        request_delay_ms=int(args.request_delay_ms),
    )
    stats: Counter[str] = Counter()
    licenses: Counter[str] = Counter()
    try:
        for start in range(0, len(taxa), max(1, int(args.batch_size))):
            batch = taxa[start:start + max(1, int(args.batch_size))]
            names = [name for _, name in batch]
            batch_started = time.monotonic()
            try:
                assets, ambiguous = client.exact_assets(names)
                category_files: dict[tuple[str, str], list[str]] = {}
                all_filenames: list[str] = []
                for name in names:
                    if name in ambiguous:
                        continue
                    item = assets.get(name) or {}
                    p18 = sorted(item.get("p18") or [])
                    all_filenames.extend(p18)
                    if not p18:
                        for category in sorted(item.get("categories") or [])[:1]:
                            files = client.category_files(category, int(args.category_file_limit))
                            category_files[(name, category)] = files
                            all_filenames.extend(files)
                info480 = client.commons_info(all_filenames, 480) if all_filenames else {}
                info960 = client.commons_info(all_filenames, 960) if all_filenames else {}
            except Exception as exc:  # noqa: BLE001
                elapsed = int((time.monotonic() - batch_started) * 1000)
                for taxon_id, name in batch:
                    stats["network_failures"] += 1
                    upsert_attempt(
                        conn, taxon_id=taxon_id, scientific_name=name, result="network_error",
                        reason=type(exc).__name__, asset_id=None, licence=None, duration_ms=elapsed,
                        checked_at=now_iso(),
                    )
                conn.commit()
                continue

            for taxon_id, name in batch:
                one_started = time.monotonic()
                checked_at = now_iso()
                if name in ambiguous:
                    stats["rejected_taxonomy"] += 1
                    upsert_attempt(
                        conn, taxon_id=taxon_id, scientific_name=name, result="rejected_taxonomy",
                        reason="multiple_wikidata_taxa_for_exact_p225", asset_id=None, licence=None,
                        duration_ms=int((time.monotonic() - one_started) * 1000), checked_at=checked_at,
                    )
                    continue
                item = assets.get(name) or {"p18": set(), "categories": set()}
                sources: dict[str, tuple[str, str | None]] = {}
                for filename in sorted(item.get("p18") or []):
                    sources[filename] = ("wikidata_p18", None)
                if not sources:
                    for category in sorted(item.get("categories") or [])[:1]:
                        for filename in category_files.get((name, category), []):
                            sources.setdefault(filename, ("wikidata_p373_category", category))
                candidates = []
                rejected_licence = 0
                for filename, (source_method, category) in sources.items():
                    info = info480.get(filename)
                    if not info:
                        continue
                    candidate = candidate_from_info(
                        filename, info, info960.get(filename), checked_at, name, source_method, category
                    )
                    if candidate is None:
                        ext = info.get("extmetadata") or {}
                        if canonical_open_license(clean_text((ext.get("LicenseShortName") or {}).get("value"), 120)) is None:
                            rejected_licence += 1
                        continue
                    candidates.append(candidate)
                if not candidates:
                    result = "rejected_license" if rejected_licence else "no_result"
                    reason = "no_whitelisted_candidate" if rejected_licence else "no_safe_exact_wikimedia_candidate"
                    stats[result] += 1
                    upsert_attempt(
                        conn, taxon_id=taxon_id, scientific_name=name, result=result, reason=reason,
                        asset_id=None, licence=None,
                        duration_ms=int((time.monotonic() - one_started) * 1000), checked_at=checked_at,
                    )
                    continue
                candidates.sort(
                    key=lambda item: (
                        int(item["display_blurred"]),
                        -int(item["quality_rank"]),
                        int(item["permissive_rank"]),
                        -(int(item.get("width") or 0) * int(item.get("height") or 0)),
                        str(item["asset_id"]),
                    )
                )
                selected = candidates[0]
                source_metadata = json.dumps(
                    {
                        "filename": selected["filename"],
                        "scientific_name": name,
                        "source_method": selected["source_method"],
                        "category": selected["category"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO plant_image_asset(
                      taxon_id,asset_id,source_name,source_page_url,image_url,thumbnail_url,
                      license,license_url,author,attribution,width,height,mime_type,is_primary,
                      materialized,display_blurred,ambiguity_reason,match_method,match_confidence,
                      quality_rank,retrieved_at,last_checked_at,source_metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        taxon_id, selected["asset_id"], selected["source_name"], selected["source_page_url"],
                        selected["image_url"], selected["thumbnail_url"], selected["license"], selected["license_url"],
                        selected["author"], selected["attribution"], selected["width"], selected["height"],
                        selected["mime_type"], selected["materialized"], selected["display_blurred"],
                        selected["ambiguity_reason"], selected["match_method"], selected["match_confidence"],
                        selected["quality_rank"], selected["retrieved_at"], selected["last_checked_at"], source_metadata,
                    ),
                )
                result = "selected_blurred" if selected["display_blurred"] else "selected"
                upsert_attempt(
                    conn, taxon_id=taxon_id, scientific_name=name, result=result,
                    reason=selected["ambiguity_reason"], asset_id=selected["asset_id"], licence=selected["license"],
                    duration_ms=int((time.monotonic() - one_started) * 1000), checked_at=checked_at,
                )
                stats["primary_images_selected"] += 1
                stats[result] += 1
                stats[selected["source_method"]] += 1
                licenses[selected["license"]] += 1
            conn.commit()
    finally:
        client.close()

    finished = now_iso()
    stats["requested_taxa"] = len(taxa)
    stats["processed_taxa"] = int(conn.execute("SELECT COUNT(*) FROM media_ingest_attempt").fetchone()[0])
    stats["media_primary_duplicate_taxa"] = int(conn.execute(
        "SELECT COUNT(*) FROM (SELECT taxon_id FROM plant_image_asset WHERE is_primary=1 GROUP BY taxon_id HAVING COUNT(*)>1)"
    ).fetchone()[0])
    stats["invalid_primary_licenses"] = int(conn.execute(
        """
        SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND (
          license IS NULL OR trim(license)='' OR upper(license) LIKE '%NC%' OR upper(license) LIKE '%ND%'
        )
        """
    ).fetchone()[0])
    stats["blurred_primary"] = int(conn.execute(
        "SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND display_blurred=1"
    ).fetchone()[0])
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if not args.dry_run:
        with sqlite3.connect(f"file:{catalog.resolve()}?mode=ro", uri=True) as source_conn:
            source_catalog_version = catalog_version(source_conn)
        for key, value in {
            "schema_version": "1.1",
            "ingester_version": INGESTER_VERSION,
            "source": SOURCE_NAME,
            "source_catalog_sha256": catalog_sha,
            "source_catalog_version": source_catalog_version or "unknown",
            "image_scoring_effect": "false",
            "uncertain_media_policy": "retain_blurred",
            "generated_at": finished,
        }.items():
            set_metadata(conn, key, str(value))
        conn.commit()
    conn.close()

    if integrity != "ok":
        raise RuntimeError(f"media sidecar integrity_check failed: {integrity}")
    if stats["invalid_primary_licenses"] or stats["media_primary_duplicate_taxa"]:
        raise RuntimeError("media legal/primary uniqueness gate failed")

    report = {
        "started_at": started,
        "finished_at": finished,
        "source": SOURCE_NAME,
        "ingester_version": INGESTER_VERSION,
        "git_commit": args.git_commit or os.getenv("GITHUB_SHA") or None,
        "source_catalog_sha256": catalog_sha,
        "requested_taxa": stats["requested_taxa"],
        "processed_taxa": stats["processed_taxa"],
        "primary_images_selected": stats["primary_images_selected"],
        "selected_clear": stats["selected"],
        "selected_blurred": stats["selected_blurred"],
        "wikidata_p18": stats["wikidata_p18"],
        "wikidata_p373_category": stats["wikidata_p373_category"],
        "no_result": stats["no_result"],
        "rejected_license": stats["rejected_license"],
        "rejected_taxonomy": stats["rejected_taxonomy"],
        "network_failures": stats["network_failures"],
        "media_primary_duplicate_taxa": stats["media_primary_duplicate_taxa"],
        "invalid_primary_licenses": stats["invalid_primary_licenses"],
        "licenses": dict(sorted(licenses.items())),
        "integrity_check": integrity,
        "rules": {
            "fuzzy_matching": False,
            "taxonomic_homonyms_rejected": True,
            "uncertain_media_policy": "retain_blurred",
            "sources": ["wikidata_p18", "wikidata_p373_category"],
            "allowed_licenses": ["CC0", "Public domain", "CC BY", "CC BY-SA"],
            "image_scoring_effect": False,
            "materialized": False,
        },
    }
    Path(args.report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=os.getenv("CLIMAFLORA_CATALOG_DB", "/data/climaflora_global_plants_v2_0.sqlite"))
    parser.add_argument("--output", default="data/climaflora_media_v1.sqlite")
    parser.add_argument("--report-path", default="data/climaflora_media_v1_report.json")
    parser.add_argument("--taxon")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--retry-missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--request-delay-ms", type=int, default=75)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--category-file-limit", type=int, default=8)
    parser.add_argument("--catalog-sha256")
    parser.add_argument("--git-commit")
    return parser.parse_args()


def main() -> None:
    print(json.dumps(build(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
