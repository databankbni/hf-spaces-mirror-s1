"""Filing provenance — what a set of figures *is*, before anyone reads the numbers.

The dashboard renders a category III unaudited simplified filing with exactly the
same visual confidence as a PIE's audited IFRS statements. This module derives the
labels that tell them apart, from fields the ingest already captures.

Three facts, all keyed off the filer's SARAS category:

* **Category** — PIE / I / II / III, the filer's own declaration (raw ``CategoryMain``).
* **Reporting standard** — full IFRS for PIE/I/II, IFRS for SMEs for III.
* **Audit requirement** — mandatory for PIE/I/II, not for III.

Plus one fact read off the balance sheet:

* **PP&E measurement model** — a non-zero PP&E revaluation reserve *is* the
  revaluation model (IAS 16.39); its absence means cost model.

What this module deliberately will NOT say
------------------------------------------
**"Audited".** Category tells us whether an audit was *required*, never whether one
happened. A category III filer may obtain one voluntarily and we cannot see it from
any field in the reportal export — that answer lives in the PDF's auditor's report.
Every function here therefore distinguishes *requirement* from *fact*, and
``audit_status`` only returns "Audited" when handed positive evidence
(``has_audit_report``) from outside this module. Labelling a PIE "Audited" purely
because the law demands it would be exactly the false precision this whole feature
exists to remove.

Likewise **the standard is a legal default, not an observation**: a category III
company may voluntarily apply full IFRS, and nothing in the export reveals it. The
tooltips say so.

Pure — no DB, no Streamlit. See ``scripts/build_filing_meta.py`` for the per-year
data this consumes.
"""
from __future__ import annotations

from dataclasses import dataclass

# Ordered strongest-disclosure-first; also the display order.
CATEGORIES: tuple[str, ...] = ("PIE", "I", "II", "III")

# Categories whose financial statements the law requires to be audited. Category
# III (and IV, which this dataset cannot see) carry no such obligation.
AUDIT_REQUIRED_CATEGORIES: frozenset[str] = frozenset({"PIE", "I", "II"})

# Categories that report under full IFRS. Category III reports under IFRS for SMEs.
FULL_IFRS_CATEGORIES: frozenset[str] = frozenset({"PIE", "I", "II"})

# Form types that imply full IFRS regardless of the category field — banks and
# insurers are public-interest entities by law, so a missing/odd category on one
# of these filings should not downgrade the standard shown.
FULL_IFRS_FORM_TYPES: frozenset[str] = frozenset({"bank", "insurer"})

CATEGORY_LABELS: dict[str, str] = {
    "PIE": "PIE",
    "I": "Category I",
    "II": "Category II",
    "III": "Category III",
}

CATEGORY_TOOLTIPS: dict[str, str] = {
    "PIE": "Public-interest entity — the strictest reporting and audit regime.",
    "I": "Category I — the largest non-PIE enterprises.",
    "II": "Category II.",
    "III": "Category III — small enterprises, filing on simplified forms.",
}

FORM_TYPE_LABELS: dict[str, str] = {
    "nonfin": "Non-financial institution form",
    "bank": "Financial institution form",
    "insurer": "Insurer form",
    "cat3_simplified": "Simplified category III form",
}


@dataclass(frozen=True)
class Badge:
    """One provenance chip: a Material icon name, a short label, a tooltip."""

    icon: str
    label: str
    tooltip: str


def normalize_category(category: str | None) -> str | None:
    """Return a known category code, or ``None`` for anything unrecognised.

    The ingest maps unparseable ``CategoryMain`` values to ``"Unknown"`` and
    ``build_companies`` stores that as NULL, so both spellings arrive here.
    """
    if category is None:
        return None
    cat = str(category).strip()
    if not cat or cat.lower() == "unknown":
        return None
    return cat if cat in CATEGORIES else None


def category_badge(category: str | None) -> Badge | None:
    """Chip naming the filer's SARAS category, or ``None`` if we don't know it."""
    cat = normalize_category(category)
    if cat is None:
        return None
    return Badge(
        icon="workspace_premium" if cat == "PIE" else "label",
        label=CATEGORY_LABELS[cat],
        tooltip=(
            f"{CATEGORY_TOOLTIPS[cat]} Declared by the filer on this year's "
            f"submission. Category IV is not identified in the source data at all, "
            f"so it never appears here."
        ),
    )


def reporting_standard(category: str | None, form_type: str | None = None) -> str | None:
    """``"IFRS"`` / ``"IFRS for SMEs"`` / ``None`` when the category is unknown.

    Follows the category, since the law ties the standard to it. ``form_type`` is
    only consulted to keep a bank or insurer on full IFRS when the category field
    is missing.
    """
    cat = normalize_category(category)
    if cat is None:
        if form_type in FULL_IFRS_FORM_TYPES:
            return "IFRS"
        return None
    if cat in FULL_IFRS_CATEGORIES:
        return "IFRS"
    return "IFRS for SMEs"


def standard_badge(category: str | None, form_type: str | None = None) -> Badge | None:
    """Chip naming the reporting standard, with the voluntary-adoption caveat."""
    std = reporting_standard(category, form_type)
    if std is None:
        return None
    if std == "IFRS":
        tip = (
            "Full IFRS — required for public-interest entities and category I and "
            "II enterprises. Derived from the filer's category, not read from the "
            "report itself."
        )
    else:
        tip = (
            "IFRS for SMEs — the standard category III enterprises report under. "
            "Recognition and measurement differ from full IFRS in places, so take "
            "care comparing against a category I or II filer. A category III "
            "company that voluntarily applies full IFRS cannot be distinguished "
            "here."
        )
    return Badge(icon="menu_book", label=std, tooltip=tip)


def audit_required(category: str | None) -> bool | None:
    """``True`` / ``False`` whether the law mandates an audit; ``None`` if unknown."""
    cat = normalize_category(category)
    if cat is None:
        return None
    return cat in AUDIT_REQUIRED_CATEGORIES


def audit_status(
    category: str | None,
    has_audit_report: bool | None = None,
) -> Badge | None:
    """Chip describing audit status, stating requirement and fact separately.

    ``has_audit_report`` is evidence from outside this module — the presence of an
    auditor's report in the filed PDF. Leave it ``None`` (the default, and all this
    feature can supply today) and the chip speaks only about the legal requirement.
    """
    required = audit_required(category)

    if has_audit_report is True:
        tip = "An auditor's report was found in the filed document."
        if required is False:
            tip += " Not required for this category — the company obtained one voluntarily."
        return Badge(icon="verified", label="Audited", tooltip=tip)

    if has_audit_report is False:
        if required:
            # Contradiction worth surfacing rather than smoothing over: the law
            # demanded an audit and the filed document does not contain one.
            return Badge(
                icon="report",
                label="Audit required — none found",
                tooltip=(
                    "An audit is mandatory for this category, but no auditor's "
                    "report was found in the filed document. Treat as a gap in "
                    "either the filing or our extraction, not as proof of neither."
                ),
            )
        return Badge(
            icon="do_not_disturb_on",
            label="Unaudited",
            tooltip=(
                "No audit is required for this category and no auditor's report "
                "was found in the filed document."
            ),
        )

    if required is None:
        return None
    if required:
        return Badge(
            icon="gavel",
            label="Audit required by law",
            tooltip=(
                "Financial statements of this category must be audited. This states "
                "the legal requirement — we have not yet read the auditor's report "
                "itself, so the opinion type is not shown."
            ),
        )
    return Badge(
        icon="help",
        label="Audit not required",
        tooltip=(
            "No audit obligation for this category. The company may still have been "
            "audited voluntarily — the reportal data does not say either way, so "
            "treat these figures as unverified unless you check the filed report."
        ),
    )


# --- PP&E measurement model --------------------------------------------------
#
# IAS 16.39 puts a PP&E upward revaluation in a "revaluation surplus" within
# equity, so a non-zero balance on such a line is direct evidence of the
# revaluation model. Its absence means the cost model, which is the default and
# needs no chip.
#
# Excluded: reserves that revalue something OTHER than PP&E. Financial assets and
# securities carried at fair value are a different policy question, and investment
# property has its own fair-value model under IAS 40 — neither affects the
# depreciation and asset-base comparability this chip is about.
_REVAL_EXCLUDE_TOKENS: tuple[str, ...] = (
    "financal asset",  # sic — the spelling used in the source data
    "financial asset",
    "securities",
    "available for sale",
    "investment propert",
    "biological",
)

_PPE_TOKENS: tuple[str, ...] = (
    "property, plant",
    "property plant",
    "plant and equipment",
    "fixed asset",
)

# Generic names that IAS 16 reserves for PP&E even without naming it.
_GENERIC_PPE_REVAL: tuple[str, ...] = (
    "revaluation surplus",
    "revaluation model",
)


def is_ppe_revaluation_line(line_item: str) -> bool:
    """True if this line-item name is a PP&E revaluation reserve.

    Matches the four spellings the dataset actually carries plus the literal
    ``revaluation model`` line, and rejects revaluation reserves belonging to
    financial assets, securities, investment property or biological assets.
    """
    if not line_item:
        return False
    name = line_item.strip().lower()
    if "revalu" not in name:
        return False
    if any(tok in name for tok in _REVAL_EXCLUDE_TOKENS):
        return False
    if any(tok in name for tok in _PPE_TOKENS):
        return True
    return any(tok in name for tok in _GENERIC_PPE_REVAL)


def uses_revaluation_model(rows: object) -> bool:
    """True if any row is a PP&E revaluation line carrying a non-zero value.

    ``rows`` is an iterable of mappings with ``LineItemENG`` and ``Value`` keys —
    the shape ``lib.data_loader.get_financial_rows`` returns. A zero balance is
    not evidence: the export emits explicit zeros for lines a filer left blank.
    """
    for row in rows:  # type: ignore[union-attr]
        try:
            name = row["LineItemENG"]
            value = row["Value"]
        except (TypeError, KeyError, IndexError):
            continue
        if value and is_ppe_revaluation_line(name):
            return True
    return False


def revaluation_years(rows: object) -> set[int]:
    """Years in which a PP&E revaluation reserve carries a non-zero balance.

    ``rows`` is the output of ``lib.data_loader.get_revaluation_rows``. The set is
    returned rather than a bool so callers can say *when* — but see
    ``measurement_model_badge`` for why the badge must not be gated on the latest
    year alone.
    """
    years: set[int] = set()
    for row in rows:  # type: ignore[union-attr]
        try:
            name = row["LineItemENG"]
            value = row["Value"]
            year = int(row["FVYear"])
        except (TypeError, KeyError, IndexError, ValueError):
            continue
        if value and is_ppe_revaluation_line(name):
            years.add(year)
    return years


def measurement_model_badge(
    reval_years: set[int] | bool,
    latest_year: int | None = None,
) -> Badge | None:
    """Chip flagging the revaluation model. Returns ``None`` for the cost model.

    Only the revaluation model gets a chip — it is the exception, and the one that
    breaks comparability of asset bases and depreciation against a cost-model peer.
    Badging every cost-model filer would be noise on ~87% of the universe.

    **Fires on ANY year, not just the latest, and that is deliberate.** Gating on
    the latest year was measured against the live DB (2026-07-31) and dropped 345
    of 1,106 companies. Every single one of those 345 had simply stopped
    disclosing the line — not one carried it at zero. A revaluation surplus does
    not evaporate, and moving off the revaluation model is a policy change under
    IAS 8, so a missing line is a disclosure gap, not a return to cost. The
    revalued carrying amount is still in the asset base either way, which is what
    the comparability warning is about. When the reserve was last seen in an
    earlier year the tooltip says so.
    """
    years = reval_years if isinstance(reval_years, set) else set()
    if isinstance(reval_years, bool):
        if not reval_years:
            return None
    elif not years:
        return None

    tip = (
        "This company carries a PP&E revaluation reserve, so it measures "
        "property, plant and equipment at revalued amount (IAS 16) rather than at "
        "cost. Asset base, depreciation and any ratio built on them are not "
        "directly comparable with a cost-model peer."
    )
    if years and latest_year is not None and latest_year not in years:
        tip += (
            f" Last separately disclosed in FY{max(years)}; the line is absent "
            f"from later filings. That is a disclosure gap — the revalued amounts "
            f"remain in the asset base — not a return to the cost model."
        )
    return Badge(icon="swap_vert", label="PP&E at revalued amount", tooltip=tip)


def provenance_badges(
    category: str | None,
    form_type: str | None = None,
    revaluation: set[int] | bool = False,
    has_audit_report: bool | None = None,
    latest_year: int | None = None,
) -> list[Badge]:
    """The full provenance strip, in display order, skipping what we can't say."""
    candidates = (
        category_badge(category),
        standard_badge(category, form_type),
        audit_status(category, has_audit_report),
        measurement_model_badge(revaluation, latest_year),
    )
    return [b for b in candidates if b is not None]


# --- resolving a company's years into one strip ------------------------------

def category_runs(meta_by_year: dict[int, dict]) -> list[tuple[int, int, str]]:
    """Contiguous ``(first_year, last_year, category)`` runs, oldest first.

    Years with an unknown category are skipped rather than breaking a run — a
    single missing declaration in the middle of a stable history is a gap in our
    data, not evidence the company changed category and changed back.
    """
    known = [
        (year, cat)
        for year, cat in sorted(
            (y, normalize_category(m.get("category"))) for y, m in meta_by_year.items()
        )
        if cat is not None
    ]
    runs: list[tuple[int, int, str]] = []
    for year, cat in known:
        if runs and runs[-1][2] == cat:
            runs[-1] = (runs[-1][0], year, cat)
        else:
            runs.append((year, year, cat))
    return runs


def category_change_note(meta_by_year: dict[int, dict]) -> str | None:
    """A caption when the category changed across the years held; else ``None``.

    This is the payoff of storing category per year: a company that moved from
    III to II changed reporting standard *and* picked up an audit obligation
    mid-history, so the earlier years are not like the later ones. Badging only
    the latest year would hide that.
    """
    runs = category_runs(meta_by_year)
    if len(runs) < 2:
        return None
    parts = [
        f"{CATEGORY_LABELS[cat]} (FY{lo})" if lo == hi
        else f"{CATEGORY_LABELS[cat]} (FY{lo}–FY{hi})"
        for lo, hi, cat in runs
    ]
    return (
        "Category changed over the period held: " + " → ".join(parts) + ". "
        "The reporting standard and audit obligation change with it, so the "
        "earlier years are not prepared on the same basis as the later ones."
    )


def resolve_filing_provenance(
    meta_by_year: dict[int, dict],
    latest_fallback: dict | None = None,
    revaluation: set[int] | bool = False,
    has_audit_report: bool | None = None,
) -> tuple[int | None, list[Badge], str | None]:
    """``(year_described, badges, change_note)`` for a company's header strip.

    The strip describes the **latest filed year**, since that is the company's
    current standing; ``change_note`` covers the rest of the history.

    ``latest_fallback`` is ``companies.LatestCategory``/``LatestFormType``, used
    only when ``meta_by_year`` is empty (a DB built before
    ``company_filing_meta`` existed). That fallback describes the latest filing
    and is applied to the latest year only, never spread across the history.
    """
    if meta_by_year:
        year = max(meta_by_year)
        latest = meta_by_year[year]
        badges = provenance_badges(
            latest.get("category"), latest.get("form_type"),
            revaluation, has_audit_report, latest_year=year,
        )
        return year, badges, category_change_note(meta_by_year)

    if latest_fallback:
        badges = provenance_badges(
            latest_fallback.get("category"), latest_fallback.get("form_type"),
            revaluation, has_audit_report,
            latest_year=latest_fallback.get("latest_year"),
        )
        return None, badges, None

    return None, [], None
