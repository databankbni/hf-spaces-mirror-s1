"""Lightweight usage tracking for the Streamlit app.

Two independent layers, both no-op-safe (mirrors the optional-feature pattern
of ``lib/auth`` and the chat sidebar — nothing here can crash the app):

1. **Server-side session counter (always on).** Counts sessions this process has
   served since boot + a rolling "active in the last N minutes" gauge, and
   prints a structured ``[usage]`` line to stdout on each new session so it
   surfaces in the HF Space logs (grep-able, zero external dependencies). The
   process is single (one Streamlit server), so a module-global under a lock is
   an accurate per-deployment counter. Resets on Space restart — for durable
   history use layer 2 or scrape the logs.

2. **Client-side web analytics (opt-in via env / st.secrets).** If any of
   ``PLAUSIBLE_DOMAIN`` / ``POSTHOG_KEY`` / ``ANALYTICS_HEAD_HTML`` is set, the
   matching snippet is injected into the PARENT document's <head>. Streamlit
   renders ``components.html`` inside a same-origin iframe, so we reach
   ``window.parent.document`` (the exact trick app.py already uses for the "/"
   search shortcut). No config → nothing injected, no network calls.

Wire-up: call :func:`track_session` once per run, right after the login gate.
"""
from __future__ import annotations

import html
import json
import os
import threading
import time
import uuid

import streamlit as st
import streamlit.components.v1 as components

# Count a session "active" if seen within this window (seconds).
_ACTIVE_WINDOW = int(os.environ.get("USAGE_ACTIVE_WINDOW_S", "900"))

_lock = threading.Lock()
_state = {"total": 0, "active": {}}  # active: token -> last_seen_ts


# --- config lookup (env first, then st.secrets, both optional) --------------
def _cfg(name: str) -> str | None:
    val = os.environ.get(name)
    if val:
        return val
    try:
        # st.secrets raises if there is no secrets.toml at all — swallow it.
        return st.secrets.get(name)  # type: ignore[no-any-return]
    except Exception:
        return None


# --- server-side counter ----------------------------------------------------
def _count_active_locked() -> int:
    now = time.time()
    stale = [k for k, ts in _state["active"].items() if now - ts > _ACTIVE_WINDOW]
    for k in stale:
        del _state["active"][k]
    return len(_state["active"])


def track_session() -> None:
    """Count this session once, refresh its activity gauge, and (re)emit analytics.

    Streamlit reruns the whole script on every interaction and reconciles the
    element tree — any component not re-emitted on the latest run is dropped from
    the DOM. So :func:`_inject_analytics` must be called on EVERY run (its
    client-side guard makes the actual injection idempotent), not just the first,
    or the analytics iframe is torn down before its script executes.
    """
    token = st.session_state.get("_usage_token")
    if token:  # already counted this session — just refresh the active gauge
        with _lock:
            _state["active"][token] = time.time()
    else:
        token = uuid.uuid4().hex
        st.session_state["_usage_token"] = token
        with _lock:
            _state["total"] += 1
            _state["active"][token] = time.time()
            total, active = _state["total"], _count_active_locked()
        print(f"[usage] session_start total={total} active~{active} ts={int(time.time())}",
              flush=True)

    _inject_analytics()  # every run; idempotent via the parent __usage_analytics guard


def stats() -> dict:
    """Current counters (for an admin badge / future /health-style surface)."""
    with _lock:
        return {"total": _state["total"], "active": _count_active_locked()}


# --- client-side analytics injection ----------------------------------------
# Standard PostHog web snippet; placeholders filled with JSON-encoded values.
_POSTHOG_SNIPPET = (
    "!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){"
    "function g(t,e){var o=e.split('.');2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){"
    "t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement('script'))"
    ".type='text/javascript',p.async=!0,p.src=s.api_host+'/static/array.js',(r=t.getElementsByTagName"
    "('script')[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a='posthog',"
    "u.people=u.people||[],u.toString=function(t){var e='posthog';return'posthog'!==a&&(e+='.'+a),"
    "t||(e+=' (stub)'),e},u.people.toString=function(){return u.toString(1)+'.people (stub)'},"
    "o='capture identify alias people.set people.set_once set_config register register_once "
    "unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled "
    "onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group'.split(' '),"
    "n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);"
    "posthog.init(__KEY__,{api_host:__HOST__});"
)


def _build_head_html() -> str:
    """Assemble the <head> HTML to inject, or '' if nothing is configured."""
    out: list[str] = []

    domain = _cfg("PLAUSIBLE_DOMAIN")
    if domain:
        src = _cfg("PLAUSIBLE_SRC") or "https://plausible.io/js/script.js"
        out.append(
            f'<script defer data-domain="{html.escape(domain, quote=True)}" '
            f'src="{html.escape(src, quote=True)}"></script>'
        )

    ph_key = _cfg("POSTHOG_KEY")
    if ph_key:
        host = _cfg("POSTHOG_HOST") or "https://us.i.posthog.com"
        snippet = (_POSTHOG_SNIPPET
                   .replace("__KEY__", json.dumps(ph_key))
                   .replace("__HOST__", json.dumps(host)))
        out.append(f"<script>{snippet}</script>")

    raw = _cfg("ANALYTICS_HEAD_HTML")  # escape hatch: GA4 / Umami / etc.
    if raw:
        out.append(raw)

    return "\n".join(out)


def _inject_analytics() -> None:
    head_html = _build_head_html()
    if not head_html:
        return
    # Move each node into the PARENT <head>; re-create <script>s so they execute
    # (innerHTML-parsed scripts are inert). Guarded to inject once per parent doc.
    # NB: the guard flag lives on the parent DOCUMENT, not the parent window —
    # expando properties on a cross-frame WindowProxy don't reliably persist, so
    # `window.parent.__flag = true` silently no-ops. Setting it on
    # `window.parent.document` works (same pattern as app.py's search shortcut).
    # Escape '</' → '<\/' so any literal "</script>" INSIDE this payload string
    # doesn't prematurely close the inline <script> we're embedding it in (the
    # HTML parser would otherwise cut the script off at the first "</script>").
    # '<\/' is an identical JS string but invisible to the HTML parser.
    payload = json.dumps(head_html).replace("</", "<\\/")
    components.html(
        f"""
        <script>
        (function() {{
          try {{
            var d = window.parent && window.parent.document;
            if (!d || d.__usage_analytics) return;
            d.__usage_analytics = true;
            var head = d.head || d.documentElement;
            var tmp = d.createElement('div');
            tmp.innerHTML = {payload};
            Array.prototype.slice.call(tmp.childNodes).forEach(function(node) {{
              if (node.tagName === 'SCRIPT') {{
                var s = d.createElement('script');
                for (var i = 0; i < node.attributes.length; i++) {{
                  s.setAttribute(node.attributes[i].name, node.attributes[i].value);
                }}
                s.text = node.textContent || '';
                head.appendChild(s);
              }} else if (node.nodeType === 1) {{
                head.appendChild(node.cloneNode(true));
              }}
            }});
          }} catch (e) {{ /* cross-origin/sandbox/CSP — analytics unavailable, app unaffected */ }}
        }})();
        </script>
        """,
        height=0,
    )
