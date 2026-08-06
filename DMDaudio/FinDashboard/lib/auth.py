"""Password-gated access for the deployed HF Space (roadmap T3.2).

``require_login()`` is called once at the top of ``app.py``. It is a **no-op**
unless the auth secrets are present, so local dev and the test suite run
ungated — the gate only activates on the Space, where the secrets below are
set. Login state persists in a signed cookie (default 7 days: "log in once a
week"); ``streamlit_authenticator`` handles the cookie and password hashing.

Secrets (set as HF Space secrets, i.e. env vars; a local ``.streamlit/
secrets.toml`` is also honored — the same ``st.secrets`` -> env fallback the
rest of the codebase uses, cf. views/chat.py and lib/reportal_pdf.py):

    AUTH_COOKIE_KEY          required to activate the gate; signs the cookie.
    APP_PASSWORD             the shared password (paired with APP_USERNAME).
    APP_USERNAME             login name for the shared password (default "gcap").
    APP_USERS                optional JSON {username: {name, password}} for
                             per-analyst logins; takes precedence over
                             APP_PASSWORD when set.
    AUTH_COOKIE_EXPIRY_DAYS  optional, default 7.
"""
from __future__ import annotations

import json
import os

import streamlit as st

_COOKIE_NAME = "gcap_officer_auth"


def _secret(key: str, default: str | None = None) -> str | None:
    """st.secrets (local secrets.toml) first, then env var (HF Space secrets
    arrive as env vars)."""
    val = None
    try:
        val = st.secrets.get(key)
    except Exception:
        val = None
    return val or os.environ.get(key) or default


def _credentials() -> dict | None:
    """Build a streamlit-authenticator credentials dict from secrets, or None
    when the gate isn't configured."""
    users_raw = _secret("APP_USERS")
    if users_raw:
        users = json.loads(users_raw)
        return {"usernames": {
            name: {
                "name": info.get("name", name),
                "email": info.get("email", f"{name}@gcap.ge"),
                "password": info["password"],
            }
            for name, info in users.items()
        }}
    password = _secret("APP_PASSWORD")
    if password:
        username = _secret("APP_USERNAME") or "gcap"
        return {"usernames": {
            username: {"name": "GCAP", "email": f"{username}@gcap.ge", "password": password},
        }}
    return None


def require_login() -> None:
    """Gate the app behind a login. No-op when unconfigured (dev / tests);
    calls ``st.stop()`` until the visitor authenticates on the Space."""
    cookie_key = _secret("AUTH_COOKIE_KEY")
    credentials = _credentials()
    if not cookie_key or credentials is None:
        return  # auth not configured -> app runs open (local dev / test suite)

    import streamlit_authenticator as stauth

    expiry_days = float(_secret("AUTH_COOKIE_EXPIRY_DAYS") or "7")
    authenticator = stauth.Authenticate(credentials, _COOKIE_NAME, cookie_key, expiry_days)

    try:
        authenticator.login(location="main")
    except stauth.LoginError as exc:  # pragma: no cover - runtime-only path
        st.error(str(exc))
        st.stop()

    status = st.session_state.get("authentication_status")
    if status is True:
        with st.sidebar:
            authenticator.logout("Log out", location="sidebar")
        return
    if status is False:
        st.error("Incorrect username or password.")
    else:
        st.info("Please log in to continue.")
    st.stop()
