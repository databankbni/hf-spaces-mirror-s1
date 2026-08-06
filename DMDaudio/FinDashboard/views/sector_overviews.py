"""Sector Overviews — hub for curated, interactive sector dashboards.

A landing page that hosts one rich overview per sector. Today it carries the
**Insurance** market dashboard; more sectors will be added over time — register a
new ``render(ctx)`` in ``_OVERVIEWS`` and it appears in the picker automatically.

Distinct from ``lib/sector_overviews.py`` (which renders neutral *text* market-overview
panels inside the Sectoral Data view) — this is the top-nav page for full dashboards.
"""
from __future__ import annotations

import streamlit as st

import views.insurance as _insurance
from views.shared import ViewContext

# Display label -> (emoji, render_fn).  Add future sector overviews here.
_OVERVIEWS: dict[str, tuple[str, callable]] = {
    "Insurance": ("🛡️", _insurance.render),
}

_PICK_KEY = "sectoroverview_pick"


def render(ctx: ViewContext) -> None:
    labels = list(_OVERVIEWS)

    # Seed the default selection once, BEFORE the widget instantiates (Sprint-26 safe).
    if _PICK_KEY not in st.session_state:
        st.session_state[_PICK_KEY] = labels[0]

    st.pills(
        "Sector overview",
        labels,
        format_func=lambda lbl: f"{_OVERVIEWS[lbl][0]} {lbl}",
        key=_PICK_KEY,
    )
    st.caption("Pick a sector. More sector overviews coming soon.")

    pick = st.session_state.get(_PICK_KEY)
    if pick is None:  # user deselected the active pill
        st.info("👆 Choose a sector overview to view.")
        return

    st.divider()
    _OVERVIEWS[pick][1](ctx)
