# -*- coding: ascii -*-
"""
run_verify.py -- Standalone verification worker for the MemorialWiki-4C Space.

Runs as a SUBPROCESS per request (fresh SWI-Prolog engine each time), so
facts from one visitor's file can never leak into another session.

Usage:   python run_verify.py <input.ged>
Output:  single JSON document on stdout.

ASCII-only. Works on Python 3.10 (local llmwiki env) and 3.12 (HF Space).
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gedcom_to_prolog import compile_gedcom  # noqa: E402

RULES_PATH = os.path.join(HERE, "genealogy_rules.pl")

MESSAGES = {
    "death_before_birth":
        "{0} has a death date earlier than their birth date.",
    "ancestry_cycle":
        "{0} appears in an ancestry cycle (is recorded as their own "
        "ancestor).",
    "parent_born_after_child":
        "{0} is recorded as a parent of {1} but was born after them.",
    "parent_under_12_at_birth":
        "{0} would have been under 12 years old at the birth of {1}.",
    "mother_over_70_at_birth":
        "{0} would have been over 70 years old at the birth of {1}.",
    "born_after_mother_death":
        "{1} is recorded as born after the death of their mother {0}.",
    "born_after_father_death":
        "{1} is recorded as born more than a year after the death of "
        "their father {0}.",
    "lifespan_over_125":
        "{0} has a recorded lifespan exceeding 125 years.",
    "married_after_death":
        "{0} has a marriage in family {1} dated after their death.",
    "married_before_birth":
        "{0} has a marriage in family {1} dated before their birth.",
    "spouse_role_conflict":
        "{0} is recorded as both husband and wife in family {1}.",
    "self_parent":
        "{0} is recorded as both spouse and child in family {1}.",
    "parent_under_16_at_birth":
        "{0} would have been under 16 at the birth of {1} (please review).",
    "mother_over_55_at_birth":
        "{0} would have been over 55 at the birth of {1} (please review).",
    "lifespan_over_110":
        "{0} has a recorded lifespan over 110 years (please review).",
    "married_under_16":
        "{0} would have been under 16 at their marriage in family {1}.",
    "husband_recorded_female":
        "{0} is recorded as husband in family {1} but has sex F "
        "(possible data-entry issue).",
    "wife_recorded_male":
        "{0} is recorded as wife in family {1} but has sex M "
        "(possible data-entry issue).",
    "father_over_80_at_birth":
        "{0} would have been over 80 at the birth of {1} (please review).",
    "violation_uses_approx_date":
        "A finding involving {0} relies on an approximate date "
        "(ABT/EST/BEF/AFT); confirm the underlying record.",
}

GAP_MESSAGES = {
    "name": "no name recorded",
    "birth_date": "no birth date recorded",
    "birth_year": "birth date has no usable year",
    "sex": "no sex recorded",
    "marriage_date": "married couple has no marriage date",
}


def _s(t):
    x = str(t)
    if x.startswith("'") and x.endswith("'"):
        x = x[1:-1]
    return x


def verify(gedcom_path):
    tmp = tempfile.mkdtemp(prefix="mw4c_")
    facts_path = os.path.join(tmp, "facts.pl")
    stats = compile_gedcom(gedcom_path, facts_path)

    from pyswip import Prolog
    prolog = Prolog()
    prolog.consult(RULES_PATH.replace(os.sep, "/"))
    prolog.consult(facts_path.replace(os.sep, "/"))

    names = {}
    for r in prolog.query("person_name(P, N)"):
        names[_s(r["P"])] = _s(r["N"])

    def label(e):
        e = _s(e)
        return "%s (%s)" % (names[e], e) if e in names else e

    findings, seen = [], set()
    for r in prolog.query("finding(Sev, Code, Args)"):
        sev, code = _s(r["Sev"]), _s(r["Code"])
        args = [_s(a) for a in r["Args"]]
        key = (sev, code, tuple(args))
        if key in seen:
            continue
        seen.add(key)
        labeled = [label(a) for a in args]
        msg = MESSAGES.get(code, code + ": " + ", ".join(labeled))
        findings.append({"severity": sev, "code": code,
                         "entities": args, "message": msg.format(*labeled)})

    gaps = []
    for r in prolog.query("gap(E, W)"):
        e, w = _s(r["E"]), _s(r["W"])
        gaps.append({"entity": e, "gap": w,
                     "message": "%s: %s" % (label(e),
                                            GAP_MESSAGES.get(w, w))})

    parse_issues = [_s(r["M"]) for r in prolog.query("parse_issue(M)")]

    report = {
        "source": os.path.basename(gedcom_path),
        "stats": stats,
        "violations": [f for f in findings if f["severity"] == "violation"],
        "warnings": [f for f in findings if f["severity"] == "warning"],
        "completeness_gaps": gaps,
        "parse_issues": parse_issues,
    }
    report["summary"] = {
        "violations": len(report["violations"]),
        "warnings": len(report["warnings"]),
        "completeness_gaps": len(gaps),
        "parse_issues": len(parse_issues),
        "verdict": ("REJECT" if report["violations"]
                    else "REVIEW" if report["warnings"] or parse_issues
                    else "PASS"),
    }
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: run_verify.py <input.ged>"}))
        sys.exit(1)
    try:
        rep = verify(sys.argv[1])
        print(json.dumps(rep))
    except Exception as exc:  # report as JSON, never crash the UI
        print(json.dumps({"error": str(exc)}))
        sys.exit(0)
