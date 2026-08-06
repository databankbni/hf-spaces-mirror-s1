"""Sector overview panels (roadmap T4.3).

Loads a precomputed ``data/sector_overviews.json`` — neutral, general market/sector
overviews (structure, key players, market snapshot, drivers, risks, outlook) synthesized
from TBC Capital, Galt & Taggart and Georgia Capital sector research — and renders an
on-page panel in the Sector View. These are MARKET overviews, not investment opinions:
no ratings, price targets, or recommendations (that material lives on separate slides).

The file is built by ``Raw Data/sector_research/_build_neutral.py`` (which hard-fails on
any leaked deal codename / valuation-call language). It is committed and copied to the
HF Space by ``deploy.bat``. Override the path with ``SECTOR_OVERVIEWS_PATH``. Missing or
invalid file → ``{}`` → no panel renders.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "sector_overviews.json"
)


@st.cache_data(show_spinner=False, ttl=3600)
def load_sector_overviews() -> dict:
    """Return the {sector: overview} map, or {} when the file is absent/invalid."""
    path = os.environ.get("SECTOR_OVERVIEWS_PATH") or str(_DEFAULT_PATH)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def render_sector_overview(sector: str, container=None) -> bool:
    """Render the neutral market-overview panel for one sector. False if absent."""
    data = load_sector_overviews().get(sector)
    if not data:
        return False
    c = container if container is not None else st

    if data.get("headline"):
        c.markdown(f"**{data['headline']}**")
    if data.get("summary"):
        c.markdown(data["summary"])

    players = data.get("players") or []
    if players:
        c.markdown("**Key players**")
        c.markdown(
            "\n".join(
                f"- **{p.get('name', '')}**" + (f" — {p['note']}" if p.get("note") else "")
                for p in players
            )
        )

    stats = data.get("key_stats") or []
    if stats:
        c.markdown("**Market snapshot**")
        df = pd.DataFrame(
            [
                {"Metric": s.get("label", ""), "Value": str(s.get("value", "")), "Period": s.get("period", "")}
                for s in stats
            ]
        )
        c.dataframe(df, use_container_width=True, hide_index=True)

    drivers = data.get("drivers") or []
    risks = data.get("risks") or []
    if drivers or risks:
        dcol, rcol = c.columns(2)
        if drivers:
            dcol.markdown("**Growth drivers**")
            dcol.markdown("\n".join(f"- {d}" for d in drivers))
        if risks:
            rcol.markdown("**Challenges & risks**")
            rcol.markdown("\n".join(f"- {r}" for r in risks))

    if data.get("outlook"):
        c.markdown("**Outlook**")
        c.markdown(data["outlook"])

    sources = data.get("sources") or []
    if sources:
        c.caption(
            "Sources — "
            + "  ·  ".join(
                f"{s.get('firm', '')}: {s.get('title', '')} ({s.get('date', '')})" for s in sources
            )
        )
    if data.get("caveats"):
        c.caption("Note: " + str(data["caveats"]))
    return True
