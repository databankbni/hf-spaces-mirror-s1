"""How long this plate appearance runs, and how confident that is.

The rest of this app answers "how does the at-bat end". This answers "how many
pitches does it take" — one number, plus the spread around it, from wherever the
count currently stands.

**It is conditioned on the app's own answer, not a second opinion of it.** The
Log5 matchup model already says what this batter does against this pitcher: some
probability of a strikeout, a walk, a ball in play. Those numbers back the
matchup card, the projections and every prop on the board. So the chain below is
*solved* to reproduce them — two free parameters, one for the pitcher's control
and one for his stuff, fitted until the at-bat ends in a strikeout and a walk
exactly as often as Log5 says. The pitch count then falls out of a model that
already agrees with everything else on the page.

How the chain works. A plate appearance is a walk through the twelve live
counts, 0-0 to 3-2, one pitch at a time:

    in the zone?  ── yes ─→ swing? ── yes ─→ contact? ── yes ─→ foul or in play
                  │                 │                  └─ no ─→ swinging strike
                  │                 └─ no ──→ called strike
                  └─ no ──→ swing? ── yes ─→ contact? ── (chase contact)
                                    └─ no ──→ ball

Each branch depends on the count, because the count is what makes a plate
appearance interesting: a pitcher at 3-0 throws a strike and a hitter at 3-0
does not swing, and both are enormous effects. Those rates are league-average
behaviour by count, stable enough year to year to encode directly.

What is deliberately *not* here any more: this used to try to call each pitch —
strike, ball, foul — and name the pitch type. The calls were honest but thin
(no single call ever cleared 40%, and the pitch types were a league-average mix
rather than this pitcher's actual arsenal), and they buried the one number the
model is genuinely good at. Length is what a count model can tell you well, so
length is what it reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

# ── League behaviour by count ────────────────────────────────────────────────
# `zone` is how often the pitch is in the strike zone; `z_swing` and `o_swing`
# are how often the batter offers at one that is and one that isn't. The shape
# is the familiar one and the reason this model works at all: a pitcher ahead
# 0-2 expands the zone and the hitter chases, a pitcher behind 3-0 has to throw
# a strike and the hitter takes it.
#
# Calibrated against the league's actual per-pitch mix, not eyeballed: at a
# league-average matchup the chain produces ball 35.2%, called strike 16.7%,
# swinging strike 11.0%, foul 18.4%, in play 18.7%, against real MLB figures of
# roughly 36 / 17 / 11 / 18 / 17.5. `tests/test_pitch_sequence.py` pins that,
# because it is the check that this model describes baseball rather than merely
# hitting the two numbers it was fitted to.
_COUNTS: dict[tuple[int, int], dict[str, float]] = {
    (0, 0): {"zone": 0.49, "z_swing": 0.52, "o_swing": 0.22},
    (0, 1): {"zone": 0.44, "z_swing": 0.68, "o_swing": 0.30},
    (0, 2): {"zone": 0.33, "z_swing": 0.77, "o_swing": 0.42},
    (1, 0): {"zone": 0.51, "z_swing": 0.64, "o_swing": 0.24},
    (1, 1): {"zone": 0.48, "z_swing": 0.73, "o_swing": 0.31},
    (1, 2): {"zone": 0.36, "z_swing": 0.81, "o_swing": 0.43},
    (2, 0): {"zone": 0.58, "z_swing": 0.68, "o_swing": 0.20},
    (2, 1): {"zone": 0.54, "z_swing": 0.77, "o_swing": 0.28},
    (2, 2): {"zone": 0.42, "z_swing": 0.84, "o_swing": 0.40},
    (3, 0): {"zone": 0.68, "z_swing": 0.13, "o_swing": 0.04},
    (3, 1): {"zone": 0.61, "z_swing": 0.66, "o_swing": 0.18},
    (3, 2): {"zone": 0.53, "z_swing": 0.86, "o_swing": 0.35},
}

_ORDER = sorted(_COUNTS, key=lambda bs: (bs[0] + bs[1], bs[0], bs[1]))

# League contact rates, in and out of the zone. Chasing produces worse contact,
# which is most of why an 0-2 count is worth so much.
_Z_CONTACT = 0.85
_O_CONTACT = 0.62

# Share of contact that goes foul rather than into play. Higher out of the zone:
# a hitter reaching for a pitcher's pitch fouls it off far more often than he
# squares it up.
#
# Known residual, stated rather than tuned away: these leave the chain at about
# 3.7 pitches per plate appearance against a real league figure near 3.9. Balls
# in play come out roughly a point too common, and a ball in play ends the
# at-bat, so at-bats finish slightly early. Raising the foul share closes that
# gap and pulls three of the five pitch classes further from their real values,
# which is a worse model that happens to match one summary statistic — so the
# residual stays, and the headline number should be read as a shade low.
_Z_FOUL = 0.46
_O_FOUL = 0.60

# How far the two fitted parameters are allowed to move the league rates. A
# solver with no leash will happily explain a 40% strikeout hitter by inventing
# a pitcher who misses every bat, which fits the target and describes nobody.
_MIN_KNOB, _MAX_KNOB = 0.25, 4.0

_EPS = 1e-12

# A plate appearance has no hard length limit — 3-2 fouls can go on forever —
# so the propagation is cut here. At sixteen pitches there is less than a
# thousandth of the mass left, and whatever remains is folded into the last
# bucket rather than silently dropped.
_MAX_DEPTH = 16

OUTCOMES = ("ball", "called_strike", "swinging_strike", "foul", "in_play")


def _odds_shift(p: float, knob: float) -> float:
    """Move a probability by an odds multiplier, staying inside (0, 1).

    Scaling a probability directly is how a fitted parameter ends up asking for
    a 130% chance of a strike. Working in odds — p/(1-p) × knob — cannot leave
    the interval however hard the solver pushes.
    """
    p = min(max(p, _EPS), 1.0 - _EPS)
    o = (p / (1.0 - p)) * knob
    return o / (1.0 + o)


def _pitch_outcomes(balls: int, strikes: int, control: float,
                    stuff: float, patience: float = 1.0) -> dict[str, float]:
    """P(each outcome class) for one pitch thrown in this count.

    `control` shifts how often the pitch is a strike, `stuff` shifts how often
    the batter misses it, `patience` shifts how often he offers at a ball. All
    three move league behaviour rather than replacing it, so a fitted pitcher
    is still recognisably doing what pitchers do.
    """
    c = _COUNTS[(balls, strikes)]
    zone = _odds_shift(c["zone"], control)
    z_swing = c["z_swing"]
    if strikes == 2:
        # Two-strike protection, tied to contact ability. A hitter who makes
        # more contact than average also takes strike three less often — the
        # two travel together, and it is bat control that produces both.
        #
        # Without it the model cannot reach a strikeout rate below about 16%:
        # called strikes keep accumulating however good the contact is, so
        # every genuine contact hitter came out capped and four points high.
        z_swing = _odds_shift(z_swing, (1.0 / stuff) ** 0.5)
    o_swing = _odds_shift(c["o_swing"], 1.0 / patience)
    z_contact = _odds_shift(_Z_CONTACT, 1.0 / stuff)
    o_contact = _odds_shift(_O_CONTACT, 1.0 / stuff)

    out = dict.fromkeys(OUTCOMES, 0.0)

    p = zone
    out["called_strike"] += p * (1.0 - z_swing)
    swung = p * z_swing
    out["swinging_strike"] += swung * (1.0 - z_contact)
    contact = swung * z_contact
    out["foul"] += contact * _Z_FOUL
    out["in_play"] += contact * (1.0 - _Z_FOUL)

    p = 1.0 - zone
    out["ball"] += p * (1.0 - o_swing)
    swung = p * o_swing
    out["swinging_strike"] += swung * (1.0 - o_contact)
    contact = swung * o_contact
    out["foul"] += contact * _O_FOUL
    out["in_play"] += contact * (1.0 - _O_FOUL)

    return out


def _advance(balls: int, strikes: int, outcome: str):
    """Where an outcome leaves the count, or which terminal it reaches."""
    if outcome == "in_play":
        return "in_play"
    if outcome == "ball":
        return "walk" if balls == 3 else (balls + 1, strikes)
    if outcome == "foul":
        # The rule that makes a plate appearance able to run long: with two
        # strikes a foul is not a strike, so the count simply does not move.
        return (balls, strikes) if strikes == 2 else (balls, strikes + 1)
    return "strikeout" if strikes == 2 else (balls, strikes + 1)


def _terminals(control: float, stuff: float, patience: float = 1.0,
               start: tuple[int, int] = (0, 0)) -> tuple[float, float, float]:
    """(strikeout, walk, in_play) only — no length bookkeeping.

    The solver runs this a few hundred times and needs nothing but the three
    absorption probabilities. The full version below also tracks which pitch
    the at-bat ends on, which costs far more and made a single forecast take
    three seconds — long enough that a panel refreshing every few seconds would
    spend its life waiting on it.

    `start` is where the at-bat already is. The fit always runs from 0-0 —
    that's what defines these two players — but a plate appearance in progress
    is asked about from the count it is actually in.
    """
    arrive = dict.fromkeys(_COUNTS, 0.0)
    arrive[start] = 1.0
    k = bb = ip = 0.0
    for bs in _ORDER:
        w = arrive[bs]
        if w <= _EPS:
            continue
        balls, strikes = bs
        probs = _pitch_outcomes(balls, strikes, control, stuff, patience)
        stay = min(probs["foul"], 1.0 - 1e-9) if strikes == 2 else 0.0
        scale = w / (1.0 - stay)
        for outcome, p in probs.items():
            if strikes == 2 and outcome == "foul":
                continue
            nxt = _advance(balls, strikes, outcome)
            moved = scale * p
            if nxt == "strikeout":
                k += moved
            elif nxt == "walk":
                bb += moved
            elif nxt == "in_play":
                ip += moved
            else:
                arrive[nxt] += moved
    return k, bb, ip


def _run_chain(control: float, stuff: float, patience: float = 1.0,
               start: tuple[int, int] = (0, 0)) -> dict:
    """Propagate the at-bat, tracking which pitch it ends on.

    Exact rather than simulated. The counts form a directed acyclic graph with
    one exception — a foul with two strikes returns to the same count — and
    that loop is summed geometrically rather than cut off after some arbitrary
    number of pitches, so a nine-pitch at-bat is represented at its true weight
    instead of being truncated into nonexistence.

    `ends_at[n]` is the probability the plate appearance finishes on its nth
    pitch, counting from `start`. That distribution is the whole product: the
    headline number is its mean, and the spread around it is what makes the
    headline worth anything.
    """
    arrive: dict[tuple[int, int], float] = {bs: 0.0 for bs in _COUNTS}
    arrive[start] = 1.0
    # {count: {which pitch of the at-bat the next one would be: mass}}. Depth 1
    # is the *next* pitch, not the first of the plate appearance — when the
    # at-bat is already 1-2, "pitch 1" is the one about to be thrown.
    depth_of: dict[tuple[int, int], dict[int, float]] = {bs: {} for bs in _COUNTS}
    depth_of[start][1] = 1.0

    terminals = {"strikeout": 0.0, "walk": 0.0, "in_play": 0.0}
    ends_at: dict[int, float] = {}
    expected_pitches = 0.0

    for bs in _ORDER:
        w = arrive[bs]
        if w <= _EPS:
            continue
        balls, strikes = bs
        probs = _pitch_outcomes(balls, strikes, control, stuff, patience)

        stay = min(probs["foul"], 1.0 - 1e-9) if strikes == 2 else 0.0
        visits = 1.0 / (1.0 - stay)
        expected_pitches += w * visits

        # Chance a pitch thrown from this count ends the plate appearance.
        end_p = 0.0
        for outcome, p in probs.items():
            if strikes == 2 and outcome == "foul":
                continue
            if isinstance(_advance(balls, strikes, outcome), str):
                end_p += p

        # Spread the endings across depths. Each two-strike foul pushes the
        # same mass one pitch deeper, which is exactly how a long at-bat is
        # built and the only reason the tail of this distribution exists.
        for d, dw in list(depth_of[bs].items()):
            remaining, extra = dw, 0
            while remaining > _EPS and d + extra <= _MAX_DEPTH:
                ends_at[d + extra] = ends_at.get(d + extra, 0.0) + remaining * end_p
                remaining *= stay
                extra += 1

        scale = w * visits
        for outcome, p in probs.items():
            if strikes == 2 and outcome == "foul":
                continue
            nxt = _advance(balls, strikes, outcome)
            moved = scale * p
            if isinstance(nxt, str):
                terminals[nxt] += moved
                continue
            arrive[nxt] += moved
            for d, dw in list(depth_of[bs].items()):
                remaining, extra = dw, 0
                while remaining > _EPS and d + extra + 1 <= _MAX_DEPTH:
                    tgt = depth_of[nxt]
                    tgt[d + extra + 1] = tgt.get(d + extra + 1, 0.0) + remaining * p
                    remaining *= stay
                    extra += 1

    return {"terminals": terminals, "expected_pitches": expected_pitches,
            "ends_at": ends_at}


@lru_cache(maxsize=4096)
def _solve(target_k: float, target_bb: float,
           iterations: int = 26) -> tuple[float, float, bool, float]:
    """Fit control and stuff so the chain ends where Log5 says it should.

    Nested bisection rather than a gradient step, because both relationships
    are monotone and bisection cannot diverge: more control always means fewer
    walks, more stuff always means more strikeouts. The outer loop finds the
    control that produces the right walk rate; the inner one, for each control
    it tries, finds the stuff that produces the right strikeout rate.

    Cached, and that matters more than it looks. The fit depends only on the
    two players, not on the count, so every refresh during the same at-bat —
    and every viewer watching the same game — reuses one solve. Without it a
    panel refreshing every few seconds would re-run the same bisection forever.

    Measured over 2000 real batter-pitcher pairs from the stored 2026 season:
    **95.5% fit exactly** (error below 1e-6), 2.4% hit the leash and are
    flagged, and the remainder miss by a fraction of a point. The worst case is
    the one you would predict — Arráez, whose Log5 strikeout rate against a
    soft-contact arm comes out near 2%, which no amount of bat control reaches
    once called strikes are in the model.

    Returns (control, stuff, capped, error). `capped` is true when the leash
    bound it before the target was met — a real matchup that league-average
    pitch behaviour cannot reproduce, which is worth admitting rather than
    presenting a fit that missed.
    """
    def stuff_for(control: float) -> float:
        lo, hi = _MIN_KNOB, _MAX_KNOB
        for _ in range(iterations):
            mid = (lo + hi) / 2.0
            if _terminals(control, mid)[0] < target_k:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    lo, hi = _MIN_KNOB, _MAX_KNOB
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if _terminals(mid, stuff_for(mid))[1] > target_bb:
            lo = mid          # too many walks → needs more control
        else:
            hi = mid
    control = (lo + hi) / 2.0
    stuff = stuff_for(control)

    got_k, got_bb, _ = _terminals(control, stuff)
    error = abs(got_k - target_k) + abs(got_bb - target_bb)
    capped = (
        not (_MIN_KNOB * 1.01 < control < _MAX_KNOB * 0.99)
        or not (_MIN_KNOB * 1.01 < stuff < _MAX_KNOB * 0.99)
    )
    return control, stuff, bool(capped and error > 0.01), error


def _fmt(bs: tuple[int, int]) -> str:
    return f"{bs[0]}-{bs[1]}"


@dataclass
class AtBatForecast:
    """How long this plate appearance runs, and what it ends in."""
    batter: str
    pitcher: str
    batter_hand: str
    pitcher_hand: str

    # ── The headline ─────────────────────────────────────────────────────────
    # The mean, and the whole number a reader actually carries away.
    expected_pitches: float
    likely_pitches: int
    # The scale around it. Three numbers that sum to 100: more than the
    # headline, exactly it, fewer than it. A single expectation with no spread
    # is the kind of number that looks authoritative and says nothing — an
    # at-bat that averages four pitches is very rarely four pitches.
    more_pct: float
    same_pct: float
    fewer_pct: float
    # P(the at-bat ends on exactly n more pitches), n = 1 upward.
    distribution: list[dict] = field(default_factory=list)

    # ── Context ──────────────────────────────────────────────────────────────
    # Fitted to Log5, so these are the numbers the matchup card already shows.
    strikeout_pct: float = 0.0
    walk_pct: float = 0.0
    in_play_pct: float = 0.0
    hit_by_pitch_pct: float = 0.0
    # The count the forecast starts from — "0-0" for an at-bat that hasn't
    # begun, otherwise wherever the live one actually is.
    start_count: str = "0-0"
    # What the same matchup looked like at 0-0, when the at-bat is already
    # under way. The contrast is the point of a live panel: a hitter down 1-2
    # is a different proposition from the one who stepped in.
    started_expected_pitches: Optional[float] = None
    started_strikeout_pct: Optional[float] = None
    started_walk_pct: Optional[float] = None
    started_in_play_pct: Optional[float] = None
    # True when the solver hit its leash instead of matching the target.
    fit_capped: bool = False
    fit_error: float = 0.0
    notes: list[str] = field(default_factory=list)


def forecast(
    *,
    batter: str,
    pitcher: str,
    strikeout_p: float,
    walk_p: float,
    hbp_p: float = 0.0,
    batter_hand: str = "R",
    pitcher_hand: str = "R",
    # Where the at-bat already is. (0, 0) forecasts a plate appearance that
    # hasn't started; anything else forecasts the rest of one in progress.
    start_count: tuple[int, int] = (0, 0),
    # How far the shown distribution runs. Past ten the buckets are worth
    # fractions of a percent each and the tail is folded into the last one.
    max_shown: int = 10,
) -> AtBatForecast:
    """Forecast the length of a plate appearance from wherever it stands.

    `strikeout_p` / `walk_p` / `hbp_p` come from the Log5 matchup distribution —
    the same numbers behind the matchup card. They are targets, and the fit is
    always run **from 0-0**, because they describe a whole plate appearance
    between these two players; that fit is what "this batter against this
    pitcher" means and it does not depend on where tonight's at-bat happens to
    be.

    The chain is then *evaluated* from `start_count`. Those two being different
    operations is the point: a hitter at 1-2 has fewer pitches left than the
    one who stepped in, and reporting the full-at-bat figure while he stands
    there down 1-2 describes a plate appearance that is no longer happening.

    A hit-by-pitch is reported but not modelled as part of the sequence. It
    isn't a count event and it's about one plate appearance in a hundred;
    folding it into walks would misstate both, so the three modelled outcomes
    are renormalized over the non-HBP mass and HBP is carried alongside.
    """
    if start_count not in _COUNTS:
        start_count = (0, 0)

    live = max(1.0 - hbp_p, _EPS)
    target_k = min(max(strikeout_p / live, 0.005), 0.95)
    target_bb = min(max(walk_p / live, 0.002), 0.95)

    # Rounded before the cache sees them: two matchups agreeing to four decimal
    # places produce the same fit, and there is no sense solving twice.
    control, stuff, capped, error = _solve(round(target_k, 4), round(target_bb, 4))
    chain = _run_chain(control, stuff, start=start_count)
    term = chain["terminals"]

    notes: list[str] = []
    if capped:
        notes.append(
            "This matchup is more extreme than league-average pitch behaviour "
            "can reproduce, so the spread below is the closest fit rather than "
            "an exact one.")

    # ── The length distribution ──────────────────────────────────────────────
    ends = chain["ends_at"]
    total = sum(ends.values()) or 1.0
    expected = chain["expected_pitches"]
    likely = max(1, int(round(expected)))

    dist: list[dict] = []
    tail = 0.0
    for n in sorted(ends):
        pct = 100.0 * ends[n] / total
        if n <= max_shown:
            dist.append({"n": n, "pct": round(pct, 1)})
        else:
            tail += pct
    if tail > 0.05 and dist:
        # Folded into the last bucket rather than dropped, so the bars still
        # sum to a hundred and a long at-bat isn't quietly deleted.
        dist[-1] = {"n": dist[-1]["n"], "pct": round(dist[-1]["pct"] + tail, 1),
                    "plus": True}

    more = 100.0 * sum(p for n, p in ends.items() if n > likely) / total
    same = 100.0 * sum(p for n, p in ends.items() if n == likely) / total
    fewer = 100.0 * sum(p for n, p in ends.items() if n < likely) / total

    # What this matchup looked like before the count did anything to it. Only
    # carried when the at-bat is under way, since otherwise it is the same
    # number twice.
    began_pitches = began_k = began_bb = began_ip = None
    if start_count != (0, 0):
        fresh = _run_chain(control, stuff)
        began_pitches = round(fresh["expected_pitches"], 2)
        k0, bb0, ip0 = fresh["terminals"].values()
        began_k = round(100.0 * fresh["terminals"]["strikeout"] * live, 1)
        began_bb = round(100.0 * fresh["terminals"]["walk"] * live, 1)
        began_ip = round(100.0 * fresh["terminals"]["in_play"] * live, 1)

    return AtBatForecast(
        batter=batter, pitcher=pitcher,
        batter_hand=batter_hand, pitcher_hand=pitcher_hand,
        expected_pitches=round(expected, 2),
        likely_pitches=likely,
        more_pct=round(more, 1), same_pct=round(same, 1),
        fewer_pct=round(fewer, 1),
        distribution=dist,
        strikeout_pct=round(100.0 * term["strikeout"] * live, 1),
        walk_pct=round(100.0 * term["walk"] * live, 1),
        in_play_pct=round(100.0 * term["in_play"] * live, 1),
        hit_by_pitch_pct=round(100.0 * hbp_p, 1),
        start_count=_fmt(start_count),
        started_expected_pitches=began_pitches,
        started_strikeout_pct=began_k,
        started_walk_pct=began_bb,
        started_in_play_pct=began_ip,
        fit_capped=capped,
        fit_error=round(error, 4),
        notes=notes,
    )


def forecast_from_distribution(dist, *, batter: str, pitcher: str,
                               batter_hand: str = "R", pitcher_hand: str = "R",
                               start_count: tuple[int, int] = (0, 0)
                               ) -> AtBatForecast:
    """Forecast straight off a `PAOutcomeDistribution`.

    The intended entry point: hand it the Log5 output for this batter against
    this pitcher and the length model is fitted to it, which is the whole
    reason the two can never disagree on screen.
    """
    return forecast(
        batter=batter, pitcher=pitcher,
        strikeout_p=float(dist.strikeout),
        walk_p=float(dist.walk),
        hbp_p=float(dist.hit_by_pitch),
        batter_hand=batter_hand, pitcher_hand=pitcher_hand,
        start_count=start_count,
    )
