"""Election Insights — 2026 TN Assembly election (OBSERVED layer, P1).

Serves the analysis tab: state summary, all 234 constituencies, district
rollups, and the 2021->2026 swing. Everything here is OBSERVED (results,
turnout, electors) — the inferred demographic layer (P3) is a separate route.

Credits (per the dashboard's sourcing rule, shown on the tab too):
  - Method / forensics primer: github.com/kaduvan/election-forensics
  - Analysis inspiration:        X / @_kaduvan
  - Results data:                ECI (results.eci.gov.in), via the
                                 tnelections2026.in aggregator; headline
                                 figures spot-checked against ECI final.
"""
from __future__ import annotations
from fastapi import APIRouter
from app.database import get_db

router = APIRouter(prefix="/election", tags=["election"])

# ECI-certified state figures (results.eci.gov.in / ECI final, cross-checked
# 2026-06-28). Hard-coded as a Tier-1 reference because the per-candidate vote
# counts are not in the accessible feed; these are the official state totals.
_ECI_STATE = {
    "turnout_pct": 85.1,
    "registered_electors": 57343291,
    "parties": [
        {"party": "TVK",    "votes": 17226209, "vote_share": 34.92, "swing": None,    "seats": 108},
        {"party": "DMK",    "votes": 11926144, "vote_share": 24.19, "swing": -13.51,  "seats": 59},
        {"party": "AIADMK", "votes": 10462146, "vote_share": 21.21, "swing": -12.08,  "seats": 47},
    ],
    "alliances": [
        {"alliance": "TVK",       "vote_share": 35.02, "seats": 108},
        {"alliance": "SPA-DMK+",  "vote_share": 31.40, "seats": 73},
        {"alliance": "NDA-ADMK+", "vote_share": 27.21, "seats": 53},
    ],
    # OBSERVED gender turnout — % of each gender's electors who actually voted.
    # This is turnout (who showed up), NOT how they voted. Source: ECI / CEO TN.
    "turnout_by_gender": {"male": 83.57, "female": 85.76, "third": 60.49},
    "source": "ECI (results.eci.gov.in), 2026 final",
}

_CREDITS = {
    "method": "github.com/kaduvan/election-forensics",
    "analysis_inspiration": "X / @_kaduvan",
    "results_data": "ECI via tnelections2026.in (aggregator); spot-checked vs ECI final",
}


# 5-player focus: collapse every party into TVK / DMK+ (SPA) / ADMK+ (NDA) /
# NTK / OTHERS so charts show the major players, not a long tail of small parties.
# 2026 alliances (per CEO TN / DMK seat-sharing): DMDK is in SPA (DMK+) this
# time, and AMMK is in NDA (ADMK+). PT contested outside the two fronts (OTHERS).
_BUCKET_MAP = {
    "TVK": "TVK", "NTK": "NTK",
    # SPA / DMK+
    "DMK": "DMK+", "INC": "DMK+", "DMDK": "DMK+", "VCK": "DMK+", "CPI": "DMK+", "CPI(M)": "DMK+",
    "CPM": "DMK+", "IUML": "DMK+", "MDMK": "DMK+", "KMDK": "DMK+", "MMK": "DMK+", "MVK": "DMK+",
    "MJK": "DMK+", "SDPI": "DMK+", "MPP": "DMK+", "TDK": "DMK+",
    # NDA / ADMK+
    "ADMK": "ADMK+", "AIADMK": "ADMK+", "PMK": "ADMK+", "BJP": "ADMK+", "AMMK": "ADMK+",
}
PLAYER_ORDER = {"TVK": 0, "DMK+": 1, "ADMK+": 2, "NTK": 3, "OTHERS": 4}


def bucket(party: str) -> str:
    return _BUCKET_MAP.get((party or "").strip(), "OTHERS")


def _all_constituencies(db) -> list[dict]:
    rows, offset = [], 0
    while True:
        batch = (db.table("election_constituencies").select("*")
                 .range(offset, offset + 999).order("ac_no").execute().data or [])
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    return rows


@router.get("/summary")
async def election_summary():
    db = get_db()
    cons = _all_constituencies(db)

    seats_2026: dict[str, int] = {}
    seats_2021: dict[str, int] = {}
    flips = 0
    e_total = e_male = e_female = e_third = 0
    for c in cons:
        w26, w21 = c.get("winner_2026"), c.get("winner_2021")
        if w26:
            b = bucket(w26); seats_2026[b] = seats_2026.get(b, 0) + 1
        if w21:
            b = bucket(w21); seats_2021[b] = seats_2021.get(b, 0) + 1
        if w26 and w21 and w26 != w21:
            flips += 1
        e_total  += c.get("electors") or 0
        e_male   += c.get("electors_male") or 0
        e_female += c.get("electors_female") or 0
        e_third  += c.get("electors_third") or 0

    return {
        "total_seats": len(cons),
        "seats_2026": dict(sorted(seats_2026.items(), key=lambda x: -x[1])),
        "seats_2021": dict(sorted(seats_2021.items(), key=lambda x: -x[1])),
        "flips_2021_to_2026": flips,
        "electors": {"total": e_total, "male": e_male, "female": e_female, "third": e_third},
        "eci_state": _ECI_STATE,
        "credits": _CREDITS,
        "honest_note": (
            "Seat counts are computed from per-constituency winners (matches ECI "
            "final: TVK 108 / DMK 59 / AIADMK 47). State vote totals are ECI-certified. "
            "DMK fell 133->59 and TVK rose 0->108: a real anti-incumbent wave, shown "
            "straight. No fraud is claimed — this is post-result analysis."
        ),
    }


@router.get("/constituencies")
async def list_constituencies():
    """All 234 ACs for the map / filterable table, with flip flag + female share."""
    db = get_db()
    out = []
    for c in _all_constituencies(db):
        el = c.get("electors") or 0
        out.append({
            **c,
            "flipped": bool(c.get("winner_2026") and c.get("winner_2021")
                            and c["winner_2026"] != c["winner_2021"]),
            "female_share": round((c.get("electors_female") or 0) / el * 100, 1) if el else None,
        })
    return out


def _booths_for_acs(db, ac_nos: list[int]) -> dict[int, list[dict]]:
    """All booth rows grouped by ac_no (paged past 1000)."""
    out: dict[int, list[dict]] = {}
    # Fetch one AC at a time with a STABLE order so range-pagination can't drop
    # or duplicate rows (PostgREST range without ORDER BY is undefined order).
    for ac in ac_nos:
        offset = 0
        while True:
            batch = (db.table("election_booth_results").select("*").eq("ac_no", ac)
                     .order("booth_no").order("party")
                     .range(offset, offset + 999).execute().data or [])
            for r in batch:
                out.setdefault(r["ac_no"], []).append(r)
            if len(batch) < 1000:
                break
            offset += 1000
    return out


def _booth_summary(rows: list[dict]) -> dict:
    """From per-booth-per-party rows -> AC booth insight: booth-wins by party,
    party totals, stronghold/swing counts."""
    booths: dict[int, dict[str, int]] = {}
    totals: dict[int, int] = {}
    for r in rows:
        booths.setdefault(r["booth_no"], {})[r["party"]] = r["votes"]
        totals[r["booth_no"]] = r.get("total_polled") or totals.get(r["booth_no"], 0)
    booth_wins: dict[str, int] = {}
    party_totals: dict[str, int] = {}
    margins = []
    for bno, pv in booths.items():
        contest = {p: v for p, v in pv.items() if p != "NOTA"}
        for p, v in pv.items():
            party_totals[p] = party_totals.get(p, 0) + v
        if not contest:
            continue
        win = max(contest, key=contest.get)
        booth_wins[win] = booth_wins.get(win, 0) + 1
        tot = totals.get(bno) or sum(contest.values())
        srt = sorted(contest.values(), reverse=True)
        lead = (srt[0] - (srt[1] if len(srt) > 1 else 0))
        margins.append({"booth_no": bno, "winner": win, "lead_pct": round(lead / tot * 100, 1) if tot else 0})
    strongholds = sum(1 for m in margins if m["lead_pct"] >= 30)
    swing = sum(1 for m in margins if m["lead_pct"] <= 5)
    return {
        "total_booths": len(booths),
        "booth_wins": dict(sorted(booth_wins.items(), key=lambda x: -x[1])),
        "party_totals": dict(sorted(party_totals.items(), key=lambda x: -x[1])),
        "strongholds": strongholds,   # won by 30%+ margin
        "swing_booths": swing,        # decided by <=5%
    }


@router.get("/booths/{ac_no}")
async def ac_booths(ac_no: int):
    """Full booth-level breakdown for one AC (Form 20)."""
    db = get_db()
    con = (db.table("election_constituencies").select("*").eq("ac_no", ac_no).execute().data or [None])[0]
    rows = _booths_for_acs(db, [ac_no]).get(ac_no, [])
    if not rows:
        return {"ac_no": ac_no, "ac_name": con and con.get("ac_name"), "available": False}
    booths: dict[int, dict] = {}
    for r in rows:
        b = booths.setdefault(r["booth_no"], {"booth_no": r["booth_no"], "total": r.get("total_polled"), "parties": {}})
        b["parties"][r["party"]] = r["votes"]
    for b in booths.values():
        contest = {p: v for p, v in b["parties"].items() if p != "NOTA"}
        b["winner"] = max(contest, key=contest.get) if contest else None
    return {
        "ac_no": ac_no, "ac_name": con and con.get("ac_name"), "available": True,
        "summary": _booth_summary(rows),
        "booths": sorted(booths.values(), key=lambda x: x["booth_no"]),
        "source": "ECI Form 20 (via OpenCity); columns validated against official winner",
    }


def _candidate_stats(cands: list[dict]) -> dict:
    total = len(cands)
    women = sum(1 for c in cands if (c.get("gender") or "").lower().startswith("f"))
    crim = sum(1 for c in cands if c.get("criminal"))
    ages = [c["age"] for c in cands if c.get("age")]
    assets = [c["assets_cr"] for c in cands if c.get("assets_cr") is not None]
    winners = [c for c in cands if c.get("result") == "won"]
    crim_win = sum(1 for c in winners if c.get("criminal"))
    return {
        "candidates": total,
        "women": women,
        "criminal": crim,
        "criminal_pct": round(crim / total * 100, 1) if total else None,
        "avg_age": round(sum(ages) / len(ages), 1) if ages else None,
        "avg_assets_cr": round(sum(assets) / len(assets), 2) if assets else None,
        "winners_total": len(winners),
        "winners_with_criminal": crim_win,
        "women_winners": sum(1 for c in winners if (c.get("gender") or "").lower().startswith("f")),
    }


@router.get("/district/{district}")
async def district_detail(district: str):
    """Drill-down for one district: its constituencies + candidate insights.
    (Booth-level / Form 20 is a separate, pending layer — see booth_status.)"""
    db = get_db()
    cons = [c for c in _all_constituencies(db)
            if (c.get("district") or "").lower() == district.lower()]
    if not cons:
        return {"district": district, "found": False}
    ac_nos = [c["ac_no"] for c in cons]

    cands: list[dict] = []
    try:
        for i in range(0, len(ac_nos), 50):
            chunk = ac_nos[i:i + 50]
            cands.extend(db.table("election_candidates").select("*")
                         .in_("ac_no", chunk).execute().data or [])
    except Exception:
        cands = []  # table not migrated yet — degrade gracefully

    booths_by_ac = _booths_for_acs(db, ac_nos)

    for c in cons:
        el = c.get("electors") or 0
        c["flipped"] = bool(c.get("winner_2026") and c.get("winner_2021")
                            and c["winner_2026"] != c["winner_2021"])
        c["female_share"] = round((c.get("electors_female") or 0) / el * 100, 1) if el else None
        brows = booths_by_ac.get(c["ac_no"])
        c["booth_summary"] = _booth_summary(brows) if brows else None
        if cands:
            c["candidates_list"] = sorted(
                [{k: x.get(k) for k in ("name", "party", "alliance", "gender", "age",
                                        "assets_text", "assets_cr", "criminal", "result")}
                 for x in cands if x.get("ac_no") == c["ac_no"]],
                key=lambda x: (x.get("result") != "won", -(x.get("assets_cr") or 0)))

    acs_with_booths = sum(1 for c in cons if c.get("booth_summary"))
    total_booths = sum(c["booth_summary"]["total_booths"] for c in cons if c.get("booth_summary"))
    return {
        "district": cons[0]["district"],
        "found": True,
        "seats": len(cons),
        "flips": sum(1 for c in cons if c["flipped"]),
        "constituencies": sorted(cons, key=lambda c: c["ac_no"]),
        "candidate_stats": _candidate_stats(cands) if cands else None,
        "booth_status": {
            "available": acs_with_booths > 0,
            "acs_with_booths": acs_with_booths,
            "acs_total": len(cons),
            "total_booths": total_booths,
            "note": ("Booth-level data is sourced strictly from ECI Form 20 and validated "
                     "against the official AC winner. ACs without it are pending Form 20."
                     if acs_with_booths else
                     "Booth-level (Form 20) not yet ingested for this district."),
        },
    }


@router.get("/candidate-insights")
async def candidate_insights():
    """State-level candidate highlights (winners): criminal cases, richest, women."""
    db = get_db()
    try:
        winners = (db.table("election_candidates").select("*")
                   .eq("result", "won").execute().data or [])
    except Exception:
        return {"available": False, "note": "election_candidates not migrated yet"}
    if not winners:
        return {"available": False}
    crim = [w for w in winners if w.get("criminal")]
    richest = sorted([w for w in winners if w.get("assets_cr")],
                     key=lambda w: -(w["assets_cr"]))[:10]
    return {
        "available": True,
        "winners": len(winners),
        "with_criminal_cases": len(crim),
        "criminal_pct": round(len(crim) / len(winners) * 100, 1),
        "women_winners": sum(1 for w in winners if (w.get("gender") or "").lower().startswith("f")),
        "richest": [{"name": w["name"], "party": w.get("party"),
                     "assets_text": w.get("assets_text"), "ac_no": w.get("ac_no")} for w in richest],
    }


@router.get("/swing")
async def swing():
    """2021 -> 2026 alliance vote-share swing per AC (full-count). Shows where
    the Dravidian fronts lost their holds and where TVK's vote came from."""
    db = get_db()
    rows, off = [], 0
    while True:
        b = (db.table("election_ac_results").select("ac_no,year,party,votes,vote_share")
             .in_("year", [2021, 2026]).range(off, off + 999).execute().data or [])
        rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000
    by_ac: dict[int, dict] = {}
    sw21: dict[str, int] = {}
    for r in rows:
        by_ac.setdefault(r["ac_no"], {}).setdefault(str(r["year"]), {})[r["party"]] = r["vote_share"]
        if r["year"] == 2021:
            sw21[r["party"]] = sw21.get(r["party"], 0) + (r["votes"] or 0)

    cons = {c["ac_no"]: c for c in _all_constituencies(db)}
    tot21 = sum(sw21.values()) or 1
    statewide_2021 = {k: round(v / tot21 * 100, 1) for k, v in sw21.items()}
    # 2026 statewide = ECI-certified alliance shares (true full-state)
    statewide_2026 = {"TVK": 35.02, "DMK+": 31.40, "ADMK+": 27.21}
    swing = {b: round(statewide_2026.get(b, 0) - statewide_2021.get(b, 0), 1)
             for b in ("TVK", "DMK+", "ADMK+", "NTK")}

    out = []
    for ac, c in cons.items():
        d = by_ac.get(ac, {})
        v21, v26 = d.get("2021"), d.get("2026")
        per_swing = None
        if v21 and v26:
            per_swing = {b: round((v26.get(b, 0)) - (v21.get(b, 0)), 1)
                         for b in ("TVK", "DMK+", "ADMK+", "NTK", "OTHERS")}
        out.append({
            "ac_no": ac, "ac_name": c.get("ac_name"), "district": c.get("district"),
            "winner_2021": bucket(c.get("winner_2021")), "winner_2026": bucket(c.get("winner_2026")),
            "winner_2021_party": c.get("winner_2021"), "winner_2026_party": c.get("winner_2026"),
            "flipped": bool(c.get("winner_2021") and c.get("winner_2026")
                            and bucket(c["winner_2021"]) != bucket(c["winner_2026"])),
            "v2021": v21, "v2026": v26, "swing": per_swing,
        })
    out.sort(key=lambda x: (x["swing"]["DMK+"] if x.get("swing") else 999))
    return {
        "statewide": {"y2021": statewide_2021, "y2026": statewide_2026, "swing": swing},
        "constituencies": out,
        "with_voteshare": sum(1 for x in out if x.get("swing")),
        "note": ("2021 from TCPD (all 234 ACs, full count); 2026 vote-share from the "
                 "booth-level Form 20 loaded so far. Both Dravidian fronts lost ~13 points; "
                 "TVK rose by pulling from both. Full-count, not a survey."),
    }


@router.get("/districts")
async def district_rollup():
    """38-district rollup: seats by party 2026, electors, female share."""
    db = get_db()
    agg: dict[str, dict] = {}
    for c in _all_constituencies(db):
        d = c.get("district") or "Unknown"
        a = agg.setdefault(d, {"district": d, "seats": 0, "seats_2026": {},
                               "electors": 0, "electors_female": 0})
        a["seats"] += 1
        w = c.get("winner_2026")
        if w:
            b = bucket(w); a["seats_2026"][b] = a["seats_2026"].get(b, 0) + 1
        a["electors"] += c.get("electors") or 0
        a["electors_female"] += c.get("electors_female") or 0
    for a in agg.values():
        a["female_share"] = round(a["electors_female"] / a["electors"] * 100, 1) if a["electors"] else None
        a["lead_party"] = max(a["seats_2026"], key=a["seats_2026"].get) if a["seats_2026"] else None
    return sorted(agg.values(), key=lambda x: -x["seats"])
