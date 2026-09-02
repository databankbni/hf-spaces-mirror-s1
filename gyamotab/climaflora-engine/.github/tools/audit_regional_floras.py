#!/usr/bin/env python3
"""Inspect regional-flora Darwin Core Archives for ClimaFlora Media candidates."""
from __future__ import annotations

import argparse
import csv
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path


def clean(value) -> str:
    return " ".join(str(value or "").strip().split())


def term(value: str | None) -> str:
    text = clean(value)
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    return text.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def decoded(value: str | None, default: str) -> str:
    if not value:
        return default
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return value


def section_info(node: ET.Element) -> dict:
    files = next((x for x in node if term(x.tag) == "files"), None)
    loc = next((x for x in list(files or []) if term(x.tag) == "location"), None)
    fields: dict[str, int] = {}
    defaults: dict[str, str] = {}
    id_index = coreid_index = None
    for child in node:
        kind = term(child.tag)
        if kind == "id" and "index" in child.attrib:
            id_index = int(child.attrib["index"])
        elif kind == "coreid" and "index" in child.attrib:
            coreid_index = int(child.attrib["index"])
        elif kind == "field" and "index" in child.attrib:
            key = term(child.attrib.get("term"))
            fields[key] = int(child.attrib["index"])
            if "default" in child.attrib:
                defaults[key] = clean(child.attrib["default"])
    return {
        "row_type": term(node.attrib.get("rowType")),
        "location": clean(loc.text if loc is not None else ""),
        "id_index": id_index,
        "coreid_index": coreid_index,
        "fields": fields,
        "defaults": defaults,
        "delimiter": decoded(node.attrib.get("fieldsTerminatedBy"), "\t"),
        "quotechar": decoded(node.attrib.get("fieldsEnclosedBy"), '"') or None,
        "encoding": node.attrib.get("encoding", "utf-8"),
        "headers": int(node.attrib.get("ignoreHeaderLines", "0") or 0),
    }


def iter_rows(zf: zipfile.ZipFile, section: dict):
    with zf.open(section["location"]) as binary:
        text = io.TextIOWrapper(binary, encoding=section["encoding"], errors="replace", newline="")
        kwargs = {"delimiter": section["delimiter"]}
        if section["quotechar"]:
            kwargs["quotechar"] = section["quotechar"][0]
        else:
            kwargs["quoting"] = csv.QUOTE_NONE
        reader = csv.reader(text, **kwargs)
        for _ in range(section["headers"]):
            next(reader, None)
        yield from reader


def value(row: list[str], section: dict, name: str) -> str:
    idx = section["fields"].get(name)
    if idx is not None and idx < len(row):
        out = clean(row[idx])
        if out:
            return out
    return clean(section["defaults"].get(name))


def audit_archive(label: str, path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if "meta.xml" not in names:
            return {"label": label, "archive": str(path), "error": "missing meta.xml", "files": names[:100]}
        root = ET.fromstring(zf.read("meta.xml"))
        nodes = [x for x in root if term(x.tag) in {"core", "extension"}]
        sections = [section_info(node) for node in nodes]
        out = {
            "label": label,
            "archive": str(path),
            "archive_size": path.stat().st_size,
            "files": names,
            "sections": [],
        }
        for section in sections:
            summary = {
                "row_type": section["row_type"],
                "location": section["location"],
                "id_index": section["id_index"],
                "coreid_index": section["coreid_index"],
                "fields": section["fields"],
                "defaults": section["defaults"],
            }
            rows = 0
            core_ids = set()
            licenses = Counter()
            identifiers = 0
            names_present = 0
            samples = []
            for row in iter_rows(zf, section):
                rows += 1
                if section["coreid_index"] is not None and section["coreid_index"] < len(row):
                    cid = clean(row[section["coreid_index"]])
                    if cid:
                        core_ids.add(cid)
                licence = value(row, section, "license") or value(row, section, "UsageTerms") or value(row, section, "rights")
                if licence:
                    licenses[licence] += 1
                else:
                    licenses["<blank>"] += 1
                if value(row, section, "identifier") or value(row, section, "accessURI"):
                    identifiers += 1
                if value(row, section, "scientificName") or value(row, section, "taxonID"):
                    names_present += 1
                if len(samples) < 3:
                    sample = {}
                    for key in ("taxonID", "scientificName", "acceptedNameUsageID", "identifier", "accessURI", "source", "license", "UsageTerms", "rights", "creator", "references"):
                        v = value(row, section, key)
                        if v:
                            sample[key] = v
                    if section["coreid_index"] is not None and section["coreid_index"] < len(row):
                        sample["coreid"] = clean(row[section["coreid_index"]])
                    if section["id_index"] is not None and section["id_index"] < len(row):
                        sample["id"] = clean(row[section["id_index"]])
                    samples.append(sample)
            summary.update({
                "rows": rows,
                "distinct_core_ids": len(core_ids),
                "identifier_rows": identifiers,
                "taxon_reference_rows": names_present,
                "license_top": licenses.most_common(20),
                "samples": samples,
            })
            out["sections"].append(summary)
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="append", required=True, help="LABEL=/path/archive.zip")
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    reports = []
    for spec in args.archive:
        label, raw_path = spec.split("=", 1)
        reports.append(audit_archive(label, Path(raw_path)))
    payload = {"status": "ready", "archives": reports}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
