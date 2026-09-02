"""Deterministic Mutterschutz timeline — the dates a language model must NOT compute itself.

Why this file exists
--------------------
An LLM asked to do date arithmetic will be right most of the time, and "most of the time" is
unacceptable for a legal deadline: a wrong Mutterschutz start date can cost someone a benefit
or a job protection they were entitled to. So the labour is split. The model's job is to
*retrieve the rule* and explain it; this module's job is to *apply the rule* with Python's
calendar arithmetic, which is exact by construction. That separation is the entire point of
Phase 9 — there is no model call anywhere in this file, and there must never be one.

Every date this returns carries the rule it came from and the `source_chunk` (a corpus
chunk_id) that states that rule. A date without a traceable rule is not returned. The rules
below were verified against `data/chunks.jsonl`; the chunk_ids are load-bearing, not decorative.

Scope (Phase 9): dates only. This tool never states a benefit amount and never decides whether
a person is eligible — it reports the general statutory rule and names who confirms the rest.
It is standalone and tested; wiring it into generation / the graph is Phase 11.

    from tools.timeline import calculate_timeline
    calculate_timeline("2027-03-15", "employed")
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

# --- rule constants (verified against data/chunks.jsonl) --------------------------------------
# Each rule is (text, source_chunk, authority, authority_tier, last_verified).
_FAM = ("Familienportal des Bundes", "federal", "2026-08-03")
_TIMELINE_CHUNK = "fam_mutterschutz__wie-lange-besteht-der-mutterschutz-vor-und-nach-der-geburt__ac481a5a"

RULE_START = (
    "The maternity protection period (Mutterschutzfrist) begins 6 weeks before the expected "
    "date of birth.", _TIMELINE_CHUNK, *_FAM)
RULE_END_NORMAL = (
    "The protection period normally ends 8 weeks after birth.", _TIMELINE_CHUNK, *_FAM)
RULE_EARLY = (
    "If the child is born before the expected date, the period after birth is lengthened by the "
    "number of days the birth came early, so the total protection stays 14 weeks.",
    _TIMELINE_CHUNK, *_FAM)
RULE_LATE = (
    "If the child is born after the expected date, the full 8 weeks after the actual birth "
    "still apply.", _TIMELINE_CHUNK, *_FAM)
RULE_PREMATURE = (
    "For a premature birth (Fruehgeburt), the period after birth is 12 weeks.",
    _TIMELINE_CHUNK, *_FAM)
RULE_MULTIPLE = (
    "For a multiple birth (twins or more), the period after birth is extended to 12 weeks.",
    "fam_mutterschutz__welche-regelungen-gelten-wenn-ich-zwillinge-oder-weitere-meh__e7d7850e",
    *_FAM)
RULE_DISABILITY = (
    "If a disability is diagnosed in the newborn within 8 weeks of birth, the period after "
    "birth can be extended to 12 weeks on application to the health insurer.",
    "fam_mutterschutz__welche-regelungen-gelten-fuer-die-mutterschutzfrist-bei-eine__cef1fbda",
    *_FAM)
RULE_ELTERNGELD = (
    "Elterngeld can only be applied for after birth and should be applied for within the first "
    "3 months of the child's life; it is paid retroactively for at most 3 months of life.",
    "fam_elterngeld_antrag__wie-kann-ich-elterngeld-beantragen__ab9bc2fa", *_FAM)
RULE_BEAMTIN = (
    "For civil servants (Beamtinnen), maternity protection follows a separate regulation "
    "(Mutterschutzverordnung of the Bund or the Land), not the general Mutterschutzgesetz.",
    "fam_mutterschutz__welche-regelungen-fuer-den-mutterschutz-gelten-fuer-beamtinn__eb325d8b",
    *_FAM)

_PRE = timedelta(days=42)          # 6 weeks before expected birth
_POST_NORMAL = timedelta(days=56)  # 8 weeks after birth
_POST_EXTENDED = timedelta(days=84)  # 12 weeks after birth

MAX_FUTURE_DAYS = 315              # a plausible due date is at most ~10 months ahead
ALLOWED_STATUS = {"employed", "self-employed", "marginally-employed", "student",
                  "civil-servant", "not-employed"}


def add_months(d: date, n: int) -> date:
    """Add n calendar months, clamping to the last valid day (31 Jan + 1 month -> 28/29 Feb)."""
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse(value, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field} is not a valid ISO date (YYYY-MM-DD): {value!r}")


def _rule(t: tuple) -> dict:
    return {"rule": t[0], "source_chunk": t[1], "authority": t[2],
            "authority_tier": t[3], "last_verified": t[4]}


def calculate_timeline(
    due_date,
    employment_status: str,
    *,
    actual_birth_date=None,
    multiple_birth: bool = False,
    premature: bool = False,
    disability_diagnosed_within_8_weeks: bool = False,
    today: date | None = None,
) -> dict:
    """Return the Mutterschutz timeline for an expected (or actual) birth. Dates only.

    Planning mode (no actual_birth_date): dates are anchored on the expected date.
    Actual mode (actual_birth_date given): the after-period follows the early/late/extension
    rules from the corpus. Raises ValueError on implausible or malformed input.
    """
    due = _parse(due_date, "due_date")
    birth = _parse(actual_birth_date, "actual_birth_date") if actual_birth_date is not None else None
    if employment_status not in ALLOWED_STATUS:
        raise ValueError(f"unknown employment_status: {employment_status!r} "
                         f"(expected one of {sorted(ALLOWED_STATUS)})")
    today = today or date.today()

    if birth is None:
        if due < today:
            raise ValueError("expected date of birth is in the past")
        if (due - today).days > MAX_FUTURE_DAYS:
            raise ValueError("expected date of birth is implausibly far in the future")
    else:
        if birth > today:
            raise ValueError("actual birth date is in the future")

    extended = premature or multiple_birth or disability_diagnosed_within_8_weeks
    protection_starts = due - _PRE

    rules = [_rule(RULE_START)]
    if birth is None:
        protection_ends = due + (_POST_EXTENDED if extended else _POST_NORMAL)
    elif not extended and birth < due:
        days_early = (due - birth).days
        protection_ends = birth + _POST_NORMAL + timedelta(days=days_early)
    else:
        protection_ends = birth + (_POST_EXTENDED if extended else _POST_NORMAL)

    # rules backing the after-period
    if extended:
        if premature:
            rules.append(_rule(RULE_PREMATURE))
        if multiple_birth:
            rules.append(_rule(RULE_MULTIPLE))
        if disability_diagnosed_within_8_weeks:
            rules.append(_rule(RULE_DISABILITY))
    else:
        rules.append(_rule(RULE_END_NORMAL))
        if birth is not None and birth < due:
            rules.append(_rule(RULE_EARLY))
        elif birth is not None and birth > due:
            rules.append(_rule(RULE_LATE))

    # Elterngeld application window (a real date the corpus states)
    anchor_birth = birth if birth is not None else due
    elterngeld_apply_by = add_months(anchor_birth, 3)
    rules.append(_rule(RULE_ELTERNGELD))

    caveats = [
        "Actual dates depend on the certificate of your expected date of birth from your "
        "doctor or midwife (recorded in the Mutterpass).",
        "This tool reports the general statutory rule only; it does not decide what applies to "
        "you personally or state any payment.",
        "The corpus does not state an application window for Mutterschaftsgeld — ask your "
        "health insurer (Krankenkasse) how and when to claim it.",
    ]
    if birth is None:
        caveats.append("These dates assume birth on the expected date; if the birth is earlier "
                       "or later, the period after birth adjusts (see the rules).")

    confirm = {
        "employed": ["your employer", "your health insurer (Krankenkasse)"],
        "marginally-employed": ["your employer", "your health insurer (Krankenkasse)"],
        "self-employed": ["your health insurer (Krankenkasse)"],
        "student": ["your university", "your health insurer (Krankenkasse)"],
        "civil-servant": ["your Personalstelle (HR office)"],
        "not-employed": ["your health insurer (Krankenkasse)"],
    }[employment_status]

    if employment_status == "civil-servant":
        rules.append(_rule(RULE_BEAMTIN))
        caveats.append("As a civil servant (verbeamtet), your maternity protection follows a "
                       "separate regulation (Mutterschutzverordnung), which can differ by Bund "
                       "and Land; confirm the dates that apply to you with your Personalstelle.")

    return {
        "expected_birth": due.isoformat(),
        "actual_birth": birth.isoformat() if birth is not None else None,
        "protection_starts": protection_starts.isoformat(),
        "protection_ends": protection_ends.isoformat(),
        "elterngeld_apply_by": elterngeld_apply_by.isoformat(),
        "rules_applied": rules,
        "caveats": caveats,
        "needs_confirmation_from": confirm,
    }
