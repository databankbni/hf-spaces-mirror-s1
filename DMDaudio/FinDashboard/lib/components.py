"""Shared designed UI states — empty / error cards (2026-07-02 review, U2).

Every view used to end its no-selection / no-data path in a bare
``st.info(...)`` + ``st.stop()`` one-liner, so first-time users got a wall of
plain text with no visual hierarchy and no suggested next step. These two
helpers give all modes one consistent, centered call-to-action card.

Both are plain render helpers (no session-state writes of their own). Action
callbacks run via ``st.button(on_click=...)`` — i.e. before the next script
run — so staging ``_pending_*`` keys or dialog-trigger flags inside them is
Sprint-26-safe by construction.
"""
from __future__ import annotations

from collections.abc import Callable

import streamlit as st

# (button label, widget key, on_click callback)
Action = tuple[str, str, Callable[[], None]]


def _state_card(
    title: str,
    body: str,
    icon: str,
    actions: list[Action] | None,
) -> None:
    with st.container(border=True):
        st.markdown(
            f"<div style='text-align:center;font-size:40px;line-height:1.1;"
            f"padding-top:8px'>{icon}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<h3 style='text-align:center;margin:4px 0 0 0'>{title}</h3>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<p style='text-align:center;opacity:0.75;margin:6px 0 10px 0'>{body}</p>",
            unsafe_allow_html=True,
        )
        if actions:
            # Center the action row: pad with empty side columns.
            side = max(1, 4 - len(actions))
            cols = st.columns([side, *([2] * len(actions)), side])
            for col, (label, key, cb) in zip(cols[1:-1], actions):
                with col:
                    st.button(label, key=key, on_click=cb, use_container_width=True)


def empty_state(
    title: str,
    body: str,
    icon: str = "🔍",
    actions: list[Action] | None = None,
) -> None:
    """Recoverable "nothing selected yet" card with optional action buttons.

    Callers still own the surrounding ``st.stop()`` — the card only renders.
    ``body`` accepts inline HTML/markdown-free text; keep it one or two short
    sentences pointing at the control that resolves the state.
    """
    _state_card(title, body, icon, actions)


def error_state(
    title: str,
    body: str,
    icon: str = "⚠️",
    actions: list[Action] | None = None,
) -> None:
    """Non-recoverable / data-problem card ("no data for this company",
    "download failed"). Visually identical to :func:`empty_state` except the
    icon default — the distinction is semantic, so call sites read correctly
    and a future restyle can diverge them without touching callers."""
    _state_card(title, body, icon, actions)
