"""Persistent storage for user-saved Screener filter presets.

Single-tenant local storage: presets are read from / written to a JSON file
on the project root (``saved_filters.json``). Reads are cached briefly via
Streamlit so repeated calls in a single rerun don't hit the disk.

Shape on disk: ``{preset_name: [{metric, op, value, logic}, ...]}``.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

# Local JSON file — canonical (and only) storage location.
_LOCAL_PATH = Path(__file__).parent.parent / "saved_filters.json"


@st.cache_data(ttl=60, show_spinner=False)
def load_filters() -> dict[str, list[dict]]:
    """Load saved screener filter presets as ``{name: [filter_dict, ...]}``.

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


def save_filters(filters: dict[str, list[dict]]) -> tuple[bool, str]:
    """Persist the full presets dict to the local JSON file.

    Returns ``(success, message_for_user)``.
    """
    try:
        _LOCAL_PATH.write_text(
            json.dumps(filters, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        return False, f"Local save failed: {e}"
    load_filters.clear()
    return True, "Saved locally."


def add_filter_preset(name: str, filters_list: list[dict]) -> tuple[bool, str]:
    """Add or overwrite a named preset. ``filters_list`` is the same shape
    as ``st.session_state['screener_filters']`` — a list of
    ``{metric, op, value, logic}`` dicts."""
    name = name.strip()
    if not name:
        return False, "Preset name can't be empty."
    if not filters_list:
        return False, "Preset must have at least one filter."
    presets = dict(load_filters())
    # Strip any non-essential keys; only persist the four canonical fields.
    cleaned = []
    for f in filters_list:
        cleaned.append({
            "metric": str(f.get("metric") or "").strip(),
            "op": str(f.get("op") or ">").strip(),
            "value": str(f.get("value") or "").strip(),
            "logic": str(f.get("logic") or "and").strip(),
        })
    presets[name] = cleaned
    return save_filters(presets)


def delete_filter_preset(name: str) -> tuple[bool, str]:
    """Remove a named preset and persist."""
    presets = dict(load_filters())
    if name not in presets:
        return False, f"No preset named '{name}'."
    del presets[name]
    return save_filters(presets)
