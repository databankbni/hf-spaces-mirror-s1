#!/usr/bin/env python3
"""Validated source adapters for ClimaFlora Media v2.

This entrypoint adapts source-specific serialization and licensing rules while
keeping exact taxonomic matching and explicit provenance.

Pl@ntNet policy:
- known CC BY-SA / CC BY / CC0 / public-domain licences are normalized;
- explicit NC / ND / all-rights-reserved restrictions remain rejected;
- missing or ambiguous image licences are retained in production with the
  explicit label ``Pl@ntNet : licence non renseignée``.

WFO policy remains strict: only explicit open licences are retained.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import re
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).with_name("build_media_v2.py")
spec = importlib.util.spec_from_file_location("climaflora_media_v2_base", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load {BASE}")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

PLANTNET_UNVERIFIED_LICENSE = "Pl@ntNet : licence non renseignée"

_original_license = base.canonical_open_license
_original_value = base.value


def canonical_open_license(value: str | None) -> str | None:
    """Normalize explicit open licences without accepting NC/ND."""
    existing = _original_license(value)
    if existing:
        return existing
    raw = base.clean(value)
    low = raw.lower()
    if not low:
        return None
    if any(token in low for token in ("by-nc", "by-nd", "noncommercial", "no derivatives", "all rights reserved")):
        return None
    # Pl@ntNet/GBIF serializes many individual image licences as
    # "author (cc-by-sa)" or equivalent shorthand.
    if re.search(r"(?:^|[^a-z])cc[- ]by[- ]sa(?:[^a-z]|$)", low):
        return "CC BY-SA 4.0"
    if re.search(r"(?:^|[^a-z])cc[- ]by(?:[^a-z]|$)", low):
        return "CC BY 4.0"
    if re.search(r"(?:^|[^a-z])cc0(?:[^a-z]|$)", low):
        return "CC0 1.0"
    return None


def canonical_plantnet_license(value: str | None) -> str | None:
    """Accept Pl@ntNet missing/ambiguous licences, but never explicit NC/ND."""
    raw = base.clean(value)
    low = raw.lower()
    if raw == PLANTNET_UNVERIFIED_LICENSE:
        return PLANTNET_UNVERIFIED_LICENSE
    explicit = canonical_open_license(raw)
    if explicit:
        return explicit
    if any(token in low for token in ("by-nc", "by-nd", "noncommercial", "no derivatives", "all rights reserved")):
        return None
    return PLANTNET_UNVERIFIED_LICENSE


def source_value(row: list[str], section, name: str) -> str:
    """Bridge Pl@ntNet's image licence term while preserving missing status."""
    out = _original_value(row, section, name)
    if out:
        return out
    if name == "UsageTerms":
        raw = _original_value(row, section, "license")
        if raw:
            return raw
        # Pl@ntNet multimedia exposes accessURI; WFO's image extension does not.
        # This prevents an absent image licence from being silently replaced by
        # the occurrence-level dataset licence.
        if "accessURI" in section.fields:
            return PLANTNET_UNVERIFIED_LICENSE
    return out


def load_wfo_backbone(archive: Path) -> dict[str, str]:
    """Read WFO 2026-06 classification.csv directly by Darwin Core headers."""
    raw: dict[str, tuple[str, str | None]] = {}
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        if "classification.csv" not in names:
            return base.load_wfo_backbone(archive)
        with zf.open("classification.csv") as binary:
            text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline="")
            reader = csv.DictReader(text, delimiter="\t", quotechar='"')
            required = {"taxonID", "scientificName", "scientificNameAuthorship", "acceptedNameUsageID"}
            if not required <= set(reader.fieldnames or []):
                raise RuntimeError(f"Unexpected WFO backbone columns: {reader.fieldnames}")
            for row in reader:
                wid = base.clean(row.get("taxonID"))
                if not wid:
                    continue
                name = base.canonical_name(row.get("scientificName"), row.get("scientificNameAuthorship"))
                accepted = base.clean(row.get("acceptedNameUsageID")) or None
                if name:
                    raw[wid] = (name, accepted)
    out: dict[str, str] = {}
    for wid, (name, accepted) in raw.items():
        out[wid] = raw[accepted][0] if accepted and accepted in raw else name
    return out


base.canonical_open_license = canonical_open_license
base.canonical_plantnet_license = canonical_plantnet_license
base.value = source_value
base.load_wfo_backbone = load_wfo_backbone

if __name__ == "__main__":
    base.main()
