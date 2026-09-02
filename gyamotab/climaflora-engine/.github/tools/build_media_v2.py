#!/usr/bin/env python3
"""Build ClimaFlora Media v2 from Pl@ntNet/GBIF and World Flora Online.

Media is descriptive only. Taxonomic linkage is exact canonical-name equality.
Licence policy is source-specific: WFO remains restricted to explicit open
licences, while the Pl@ntNet adapter may explicitly retain unverified licences.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

PLANTNET_DATASET_KEY = "7a3679ef-5582-4aaa-81f0-8c2545cafc81"
PLANTNET_DATASET_DOI = "10.15468/gtebaa"
WFO_RELEASE = "2026-06"
WFO_RELEASE_DOI = "10.5281/zenodo.20782718"
WFO_IMAGE_RESOURCE = "MBG Floras Images"
WFO_PORTAL = "https://www.worldfloraonline.org"

try:
    csv.field_size_limit(64 * 1024 * 1024)
except OverflowError:
    csv.field_size_limit(16 * 1024 * 1024)


def clean(value) -> str:
    return " ".join(str(value or "").strip().split())


def term(value: str | None) -> str:
    text = clean(value)
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    return text.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_open_license(value: str | None) -> str | None:
    raw = clean(value)
    low = raw.lower()
    if not low:
        return None
    if any(token in low for token in ("by-nc", "by-nd", "noncommercial", "no derivatives", "all rights reserved")):
        return None
    if "creativecommons.org/publicdomain/zero" in low or low in {"cc0", "cc0 1.0"}:
        return "CC0 1.0"
    if "creativecommons.org/publicdomain/mark" in low or "public domain" in low:
        return "Public domain"
    if "creativecommons.org/licenses/by-sa/" in low or low.startswith("cc by-sa"):
        version = next((x for x in ("4.0", "3.0", "2.5", "2.0", "1.0") if x in low), "")
        return ("CC BY-SA " + version).strip()
    if "creativecommons.org/licenses/by/" in low or low.startswith("cc by"):
        version = next((x for x in ("4.0", "3.0", "2.5", "2.0", "1.0") if x in low), "")
        return ("CC BY " + version).strip()
    return None


def canonical_plantnet_license(value: str | None) -> str | None:
    """Default Pl@ntNet policy; the validated source adapter may extend it."""
    return canonical_open_license(value)


def https_url(value: str | None, *, upgrade_hosts: set[str] | None = None) -> str | None:
    raw = clean(value)
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
        return raw
    if parsed.scheme == "http" and parsed.hostname in (upgrade_hosts or set()):
        return "https://" + raw[len("http://"):]
    return None


def canonical_name(scientific_name: str | None, authorship: str | None = None) -> str:
    name = clean(scientific_name)
    author = clean(authorship)
    if author and name.endswith(author):
        return clean(name[:-len(author)])
    return name


@dataclass(frozen=True)
class Section:
    location: str
    id_index: int | None
    coreid_index: int | None
    fields: dict[str, int]
    defaults: dict[str, str]
    delimiter: str
    quotechar: str | None
    encoding: str
    headers: int


def _decoded(value: str | None, default: str) -> str:
    if not value:
        return default
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return value


def parse_dwca_meta(zf: zipfile.ZipFile) -> tuple[Section, list[tuple[str, Section]]]:
    root = ET.fromstring(zf.read("meta.xml"))

    def parse(node: ET.Element, is_core: bool) -> Section:
        files = next((x for x in node if term(x.tag) == "files"), None)
        loc = next((x for x in list(files or []) if term(x.tag) == "location"), None)
        if loc is None or not clean(loc.text):
            raise RuntimeError("Darwin Core section has no location")
        fields: dict[str, int] = {}
        defaults: dict[str, str] = {}
        id_index = coreid_index = None
        for child in node:
            kind = term(child.tag)
            if kind == "id":
                id_index = int(child.attrib["index"])
            elif kind == "coreid":
                coreid_index = int(child.attrib["index"])
            elif kind == "field" and "index" in child.attrib:
                key = term(child.attrib.get("term"))
                fields[key] = int(child.attrib["index"])
                if "default" in child.attrib:
                    defaults[key] = clean(child.attrib["default"])
        return Section(
            clean(loc.text),
            id_index,
            coreid_index,
            fields,
            defaults,
            _decoded(node.attrib.get("fieldsTerminatedBy"), "\t"),
            (_decoded(node.attrib.get("fieldsEnclosedBy"), '"') or None),
            node.attrib.get("encoding", "utf-8"),
            int(node.attrib.get("ignoreHeaderLines", "0") or 0),
        )

    core_node = next((x for x in root if term(x.tag) == "core"), None)
    if core_node is None:
        raise RuntimeError("Darwin Core archive has no core")
    core = parse(core_node, True)
    extensions = [
        (term(node.attrib.get("rowType")), parse(node, False))
        for node in root
        if term(node.tag) == "extension"
    ]
    return core, extensions


def iter_rows(zf: zipfile.ZipFile, section: Section) -> Iterable[list[str]]:
    with zf.open(section.location) as raw:
        text = io.TextIOWrapper(raw, encoding=section.encoding, errors="replace", newline="")
        kwargs = {"delimiter": section.delimiter}
        if section.quotechar:
            kwargs["quotechar"] = section.quotechar[0]
        else:
            kwargs["quoting"] = csv.QUOTE_NONE
        reader = csv.reader(text, **kwargs)
        for _ in range(section.headers):
            next(reader, None)
        yield from reader


def value(row: list[str], section: Section, name: str) -> str:
    idx = section.fields.get(name)
    if idx is not None and idx < len(row):
        out = clean(row[idx])
        if out:
            return out
    return clean(section.defaults.get(name))


def row_id(row: list[str], section: Section, *, extension: bool = False) -> str:
    idx = section.coreid_index if extension else section.id_index
    return clean(row[idx]) if idx is not None and idx < len(row) else ""


def load_catalog(path: Path) -> tuple[dict[str, str | None], int]:
    by_name: dict[str, str | None] = {}
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        count = int(conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0])
        for taxon_id, scientific_name in conn.execute("SELECT taxon_id,scientific_name FROM plant_index"):
            name = clean(scientific_name)
            if not name:
                continue
            tid = str(taxon_id)
            if name in by_name and by_name[name] != tid:
                by_name[name] = None
            elif name not in by_name:
                by_name[name] = tid
    return by_name, count


def make_asset(*, asset_id: str, taxon_id: str, image_url: str, thumbnail_url: str | None,
               source: str, source_record_id: str, source_dataset_id: str, license_name: str,
               license_raw: str, author: str | None, attribution_url: str, quality_rank: float,
               verified_taxon_name: str) -> dict:
    return {
        "asset_id": asset_id,
        "taxon_id": taxon_id,
        "thumbnail_url": thumbnail_url or image_url,
        "image_url": image_url,
        "source": source,
        "source_record_id": source_record_id,
        "source_dataset_id": source_dataset_id,
        "license": license_name,
        "license_raw": license_raw,
        "author": clean(author) or None,
        "attribution_url": attribution_url,
        "is_primary": 0,
        "quality_rank": float(quality_rank),
        "verified_taxon_name": verified_taxon_name,
        "local_filename": None,
        "materialized": 0,
        "materialization_error": None,
    }


def audit_plantnet(catalog_by_name: dict[str, str | None], archive: Path) -> tuple[dict[str, dict], dict]:
    stats = Counter()
    best: dict[str, dict] = {}
    with zipfile.ZipFile(archive) as zf:
        core, extensions = parse_dwca_meta(zf)
        media = next((s for kind, s in extensions if kind.lower() in {"multimedia", "image"}), None)
        if media is None:
            raise RuntimeError("Pl@ntNet archive has no Multimedia extension")
        occurrence: dict[str, tuple[str, str, str, str]] = {}
        for row in iter_rows(zf, core):
            stats["occurrence_rows"] += 1
            rid = row_id(row, core)
            if not rid:
                continue
            name = canonical_name(value(row, core, "scientificName"), value(row, core, "scientificNameAuthorship"))
            taxon_id = catalog_by_name.get(name)
            if not taxon_id:
                continue
            stats["exact_occurrence_rows"] += 1
            occurrence[rid] = (taxon_id, name, value(row, core, "references"), value(row, core, "license"))
        stats["exact_occurrence_taxa"] = len({x[0] for x in occurrence.values()})

        for row in iter_rows(zf, media):
            stats["media_rows"] += 1
            rid = row_id(row, media, extension=True)
            match = occurrence.get(rid)
            if match is None:
                continue
            taxon_id, name, reference, occurrence_license = match
            raw_license = value(row, media, "UsageTerms") or value(row, media, "rights") or occurrence_license
            licence = canonical_plantnet_license(raw_license)
            if not licence:
                stats["rejected_license_rows"] += 1
                continue
            image = https_url(value(row, media, "accessURI") or value(row, media, "identifier"))
            if not image:
                stats["rejected_url_rows"] += 1
                continue
            thumb = https_url(value(row, media, "identifier")) or image
            page = https_url(reference) or f"https://www.gbif.org/occurrence/search?dataset_key={PLANTNET_DATASET_KEY}"
            asset_key = clean(value(row, media, "identifier")) or image
            asset_id = "plantnet:" + hashlib.sha1(asset_key.encode("utf-8")).hexdigest()
            author = value(row, media, "creator")
            candidate = make_asset(
                asset_id=asset_id, taxon_id=taxon_id, image_url=image, thumbnail_url=thumb,
                source="plantnet_gbif", source_record_id=rid, source_dataset_id=PLANTNET_DATASET_KEY,
                license_name=licence, license_raw=raw_license, author=author, attribution_url=page,
                quality_rank=200.0 + (5.0 if author else 0.0), verified_taxon_name=name,
            )
            stats["eligible_media_rows"] += 1
            current = best.get(taxon_id)
            if current is None or (candidate["quality_rank"], candidate["asset_id"]) > (current["quality_rank"], current["asset_id"]):
                best[taxon_id] = candidate
    stats["eligible_taxa"] = len(best)
    return best, dict(stats)


def load_wfo_backbone(archive: Path) -> dict[str, str]:
    with zipfile.ZipFile(archive) as zf:
        core, _ = parse_dwca_meta(zf)
        raw: dict[str, tuple[str, str | None]] = {}
        for row in iter_rows(zf, core):
            wid = row_id(row, core) or value(row, core, "taxonID")
            if not wid:
                continue
            name = canonical_name(value(row, core, "scientificName"), value(row, core, "scientificNameAuthorship"))
            accepted = value(row, core, "acceptedNameUsageID") or None
            if name:
                raw[wid] = (name, accepted)
        out: dict[str, str] = {}
        for wid, (name, accepted) in raw.items():
            out[wid] = raw[accepted][0] if accepted and accepted in raw else name
        return out


def audit_wfo(catalog_by_name: dict[str, str | None], image_archive: Path,
              backbone_archive: Path) -> tuple[dict[str, dict], dict]:
    stats = Counter()
    best: dict[str, dict] = {}
    names = load_wfo_backbone(backbone_archive)
    stats["backbone_ids"] = len(names)
    with zipfile.ZipFile(image_archive) as zf:
        _, extensions = parse_dwca_meta(zf)
        image_section = next((s for kind, s in extensions if kind.lower() in {"image", "document"}), None)
        if image_section is None:
            raise RuntimeError("WFO archive has no image extension")
        for row in iter_rows(zf, image_section):
            stats["media_rows"] += 1
            wid = row_id(row, image_section, extension=True) or value(row, image_section, "taxonID")
            name = names.get(wid)
            if not name:
                stats["missing_backbone_name_rows"] += 1
                continue
            taxon_id = catalog_by_name.get(name)
            if not taxon_id:
                continue
            stats["exact_media_rows"] += 1
            raw_license = value(row, image_section, "license") or value(row, image_section, "UsageTerms")
            licence = canonical_open_license(raw_license)
            if not licence:
                stats["rejected_license_rows"] += 1
                continue
            upgrade = {"images.mobot.org"}
            image = https_url(value(row, image_section, "identifier") or value(row, image_section, "accessURI"), upgrade_hosts=upgrade)
            thumb = https_url(value(row, image_section, "source"), upgrade_hosts=upgrade)
            if not image:
                stats["rejected_url_rows"] += 1
                continue
            raw_id = clean(row[0] if row else "") or image
            asset_id = "wfo:" + hashlib.sha1(raw_id.encode("utf-8")).hexdigest()
            author = value(row, image_section, "creator")
            candidate = make_asset(
                asset_id=asset_id, taxon_id=taxon_id, image_url=image, thumbnail_url=thumb,
                source="world_flora_online", source_record_id=raw_id,
                source_dataset_id=f"{WFO_IMAGE_RESOURCE}:{WFO_RELEASE}", license_name=licence,
                license_raw=raw_license, author=author, attribution_url=f"{WFO_PORTAL}/taxon/{wid}",
                quality_rank=100.0 + (5.0 if author else 0.0) + (2.0 if thumb else 0.0),
                verified_taxon_name=name,
            )
            stats["eligible_media_rows"] += 1
            current = best.get(taxon_id)
            if current is None or (candidate["quality_rank"], candidate["asset_id"]) > (current["quality_rank"], current["asset_id"]):
                best[taxon_id] = candidate
    stats["eligible_taxa"] = len(best)
    return best, dict(stats)


def create_sidecar(path: Path, assets_by_source: dict[str, dict[str, dict]], metadata: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    all_assets: list[dict] = []
    by_taxon: dict[str, list[dict]] = {}
    for source_assets in assets_by_source.values():
        for asset in source_assets.values():
            all_assets.append(asset)
            by_taxon.setdefault(asset["taxon_id"], []).append(asset)
    for candidates in by_taxon.values():
        max(candidates, key=lambda x: (x["quality_rank"], x["asset_id"]))["is_primary"] = 1
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE media_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE plant_image_asset(
          asset_id TEXT PRIMARY KEY, taxon_id TEXT NOT NULL, thumbnail_url TEXT,
          image_url TEXT NOT NULL, source TEXT NOT NULL, source_record_id TEXT,
          source_dataset_id TEXT, license TEXT NOT NULL, license_raw TEXT, author TEXT,
          attribution_url TEXT, is_primary INTEGER NOT NULL DEFAULT 0,
          quality_rank REAL NOT NULL DEFAULT 0, verified_taxon_name TEXT NOT NULL,
          local_filename TEXT, materialized INTEGER NOT NULL DEFAULT 0,
          materialization_error TEXT);
        CREATE INDEX idx_media_v2_taxon ON plant_image_asset(taxon_id,is_primary DESC,quality_rank DESC);
        CREATE INDEX idx_media_v2_source ON plant_image_asset(source,taxon_id);
        """)
        conn.executemany("INSERT INTO media_metadata(key,value) VALUES(?,?)", sorted(metadata.items()))
        if all_assets:
            cols = list(all_assets[0].keys())
            marks = ",".join("?" for _ in cols)
            conn.executemany(
                f"INSERT INTO plant_image_asset({','.join(cols)}) VALUES({marks})",
                [[asset[col] for col in cols] for asset in all_assets],
            )
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Media sidecar integrity failure")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--plantnet", required=True, type=Path)
    ap.add_argument("--wfo-images", required=True, type=Path)
    ap.add_argument("--wfo-backbone", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args()

    catalog_by_name, catalog_total = load_catalog(args.catalog)
    plantnet, pstats = audit_plantnet(catalog_by_name, args.plantnet)
    wfo, wstats = audit_wfo(catalog_by_name, args.wfo_images, args.wfo_backbone)
    pset, wset = set(plantnet), set(wfo)
    union, overlap = pset | wset, pset & wset
    report = {
        "status": "ready", "catalog_taxa_total": catalog_total,
        "matching_policy": "exact_canonical_scientific_name",
        "license_policy": "Pl@ntNet: explicit open or unverified/ambiguous; WFO: CC0/Public Domain/CC BY/CC BY-SA; reject explicit NC/ND/restricted",
        "scoring_effect": False,
        "plantnet_gbif": {"dataset_key": PLANTNET_DATASET_KEY, "doi": PLANTNET_DATASET_DOI, **pstats,
                          "coverage_pct": round(len(pset) / catalog_total * 100, 4) if catalog_total else 0},
        "world_flora_online": {"release": WFO_RELEASE, "release_doi": WFO_RELEASE_DOI,
                               "image_resource": WFO_IMAGE_RESOURCE, **wstats,
                               "coverage_pct": round(len(wset) / catalog_total * 100, 4) if catalog_total else 0},
        "matrix": {"plantnet_only_taxa": len(pset - wset), "wfo_only_taxa": len(wset - pset),
                   "overlap_taxa": len(overlap), "cumulative_unique_taxa": len(union),
                   "cumulative_coverage_pct": round(len(union) / catalog_total * 100, 4) if catalog_total else 0},
        "input_sha256": {"catalog": sha256_file(args.catalog), "plantnet": sha256_file(args.plantnet),
                         "wfo_images": sha256_file(args.wfo_images), "wfo_backbone": sha256_file(args.wfo_backbone)},
    }
    metadata = {
        "media_version": "2.0.0", "source": "plantnet_gbif+world_flora_online",
        "image_scoring_effect": "false", "catalog_taxa_total": str(catalog_total),
        "media_primary_taxa": str(len(union)), "plantnet_taxa": str(len(pset)), "wfo_taxa": str(len(wset)),
        "overlap_taxa": str(len(overlap)), "coverage_pct": str(report["matrix"]["cumulative_coverage_pct"]),
        "matching_policy": report["matching_policy"], "license_policy": report["license_policy"],
        "plantnet_dataset_key": PLANTNET_DATASET_KEY, "wfo_release": WFO_RELEASE,
    }
    create_sidecar(args.output, {"plantnet_gbif": plantnet, "world_flora_online": wfo}, metadata)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
