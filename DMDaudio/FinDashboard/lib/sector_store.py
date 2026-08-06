"""Persistent storage for user-saved sectors.

Single-tenant local storage: sectors are read from / written to a JSON file
on the project root (``saved_sectors.json``). Reads are cached briefly via
Streamlit so repeated calls in a single rerun don't hit the disk.

Shape on disk: ``{sector_name: [idcode, ...]}``.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

# Local JSON file — canonical (and only) storage location.
_LOCAL_PATH = Path(__file__).parent.parent / "saved_sectors.json"


@st.cache_data(ttl=60, show_spinner=False)
def load_sectors() -> dict[str, list[str]]:
    """Load saved sectors as ``{name: [idcodes]}``.

    Reads the local JSON file. Returns ``{}`` if the file is missing or
    unparseable. Cached for 60s so repeated reads inside a single render
    pass don't repeatedly hit the disk.
    """
    if _LOCAL_PATH.exists():
        try:
            data = json.loads(_LOCAL_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}


def save_sectors(sectors: dict[str, list[str]]) -> tuple[bool, str]:
    """Persist the full sectors dict to the local JSON file.

    Returns ``(success, message_for_user)``.
    """
    try:
        _LOCAL_PATH.write_text(
            json.dumps(sectors, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        return False, f"Local save failed: {e}"
    load_sectors.clear()
    return True, "Saved locally."


def add_sector(name: str, idcodes: list[str]) -> tuple[bool, str]:
    """Add or overwrite a named sector and persist."""
    name = name.strip()
    if not name:
        return False, "Sector name can't be empty."
    sectors = dict(load_sectors())
    # Dedup + filter empty strings
    clean = sorted(set(c.strip() for c in idcodes if c.strip()))
    if not clean:
        return False, "Sector must have at least one IdCode."
    sectors[name] = clean
    return save_sectors(sectors)


def delete_sector(name: str) -> tuple[bool, str]:
    """Remove a named sector and persist."""
    sectors = dict(load_sectors())
    if name not in sectors:
        return False, f"No sector named '{name}'."
    del sectors[name]
    return save_sectors(sectors)


def parse_idcode_list(text: str) -> list[str]:
    """Parse a user-pasted blob of IdCodes (comma / whitespace / newline separated)."""
    if not text:
        return []
    # Allow comma, semicolon, whitespace, newlines as separators.
    import re
    tokens = re.split(r"[,;\s]+", text.strip())
    return [t for t in tokens if t]
