"""In-app "Ask Claude" chat sidebar (T4.1b) — thin Streamlit wiring.

All model/tool logic lives in ``lib/chat.py`` (pure, no Streamlit). This module
only renders the sidebar surface and manages the ephemeral chat state in
``st.session_state``. Rendered once from ``app.py`` on every mode.

Sprint-26 rule (CLAUDE.md #3): the only session_state keys written after a
widget instantiates are ``chat_history`` / ``chat_turns`` — NOT the widget keys
(``chat_prompt`` / ``chat_clear``) — and every write is followed by ``st.rerun``.
``st.chat_input`` is the sanctioned input widget.
"""
from __future__ import annotations

import os

import streamlit as st

from lib.chat import MAX_TURNS, run_chat_turn


def _get_api_key() -> str | None:
    """Resolve the Anthropic key: st.secrets first, then env. None if absent."""
    key = None
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:  # noqa: BLE001 - no secrets.toml at all raises here
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY") or None


def render_chat_sidebar(ctx) -> None:
    """Render the "Ask Claude" chat section into the sidebar.

    Lives inside a collapsed ``st.expander`` (hidden by default, click to open)
    at the very bottom of the sidebar — app.py renders it after the per-view
    controls. ``st.chat_input`` renders inline inside the expander (allowed since
    Streamlit 1.46; our floor is 1.55). No key configured → a friendly "not
    configured" caption (never crashes).
    """
    with st.sidebar:
        # Keyed container so inject_brand_css()'s flex-`order` rule can dock this
        # whole block to the BOTTOM of the sidebar. It renders before the per-view
        # controls (to survive st.stop() on empty states) but displays last; see
        # app.py's dispatch note and the .st-key-ask_claude_dock rule in lib/ui.py.
        with st.container(key="ask_claude_dock"):
            # A consistent group header (matches the filter-view sidebar groups);
            # its trailing rule doubles as the divider from the per-view controls
            # above. Rendered inside the dock container so it floats to the bottom
            # with the expander (see the flex-order rule in lib/ui.py).
            st.markdown('<div class="fd-sbgroup">Assistant</div>', unsafe_allow_html=True)
            with st.expander("🤖 Ask Claude", expanded=False):
                api_key = _get_api_key()
                if not api_key:
                    st.caption(
                        "Chat not configured. Add `ANTHROPIC_API_KEY` to "
                        "`.streamlit/secrets.toml` (local) or a Space secret to enable it."
                    )
                    return

                history: list[dict[str, str]] = st.session_state.setdefault("chat_history", [])
                turns: int = int(st.session_state.get("chat_turns", 0))
                cap_hit = turns >= MAX_TURNS

                # Transcript (scrollable, fixed height so a long chat doesn't blow
                # the expander open to full length).
                box = st.container(height=340, border=True)
                if history:
                    for m in history:
                        box.chat_message(m["role"]).write(m["content"])
                else:
                    box.caption(
                        "Ask about companies, sectors, metrics, or GDP penetration — "
                        "answers are grounded in the dashboard's data and cite IdCode + year."
                    )

                if cap_hit:
                    st.caption(f"Session limit reached ({MAX_TURNS} questions). Clear to continue.")
                if history and st.button("Clear chat", key="chat_clear", use_container_width=True):
                    st.session_state["chat_history"] = []
                    st.session_state["chat_turns"] = 0
                    st.rerun()

                prompt = st.chat_input(
                    "Ask about the data…",
                    key="chat_prompt",
                    disabled=cap_hit,
                )
                if prompt:
                    with st.spinner("Claude is researching…"):
                        try:
                            answer, _tools = run_chat_turn(
                                list(history),
                                prompt,
                                api_key=api_key,
                                db_path=ctx.db_path,
                            )
                        except Exception as e:  # noqa: BLE001 - show the error, don't crash
                            answer = f"⚠️ Chat error: {type(e).__name__}: {e}"
                    history.append({"role": "user", "content": prompt})
                    history.append({"role": "assistant", "content": answer})
                    st.session_state["chat_history"] = history
                    st.session_state["chat_turns"] = turns + 1
                    st.rerun()
