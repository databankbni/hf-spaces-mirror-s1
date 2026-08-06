"""bia.ge business-directory model — pure parsing + the ID-CODE VERIFICATION GATE.

bia.ge is a Georgian business directory that publishes, per company, its
PRODUCTS (``პროდუქტები``), ACTIVITY CATEGORIES (``საქმიანობის კატეგორიები``),
ACTIVITY FIELDS (``საქმიანობის სფერო``) and the national NACE classifiers. That
is exactly the evidence the sector pipeline lacks when a filer's activity note
says nothing (see ``docs/sector-adjudication-brief.md``), so it is worth having
as a systematic cross-check rather than ad-hoc hand lookups.

No Streamlit, no DB, no network here — this module is only the URL model, the
HTML parsers and the verification decision. The scraper lives in
``scripts/build_bia_directory.py``; the reader in ``lib/data_loader.py``.

WHY THE VERIFICATION GATE EXISTS
--------------------------------
**bia.ge has no IdCode → URL pattern.** A company page is ``/Company/<biaId>``
where ``biaId`` is bia's own surrogate key, unrelated to the state
``საიდენტიფიკაციო კოდი``. So every lookup goes through a search, and Georgian
company names collide constantly: a search for ``ყვარლის ბაგა`` returns nine
kindergartens (``ბაგა-ბაღი``) alongside the right company. In the 2026-07
sector adjudication round, agents doing this by hand attempted ~20 lookups and
had to DISCARD at least 8 pages on code mismatch — bia's "Gudauri Lodge" is
402084221, its "Axis Towers" 405077704, its "Euphoria Hotel Batumi" 448050046,
its "არგო ანურია" 245621028, none of them the company being asked about. Every
one of those would otherwise have produced a confident WRONG sector off a
perfectly plausible-looking page.

Hence the rule this module enforces, with no escape hatch:

    **Parse the საიდენტიფიკაციო კოდი off the page and accept NOTHING unless it
    equals the IdCode that was searched for.**

There is deliberately no "best name match" fallback and no similarity score. A
mismatch is a FIRST-CLASS RECORDED OUTCOME (``STATUS_CODE_MISMATCH``, carrying
the code that was actually found and the candidates considered), never a silent
skip — a recorded mismatch is evidence that bia has a same-named different
company, which is itself worth knowing. A page with no parseable code at all is
``STATUS_NO_CODE``: unverifiable, therefore not stored either.
"""
from __future__ import annotations

import html as _html
import re
import unicodedata

# --- URL model --------------------------------------------------------------

BASE_URL = "https://www.bia.ge"
HOME_URL = BASE_URL + "/"
# Company search is POST-only (a GET bounces to the homepage) and carries an
# ASP.NET antiforgery token scraped from any page's form.
SEARCH_URL = BASE_URL + "/Company/Search"
COMPANY_URL_TMPL = BASE_URL + "/Company/{bia_id}"

# The query field name in the search form (`id="Filter_Query"`).
QUERY_FIELD = "Filter.Query"
TOKEN_FIELD = "__RequestVerificationToken"


def company_url(bia_id: int | str) -> str:
    """Absolute bia.ge company-page URL for a bia surrogate id."""
    return COMPANY_URL_TMPL.format(bia_id=bia_id)


def search_form_fields(query: str, token: str) -> dict[str, str]:
    """POST body for a company search. ``Id`` empty = free-text (not a picked
    autocomplete hit), which is what makes bia return the full hit list."""
    return {TOKEN_FIELD: token, QUERY_FIELD: query, "Id": ""}


# --- Statuses (mirrors company_ownership's vocabulary, plus the gate) -------

STATUS_OK = "ok"                        # code verified, detail stored
STATUS_NOTFOUND = "notfound"            # search returned no candidates at all
STATUS_CODE_MISMATCH = "code_mismatch"  # candidate(s) found, none had our code
STATUS_NO_CODE = "no_code"              # candidate page carries no parseable code
STATUS_ERROR = "error"                  # HTTP/throttle failure — retried later

#: Statuses that count as resolved, so a re-run skips them (``error`` never does).
RESOLVED_STATUSES: tuple[str, ...] = (
    STATUS_OK, STATUS_NOTFOUND, STATUS_CODE_MISMATCH, STATUS_NO_CODE,
)
#: Negative outcomes ``--verify`` re-checks (a name may have been added since).
VERIFIABLE_STATUSES: tuple[str, ...] = (
    STATUS_NOTFOUND, STATUS_CODE_MISMATCH, STATUS_NO_CODE,
)

# --- Verification verdicts --------------------------------------------------

MATCH = "match"        # page code == requested code
MISMATCH = "mismatch"  # page code != requested code  -> DISCARD the page
MISSING = "missing"    # no code on the page          -> DISCARD the page


def should_store(status: str) -> bool:
    """Only a verified match may be written as directory data. The single
    place that answers "am I allowed to keep this page?" — keep it that way."""
    return status == STATUS_OK


# --- ID codes ---------------------------------------------------------------

_ASCII_DIGITS = frozenset("0123456789")


def _is_code_noise(ch: str) -> bool:
    """True for characters that carry no information in a rendered code cell.

    Classified by Unicode category rather than a hand-typed literal set: NBSP,
    zero-width space/joiners and the BOM are invisible in an editor and get
    eaten by copy/paste, so spelling them out in a string would silently weaken
    the gate's input cleaning with no test noticing.

      * any whitespace (incl. NBSP, narrow NBSP, figure space)
      * ``Cf``/``Cc`` — format & control chars: zero-width space, joiners, BOM
      * ``Pd`` — every dash/hyphen variant
      * ``.`` and ``,`` — thousands separators someone may have typed
    """
    return (ch.isspace()
            or unicodedata.category(ch) in ("Cf", "Cc", "Pd")
            or ch in ".,")


def normalize_idcode(value) -> str:
    """Canonical form of an identification code, or ``""`` if it isn't one.

    Drops whitespace/zero-width/separator noise, then requires everything that
    is left to be ASCII DIGITS. Anything else (``"n/a"``, ``"441554051 (active)"``,
    a non-ASCII digit, ``None``) normalizes to ``""`` — i.e. "no usable code",
    which the gate treats as unverifiable rather than guessing. Length is not
    checked: Georgian legal entities carry 9 digits and sole traders 11, and a
    stray length must not silently drop a real code. The result stays a STRING so
    a leading zero can never be lost to an int round-trip.
    """
    if value is None:
        return ""
    out = []
    for ch in str(value):
        if ch in _ASCII_DIGITS:
            out.append(ch)
        elif not _is_code_noise(ch):
            return ""          # a real non-digit character: not a code at all
    return "".join(out)


def decide_idcode_match(requested, found) -> str:
    """THE decision: ``MATCH`` / ``MISMATCH`` / ``MISSING``.

    Both sides are normalized first, so ``" 441554051 "`` matches ``441554051``
    and a leading-zero code is never mangled by an int round-trip. A requested
    code that is itself unusable yields ``MISSING`` — we cannot verify against
    nothing, so we must not store.
    """
    req = normalize_idcode(requested)
    got = normalize_idcode(found)
    if not got or not req:
        return MISSING
    return MATCH if got == req else MISMATCH


def status_for_verdict(verdict: str) -> str:
    """Map a verification verdict to the stored ``Status``."""
    if verdict == MATCH:
        return STATUS_OK
    if verdict == MISMATCH:
        return STATUS_CODE_MISMATCH
    return STATUS_NO_CODE


# --- Company names ----------------------------------------------------------

# Georgian legal-form prefixes (and Latin equivalents) that carry no identity.
# Order matters: longest/most specific first so "შ.პ.ს." is not left as "ს.".
_LEGAL_FORMS = (
    "ინდივიდუალური მეწარმე",
    "შეზღუდული პასუხისმგებლობის საზოგადოება",
    "სააქციო საზოგადოება",
    "სოლიდარული პასუხისმგებლობის საზოგადოება",
    "კომანდიტური საზოგადოება",
    "არასამეწარმეო (არაკომერციული) იურიდიული პირი",
    "არასამეწარმეო არაკომერციული იურიდიული პირი",
    "საჯარო სამართლის იურიდიული პირი",
    "შ.პ.ს.", "შპს", "ს.ს.", "სს", "ს.პ.ს.", "სპს", "კ.ს.", "კს",
    "ა(ა)იპ", "ააიპ", "სსიპ", "ი.მ.", "ი/მ", "იმ",
    "llc", "ltd", "ltd.", "jsc", "j.s.c.", "plc", "inc", "inc.", "co.", "l.t.d.",
)
_QUOTES = "\"'«»„“”‘’`´"
_NAME_NOISE_RE = re.compile(r"[^\wႠ-ჿ]+", re.UNICODE)


def strip_legal_form(name) -> str:
    """The name with its legal-form prefix/suffix removed, otherwise verbatim.

    This is the SEARCH QUERY form, distinct from ``normalize_company_name``
    (the comparison form, which also casefolds and strips punctuation). Our
    ``companies.CompanyName`` carries the form — ``შპს გუდაური ლოჯი`` — while
    bia indexes the bare name — ``გუდაური ლოჯი`` — so querying the raw value
    returns ZERO HITS for perfectly present companies. Measured on the live
    probe: ``შპს გუდაური ლოჯი`` found nothing, ``გუდაური ლოჯი`` found the
    company. Casing and internal punctuation are preserved because they are part
    of what bia's own index matches on.
    """
    if name is None:
        return ""
    s = re.sub(r"\s+", " ", _html.unescape(str(name))).strip()
    s = s.strip(_QUOTES + " ")
    changed = True
    while changed:
        changed = False
        for form in _LEGAL_FORMS:
            for cand in (form, form.upper()):
                if s.lower().startswith(cand.lower() + " "):
                    s = s[len(cand):].strip().strip(_QUOTES + " ")
                    changed = True
                elif s.lower().endswith(" " + cand.lower()):
                    s = s[: -len(cand)].strip().strip(_QUOTES + " ")
                    changed = True
    return s


def normalize_company_name(name) -> str:
    """Comparison form of a company name: legal form and punctuation removed.

    Used ONLY to pick which search hits are worth opening and to record how a
    hit was reached. It is **never** allowed to decide identity — that is
    ``decide_idcode_match``'s job alone. Georgian has no case, but Latin names
    are casefolded so ``Tegeta Motors`` == ``TEGETA MOTORS``.
    """
    if name is None:
        return ""
    s = _html.unescape(str(name))
    s = "".join(" " if ch in _QUOTES else ch for ch in s)
    s = re.sub(r"\s+", " ", s).strip().casefold()
    # Peel legal forms off either end, repeatedly ("შპს სს ..." happens).
    changed = True
    while changed:
        changed = False
        for form in _LEGAL_FORMS:
            f = form.casefold()
            if s.startswith(f + " ") or s == f:
                s = s[len(f):].strip()
                changed = True
            if s.endswith(" " + f):
                s = s[: -len(f)].strip()
                changed = True
    return _NAME_NOISE_RE.sub(" ", s).strip()


def names_match(a, b) -> bool:
    """True when two names normalize identically. Advisory only — see above."""
    na, nb = normalize_company_name(a), normalize_company_name(b)
    return bool(na) and na == nb


# --- HTML helpers -----------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_NO_VALUE_MARKERS = ("არ აქვს", "არ არის", "არ აცხადებს")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub(" ", fragment or ""))).strip()


def _label_window(page: str, label: str) -> str:
    """HTML between a ``data-title`` label and the next one (or end of page)."""
    m = re.search(
        r'class="data-title"[^>]*>\s*' + re.escape(label) + r'\s*:?\s*</(?:span|div)>'
        r'(.*?)(?=class="data-title"|\Z)',
        page or "", re.S,
    )
    return m.group(1) if m else ""


def _label_value(page: str, label: str) -> str:
    """Single-value field: the ``data-list`` span/div right after the label."""
    win = _label_window(page, label)
    if not win:
        return ""
    m = re.search(r'class="data-list[^"]*"[^>]*>(.*?)</(?:span|div)>', win, re.S)
    val = _text(m.group(1)) if m else _text(win)
    return "" if val in _NO_VALUE_MARKERS else val


def _label_list(page: str, label: str) -> list[str]:
    """Multi-value field: the ``<li>`` items of the ``<ul>`` after the label."""
    win = _label_window(page, label)
    if not win:
        return []
    ul = re.search(r"<ul[^>]*>(.*?)</ul>", win, re.S)
    if not ul:
        one = _label_value(page, label)
        return [one] if one else []
    out: list[str] = []
    for li in re.findall(r"<li[^>]*>(.*?)</li>", ul.group(1), re.S):
        val = _text(li)
        if val and val not in _NO_VALUE_MARKERS and val not in out:
            out.append(val)
    return out


# Labels as bia renders them.
L_IDCODE = "საიდენტიფიკაციო კოდი"
L_LEGAL_FORM = "სამართლებრივი ფორმა"
L_STATUS = "სტატუსი"
L_ADDRESS = "იურიდიული მისამართი"
L_REGISTERED = "რეგისტრაციის თარიღი"
L_TRADEMARKS = "სავაჭრო მარკები"
L_PRODUCTS = "პროდუქტები"
L_CATEGORIES = "საქმიანობის კატეგორიები"
L_INDUSTRIES = "საქმიანობის სფერო"
L_NACE_2004 = "ეროვნული კლასიფიკატორები (NACE 2004)"
L_NACE_2016 = "ეროვნული კლასიფიკატორები (NACE 2016)"

# Each product renders as "პროდუქტი - <thing>"; the prefix is noise.
_PRODUCT_PREFIX_RE = re.compile(r"^\s*პროდუქტი\s*[-–—:]\s*")


def extract_idcode_detail(page: str) -> tuple[str, str]:
    """``(normalized_code, source)`` for the code printed on a company page.

    Primary source is the labelled ``საიდენტიფიკაციო კოდი`` cell. Secondary is
    the page's own ``<meta name="keywords" content="<code>,<name>,…">``, which
    bia emits with the code first — same page, same data, used only when the
    labelled cell is missing (older/partial renders). ``source`` is recorded on
    the row so a mismatch verdict can always be audited back to what was read.
    Returns ``("", "")`` when neither yields a usable code.
    """
    val = _label_value(page, L_IDCODE)
    code = normalize_idcode(val)
    if code:
        return code, "label"
    m = re.search(r'<meta\s+name="keywords"\s+content="([^",]*)', page or "")
    if m:
        code = normalize_idcode(m.group(1))
        if code:
            return code, "meta-keywords"
    return "", ""


def extract_idcode(page: str) -> str:
    """Normalized ``საიდენტიფიკაციო კოდი`` from a company page (``""`` if none)."""
    return extract_idcode_detail(page)[0]


def extract_company_name(page: str) -> str:
    """bia's display name for the company."""
    m = re.search(r'id="CompanyNameBox"[^>]*>(.*?)</div>', page or "", re.S)
    if m:
        name = _text(m.group(1))
        if name:
            return name
    m = re.search(r"<title>(.*?)</title>", page or "", re.S)
    if m:
        return re.sub(r"\s*-\s*BIA\s*$", "", _text(m.group(1)))
    return ""


def extract_products(page: str) -> list[str]:
    """``პროდუქტები`` with bia's ``პროდუქტი - `` prefix stripped."""
    return [_PRODUCT_PREFIX_RE.sub("", p).strip() for p in _label_list(page, L_PRODUCTS)]


def extract_activity_categories(page: str) -> list[str]:
    """``საქმიანობის კატეგორიები`` — bia's ~28 top-level industry categories."""
    return _label_list(page, L_CATEGORIES)


def extract_industries(page: str) -> list[str]:
    """``საქმიანობის სფერო`` — the fine-grained activity fields."""
    return _label_list(page, L_INDUSTRIES)


def parse_company_page(page: str) -> dict:
    """Everything the sector cross-check needs from one company page.

    The ``idcode`` key is what the gate compares; it is NOT trusted to be the
    company you asked for until ``decide_idcode_match`` says so.
    """
    code, source = extract_idcode_detail(page)
    return {
        "name": extract_company_name(page),
        "idcode": code,
        "idcode_source": source,
        "legal_form": _label_value(page, L_LEGAL_FORM),
        "status": _label_value(page, L_STATUS),
        "address": _label_value(page, L_ADDRESS),
        "registered": _label_value(page, L_REGISTERED),
        "trademarks": _label_list(page, L_TRADEMARKS),
        "products": extract_products(page),
        "categories": extract_activity_categories(page),
        "industries": extract_industries(page),
        "nace_2004": _label_list(page, L_NACE_2004),
        "nace_2016": _label_list(page, L_NACE_2016),
    }


# --- Search results ---------------------------------------------------------

_RESULT_LINK_RE = re.compile(
    r'<a\s+class="title"\s+href="/Company/(\d+)"[^>]*>(.*?)</a>', re.S
)


def parse_search_results(page: str) -> list[dict]:
    """``[{"bia_id": int, "name": str}]`` from a search-results page, in order.

    Only ``<a class="title" href="/Company/N">`` links count, so the
    ``/Company/Industry/N`` and ``/Company/IndustryCategory/N`` facet links that
    litter the same markup can never be mistaken for a company hit. Deduped on
    ``bia_id`` (each hit renders the link twice: heading + "view in full").
    """
    hits: list[dict] = []
    seen: set[int] = set()
    for bid, name in _RESULT_LINK_RE.findall(page or ""):
        bid_i = int(bid)
        if bid_i in seen:
            continue
        seen.add(bid_i)
        hits.append({"bia_id": bid_i, "name": _text(name)})
    return hits


def is_search_results_page(page: str) -> bool:
    """True when a POST really landed on the search page.

    A rejected/expired antiforgery token makes bia serve the HOMEPAGE with 200
    instead of an error, which would otherwise be read as "zero hits" and
    recorded as a false ``notfound`` — the same class of bug the companyinfo.ge
    scraper's fast-empty detection exists to prevent. The search page always
    carries the query input; the homepage's search box uses a different one.
    """
    p = page or ""
    return 'id="Filter_Query"' in p and (
        'class="result-box"' in p or "/Shared/GetCompaniesForSearch" in p
    )


def is_company_page(page: str) -> bool:
    """True when a GET returned a real company page (not an error/interstitial).

    Distinguishes "page rendered but carries no code" (``STATUS_NO_CODE`` — a
    determinate outcome) from "we never got the page" (``STATUS_ERROR`` — retry
    later). bia serves its error page with HTTP 200, so the status line cannot
    make this call.
    """
    p = page or ""
    return 'id="CompanyNameBox"' in p or 'class="data-title"' in p


def rank_candidates(hits: list[dict], wanted_name: str) -> list[dict]:
    """Order search hits by how promising they look, exact name first.

    Pure ordering heuristic — it decides which pages are *opened first*, never
    which one is *accepted*. Every hit it returns still has to pass the code
    gate, so a bad ordering costs requests, not correctness.
    """
    want = normalize_company_name(wanted_name)

    def key(h: dict) -> tuple:
        got = normalize_company_name(h.get("name"))
        if want and got == want:
            rank = 0
        elif want and (got.startswith(want) or want.startswith(got)):
            rank = 1
        elif want and want in got:
            rank = 2
        else:
            rank = 3
        return (rank, len(got))

    return sorted(hits, key=key)
