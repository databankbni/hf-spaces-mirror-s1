"""Owners — the ownership register read the other way round.

Every other mode in this app starts from a company. This one starts from the
holder: who owns Georgian companies, and what their stakes add up to. It joins
the companyinfo.ge register (``company_ownership``) to the financial panel, which
is why it can't be lifted from any filing-level source.

Ranking maths and the person index are pure and live in ``lib/people.py``; this
module is presentation only. Clicking a row opens the person-portfolio dialog
(``lib.ui_chips.person_dialog``) — the same modal the company Ownership panel
opens, so the drill-down is one implementation, not two.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.cache import (
    latest_portfolio_metrics,
    people_ranked,
    person_index,
)
from lib.format import fmt_k_gel
from lib.people import (
    ACTIVE_YEAR_WINDOW,
    NO_GE_ID_BADGE as _NO_GE_ID,
    RANKABLE_METRICS,
    VINTAGE_ACTIVE_KEY,
    active_cutoff_year,
    newest_panel_year,
    people_search,
)
from lib.ui import safe_key
from views.shared import ViewContext

_METRIC_LABELS: dict[str, str] = dict(RANKABLE_METRICS)
_LABEL_TO_METRIC: dict[str, str] = {lbl: key for key, lbl in RANKABLE_METRICS}

_RANK_KEY = "owners_rank_metric"
_SEARCH_KEY = "owners_search"
_PAGE_SIZE_KEY = "owners_page_size"
_PAGE_NUM_KEY = "owners_page_num"

_PAGE_SIZE_OPTIONS: tuple[int, ...] = (25, 50, 100, 200, 500)
_DEFAULT_PAGE_SIZE = 50

# Columns shown alongside whichever metric is ranked, so the table answers "and
# what else does this portfolio look like" without a second click.
_COMPANION_METRICS: tuple[tuple[str, str], ...] = (
    ("NetProfit", "Net profit"),
    ("TotalCash", "Cash"),
    ("TotalAssets", "Assets"),
)


def _open_person(person_id) -> None:
    """Queue the person dialog for the next run (app.py pops the flag)."""
    st.session_state["_open_person"] = person_id


def _reset_page() -> None:
    """Send the reader back to page 1 when the ranking or page size changes.

    Staying on page 7 after re-ranking shows an arbitrary slice of a different
    list. Safe as an ``on_change`` callback: those run BEFORE the next script run
    instantiates any widget, so this never writes a widget's key after the widget
    exists (the Sprint-26 "Bad message format" trap).
    """
    st.session_state[_PAGE_NUM_KEY] = 1


def _rows_to_frame(rows: list[dict], metric: str, start_rank: int = 1) -> pd.DataFrame:
    """Ranked owner dicts → the display frame, money in GEL thousands.

    ``start_rank`` is the 1-based rank of ``rows[0]`` in the FULL ranking, so the
    ``#`` column keeps counting across pages instead of restarting at 1 on each.
    """
    ranked_label = _METRIC_LABELS[metric]
    companions = [(k, lbl) for k, lbl in _COMPANION_METRICS if k != metric]
    out = []
    for i, p in enumerate(rows, start=start_rank):
        rec = {
            "#": i,
            "Owner": p["name"],
            "": "" if p["is_natural_person"] else _NO_GE_ID,
            "Cos": p["owned_count"],
            ranked_label: fmt_k_gel(p["value"]),
        }
        for key, lbl in companions:
            rec[lbl] = fmt_k_gel((p["totals"] or {}).get(key))
        out.append(rec)
    return pd.DataFrame(out)


def render(ctx: ViewContext) -> None:
    db_path = ctx.db_path

    # Cold build is a few seconds over ~9k registry payloads; memoized for the
    # life of the DB file, and the person dialog reuses the same index.
    index = person_index(db_path)

    if not index:
        st.subheader("Owners")
        st.info(
            "The ownership register isn't available in this database. It's built "
            "by `scripts/build_company_ownership.py` into the `company_ownership` "
            "table."
        )
        return

    # --- Sidebar controls ---------------------------------------------------
    # Seed defaults BEFORE the widgets instantiate (Sprint-26 safe).
    st.session_state.setdefault(_RANK_KEY, _METRIC_LABELS["Revenue"])
    # Default ON: a portfolio built from each company's latest filed year silently
    # counts long-dormant companies at their last good figure, which overstates the
    # owner. Recent-filers-only is the more honest default; the switch exposes the
    # old behaviour rather than hiding it.
    st.session_state.setdefault(VINTAGE_ACTIVE_KEY, True)

    # Unfiltered join, purely to learn the panel's newest year for the cutoff.
    _latest_all = latest_portfolio_metrics(db_path)
    newest_year = newest_panel_year(_latest_all)
    cutoff = active_cutoff_year(_latest_all)

    with st.sidebar:
        st.markdown("### Owners")
        st.radio(
            "Rank by attributable",
            options=[lbl for _, lbl in RANKABLE_METRICS],
            key=_RANK_KEY,
            on_change=_reset_page,
        )
        st.toggle(
            "Recent filers only",
            key=VINTAGE_ACTIVE_KEY,
            on_change=_reset_page,
            help=(
                f"Count only companies whose latest filing is FY{cutoff} or newer"
                f" (the last {ACTIVE_YEAR_WINDOW} panel years). Off, a company that "
                "filed big numbers years ago and has since gone quiet still counts "
                "at that old figure — inflating the owner and mixing vintages."
                if cutoff else "No filing years in the panel."
            ),
        )
        st.text_input(
            "Find an owner",
            key=_SEARCH_KEY,
            placeholder="Name or personal ID…",
            help="Searches the whole register, not just the ranked table.",
        )

    # .get with a fallback: a session carried over from a build with different
    # metric labels would otherwise KeyError instead of just re-defaulting.
    metric = _LABEL_TO_METRIC.get(st.session_state[_RANK_KEY], "Revenue")
    active_only = bool(st.session_state.get(VINTAGE_ACTIVE_KEY, True))
    min_year = cutoff if active_only else None

    # --- Header -------------------------------------------------------------
    st.subheader("Owners")
    _vintage_note = (
        f"filings FY{cutoff}–FY{newest_year}" if (active_only and cutoff)
        else "each company's latest filed year, any vintage"
    )
    st.caption(
        f"{len(index):,} people in the register  ·  ranked by attributable "
        f"{_METRIC_LABELS[metric].lower()}  ·  {_vintage_note}"
    )

    # --- Search results (when searching) ------------------------------------
    query = (st.session_state.get(_SEARCH_KEY) or "").strip()
    if query:
        hits = people_search(index, query, limit=25)
        st.markdown("##### Search")
        if not hits:
            st.caption(
                f"No owner matches “{query}”. Names are as filed in the register — "
                "mostly Georgian script."
            )
        else:
            st.caption(f"{len(hits)} match(es) — click a name to open the portfolio.")
            for p in hits:
                col_name, col_meta = st.columns([5, 3])
                with col_name:
                    st.button(
                        p["name"],
                        key=safe_key("owner_hit", str(p["person_id"])),
                        on_click=_open_person,
                        args=(p["person_id"],),
                        use_container_width=True,
                    )
                with col_meta:
                    bits = [f"{p['owned_count']} owned of {p['company_count']}"]
                    if not p["is_natural_person"]:
                        bits.append(_NO_GE_ID)
                    if p["is_individual_entrepreneur"]:
                        bits.append("individual entrepreneur")
                    st.markdown(
                        f"<div style='padding-top:8px;font-size:12px;opacity:0.7'>"
                        f"{'  ·  '.join(bits)}</div>",
                        unsafe_allow_html=True,
                    )
        st.divider()

    # --- Leaderboard --------------------------------------------------------
    # The FULL ranking (cached per DB+metric); paginated below rather than capped,
    # so every owner with a measurable stake is reachable.
    ranked = people_ranked(db_path, metric, min_year)
    all_rows = ranked["people"]

    st.markdown("##### Largest owners")
    st.caption(
        "Attributable = Σ (stake % × that company's latest filed figure). "
        "Directors holding no shares are excluded — they have no attributable "
        "claim. Stakes come from the companyinfo.ge register, so an owner behind "
        "a nominee or an undisclosed holding is understated here."
        + (
            f"  Only companies filing FY{cutoff} or later are counted; a dormant "
            "company contributes nothing rather than its last good year."
            if (active_only and cutoff) else
            "  **All vintages counted** — a company dormant since e.g. FY2018 "
            "still contributes its FY2018 figure at full weight."
        )
    )
    if not all_rows:
        st.info("No owner in the register holds a stake in a company we have financials for.")
        return

    # ----- Pagination. Mirrors the Screener's controls (views/screener.py) so the
    # two tables behave identically. Sprint-26-safe: each widget owns its key and
    # is only READ here; the page number is reset via on_change callbacks, which
    # run before the next run's widgets instantiate.
    total = len(all_rows)
    pg_size_col, pg_num_col = st.columns([1, 3])
    with pg_size_col:
        page_size = int(st.selectbox(
            "Rows per page",
            options=_PAGE_SIZE_OPTIONS,
            index=_PAGE_SIZE_OPTIONS.index(_DEFAULT_PAGE_SIZE),
            key=_PAGE_SIZE_KEY,
            on_change=_reset_page,
        ))
    n_pages = max(1, (total + page_size - 1) // page_size)
    with pg_num_col:
        page = int(st.number_input(
            "Page",
            min_value=1,
            max_value=n_pages,
            value=1,
            step=1,
            key=_PAGE_NUM_KEY,
            help=f"{n_pages:,} page(s) · {total:,} owners with a measurable stake.",
        ))
    # Clamp defensively: a metric switch can shrink the population below a stored
    # page number. The widget clamps on the NEXT run, so without this the slice
    # indices would be out of range on THIS one.
    page = min(page, n_pages)
    start = (page - 1) * page_size
    rows = all_rows[start:start + page_size]

    st.caption(
        f"**{start + 1:,}–{start + len(rows):,}** of {total:,} owners with a "
        f"measurable stake  ·  page {page:,} of {n_pages:,}  ·  money in "
        "**GEL thousands**  ·  select a row to open the owner's portfolio."
    )

    frame = _rows_to_frame(rows, metric, start_rank=start + 1)
    sel = st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        height=600,
        on_select="rerun",
        selection_mode="single-row",
        # Key is scoped to the page so turning the page yields a FRESH widget with
        # no selection. A single shared key would keep the old row index selected,
        # and that index now points at a different owner — which would fire the
        # portfolio dialog for whoever happens to sit there. Re-keying avoids
        # writing widget state after instantiation (Sprint-26).
        key=f"owners_results_table_p{page}_{page_size}",
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "": st.column_config.TextColumn(
                width="small",
                help="No 11-digit Georgian personal ID on file — a corporate, "
                     "state or foreign holder.",
            ),
            "Cos": st.column_config.NumberColumn(
                "Cos", width="small",
                help="Companies held with a stake > 0 that we have financials for.",
            ),
        },
    )

    # Row click → person dialog. The selection SURVIVES the rerun, so acting on
    # it unconditionally would reopen the dialog on every subsequent run
    # (including the one that renders it) — an unclosable modal. Track the
    # person we already opened in a plain state key instead: clearing the
    # dataframe's own key here would write a widget's state after that widget
    # instantiated, which is the "Bad message format" trap (Sprint-26 rule).
    sel_rows: list[int] = []
    if sel is not None and isinstance(getattr(sel, "selection", None), dict):
        sel_rows = sel.selection.get("rows") or []
    current = rows[sel_rows[0]]["person_id"] if sel_rows else None
    if current is None:
        # Deselected — forget it, so clicking the same row again reopens.
        st.session_state.pop("_owners_last_pick", None)
    elif current != st.session_state.get("_owners_last_pick"):
        st.session_state["_owners_last_pick"] = current
        _open_person(current)
        st.rerun()

    st.caption(
        "Affiliations from companyinfo.ge (public corporate registry) · figures "
        "are each company's latest filed year, so one portfolio can mix vintages. "
        f"Holders badged “{_NO_GE_ID}” are in the index because the register has "
        "no 9-digit Georgian company code to filter them out on."
    )
