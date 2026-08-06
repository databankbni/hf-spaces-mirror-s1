"""Wrapper for the companyinfo.ge public API.

Provides ownership / directors / legal-form data keyed by IdCode. Two-step
lookup: search by IdCode → fetch detail by internal `id`. Responses are cached
for 24h so we don't hammer the upstream.

No auth required as of 2026. Light rate-limit courtesy — keep concurrent calls
modest and cache aggressively.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import streamlit as st

# The portfolio maths is pure and now lives in lib/people.py (which must stay
# streamlit-free so the Owners index can be unit-tested). Re-exported here
# because the person dialog and the tests import them from this module.
from lib.people import PORTFOLIO_METRICS, portfolio_aggregate  # noqa: F401

BASE_URL = "https://api.companyinfo.ge/api"
TIMEOUT_S = 10


def _http_get_json(path: str, params: dict | None = None) -> dict[str, Any] | None:
    qs = "?" + urlencode(params) if params else ""
    url = f"{BASE_URL}{path}{qs}"
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "georgian-financials-dashboard/1.0",
        },
    )
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:
            if resp.status != 200:
                return None
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def _search_by_idcode(idcode: str) -> dict[str, Any] | None:
    """Search the corporations endpoint by IdCode. Returns the first hit dict
    (with internal `id`) or None.
    """
    data = _http_get_json("/corporations/search", {"idCode": idcode.strip()})
    if not data:
        return None
    items = data.get("items") or []
    if not items:
        return None
    # Prefer the item whose stored idCode matches exactly (the API sometimes
    # returns an entry with a leading non-breaking-space-prefixed idCode).
    cleaned = idcode.strip()
    for item in items:
        if str(item.get("idCode", "")).strip() == cleaned:
            return item
    return items[0]


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_company_detail(idcode: str) -> dict[str, Any] | None:
    """Resolve IdCode → internal id → /corporations/{id} detail.

    Returns the merged dict with keys:
      - corporation (name, idCode, address, email, registrationDate, ...)
      - legalFormEn, legalFormKa
      - corporationAffiliations: list of {personId, personName, personCompanyId,
        personIdNumber, exPerson, role, share, date, ...}
    Or None on failure / not found.
    """
    hit = _search_by_idcode(idcode)
    if not hit or not hit.get("id"):
        return None
    detail = _http_get_json(f"/corporations/{hit['id']}")
    if not detail:
        return None
    detail["_search_hit"] = hit
    return detail


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_person(person_id) -> dict[str, Any] | None:
    """Resolve a companyinfo personId → /people/{id}.

    Returns the dict ``{"person": {...}, "affiliations": [ {companyId,
    companyName, role, date, ex, ...}, ... ]}`` or None on failure.
    """
    if person_id in (None, ""):
        return None
    return _http_get_json(f"/people/{person_id}")


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_company(company_id) -> dict[str, Any] | None:
    """Resolve a companyinfo internal companyId → /corporations/{id} detail.

    The returned detail carries both ``corporation.idCode`` and
    ``corporationAffiliations`` (per-person shares), so one call serves both
    the IdCode lookup and any person's current share.
    """
    if company_id in (None, ""):
        return None
    return _http_get_json(f"/corporations/{company_id}")


def _role_label(role_ka: str) -> str:
    """Map common Georgian role strings to a stable English label."""
    mapping = {
        "პარტნიორი": "Partner / Shareholder",
        "დირექტორი": "Director",
        "წევრი": "Board member",
        "გენერალური დირექტორი": "General Director",
        "თავმჯდომარე": "Chairperson",
        "სამეთვალყურეო საბჭოს წევრი": "Supervisory Board member",
        "ლიკვიდატორი": "Liquidator",
        "სამეთვალყურეო საბჭოს თავმჯდომარე": "Supervisory Board Chair",
    }
    return mapping.get(role_ka.strip(), role_ka)


def _parse_date_for_sort(d: str | None) -> str:
    """Return an ISO-ish sortable string from companyinfo's date strings.

    Accepts both abbreviated ('May 21, 2026') and full-month ('September 30, 2013')
    forms. Unparseable inputs sort below any parsed date so they never win a max.
    """
    if not d:
        return ""
    s = d.strip()
    import datetime as _dt
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return _dt.datetime.strptime(s, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return ""  # unknown format — won't beat a parsed date in max()



def corporate_owner_first_seen(detail: dict | None) -> dict[str, str]:
    """``{parent_IdCode: earliest YYYYMMDD that parent appears as a partner}``.

    Keyed by the 9-digit identification code (``personIdNumber``), matching
    ``ownership_edges.ParentIdCode``, so a vintage can be joined straight onto an edge.

    OWNERSHIP VINTAGE — the fact ``ownership_edges`` lacks. :func:`summarize_affiliations`
    deliberately keeps only the newest registration snapshot, because it answers
    "who owns this company NOW". That is exactly why the derived edge table has no
    start date, and why the consolidation de-dup applies today's parent/subsidiary
    links to all history.

    The history is in the same payload: companyinfo returns one affiliation row per
    historical registration document. So the earliest date on which a corporate
    partner appears is when that owner ENTERED, read from the child's own record —
    the child is where the parent shows up, not the other way round (a parent's
    affiliations list ITS shareholders, not its holdings).

    Worked case: ArtTime 202356672 shows გიორგი ღვინიაშვილი 100% up to
    2022-02-22 and შპს რონიკო 100% from 2022-11-03, so Roniko acquired it in
    November 2022. The financials agree — Roniko FY2022 revenue 23.2m is
    optics-only while FY2023 38.3m ~ 25m optics + 13.2m ArtTime. Without this the
    de-dup drops ArtTime for FY2017-2024, six years the parent never contained.

    Management rows (share 0) are ignored: a shared director is not ownership.
    Unparseable dates are skipped rather than treated as year 0, which would
    re-open the whole history the way the missing vintage already does.
    """
    out: dict[str, str] = {}
    if not detail:
        return out
    for a in detail.get("corporationAffiliations") or []:
        # Same company test as summarize_affiliations, and for the same reason:
        # companyinfo registers individual entrepreneurs as personCompanyId
        # entities too, and only the ID-number length separates them (11 digits =
        # a natural person's, 9 = a company's). An IE is not a consolidating
        # parent, so keying on personCompanyId alone would invent vintages.
        id_num = str(a.get("personIdNumber") or "").strip()
        if not a.get("personCompanyId") or len(id_num) == 11 or not id_num:
            continue
        try:
            share = float(a.get("share") or 0.0)
        except (TypeError, ValueError):
            share = 0.0
        if share <= 0:
            continue                              # director/manager row, not a stake
        when = _parse_date_for_sort(a.get("date"))
        if not when:
            continue
        prev = out.get(id_num)
        if prev is None or when < prev:
            out[id_num] = when
    return out


def summarize_affiliations(detail: dict | None) -> dict[str, Any]:
    """Bucket the affiliations into partners (share > 0) vs management (share == 0).

    The API returns one row per historical registration document, so the same
    person appears many times. We dedupe by ``(personId, role_ka)`` keeping the
    most recent entry (latest ``date``).

    Returns:
      {
        "partners": [{"name", "share", "id_number", "is_company", "ex", "role_en", "date"}],
        "management": [{"name", "role_en", "role_ka", "id_number", "ex", "date"}],
        "ex_count": int,
      }
    """
    out: dict[str, Any] = {"partners": [], "management": [], "ex_count": 0}
    if not detail:
        return out
    affil = detail.get("corporationAffiliations") or []

    # The API returns the full historical roster (every past registration
    # document creates new rows). Keep only the rows from the most recent
    # registration_number — that's the current legal state of the company.
    # Single-pass: one max-date per registration, then one max over those. The
    # obvious nested form re-scans the whole roster per candidate registration
    # (O(n²)), which cost ~13s of the full-universe person-index build.
    if affil:
        reg_max_date: dict[Any, str] = {}
        for a in affil:
            rn = a.get("registration_number")
            if not rn:
                continue
            d = _parse_date_for_sort(a.get("date"))
            if d > reg_max_date.get(rn, ""):
                reg_max_date[rn] = d
        if reg_max_date:
            latest_reg = max(reg_max_date, key=lambda rn: reg_max_date[rn])
            affil = [a for a in affil if a.get("registration_number") == latest_reg]

    # Within that snapshot, still dedup by (personId, role) in case the same
    # role appears twice for one person.
    latest: dict[tuple, dict] = {}
    for a in affil:
        key = (a.get("personId"), (a.get("role") or "").strip())
        latest.setdefault(key, a)

    for a in latest.values():
        is_ex = bool(a.get("exPerson"))
        if is_ex:
            out["ex_count"] += 1
        # `share` is a percentage in the register, but ~0.1% of rows carry
        # something else entirely — capital amounts up to 3.7e12, which is not a
        # stake in anything. They are 10 orders of magnitude out, so a single one
        # dominates any share-weighted aggregate (19 such rows produced owners
        # with GEL 57 quadrillion of "attributable revenue" at the top of the
        # Owners leaderboard). Treat >100 as unknown rather than clamping:
        # clamping to 100% would invent a controlling stake the register never
        # asserted.
        share = a.get("share") or 0
        try:
            share_unparseable = float(share) > 100.0
        except (TypeError, ValueError):
            share_unparseable = bool(share)
        if share_unparseable:
            share = 0
        role_ka = (a.get("role") or "").strip()
        # Distinguish a real corporate shareholder (9-digit IdCode) from an
        # individual entrepreneur (11-digit personal ID number). Georgian law
        # registers IEs as personCompanyId entities — the API can't tell them
        # apart on its own, but the length of the ID number reliably can.
        # Mislabelling an IE as a "company" caused the Single Company view to
        # render misleading "not in our DB" notices for partners like Mamuka
        # Tevzadze (an individual entrepreneur whose IE-entity is one of the
        # owners of Santa Trans).
        id_num = str(a.get("personIdNumber") or "").strip()
        has_company_id = bool(a.get("personCompanyId"))
        is_individual_entrepreneur = has_company_id and len(id_num) == 11
        entry = {
            "personId": a.get("personId"),
            "name": a.get("personName") or "—",
            "id_number": id_num,
            "company_idcode": id_num if (has_company_id and not is_individual_entrepreneur) else None,
            "is_company": has_company_id and not is_individual_entrepreneur,
            "is_individual_entrepreneur": is_individual_entrepreneur,
            "ex": is_ex,
            "role_ka": role_ka,
            "role_en": _role_label(role_ka),
            "share": float(share) if share else 0.0,
            # so the UI can say "the stake on file is not a percentage" instead
            # of silently treating the person as holding nothing
            "share_unparseable": share_unparseable,
            "date": a.get("date"),
        }
        if share and float(share) > 0:
            out["partners"].append(entry)
        else:
            out["management"].append(entry)
    out["partners"].sort(key=lambda e: -e["share"])
    out["management"].sort(key=lambda e: (e["role_en"], e["name"]))
    return out


def summarize_person_companies(
    person_detail: dict | None,
    person_id,
    resolve=None,
    cap: int = 60,
) -> dict[str, Any]:
    """Resolve a person's affiliated companies to {idcode, current share, roles}.

    Dedups affiliations by ``companyId`` (the API returns one row per
    role/filing). For each unique company (up to ``cap``), calls ``resolve``
    (defaults to :func:`resolve_company`) to get its IdCode and this person's
    *current* share — read from the latest-registration snapshot via
    :func:`summarize_affiliations`, matched by ``personId``.

    Returns ``{"companies": [{company_id, name, idcode, share_pct, roles, ex}],
    "truncated": bool}``. ``resolve`` is injectable for testing.
    """
    if resolve is None:
        resolve = resolve_company
    if not person_detail:
        return {"companies": [], "truncated": False}

    affs = person_detail.get("affiliations") or []

    # Dedup by companyId, preserving first-seen order; merge roles + ex flag.
    order: list = []
    meta: dict = {}
    for a in affs:
        cid = a.get("companyId")
        if cid is None:
            continue
        if cid not in meta:
            order.append(cid)
            meta[cid] = {"name": a.get("companyName") or "—", "roles": set(), "ex_all": True}
        meta[cid]["roles"].add(_role_label((a.get("role") or "").strip()))
        if not a.get("ex"):
            meta[cid]["ex_all"] = False

    truncated = len(order) > cap
    order = order[:cap]

    # Resolve all companies in parallel — each /corporations/{id} call is
    # ~1-2s network-bound, and a person with 60 affiliations was previously
    # waiting 60-120s on sequential calls. ThreadPoolExecutor with 12 workers
    # cuts that to ~5-10s on the first load; cached calls return instantly.
    from concurrent.futures import ThreadPoolExecutor

    def _resolve_one(cid):
        try:
            return cid, resolve(cid)
        except Exception:
            return cid, None

    details_by_cid: dict = {}
    if order:
        with ThreadPoolExecutor(max_workers=12) as ex:
            for cid, detail in ex.map(_resolve_one, order):
                details_by_cid[cid] = detail

    companies: list[dict] = []
    for cid in order:
        detail = details_by_cid.get(cid)
        idcode = None
        share_pct = 0.0
        if detail:
            corp = detail.get("corporation") or {}
            idcode = corp.get("idCode")
            # Current share: find this person in the latest-snapshot summary.
            summary = summarize_affiliations(detail)
            for e in summary.get("partners", []) + summary.get("management", []):
                if e.get("personId") == person_id:
                    share_pct = float(e.get("share") or 0.0)
                    break
        companies.append({
            "company_id": cid,
            "name": meta[cid]["name"],
            "idcode": idcode,
            "share_pct": share_pct,
            "roles": sorted(meta[cid]["roles"]),
            "ex": meta[cid]["ex_all"],
        })

    return {"companies": companies, "truncated": truncated}


def companyinfo_url(idcode: str) -> str:
    """Direct URL to the companyinfo.ge HTML page for a given IdCode."""
    return f"https://companyinfo.ge/en/corporations/details/{idcode.strip()}"
