"""Audit-engagement data model (reportal RMS ``Auditors`` files) — pure, no Streamlit/DB.

Source: the per-year ``Auditors <year>.xlsx`` bulk file from ``rms.reportal.ge``
(request-gated). One spreadsheet row per *filing* — a company files individually
and, if it heads a group, again on a consolidated basis, and the two can carry
**different opinions from the same firm**. So the natural key is
``(IdCode, FVYear, IsConsolidated)``, never ``(IdCode, FVYear)`` alone.

Two source quirks this module exists to absorb:

* ``CategoryMain`` fuses the reporting category and the consolidation basis into
  one string — ``"II"`` vs ``"II ჯგუფი"`` (ჯგუფი = "group"). See
  :func:`split_category`.
* A filing appears on **several rows when it has more than one non-audit service
  engagement** — every column repeats except ``ServicePayment``. Summing that
  column is the only correct read of total non-audit fees; taking one row
  understates them. See :func:`collapse_filings`.

``Income`` / ``Assets`` are absolute GEL and need no scaling. The ``Thousands``
column describes the *source filing's* presentation unit, not these values —
verified against ``metrics_panel`` FY2024, where ``Thousands=1`` rows still match
1:1 (median ratio 1.0000). Carry it as metadata; never multiply by it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Opinion taxonomy
# --------------------------------------------------------------------------
# Georgian opinion string -> (code, english).
#
# "Modified" follows ISA 705 strictly: only QUALIFIED / ADVERSE / DISCLAIMER
# modify the *opinion*. An Emphasis-of-Matter or Other-Matter paragraph
# (ISA 706) is an unmodified opinion with an added communication — it is NOT a
# modification, and grouping it as one would overstate the distress signal.
# `is_modified` is derived from the code via MODIFIED_CODES below, so the two
# never drift apart.
OPINION_CODES: dict[str, tuple[str, str]] = {
    "არამოდიფიცირებული მოსაზრება": ("UNMODIFIED", "Unmodified"),
    "არამოდიფიცირებული მოსაზრება მნიშვნელოვან გარემოებათა ამსახველი აბზაცით": (
        "UNMODIFIED_EOM", "Unmodified with emphasis of matter"),
    "არამოდიფიცირებული მოსაზრება სხვა გარემოებათა ამსახველი აბზაცით": (
        "UNMODIFIED_OM", "Unmodified with other matter"),
    "პირობითი მოსაზრება": ("QUALIFIED", "Qualified"),
    "უარყოფითი მოსაზრება": ("ADVERSE", "Adverse"),
    "მოსაზრების გამოთქმაზე უარი": ("DISCLAIMER", "Disclaimer of opinion"),
}

#: Codes that constitute a modified opinion under ISA 705.
MODIFIED_CODES: frozenset[str] = frozenset({"QUALIFIED", "ADVERSE", "DISCLAIMER"})

#: Codes that are clean opinions (no ISA 705 modification), incl. EOM/OM paragraphs.
UNMODIFIED_CODES: frozenset[str] = frozenset(
    {"UNMODIFIED", "UNMODIFIED_EOM", "UNMODIFIED_OM"}
)

#: Consolidated filings carry this suffix in ``CategoryMain`` ("group").
GROUP_SUFFIX = "ჯგუფი"

#: Public-interest entity category, as spelled in ``CategoryMain``.
PIE_CATEGORY_GEO = "სდპ"


def opinion_code(raw: str | None) -> str | None:
    """Map a raw Georgian opinion string to a stable code, or ``None``.

    Unknown non-empty strings map to ``"OTHER"`` rather than ``None`` so that a
    new opinion wording introduced by SARAS shows up as an unclassified value in
    the data instead of silently vanishing into the not-audited bucket.
    """
    if raw is None:
        return None
    s = " ".join(str(raw).split())
    if not s or s == "NULL":
        return None
    hit = OPINION_CODES.get(s)
    return hit[0] if hit else "OTHER"


def opinion_english(code: str | None) -> str | None:
    """English label for an opinion code."""
    if code is None:
        return None
    for c, eng in OPINION_CODES.values():
        if c == code:
            return eng
    return "Other / unclassified"


def is_modified_opinion(code: str | None) -> bool | None:
    """``True`` for an ISA 705 modified opinion, ``False`` for clean, ``None`` if unaudited.

    ``"OTHER"`` returns ``None``: an unrecognised wording is *unknown*, and
    defaulting it to clean would hide exactly the case worth looking at.
    """
    if code is None or code == "OTHER":
        return None
    return code in MODIFIED_CODES


def split_category(category_main: str | None) -> tuple[str | None, bool]:
    """Split ``CategoryMain`` into ``(category, is_consolidated)``.

    >>> split_category("II ჯგუფი")
    ('II', True)
    >>> split_category("სდპ")
    ('სდპ', False)
    >>> split_category(None)
    (None, False)
    """
    if category_main is None:
        return None, False
    s = " ".join(str(category_main).split())
    if not s or s == "NULL":
        return None, False
    if s.endswith(GROUP_SUFFIX):
        return (s[: -len(GROUP_SUFFIX)].strip() or None), True
    return s, False


def normalize_saras_code(raw: str | None) -> str | None:
    """Upper-case a SARAS auditor registration number and squash inner whitespace.

    The source mixes ``SARAS-A-720718``, ``saras-a-317228`` and ``Saras-A-506913``
    for what is one identifier namespace, so joins fail without this.
    """
    if raw is None:
        return None
    s = " ".join(str(raw).split()).upper()
    if not s or s == "NULL":
        return None
    return s


def normalize_firm_name(raw: str | None) -> str | None:
    """Trim and squash whitespace in an audit-firm name.

    Trailing spaces are common in the source (``"შპს KPMG Georgia "``) and would
    otherwise split one firm into two on any group-by. Unaudited filings carry the
    literal string ``"NULL"``, which must become ``None`` — left as-is it reads as
    a firm named "NULL" and marks every filing audited.
    """
    return clean_text(raw)


def clean_text(raw: object) -> str | None:
    """Normalize a free-text cell; ``None`` for empties and the literal ``"NULL"``."""
    if raw is None:
        return None
    s = " ".join(str(raw).split())
    if not s or s == "NULL":
        return None
    return s


def to_number(raw: object) -> float | None:
    """Parse a numeric cell tolerantly; ``None`` when absent or unparseable."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(",", "").replace("\xa0", "")
    if not s or s == "NULL":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(raw: object) -> int | None:
    """Parse an integer cell tolerantly (``"550"``, ``550.0`` → ``550``)."""
    v = to_number(raw)
    return None if v is None else int(v)


def to_bool(raw: object) -> bool | None:
    """Parse the source's 0/1 flag columns."""
    v = to_number(raw)
    return None if v is None else bool(v)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def to_date(raw: object) -> str | None:
    """Normalize ``'2024-12-31 00:00:00.000'`` → ``'2024-12-31'``.

    Returns ``None`` for anything that doesn't lead with an ISO date, so a
    surprise format lands as NULL rather than as a corrupt string.
    """
    s = clean_text(raw)
    if s is None:
        return None
    m = _DATE_RE.match(s)
    return m.group(0) if m else None


@dataclass(frozen=True)
class AuditFiling:
    """One audited/unaudited filing — the collapsed unit written to the DB."""

    id_code: str
    fv_year: int
    is_consolidated: bool
    category: str | None
    org_name: str | None
    period_start: str | None
    period_end: str | None
    first_publish_date: str | None
    is_listed: bool | None
    thousands_flag: int | None
    income: float | None
    assets: float | None
    employees: int | None
    partner_first_name: str | None
    partner_last_name: str | None
    saras_code: str | None
    opinion_geo: str | None
    opinion_code: str | None
    audit_firm: str | None
    audit_firm_code: str | None
    auditor_payment: float | None
    service_payment: float | None
    service_engagements: int

    @property
    def is_audited(self) -> bool:
        return self.opinion_code is not None or self.audit_firm is not None

    @property
    def is_modified(self) -> bool | None:
        return is_modified_opinion(self.opinion_code)


#: Canonical field names, as spelled in the FY2022-2024 files.
COLUMNS = (
    "ReportYear", "IdCode", "OrgNameInReport", "CategoryMain", "StartDate", "EndDate",
    "IsListedCompany", "FirstPublishDate", "StatusName", "Thousands", "Income",
    "Assets", "Employees", "LastName", "FirstName", "SARAS_code", "AuditOpinion",
    "AuditFirm", "AuditFirmCode", "AuditorPayment", "ServicePayment",
)

#: Without these a row cannot be keyed at all; a file lacking them is an error.
#: Everything else is optional — FY2018 genuinely ships no ``AuditOpinion`` column,
#: and failing the whole year over that would lose its auditor and fee data too.
REQUIRED_COLUMNS = ("ReportYear", "IdCode")

#: Older headers -> canonical name. SARAS respelled these between years while the
#: meaning stayed put; without the map, FY2018-2022 files parse as all-NULL.
#:
#: The two traps, both settled by the FY2022 pair (file 216 old-style vs 222
#: new-style, same companies):
#:   * ``Auditor`` is the engagement PARTNER's full name, not the firm —
#:     216 ``Auditor = "ივანე ჟუჟუნაშვილი"`` ↔ 222 ``FirstName/LastName``.
#:     ``AuditFirm`` is the firm in both, so it is NOT an alias of ``Auditor``.
#:   * ``Auditor_SARAS_code`` is likewise the PARTNER's registration
#:     (``SARAS-A-720718`` in both files), not the firm's.
#: ``SP_SARAS_code`` / ``SP_Firstname`` / ``SP_Lastname`` appear in some files but
#: are empty in every row sampled, so they are deliberately not mapped.
COLUMN_ALIASES: dict[str, str] = {
    "Organisation": "OrgNameInReport",
    "Category": "CategoryMain",
    "PublishDate": "FirstPublishDate",
    "CurrentStatus": "StatusName",
    "Auditor_SARAS_code": "SARAS_code",
    "AuditFirmIdCode": "AuditFirmCode",
    "Auditor": "PartnerFullName",
}

#: Old-format single-column partner name, split into first/last on read.
PARTNER_FULL_NAME = "PartnerFullName"


def resolve_header(names) -> list[str | None]:
    """Map a sheet's raw header cells to canonical names (``None`` = drop).

    A canonical name already present wins over an alias pointing at it, so a
    file carrying both spellings keeps the canonical column.
    """
    raw = [(" ".join(str(c).split()) if c is not None else None) for c in names]
    present = {c for c in raw if c in COLUMNS or c == PARTNER_FULL_NAME}
    out: list[str | None] = []
    for cell in raw:
        if cell is None:
            out.append(None)
        elif cell in COLUMNS or cell == PARTNER_FULL_NAME:
            out.append(cell)
        else:
            target = COLUMN_ALIASES.get(cell)
            out.append(target if (target and target not in present) else None)
    return out


def split_partner_name(full: str | None) -> tuple[str | None, str | None]:
    """Split an old-format ``"First Last"`` partner name into ``(first, last)``.

    Georgian auditors carry a single given name, so the first token is the
    forename and the remainder the surname. Imprecision here is low-risk: the
    join key across years is ``SARAS_code``, which every file provides.

    >>> split_partner_name("ივანე ჟუჟუნაშვილი")
    ('ივანე', 'ჟუჟუნაშვილი')
    """
    s = clean_text(full)
    if s is None:
        return None, None
    parts = s.split(" ", 1)
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], parts[1]


# --------------------------------------------------------------------------
# Audit-status chip (Single Company header) — picking + labelling one engagement
# --------------------------------------------------------------------------
# These take the dict shape `lib.cache.audit_engagements` returns (year,
# is_consolidated, opinion_code, firm, partner_first, partner_last, fee), not
# `AuditFiling`, so this module stays DB/Streamlit-free while the cache layer
# owns the SQL. Pure — no DB, no Streamlit; see lib/filing_provenance.py for
# the "no positive evidence" fallback wording these feed into.

def latest_engagement_for_basis(
    rows: list[dict], is_consolidated_pref: bool
) -> dict | None:
    """Pick the ``auditors`` row for the audit-status chip.

    Picks the LATEST year present in ``rows``, then within that year prefers
    the row matching ``is_consolidated_pref`` (the Single-Company basis
    toggle) — individual and consolidated filings can carry *different
    opinions from the same firm* (module docstring; e.g. company
    ``200002120`` is unmodified individually and qualified on the group), so
    which one renders matters. Falls back to whichever row exists for that
    year when the preferred basis has none. ``None`` for no rows at all.
    """
    if not rows:
        return None
    latest_year = max(r["year"] for r in rows)
    year_rows = [r for r in rows if r["year"] == latest_year]
    for r in year_rows:
        if r["is_consolidated"] == is_consolidated_pref:
            return r
    return year_rows[0]


def has_audit_evidence(engagement: dict) -> bool:
    """``bool(AuditFirm or OpinionCode)`` on one engagement row.

    The positive-evidence test ``lib/filing_provenance.py::audit_status`` was
    built to consume (see ``docs/handoffs/rms-auditors.md``'s open question,
    now wired up by the audit-status chip).
    """
    return bool(engagement.get("firm") or engagement.get("opinion_code"))


def audit_chip_icon(opinion_code: str | None) -> str:
    """Material icon name for an engagement chip that HAS audit evidence."""
    modified = is_modified_opinion(opinion_code)
    if modified is True:
        return "gpp_maybe"
    if modified is False:
        return "verified"
    return "task"  # opinion unknown: no AuditOpinion column (FY2018), or "OTHER"


def audit_chip_label(opinion_code: str | None, firm: str | None, year: int) -> str:
    """Caption text for an engagement with positive audit evidence.

    Caller has already established :func:`has_audit_evidence` — this only
    decides the wording. Three cases, matching :func:`is_modified_opinion`'s
    three-way return: unmodified (clean, incl. EOM/OM — the module docstring
    explains why those don't count as modified), modified (names QUALIFIED /
    ADVERSE / DISCLAIMER by their English label), and unknown (FY2018 ships no
    ``AuditOpinion`` column at all, or a future SARAS wording lands as
    ``"OTHER"``) — the last says only "Audited", never guessing which.
    """
    modified = is_modified_opinion(opinion_code)
    who = firm or "an unnamed auditor"
    if modified is True:
        eng = (opinion_english(opinion_code) or "Modified").lower()
        return f"Audited — {who} · {eng} opinion (FY{year})"
    if modified is False:
        return f"Audited — {who} · unmodified opinion (FY{year})"
    return f"Audited — {who} (FY{year})"


def collapse_filings(rows: list[dict]) -> list[AuditFiling]:
    """Collapse raw spreadsheet rows into one :class:`AuditFiling` per filing.

    ``rows`` are dicts keyed by the source headers in :data:`COLUMNS`.

    Rows sharing ``(IdCode, FVYear, IsConsolidated)`` are one filing listed once
    per non-audit service engagement. ``ServicePayment`` is **summed** across
    them and ``service_engagements`` records how many contributed; every other
    field is taken from the first row, which the source repeats verbatim.

    Rows without an ``IdCode`` are dropped — Category IV is anonymised at source
    (no IdCode, no OrgName), so those rows can never be attributed to a company.
    """
    order: list[tuple[str, int, bool]] = []
    grouped: dict[tuple[str, int, bool], list[dict]] = {}

    for r in rows:
        id_code = clean_text(r.get("IdCode"))
        fv_year = to_int(r.get("ReportYear"))
        if not id_code or fv_year is None:
            continue
        _, is_consolidated = split_category(r.get("CategoryMain"))
        key = (id_code, fv_year, is_consolidated)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(r)

    out: list[AuditFiling] = []
    for key in order:
        members = grouped[key]
        head = members[0]
        category, is_consolidated = split_category(head.get("CategoryMain"))

        # New-format files split the partner name; old ones carry it whole.
        first_name = clean_text(head.get("FirstName"))
        last_name = clean_text(head.get("LastName"))
        if first_name is None and last_name is None:
            first_name, last_name = split_partner_name(head.get(PARTNER_FULL_NAME))

        service_values = [to_number(m.get("ServicePayment")) for m in members]
        service_values = [v for v in service_values if v is not None]
        service_total = sum(service_values) if service_values else None

        opinion_geo = clean_text(head.get("AuditOpinion"))
        out.append(
            AuditFiling(
                id_code=key[0],
                fv_year=key[1],
                is_consolidated=is_consolidated,
                category=category,
                org_name=clean_text(head.get("OrgNameInReport")),
                period_start=to_date(head.get("StartDate")),
                period_end=to_date(head.get("EndDate")),
                first_publish_date=to_date(head.get("FirstPublishDate")),
                is_listed=to_bool(head.get("IsListedCompany")),
                thousands_flag=to_int(head.get("Thousands")),
                income=to_number(head.get("Income")),
                assets=to_number(head.get("Assets")),
                employees=to_int(head.get("Employees")),
                partner_first_name=first_name,
                partner_last_name=last_name,
                saras_code=normalize_saras_code(head.get("SARAS_code")),
                opinion_geo=opinion_geo,
                opinion_code=opinion_code(opinion_geo),
                audit_firm=normalize_firm_name(head.get("AuditFirm")),
                audit_firm_code=clean_text(head.get("AuditFirmCode")),
                auditor_payment=to_number(head.get("AuditorPayment")),
                service_payment=service_total,
                service_engagements=len(service_values),
            )
        )
    return out
