import streamlit as st
from pathlib import Path

# app.py is now a thin shell: setup → top nav → sidebar globals → dialog
# wiring → dispatch to the active view. Each mode's heavy lifting lives in
# views/*.py (Sprint 4.5). `companies` is the only cache helper app.py itself
# calls (to build the ViewContext); everything else is imported by the views.
from lib.cache import companies

_PROJECT_ROOT = Path(__file__).parent

st.set_page_config(page_title="Georgia Financials", layout="wide")

# Brand styling — Inter font + base CSS overrides. Must come after
# set_page_config but before any other Streamlit element renders.
from lib.ui import inject_brand_css
inject_brand_css()

# Access gate (roadmap T3.2): require login on the deployed Space. This is a
# NO-OP unless AUTH_COOKIE_KEY + APP_PASSWORD are configured as Space secrets,
# so local dev and the test suite run ungated. Placed before the DB download so
# unauthenticated visitors never trigger a fetch.
from lib.auth import require_login
require_login()

# Usage tracking (roadmap ops): count authenticated sessions + rolling active
# gauge → [usage] lines in the Space logs, and inject Plausible/PostHog if
# configured (no-op without env/secrets). Placed after the login gate so it
# measures real app sessions, not login-page bounces. See lib/usage.py.
from lib.usage import track_session
track_session()


# Database location resolution — see `_resolve_db_path` for the full flow.
#   - Local dev: the DB file sits next to app.py; we use it directly.
#   - HF Space: the DB lives in a separate Dataset (DMDaudio/findashboard-data)
#     so the Space repo stays under the 1 GB LFS quota. A mounted HF Bucket at
#     /data is the DURABLE cache (survives restarts); the SQLite file SQLite
#     actually opens is a fast EPHEMERAL local copy, re-hydrated on cold boot.
_DATASET_REPO = "DMDaudio/findashboard-data"
_DB_FILENAME = "georgian-financials-v2.db"


def _boot_log(msg: str) -> None:
    # Cold-boot breadcrumbs → Space run logs. The 2026-07-08 outage hung
    # silently inside _resolve_db_path for hours (650 MB bucket FUSE I/O on
    # cpu-basic) with nothing in the logs; flush=True makes each step visible
    # via fetch_space_logs WHILE it happens, not after the fact.
    print(f"[db-boot] {msg}", flush=True)


def _resolve_db_path() -> str:
    """Resolve a fast, local path to the SQLite DB.

    Storage layout on the Space:
      - ``/data`` — mounted HF Bucket (object storage). DURABLE: survives
        restarts, so cold boots can skip the ~424 MB Dataset re-download. But
        random reads over object storage are slow, so SQLite never reads here.
      - ``<app>/.dbcache`` — fast EPHEMERAL local SSD. The copy SQLite opens;
        wiped on cold boot and re-hydrated from the bucket (or the Dataset).

    We pick the "current" copy by matching the Dataset head SHA, preferring an
    already-hydrated fast-local copy, then the bucket (no network), and only
    downloading from the Dataset when nothing cached is current — writing that
    download to BOTH the bucket (durable) and fast-local (fast reads).
    """
    # Dev: committed DB next to app.py → use it directly (never touches the
    # bucket/fast-copy machinery below, which is Space-only).
    local_db = _PROJECT_ROOT / _DB_FILENAME
    if local_db.exists():
        return str(local_db)

    import shutil
    import time
    from huggingface_hub import HfApi, hf_hub_download

    # Durable cache = the mounted bucket at /data (when present).
    bucket_dir = Path("/data")
    have_bucket = bucket_dir.exists() and bucket_dir.is_dir()
    bucket_db = (bucket_dir / _DB_FILENAME) if have_bucket else None
    bucket_sha = (bucket_dir / f"{_DB_FILENAME}.sha") if have_bucket else None
    if have_bucket:
        # 2026-07-08: 650 MB FUSE copies to/from a mounted bucket hung cold
        # boots indefinitely on cpu-basic. Works on cpu-upgrade; prefer
        # running UNMOUNTED (direct Dataset download) on the free tier.
        _boot_log("bucket volume detected at /data (WARNING: FUSE copies are "
                  "slow on cpu-basic — unmount if boot hangs here)")
    else:
        _boot_log("no /data bucket volume — fast-local cache or Dataset download")

    # Fast read copy = ephemeral local SSD. A subdir so it can't collide with
    # the dev `local_db` check above.
    fast_dir = _PROJECT_ROOT / ".dbcache"
    fast_dir.mkdir(exist_ok=True)
    fast_db = fast_dir / _DB_FILENAME
    fast_sha = fast_dir / f"{_DB_FILENAME}.sha"

    def _sha_of(p: Path | None) -> str | None:
        return p.read_text().strip() if (p is not None and p.exists()) else None

    # Cheap remote head-SHA lookup (no file download).
    try:
        remote_sha = HfApi().dataset_info(_DATASET_REPO).sha
    except Exception:
        # Network/auth hiccup — trust whatever we already have cached.
        remote_sha = None
    _boot_log(f"dataset head SHA: {remote_sha or 'unavailable (network?)'}")

    # 1) Fast-local copy already current → use it (the warm-container path).
    if fast_db.exists() and (remote_sha is None or _sha_of(fast_sha) == remote_sha):
        _boot_log("fast-local cache hit — serving immediately")
        return str(fast_db)

    # 2) Bucket has a current copy → hydrate fast-local from it, no network.
    bucket_ok = bucket_db is not None and bucket_db.exists() and (
        (remote_sha is not None and _sha_of(bucket_sha) == remote_sha)
        or remote_sha is None  # API down — trust the durable copy
    )
    if bucket_ok:
        _boot_log(f"hydrating from bucket ({bucket_db.stat().st_size / 1e6:.0f} MB "
                  "over FUSE — can be minutes on cpu-basic)…")
        t0 = time.monotonic()
        with st.spinner("Loading database from persistent storage…"):
            shutil.copy2(bucket_db, fast_db)
            carried = remote_sha or _sha_of(bucket_sha)
            if carried:
                fast_sha.write_text(carried)
        _boot_log(f"bucket hydrate done in {time.monotonic() - t0:.0f}s")
        return str(fast_db)

    # 3) Nothing current cached → download from the Dataset once, saving to
    #    BOTH the bucket (durable) and fast-local (fast reads).
    already = fast_db.exists() or (bucket_db is not None and bucket_db.exists())
    label = "Updating database from HF Dataset…" if already else \
            "Fetching database from HF Dataset (one-time, ~424 MB)…"
    _boot_log("downloading DB from HF Dataset (~424 MB)…")
    t0 = time.monotonic()
    with st.spinner(label):
        downloaded = hf_hub_download(
            repo_id=_DATASET_REPO,
            filename=_DB_FILENAME,
            repo_type="dataset",
            # token=None → uses HF_TOKEN env var if the Dataset is private
        )
        _boot_log(f"dataset download done in {time.monotonic() - t0:.0f}s")
        shutil.copy2(downloaded, fast_db)
        if remote_sha:
            fast_sha.write_text(remote_sha)
        if bucket_db is not None:
            _boot_log("writing DB back to bucket over FUSE (slow on cpu-basic)…")
            t1 = time.monotonic()
            try:
                shutil.copy2(downloaded, bucket_db)
                if remote_sha:
                    bucket_sha.write_text(remote_sha)
                _boot_log(f"bucket write-back done in {time.monotonic() - t1:.0f}s")
            except OSError:
                # Bucket write failed (transient) — fast-local still serves
                # this run; next boot re-downloads rather than crashing.
                _boot_log("bucket write-back FAILED (OSError) — continuing on fast-local")
    return str(fast_db)


# Sprint 6: memoize the resolved path per session. _resolve_db_path() does an
# HfApi().dataset_info() network round-trip on every call on the Space (the
# local-file early-return short-circuits it in dev) — without memoization that
# network hit fires on EVERY rerun. The "Refresh data" sidebar button pops this
# key so a freshly-published Dataset can still propagate on demand.
if "_db_path" not in st.session_state:
    st.session_state["_db_path"] = _resolve_db_path()
DB_PATH = st.session_state["_db_path"]

# --- Top navigation ---------------------------------------------------------
# Phase B: top tabs replace the old sidebar Mode radio. Active mode is stored
# in st.session_state["mode"] so the downstream `if mode == ...` chain works
# unchanged. URL deep-linking is wired up in Phase C.
from lib.ui import (
    resolve_active_mode,
    render_top_bar,
    render_disclaimer_bar,
    slug_to_mode,
    mode_to_slug,
)
from lib.ui_chips import global_search_dialog, person_dialog

# URL → state on first load: if the URL carries a ?mode= slug and we haven't
# established a mode in this session yet, the URL wins. After that,
# session_state is the source of truth and we mirror it back into the URL.
if "mode" not in st.session_state:
    _url_slug = st.query_params.get("mode")
    if _url_slug:
        st.session_state["mode"] = slug_to_mode(_url_slug)
st.session_state.setdefault("mode", "Single Company")  # back-compat default

active_mode = resolve_active_mode(st.session_state.get("mode"))
new_mode, _refresh_clicked = render_top_bar(active_mode)
if _refresh_clicked:
    # Cache-bust: drop cached financials AND the memoized DB path so
    # _resolve_db_path() re-runs (re-checks the HF Dataset head SHA and
    # re-downloads on the Space if a new DB was published). app.py owns the
    # _db_path key, so the Refresh action stays here rather than in render_top_bar.
    st.cache_data.clear()
    st.session_state.pop("_db_path", None)
    st.rerun()
if new_mode != active_mode:
    st.session_state["mode"] = new_mode
    st.query_params["mode"] = mode_to_slug(new_mode)
    st.rerun()
mode = active_mode  # downstream dispatch reads this local

# Keep the URL's ?mode= slug in sync with the active mode (covers first load
# and the back-compat default). Assigning to st.query_params updates the URL
# without triggering a rerun, so this is loop-safe.
if st.query_params.get("mode") != mode_to_slug(mode):
    st.query_params["mode"] = mode_to_slug(mode)

# Mode-scoped params (?id= Single Company, ?companies= Compare, ?sectors=
# Sectoral Data) are dropped outside their mode so shared links stay clean.
for _param, _owner_mode in (
    ("id", "Single Company"),
    ("companies", "Compare"),
    ("sectors", "Sectoral Data"),
):
    if mode != _owner_mode and _param in st.query_params:
        del st.query_params[_param]


# Cross-mode helpers (sidebar_ifrs_controls, sector_metrics_panel,
# adjusted_is_sections_for, company_short_name, section_total_at) moved to
# views/shared.py in the Sprint 4.5 decomposition.


# ---------------------------------------------------------------------------
# Global controls (search, navigation, decimal precision, refresh) now live in
# the top command bar — see lib.ui.render_top_bar. The sidebar is reserved for
# per-view controls, which each view renders inside its own render(ctx).
# ---------------------------------------------------------------------------

companies = companies(DB_PATH)
options = [f"{idc} — {name}" for idc, name in companies]
labels_to_idcode = {label: idc for label, (idc, _) in zip(options, companies)}
idcode_to_label = {idc: label for label, idc in labels_to_idcode.items()}

# Per-render context handed to each view's render(ctx) (Sprint 4.5 decomposition).
from views.shared import ViewContext
ctx = ViewContext(
    db_path=DB_PATH,
    companies=companies,
    options=options,
    labels_to_idcode=labels_to_idcode,
    idcode_to_label=idcode_to_label,
)

# In-app "Ask Claude" chat (T4.1b). Rendered BEFORE view dispatch so it always
# appears — even when a view short-circuits with st.stop() (Streamlit drops any
# deltas emitted while a StopException is unwinding, so post-dispatch rendering
# would vanish on empty states). render_chat_sidebar() docks it to the BOTTOM of
# the sidebar with a collapsed expander via CSS flex `order` (see views/chat.py),
# so it renders first in DOM order but displays last, below the per-view controls.
# Optional feature: lib/chat.py imports the MCP tool functions (mcp/tools.py +
# scripts.ingest). If those aren't present (e.g. a slim deploy that didn't ship
# them) degrade gracefully — a missing add-on must never crash the whole app.
try:
    from views.chat import render_chat_sidebar
    render_chat_sidebar(ctx)
except ImportError as _chat_import_err:
    import logging
    logging.getLogger(__name__).warning(
        "Chat sidebar unavailable (%s) - continuing without it.", _chat_import_err
    )

# Subtle 'work in progress' strip + Data-sources disclosure, directly under the
# nav and above the active view (rendered before dispatch so it shows on every
# page, including views that st.stop() on an empty state).
render_disclaimer_bar()


# ---------------------------------------------------------------------------
# Phase F: global search dialog (Cmd-K style). The dialog body lives in
# lib/ui_chips.global_search_dialog; the trigger wiring (sidebar button flag +
# "/" shortcut) stays here because it's app-level navigation glue.
# ---------------------------------------------------------------------------
# Best-effort keyboard shortcuts: "/" or ⌘/Ctrl-K clicks the top-bar search pill
# (which opens the command palette). Binds a keydown listener on the parent
# document; if the iframe can't reach the parent (sandbox) it fails silently —
# the search pill still works on click.
import streamlit.components.v1 as _components
_components.html(
    """
    <script>
    try {
      const pdoc = window.parent.document;
      if (!pdoc.__findashSearchBound) {
        pdoc.__findashSearchBound = true;
        pdoc.addEventListener('keydown', function(e) {
          const tag = (pdoc.activeElement && pdoc.activeElement.tagName) || '';
          const typing = tag === 'INPUT' || tag === 'TEXTAREA';
          const slash = e.key === '/' && !typing;
          const cmdK = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
          if (slash || cmdK) {
            const el = pdoc.querySelector('.st-key-topbar_search button');
            if (el) { e.preventDefault(); el.click(); }
          }
        });
      }
    } catch (err) { /* cross-origin or sandbox — shortcut unavailable, pill still works */ }
    </script>
    """,
    height=0,
)

# Open the dialog once when the trigger flag is set. pop() returns True exactly
# once (the run after the button click), so the dialog opens; thereafter
# Streamlit re-runs only the dialog function on internal interactions, keeping
# it open until a result click calls st.rerun() (which closes it).
if st.session_state.pop("_open_search", False):
    global_search_dialog(options, labels_to_idcode, idcode_to_label, db_path=DB_PATH)


# ---------------------------------------------------------------------------
# "How to use" tour dialog: opened by the top-bar Guide button or the Home-page
# hint (both call lib.ui_help.request_help_tour, which sets the flag). Same
# trigger-flag pattern as the search dialog above.
# ---------------------------------------------------------------------------
if st.session_state.pop("_open_help", False):
    from lib.ui_help import help_dialog
    help_dialog()


# ---------------------------------------------------------------------------
# Person portfolio dialog: opened by clicking a name in the Ownership panel.
# The dialog body lives in lib/ui_chips.person_dialog. Set
# st.session_state["_open_person"] = personId to trigger.
# ---------------------------------------------------------------------------
_pending_person = st.session_state.pop("_open_person", None)
if _pending_person is not None:
    person_dialog(_pending_person, DB_PATH, idcode_to_label)


# ---------------------------------------------------------------------------
# Mode: Home  (Phase B landing page — full content arrives in Phase D)
# ---------------------------------------------------------------------------

if mode == "Home":
    import views.home as _home_view
    _home_view.render(ctx)

# ---------------------------------------------------------------------------
# Mode: Single Company  (original flow, preserved)
# ---------------------------------------------------------------------------

elif mode == "Single Company":
    import views.single_company as _single_view
    _single_view.render(ctx)

elif mode == "Compare":
    import views.compare as _compare_view
    _compare_view.render(ctx)

elif mode == "Sectoral Data":
    import views.sector as _sector_view
    _sector_view.render(ctx)

elif mode == "Sector Overviews":
    import views.sector_overviews as _overviews_view
    _overviews_view.render(ctx)

elif mode == "Macro":
    import views.macro as _macro_view
    _macro_view.render(ctx)


# Mode: "Comp Sets" — REMOVED in the Compare-merge refactor. The
# basket-explorer features (saved sets, bulk import, save/manage, aggregate
# chart + per-company contribution matrix, XLSX/CSV export) all live inside
# Compare now, switchable via the Side-by-side / Aggregate view toggle.
# Old bookmarks to ?mode=compset get redirected to ?mode=compare by
# lib.ui.slug_to_mode. The old dispatch elif is gone; the Sector View elif
# chains directly to the Screener elif below.


# ---------------------------------------------------------------------------
# Mode: Screener
# ---------------------------------------------------------------------------

elif mode == "Screener":
    import views.screener as _screener_view
    _screener_view.render(ctx)

# ---------------------------------------------------------------------------
# Mode: Owners — the ownership register inverted (holders, not companies)
# ---------------------------------------------------------------------------

elif mode == "Owners":
    import views.people as _people_view
    _people_view.render(ctx)
