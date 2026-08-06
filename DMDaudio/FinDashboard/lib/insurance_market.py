"""Pure maps + parse helpers for the insurance-regulator MARKET dataset.

Source: insurance.gov.ge "Insurance Market Statistical Indicators"
(``/ka/Statistics/Index/1``) — a per-period workbook that breaks **premium and
claims down by insurance class** (Life, Medical/Health, Casco, MTPL, Property, …)
**per company**. This is a *different* dataset from the 12-month BS/IS returns
(``/Index/2``, handled by ``lib/insurance_gov.py`` → ``insurance_statements``).

Each full-year (``type=4``) workbook has company × class matrices across several
sheets (written/reinsurance premium, earned premium, claims paid, incurred claims,
policy counts) plus a class-level market-structure summary. Layout drifts a little
year-to-year (older years carry fewer classes / shifted columns / the "Inccured"
typo), so the parser anchors on **header text**, never fixed column indices.

This module is pure: no DB, no Streamlit, no network. The downloader / parser /
analytics modules import the maps and helpers from here.
"""
from __future__ import annotations

import re

# --- Canonical insurance classes -------------------------------------------------
# key -> display label.  `total` is the all-classes roll-up the regulator prints.
CLASS_LABELS: dict[str, str] = {
    "life": "Life",
    "travel": "Travel",
    "accident": "Personal Accident",
    "medical": "Medical (Health)",
    "casco": "Motor Own Damage (Casco)",
    "mtpl": "Motor TPL",
    "railway": "Railway",
    "aviation_hull": "Aviation Hull",
    "aviation_tpl": "Aviation TPL",
    "marine_hull": "Marine Hull",
    "marine_tpl": "Marine TPL",
    "cargo": "Cargo",
    "property": "Property",
    "financial_loss": "Misc. Financial Loss",
    "suretyship": "Suretyships",
    "credit": "Credit",
    "liability": "General TPL",
    "legal": "Legal Expenses",
    "total": "Total",
}

# Display order for charts/tables (drops the roll-up; callers add 'total' as needed).
CLASS_ORDER: tuple[str, ...] = (
    "medical", "casco", "mtpl", "life", "property", "travel", "accident",
    "cargo", "liability", "financial_loss", "suretyship", "credit",
    "aviation_hull", "aviation_tpl", "marine_hull", "marine_tpl", "railway", "legal",
)

# One stable colour per class, so a class is the SAME colour everywhere it appears
# (premium-mix donut, GWP-by-class bars, loss-ratio-by-class bars, class-mix area).
_CLASS_PALETTE: tuple[str, ...] = (
    "#1a4f86", "#0f6e57", "#DBB968", "#b5651d", "#7d3c98", "#2e86c1", "#cb4335",
    "#16a085", "#8e44ad", "#d68910", "#27ae60", "#c0392b", "#2980b9", "#af7ac5",
    "#e67e22", "#1abc9c", "#34495e", "#7f8c8d",
)
CLASS_COLOR: dict[str, str] = {
    cls: _CLASS_PALETTE[i % len(_CLASS_PALETTE)] for i, cls in enumerate(CLASS_ORDER)
}
# Reverse lookup display-label -> class key (charts that only carry the label).
LABEL_TO_CLASS: dict[str, str] = {CLASS_LABELS[c]: c for c in CLASS_ORDER}


def class_color(class_key: str) -> str:
    """Hex colour for a canonical class key (grey fallback for unknowns)."""
    return CLASS_COLOR.get(class_key, "#999999")


def class_color_for_label(label: str) -> str:
    """Hex colour for a class display label (grey fallback)."""
    return CLASS_COLOR.get(LABEL_TO_CLASS.get(label, ""), "#999999")


def _norm(text: str) -> str:
    """Lowercase, strip everything but a-z0-9 — for tolerant header matching."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


# Ordered (most-specific first) header-substring → canonical class key. Order
# matters: motor/aviation/marine TPL must be tested before the generic "third
# party liability", and "casco" before plain "transport".
_CLASS_RULES: tuple[tuple[str, str], ...] = (
    ("casco", "casco"),
    ("roadtransport", "casco"),
    ("motorthirdparty", "mtpl"),
    ("aviationthirdparty", "aviation_tpl"),
    ("aviationtransport", "aviation_hull"),
    ("aviationhull", "aviation_hull"),
    ("marinethirdparty", "marine_tpl"),
    ("marinetransport", "marine_hull"),
    ("marinehull", "marine_hull"),
    ("railway", "railway"),
    ("medical", "medical"),
    ("health", "medical"),
    ("personalaccident", "accident"),
    ("accident", "accident"),
    ("travel", "travel"),
    ("cargo", "cargo"),
    ("property", "property"),
    ("financialloss", "financial_loss"),
    ("miscellaneous", "financial_loss"),
    ("suretyship", "suretyship"),
    ("credit", "credit"),
    ("legalexpense", "legal"),
    ("legal", "legal"),
    ("life", "life"),
    # generic third-party liability LAST (motor/aviation/marine already captured)
    ("thirdpartyliability", "liability"),
    ("liability", "liability"),
    ("total", "total"),
)


def class_key_for(header: str) -> str | None:
    """Map a class column header (any year's wording) to a canonical class key."""
    n = _norm(header)
    if not n:
        return None
    for sub, key in _CLASS_RULES:
        if sub in n:
            return key
    return None


# --- Company crosswalk -----------------------------------------------------------
# The market report lists insurers by English name (row order = GWP rank). Names
# drift across years (e.g. company #9 is "Wizer" in FY2025 but "PSP Insurance"
# pre-rebrand), so we resolve by an ordered list of distinctive brand tokens found
# as a substring of the normalized name. Specific/long tokens first to avoid the
# shared "georgia" suffix colliding. All 19 map to our regulator-covered insurers.
_COMPANY_RULES: tuple[tuple[str, str], ...] = (
    ("globalbenefits", "404526777"),
    ("groupofgeorgia", "405206566"),
    ("georgianinsurancegroup", "405206566"),
    ("newvision", "402160022"),
    ("gpiholding", "204426674"),
    ("gpi", "204426674"),
    ("tbc", "405042804"),
    ("aldagi", "404476189"),
    ("imedi", "204919008"),
    ("ardi", "405662242"),
    ("irao", "205023856"),
    ("unison", "404393152"),
    ("wizer", "204545572"),
    ("psp", "204545572"),          # pre-rebrand name in older reports
    ("alpha", "204568896"),
    ("bbinsurance", "406232214"),
    ("euroins", "204491344"),
    ("prime", "204540274"),
    ("cartu", "204970031"),
    ("qartu", "204970031"),
    ("autograph", "404858631"),
    ("autograf", "404858631"),
    ("tao", "202408386"),
    ("green", "404990435"),
)

# Short English display names for the 19 regulator insurers — the DB CompanyName
# is long Georgian; these keep tables/charts legible.
IDCODE_TO_SHORT: dict[str, str] = {
    "405042804": "TBC",
    "204426674": "GPI Holding",
    "404476189": "Aldagi",
    "204919008": "Imedi L",
    "405662242": "Ardi",
    "205023856": "IRAO",
    "404526777": "Global Benefits",
    "404393152": "Unison",
    "204545572": "Wizer",
    "204568896": "Alpha",
    "406232214": "BB Insurance",
    "405206566": "Georgian Ins. Group",
    "204491344": "Euroins",
    "402160022": "New Vision",
    "204540274": "Prime",
    "204970031": "Cartu",
    "404858631": "Autograph",
    "202408386": "TAO",
    "404990435": "Green",
}

# Synthetic IdCode holding the regulator's printed market total (the "Total" row /
# "Structure of Insurance Market" sheet). Keeps market share accurate even in older
# years that include now-exited insurers we don't carry as companies.
MARKET_TOTAL_IDCODE = "_MARKET"


def company_idcode_for(name: str) -> str | None:
    """Resolve a market-report company name to our DB IdCode, or None if unmapped."""
    n = _norm(name)
    if not n or n == "total":
        return None
    for token, idc in _COMPANY_RULES:
        if token in n:
            return idc
    return None


# --- Sheet → metric specs --------------------------------------------------------
# Premium basis = the regulator's **FINANCIAL** written premium (cash/collected,
# the figure that ties to the financial statements) — NOT the accrual "written"
# sheet and NOT earned premium. The Financial sheet exists only FY2015+.
#
# Two layouts:
#   • "client_total" — each class block splits Written Premium (Gross) across
#     Private/Individuals/State/**Total** then a Reinsurance **Total**. We take the
#     two "Total" sub-columns (written, then reinsurance), located by header text so
#     it's robust to width drift across years.
#   • "gross_net" — each class block is 2 sub-cols, gross then net (Incurred Claims).
SHEET_SPECS: tuple[dict, ...] = (
    {"aliases": ("financial wr", "financial written"),
     "layout": "client_total",
     "metrics": ("financial_written_premium", "financial_reinsurance_premium")},
    {"aliases": ("inccured claims", "incurred claims"),
     "layout": "gross_net",
     "metrics": ("incurred_claims_gross", "incurred_claims_net")},
)

# Metrics stored in the insurance_market table (long format).
ALL_METRICS: tuple[str, ...] = (
    "financial_written_premium", "financial_reinsurance_premium",
    "incurred_claims_gross", "incurred_claims_net",
)


def sheet_spec_for(sheet_name: str) -> dict | None:
    """Match a workbook sheet title to its spec (substring on lowercased name).

    The workbook also carries reinsurance twins ("Accept. Re. Earned Premiums",
    "Re. Incurred Claims", "Accept. Re Prem. & Retrocession", …) whose names share
    our aliases. They MUST be excluded — otherwise they'd overwrite the direct
    premium/claims with the reinsurance-accepted figures.
    """
    n = str(sheet_name or "").lower().strip()
    if n.startswith("re.") or n.startswith("re ") or "accept" in n or "retroces" in n:
        return None
    for spec in SHEET_SPECS:
        if any(a in n for a in spec["aliases"]):
            return spec
    return None

