#!/usr/bin/env python3
"""Add deterministic GBIF vernacular-name and media metadata to catalog v1.6.

Rules: exact canonical scientific-name equality only; unique accepted Plantae
GBIF usages only; no fuzzy fallback. Individual media licences are retained and
only licences compatible with local resized-thumbnail reuse are admitted.
Images are illustrative metadata, never botanical-identification evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

CATALOG_VERSION = "1.7.0"
METHOD = "GBIF_BACKBONE_EXACT_NAMES_MEDIA"
METHOD_VERSION = "1.0"
SOURCE_REF = "GBIF Backbone Taxonomy Darwin Core Archive"
SOURCE_LICENSE = "CC BY 4.0 backbone metadata; individual media licence retained"
# GBIF DWCA rows can contain long reference/description fields. Python's csv
# parser defaults to ~128 KiB, which is too small for the official backbone.
CSV_FIELD_SIZE_LIMIT = 64 * 1024 * 1024
try:
    csv.field_size_limit(CSV_FIELD_SIZE_LIMIT)
except OverflowError:
    csv.field_size_limit(16 * 1024 * 1024)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def clean(v) -> str:
    return " ".join(str(v or "").strip().split())


def term(v: str | None) -> str:
    x = clean(v)
    if "}" in x:
        x = x.rsplit("}", 1)[-1]
    return x.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _decoded(v: str | None, default: str) -> str:
    if not v:
        return default
    try:
        return bytes(v, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return v


def normalize_language(v: str | None) -> str | None:
    x = clean(v).lower().replace("_", "-")
    aliases = {
        "french": "fr", "français": "fr", "francais": "fr", "fra": "fr", "fre": "fr",
        "english": "en", "eng": "en", "german": "de", "deu": "de", "ger": "de",
        "spanish": "es", "spa": "es", "italian": "it", "ita": "it",
        "portuguese": "pt", "por": "pt",
    }
    if not x:
        return None
    x = aliases.get(x, x)
    return x[:2] if len(x) >= 2 and (len(x) == 2 or x[2:3] == "-") else x[:24]


def http_url(v: str | None) -> str | None:
    x = clean(v)
    if not x:
        return None
    p = urlparse(x)
    return x if p.scheme in {"http", "https"} and p.netloc else None


def canonical_open_license(v: str | None) -> tuple[str | None, int]:
    raw = clean(v)
    x = raw.lower()
    if not x:
        return None, 99
    if "creativecommons.org/publicdomain/zero" in x or x in {"cc0", "cc0 1.0"}:
        return "CC0 1.0", 0
    if "creativecommons.org/publicdomain/mark" in x or "public domain" in x:
        return "Public domain", 0
    if "creativecommons.org/licenses/by-sa/" in x or x.startswith("cc by-sa"):
        version = next((n for n in ("4.0", "3.0", "2.5", "2.0", "1.0") if n in x), "")
        return ("CC BY-SA " + version).strip(), 2
    if "creativecommons.org/licenses/by/" in x or x.startswith("cc by"):
        if any(bad in x for bad in ("by-nc", "by-nd", "noncommercial", "no derivatives")):
            return None, 99
        version = next((n for n in ("4.0", "3.0", "2.5", "2.0", "1.0") if n in x), "")
        return ("CC BY " + version).strip(), 1
    return None, 99


@dataclass(frozen=True)
class Section:
    location: str
    id_index: int | None
    coreid_index: int | None
    fields: dict[str, int]
    delimiter: str
    quotechar: str
    encoding: str
    headers: int


def parse_dwca_meta(zf: zipfile.ZipFile) -> tuple[Section, dict[str, Section]]:
    root = ET.fromstring(zf.read("meta.xml"))

    def parse(node: ET.Element, core: bool) -> Section:
        files = next((c for c in node if term(c.tag) == "files"), None)
        children = list(files) if files is not None else []
        loc = next((c for c in children if term(c.tag) == "location"), None)
        if loc is None or not clean(loc.text):
            raise RuntimeError("DWCA section lacks location")
        fields: dict[str, int] = {}
        id_index = coreid_index = None
        for child in node:
            kind = term(child.tag)
            if kind == "id": id_index = int(child.attrib["index"])
            elif kind == "coreid": coreid_index = int(child.attrib["index"])
            elif kind == "field" and "index" in child.attrib:
                fields[term(child.attrib.get("term"))] = int(child.attrib["index"])
        if core and id_index is None: raise RuntimeError("Taxon core lacks id")
        if not core and coreid_index is None: raise RuntimeError("extension lacks coreid")
        return Section(
            clean(loc.text), id_index, coreid_index, fields,
            _decoded(node.attrib.get("fieldsTerminatedBy"), "\t"),
            _decoded(node.attrib.get("fieldsEnclosedBy"), '"') or '"',
            node.attrib.get("encoding", "utf-8"),
            int(node.attrib.get("ignoreHeaderLines", "0") or 0),
        )

    core_node = next((n for n in root if term(n.tag) == "core"), None)
    if core_node is None or term(core_node.attrib.get("rowType")) != "Taxon":
        raise RuntimeError("DWCA Taxon core not found")
    core = parse(core_node, True)
    extensions = {
        term(n.attrib.get("rowType")): parse(n, False)
        for n in root if term(n.tag) == "extension" and term(n.attrib.get("rowType"))
    }
    return core, extensions


def iter_rows(zf: zipfile.ZipFile, s: Section) -> Iterable[list[str]]:
    with zf.open(s.location) as raw:
        text = io.TextIOWrapper(raw, encoding=s.encoding, errors="replace", newline="")
        reader = csv.reader(text, delimiter=s.delimiter, quotechar=s.quotechar[0])
        for _ in range(s.headers): next(reader, None)
        yield from reader


def val(row: list[str], s: Section, name: str) -> str:
    i = s.fields.get(name)
    return clean(row[i]) if i is not None and i < len(row) else ""


def row_id(row: list[str], s: Section, *, extension=False) -> str:
    i = s.coreid_index if extension else s.id_index
    return clean(row[i]) if i is not None and i < len(row) else ""


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    DROP TABLE IF EXISTS plant_vernacular_name;
    CREATE TABLE plant_vernacular_name(
      vernacular_id INTEGER PRIMARY KEY, taxon_id TEXT NOT NULL, name TEXT NOT NULL,
      language TEXT, source_dataset_id TEXT, source_ref TEXT NOT NULL,
      is_preferred INTEGER NOT NULL DEFAULT 0, confidence TEXT NOT NULL DEFAULT 'C',
      match_method TEXT NOT NULL, UNIQUE(taxon_id,name,language,source_ref));
    CREATE INDEX idx_cf_vernacular_taxon ON plant_vernacular_name(taxon_id);
    CREATE INDEX idx_cf_vernacular_name ON plant_vernacular_name(name COLLATE NOCASE);
    DROP TABLE IF EXISTS plant_image_asset;
    CREATE TABLE plant_image_asset(
      asset_id TEXT PRIMARY KEY, taxon_id TEXT NOT NULL, thumbnail_url TEXT,
      image_url TEXT NOT NULL, source TEXT NOT NULL, source_record_id TEXT,
      source_dataset_id TEXT, license TEXT NOT NULL, license_raw TEXT, author TEXT,
      attribution_url TEXT, is_primary INTEGER NOT NULL DEFAULT 0,
      quality_rank REAL NOT NULL DEFAULT 0, verified_taxon_name TEXT NOT NULL,
      local_filename TEXT, materialized INTEGER NOT NULL DEFAULT 0,
      materialization_error TEXT);
    CREATE INDEX idx_cf_image_taxon ON plant_image_asset(taxon_id,is_primary DESC,quality_rank DESC);
    CREATE INDEX idx_cf_image_materialized ON plant_image_asset(materialized,is_primary);
    """)


def metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO climaflora_catalog_metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,value))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='build_metadata'").fetchone():
        conn.execute("INSERT INTO build_metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,value))


def build(base: Path, gbif: Path, output: Path, report_path: Path) -> dict:
    if not zipfile.is_zipfile(gbif): raise RuntimeError("invalid GBIF ZIP")
    tmp = output.with_suffix(output.suffix + ".building")
    tmp.unlink(missing_ok=True)
    shutil.copy2(base, tmp)
    source_sha = sha256_file(gbif)
    stats = defaultdict(int)

    with sqlite3.connect(tmp) as conn, zipfile.ZipFile(gbif) as zf:
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"plant_index","climaflora_catalog_metadata"} <= tables:
            raise RuntimeError("base catalog missing plant_index/metadata")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise RuntimeError("base integrity failure")
        protected = [t for t in ("plant_index","climate_envelope","soil_envelope","soil_categorical_preference","soil_indicator_preference","soil_geographic_prior") if t in tables]
        before = {t:int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in protected}

        cf_by_name: dict[str,str|None] = {}
        for r in conn.execute("SELECT taxon_id,scientific_name FROM plant_index"):
            name = clean(r["scientific_name"])
            if name in cf_by_name and cf_by_name[name] != str(r["taxon_id"]): cf_by_name[name] = None
            elif name not in cf_by_name: cf_by_name[name] = str(r["taxon_id"])

        core, ext = parse_dwca_meta(zf)
        vern = ext.get("VernacularName"); media = ext.get("Multimedia")
        if vern is None or media is None: raise RuntimeError("GBIF archive lacks VernacularName or Multimedia extension")

        name_candidate: dict[str,tuple[str,str|None]|None] = {}
        for r in iter_rows(zf, core):
            stats["gbif_core_rows"] += 1
            if val(r,core,"kingdom") and val(r,core,"kingdom").lower() != "plantae": continue
            status = val(r,core,"taxonomicStatus").lower()
            if status and status != "accepted": continue
            name = val(r,core,"canonicalName") or val(r,core,"scientificName")
            if not name or cf_by_name.get(name) is None: continue
            cid = row_id(r,core)
            if not cid: continue
            candidate = (cid, val(r,core,"datasetID") or None)
            if name not in name_candidate: name_candidate[name] = candidate
            elif name_candidate[name] != candidate: name_candidate[name] = None

        gbif_to_cf: dict[str,tuple[str,str,str|None]] = {}
        for name,candidate in name_candidate.items():
            if candidate is None:
                stats["ambiguous_exact_names"] += 1; continue
            cid,dataset = candidate
            taxon_id = cf_by_name.get(name)
            if taxon_id: gbif_to_cf[cid] = (taxon_id,name,dataset)
        stats["exact_matched_taxa"] = len({v[0] for v in gbif_to_cf.values()})
        create_tables(conn)

        seen: set[tuple[str,str,str|None]] = set(); names=[]; best: dict[str,tuple[int,str,str|None]] = {}
        for r in iter_rows(zf, vern):
            stats["gbif_vernacular_rows"] += 1
            m = gbif_to_cf.get(row_id(r,vern,extension=True))
            if not m: continue
            taxon_id,scientific,dataset = m
            name = val(r,vern,"vernacularName"); lang = normalize_language(val(r,vern,"language"))
            if not name or len(name)>200 or name.casefold()==scientific.casefold(): continue
            k=(taxon_id,name.casefold(),lang)
            if k in seen: continue
            seen.add(k)
            preferred = val(r,vern,"isPreferredName").lower() in {"true","1","yes"}
            source = val(r,vern,"source") or SOURCE_REF
            names.append((taxon_id,name,lang,dataset,source[:1000],int(preferred),"C","GBIF_BACKBONE_EXACT_CANONICAL_NAME"))
            priority={"fr":0,"en":1}.get(lang,3) - int(preferred)
            candidate=(priority,name,lang or "")
            if taxon_id not in best or candidate < best[taxon_id]: best[taxon_id]=candidate
        conn.executemany("INSERT OR IGNORE INTO plant_vernacular_name(taxon_id,name,language,source_dataset_id,source_ref,is_preferred,confidence,match_method) VALUES(?,?,?,?,?,?,?,?)", names)
        for taxon_id,(_,name,_) in best.items():
            conn.execute("UPDATE plant_index SET common_name=? WHERE taxon_id=? AND (common_name IS NULL OR trim(common_name)='')", (name,taxon_id))

        by_taxon: dict[str,list[tuple]] = defaultdict(list)
        for r in iter_rows(zf, media):
            stats["gbif_multimedia_rows"] += 1
            m=gbif_to_cf.get(row_id(r,media,extension=True))
            if not m: continue
            taxon_id,scientific,dataset=m
            typ=(val(r,media,"type") or val(r,media,"format")).lower(); fmt=val(r,media,"format").lower()
            if typ and "image" not in typ and not fmt.startswith("image/"): continue
            image=http_url(val(r,media,"identifier"))
            if not image: continue
            license_raw=val(r,media,"license") or val(r,media,"rights")
            license_name,license_rank=canonical_open_license(license_raw)
            if not license_name:
                stats["media_rejected_license"] += 1; continue
            author=val(r,media,"creator") or val(r,media,"rightsHolder") or None
            attr=http_url(val(r,media,"references")) or image
            seed="\x1f".join((taxon_id,image,license_name)).encode()
            asset="gbif-"+hashlib.sha256(seed).hexdigest()[:24]
            quality=100-10*license_rank+(5 if author else 0)+(3 if attr!=image else 0)
            by_taxon[taxon_id].append((asset,taxon_id,None,image,SOURCE_REF,(val(r,media,"title") or image)[:1000],dataset,license_name,license_raw[:500],author[:500] if author else None,attr,0,quality,scientific,None,0,None))
        media_rows=[]
        for _, candidates in by_taxon.items():
            candidates.sort(key=lambda x:(-x[12],x[0]))
            for i,row in enumerate(candidates[:3]):
                x=list(row); x[11]=int(i==0); media_rows.append(tuple(x))
        conn.executemany("INSERT OR IGNORE INTO plant_image_asset(asset_id,taxon_id,thumbnail_url,image_url,source,source_record_id,source_dataset_id,license,license_raw,author,attribution_url,is_primary,quality_rank,verified_taxon_name,local_filename,materialized,materialization_error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", media_rows)

        queries={
            "vernacular_rows":"SELECT COUNT(*) FROM plant_vernacular_name",
            "vernacular_taxa":"SELECT COUNT(DISTINCT taxon_id) FROM plant_vernacular_name",
            "french_vernacular_taxa":"SELECT COUNT(DISTINCT taxon_id) FROM plant_vernacular_name WHERE language='fr'",
            "english_vernacular_taxa":"SELECT COUNT(DISTINCT taxon_id) FROM plant_vernacular_name WHERE language='en'",
            "common_name_filled":"SELECT COUNT(*) FROM plant_index WHERE common_name IS NOT NULL AND trim(common_name)<>''",
            "eligible_media_rows":"SELECT COUNT(*) FROM plant_image_asset",
            "eligible_media_taxa":"SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset",
        }
        for k,q in queries.items(): stats[k]=int(conn.execute(q).fetchone()[0])
        for k,v in {
            "catalog_version":CATALOG_VERSION,"names_media_method":METHOD,"names_media_method_version":METHOD_VERSION,
            "names_media_source_ref":SOURCE_REF,"names_media_source_sha256":source_sha,
            "names_media_source_license":SOURCE_LICENSE,"image_identification_evidence":"false",
            "image_materialization_complete":"false",
        }.items(): metadata(conn,k,v)
        conn.commit()
        after={t:int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in protected}
        if after != before: raise RuntimeError(f"protected row-count drift: {before} -> {after}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise RuntimeError("v1.7 integrity failure")

    os.replace(tmp,output)
    report={
        "catalog_version":CATALOG_VERSION,"method":METHOD,"method_version":METHOD_VERSION,
        "source_ref":SOURCE_REF,"source_sha256":source_sha,"source_license":SOURCE_LICENSE,
        "base_counts":before,"stats":dict(sorted(stats.items())),"sqlite_bytes":output.stat().st_size,
        "sqlite_sha256":sha256_file(output),
        "limitations":[
            "Exact unique accepted canonical-name equality only; ambiguous names remain unmatched.",
            "Individual media licences are retained; non-open/ND/NC media are excluded.",
            "Images are illustrative only and never identification/adaptation evidence.",
            "Media stay metadata-only until local thumbnail materialization succeeds.",
        ],
    }
    report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(); p.add_argument("--base",type=Path,required=True); p.add_argument("--gbif",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(); print(json.dumps(build(a.base,a.gbif,a.output,a.report),indent=2,ensure_ascii=False))

if __name__=="__main__": main()
# v1.7 corrected-parser rerun trigger 2026-08-19
