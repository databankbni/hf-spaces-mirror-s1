"""The ownership register read the other way round — owners, not companies.

Every other surface in this app starts from a company. This one starts from the
holder: who owns Georgian companies, and what their stakes actually add up to.
That needs the companyinfo.ge register (``company_ownership``) joined to the
financial panel (``metrics_panel``), which is why it can't be lifted from any
filing-level source.

Pure logic only — no DB, no Streamlit (mirrors ``lib/sectors.py`` and
``lib/ownership.py``). ``lib.data_loader`` supplies the ownership blobs and the
panel's latest-year rows; ``lib.cache`` memoizes the built index; the Owners
view (``views/people.py``) and the person dialog render it.

Three shapes flow through here:

* **index** — ``{person_id: {person_id, name, id_number,
  is_individual_entrepreneur, companies: {idcode: {...}}}}``, built once per DB
  version by :func:`build_person_index`.
* **latest** — ``{idcode: {"year": int, "metrics": {metric: value}}}``, the
  panel's most recent filed year per company (raw GEL).
* **attributable** — a stake-weighted sum over the two: Σ (share % × the
  company's latest filed figure). Not a consolidated group figure; a 10% holder
  of a company gets 10% of its revenue.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

# Metrics aggregated in a person's portfolio (raw GEL, latest year per company).
# Canonical here; ``lib.companyinfo`` re-exports for its existing call sites.
PORTFOLIO_METRICS: tuple[str, ...] = (
    "Revenue", "EBITDA", "NetProfit", "TotalAssets",
    "TotalCash", "TotalDebt", "TotalEquity",
)

# Metrics the Owners leaderboard can rank by, in display order. EBITDA and debt
# are deliberately absent: EBITDA is NULL for banks and insurers (so ranking on
# it would silently drop them), and "most indebted owner" is not a ranking
# anyone asked for.
RANKABLE_METRICS: tuple[tuple[str, str], ...] = (
    ("Revenue", "Revenue"),
    ("NetProfit", "Net profit"),
    ("TotalAssets", "Total assets"),
    ("TotalCash", "Cash"),
    ("TotalEquity", "Equity"),
)

# A Georgian personal ID is 11 digits. Anything else in the register's
# `personIdNumber` slot belongs to a corporate, state or foreign holder that
# reached the index because it has no 9-digit Georgian IdCode to filter on.
_GE_PERSONAL_ID_LEN = 11

# The badge for a holder with no 11-digit Georgian personal ID on file. Says what
# is *known*, not what is guessed: the register can't distinguish a corporate
# holder from a foreign individual, and calling the latter a corporation is
# simply wrong. Lives next to :func:`is_natural_person` so every surface that
# renders the flag renders the same words — the Owners table and the global
# search's People group both read it from here.
NO_GE_ID_BADGE = "no ge id"


def portfolio_aggregate(rows: list[dict]) -> dict[str, Any]:
    """Share-weight company metrics into an attributable portfolio.

    Input ``rows``: ``[{name, idcode, share_pct, metrics: {metric: value}}]``
    where ``metrics`` are raw-GEL latest-year values. Only rows with
    ``share_pct > 0`` contribute — a director holding no shares has no
    attributable claim on anything.

    Returns ``{"totals": {metric: Σ (share_pct/100 × value)},
    "by_company": [{name, idcode, share_pct, attributable: {metric: value}}],
    "owned_count": int}``.
    """
    owned = [r for r in rows if (r.get("share_pct") or 0) > 0]
    if not owned:
        return {"totals": {}, "by_company": [], "owned_count": 0}

    totals: dict[str, float] = {m: 0.0 for m in PORTFOLIO_METRICS}
    by_company: list[dict] = []
    for r in owned:
        frac = float(r["share_pct"]) / 100.0
        metrics = r.get("metrics") or {}
        attributable = {}
        for m in PORTFOLIO_METRICS:
            val = float(metrics.get(m) or 0.0) * frac
            attributable[m] = val
            totals[m] += val
        by_company.append({
            "name": r.get("name"),
            "idcode": r.get("idcode"),
            "share_pct": r.get("share_pct"),
            "year": r.get("year"),
            "attributable": attributable,
        })
    return {"totals": totals, "by_company": by_company, "owned_count": len(owned)}


def is_natural_person(id_number: Any) -> bool:
    """True iff an 11-digit Georgian personal ID is on file.

    This is the ONLY thing the register lets us assert, and it is NOT the same
    question as "is this a company" — a foreign individual fails it too. Callers
    should label the absence ("no ge id"), never infer "corporate" from it.
    """
    return len(str(id_number or "").strip()) == _GE_PERSONAL_ID_LEN


def build_person_index(
    details: Iterable[tuple[str, dict]],
    company_names: dict[str, str],
    summarize: Callable[[dict | None], dict],
) -> dict:
    """Invert the register: ``person_id → {name, id_number, companies}``.

    ``details`` yields ``(idcode, detail)`` pairs straight from
    ``company_ownership``; ``summarize`` is the affiliation summarizer
    (``lib.companyinfo.summarize_affiliations``), injected so this stays pure and
    testable. Corporate holders are skipped — they have their own company pages,
    and an entry keyed on a personId that is really a company would double-count
    against the company surfaces.

    A person who is both shareholder and director of the same company collapses
    to one row keeping the SHAREHOLDING (the larger share), with both roles
    listed: the stake is what the portfolio is weighted by.
    """
    index: dict = {}
    for idcode, detail in details:
        summary = summarize(detail)
        co_name = company_names.get(idcode)
        for e in summary["partners"] + summary["management"]:
            pid = e.get("personId")
            if pid is None or e.get("is_company"):
                continue
            person = index.setdefault(pid, {
                "person_id": pid,
                "name": e["name"],
                "id_number": e["id_number"],
                "is_individual_entrepreneur": e.get("is_individual_entrepreneur", False),
                "companies": {},
            })
            prev = person["companies"].get(idcode)
            if prev is None or e["share"] > (prev["share_pct"] or 0):
                roles = list(prev["roles"]) if prev else []
                if e["role_en"] not in roles:
                    roles.append(e["role_en"])
                person["companies"][idcode] = {
                    "idcode": idcode,
                    "name": co_name,
                    "share_pct": e["share"],
                    "roles": roles,
                    "ex": e.get("ex", False),
                }
            elif e["role_en"] not in prev["roles"]:
                prev["roles"].append(e["role_en"])
    return index


# Session-state key naming the vintage filter. Lives here (not in a view) because
# BOTH the Owners leaderboard and the person-portfolio dialog must read the same
# switch — otherwise clicking a row would show a portfolio computed on different
# rules than the row that opened it.
VINTAGE_ACTIVE_KEY = "portfolio_active_filers_only"

# How many years back still counts as "active", measured from the anchor year (see
# :func:`anchor_panel_year`). 2 => the anchor and the year before it, which absorbs
# the normal filing lag without keeping genuinely dormant companies.
ACTIVE_YEAR_WINDOW = 2

# A year only anchors the window if it carries at least this share of the busiest
# year's filer count. Guards against the newest year being a near-empty vanguard.
MIN_ANCHOR_COVERAGE = 0.25


def newest_panel_year(latest: dict) -> int | None:
    """The most recent filing year anywhere in the panel-side join.

    Reporting only — do NOT anchor the active window on this; see
    :func:`anchor_panel_year`.
    """
    years = [v.get("year") for v in latest.values() if v.get("year")]
    return max(years) if years else None


def panel_year_counts(latest: dict) -> dict[int, int]:
    """``{year: how many companies have that as their latest filing}``."""
    counts: dict[int, int] = {}
    for v in latest.values():
        y = v.get("year")
        if y:
            counts[int(y)] = counts.get(int(y), 0) + 1
    return counts


def anchor_panel_year(
    latest: dict, min_coverage: float = MIN_ANCHOR_COVERAGE
) -> int | None:
    """The newest filing year with MEANINGFUL coverage — the window's anchor.

    Deliberately not ``max(year)``. The panel's newest year is typically a
    vanguard of a handful of early filers: at the time of writing FY2025 holds 20
    companies against FY2024's 6,410. Anchoring on the raw maximum makes the
    active window collapse the moment a single company files for a new year — the
    Owners page would drop from ~8k rankable owners to almost none, silently.

    So walk years newest-first and take the first one carrying at least
    ``min_coverage`` of the busiest year's count.
    """
    counts = panel_year_counts(latest)
    if not counts:
        return None
    floor = max(counts.values()) * min_coverage
    for year in sorted(counts, reverse=True):
        if counts[year] >= floor:
            return year
    return max(counts)  # unreachable in practice; keeps the contract total


def active_cutoff_year(latest: dict, window: int = ACTIVE_YEAR_WINDOW) -> int | None:
    """Oldest filing year that still counts as active, or None if unknown."""
    anchor = anchor_panel_year(latest)
    return None if anchor is None else anchor - (window - 1)


def filter_latest_by_year(latest: dict, min_year: int | None) -> dict:
    """Restrict the panel-side join to companies whose LATEST filing is recent.

    Why this exists: a portfolio is built from each company's *latest filed year*,
    so a company that posted large revenue in FY2018 and has been dormant since
    still contributes that FY2018 figure at full weight. That silently inflates an
    owner's attributable total and mixes vintages — e.g. a real-estate developer
    whose one big project company stopped operating years ago reads as though it
    is still producing.

    Dropping the company entirely (rather than zeroing it) is deliberate: we have
    no evidence its revenue IS zero, only that it has not filed. Absent data is
    not a zero. ``min_year=None`` is a no-op, i.e. keep every vintage.
    """
    if min_year is None:
        return latest
    return {
        k: v for k, v in latest.items()
        if (v.get("year") or 0) >= min_year
    }


def _portfolio_rows(entry: dict, latest: dict) -> list[dict]:
    """The entry's stake-holding companies joined to their latest panel year.

    Drops both the stakeless roles (a directorship earns no attributable claim)
    and the companies outside the panel (nothing to weight).
    """
    rows = []
    for co in entry["companies"].values():
        if not (co["share_pct"] or 0) > 0:
            continue
        lm = latest.get(co["idcode"])
        if not lm or not lm.get("metrics"):
            continue
        rows.append({
            "name": co["name"],
            "idcode": co["idcode"],
            "share_pct": co["share_pct"],
            "year": lm.get("year"),
            "metrics": lm["metrics"],
        })
    return rows


def people_top(index: dict, latest: dict, metric: str = "Revenue",
               limit: int = 50) -> dict:
    """Owners ranked by an attributable portfolio metric.

    Only holders of an actual stake are ranked, and only companies present in
    the panel contribute — an owner whose companies all file nothing has no
    measurable portfolio, not a zero one, so it is dropped rather than shown at
    the bottom.

    Returns ``{"metric", "count", "people": [{person_id, name, id_number,
    is_natural_person, owned_count, value, totals}]}`` — ``count`` is the full
    ranked population, ``people`` the top ``limit`` of it (``limit=0`` for all).
    """
    if metric not in PORTFOLIO_METRICS:
        metric = "Revenue"

    ranked: list[dict] = []
    for entry in index.values():
        rows = _portfolio_rows(entry, latest)
        if not rows:
            continue
        totals = portfolio_aggregate(rows)["totals"]
        value = totals.get(metric)
        if value is None:
            continue
        ranked.append({
            "person_id": entry["person_id"],
            "name": entry["name"],
            "id_number": entry["id_number"],
            "is_natural_person": is_natural_person(entry["id_number"]),
            "is_individual_entrepreneur": entry.get("is_individual_entrepreneur", False),
            "owned_count": len(rows),
            "value": value,
            "totals": totals,
        })

    ranked.sort(key=lambda r: -(r["value"] or 0))
    return {
        "metric": metric,
        "count": len(ranked),
        "people": ranked[: max(1, limit)] if limit else ranked,
    }


def _fold(s: Any) -> str:
    """Casefold for matching. Georgian is caseless so this is a no-op there, and
    does the right thing for Latin-transliterated names."""
    return str(s or "").casefold().strip()


def people_search(index: dict, query: str, limit: int = 25) -> list[dict]:
    """Name/ID substring search over the person index.

    Ranks prefix hits above mid-string ones, then by portfolio breadth, so
    typing a common Georgian surname surfaces the biggest holder first rather
    than an arbitrary namesake. Returns ``[]`` for queries under 2 characters.
    """
    q = _fold(query)
    if len(q) < 2:
        return []

    hits: list[tuple[int, int, dict]] = []
    for entry in index.values():
        name = _fold(entry["name"])
        idn = _fold(entry.get("id_number"))
        if q in name:
            rank = 0 if name.startswith(q) else 1
        elif q in idn:
            rank = 2
        else:
            continue
        hits.append((rank, -len(entry["companies"]), entry))

    hits.sort(key=lambda h: (h[0], h[1], _fold(h[2]["name"])))
    return [
        {
            "person_id": e["person_id"],
            "name": e["name"],
            "id_number": e["id_number"],
            "is_natural_person": is_natural_person(e["id_number"]),
            "is_individual_entrepreneur": e.get("is_individual_entrepreneur", False),
            "company_count": len(e["companies"]),
            "owned_count": sum(1 for c in e["companies"].values()
                               if (c["share_pct"] or 0) > 0),
        }
        for _, _, e in hits[: max(1, limit)]
    ]


def person_portfolio(index: dict, latest: dict, person_id) -> dict | None:
    """One person's header + attributable portfolio, or None if not indexed.

    The register's ``personId`` is an int; a URL or widget key arrives as a
    string, so both are tried. Every affiliated company is returned — including
    the ones outside our panel, flagged ``in_db: False`` — because "this person
    also runs three companies we have no financials for" is information, not
    noise. Only the panel-covered, stake-holding ones feed ``totals``.
    """
    entry = index.get(person_id)
    if entry is None and isinstance(person_id, str) and person_id.lstrip("-").isdigit():
        entry = index.get(int(person_id))
    if entry is None:
        return None

    rows = _portfolio_rows(entry, latest)
    agg = portfolio_aggregate(rows)
    attributable_by_id = {c["idcode"]: c["attributable"] for c in agg["by_company"]}

    companies = []
    for co in entry["companies"].values():
        lm = latest.get(co["idcode"])
        companies.append({
            **co,
            "year": lm.get("year") if lm else None,
            "in_db": bool(lm and lm.get("metrics")),
            "metrics": (lm or {}).get("metrics", {}),
            "attributable": attributable_by_id.get(co["idcode"]),
        })
    # Panel-covered first, then by stake — the rows a reader can act on on top.
    companies.sort(key=lambda c: (not c["in_db"], -(c["share_pct"] or 0)))

    return {
        "person_id": entry["person_id"],
        "name": entry["name"],
        "id_number": entry["id_number"],
        "is_natural_person": is_natural_person(entry["id_number"]),
        "is_individual_entrepreneur": entry.get("is_individual_entrepreneur", False),
        "company_count": len(entry["companies"]),
        "owned_count": agg["owned_count"],
        "totals": agg["totals"],
        "companies": companies,
    }
