"""Who is coming up, and what their at-bat is likely to look like.

This is the join between three things that already exist separately: the live
feed's view of the game, the repository's per-player profiles, and the Log5
matchup model. None of them knows about the others, and the pitch forecast
needs all three.

The batter it forecasts is **the one in the box**, from **the count he is in**.
Those two go together and neither works alone: the hitter at the plate is the
one anybody watching cares about, and a forecast of him is only true if the
count travels with it. Reporting his whole-plate-appearance strikeout rate
while he stands there down 1-2 would describe a plate appearance that stopped
existing three pitches ago.

Between innings the feed names no batter. Then the on-deck hitter is the next
thing that will happen, forecast from 0-0 — which for him is correct — and the
payload says which of the two it is showing.

Everything here is best-effort. A live feed that can't be reached, a pitcher
who isn't in our database, a game that hasn't started — each returns a stated
reason rather than an empty panel, because "no forecast" and "no game" and
"we don't have this reliever" look identical from the outside and mean
completely different things.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as date_type
from typing import Any, Optional

from .data.names import normalize_name
from .pitch_sequence import AtBatForecast, forecast_from_distribution

# Seasons to look back through for a profile when the current one has nothing.
# A September call-up has no season-long line yet and a reliever traded in July
# may only have last year's; refusing to forecast either would empty the panel
# for exactly the players a viewer is least sure about.
_FALLBACK_SEASONS = 3

# ── Team pitch countdown ─────────────────────────────────────────────────────
# Real league rates, and they have to be league rates rather than this model's
# own: the count chain runs about 5% short on pitches per plate appearance (see
# the note on the foul constants in pitch_sequence), and multiplying a known
# bias by twenty-seven outs turns a rounding error into eight missing pitches.
#
# The three tie together, which is the check that they're right:
#   37.9 PA × 3.85 pitches  = 146 pitches per team per nine innings
#   146 pitches ÷ 27 outs   = 5.41 pitches per out
#   27 outs ÷ 37.9 PA       = 0.71 outs per plate appearance
LEAGUE_PITCHES_PER_OUT = 5.41
LEAGUE_OUTS_PER_PA = 0.71
REGULATION_INNINGS = 9
OUTS_PER_GAME = REGULATION_INNINGS * 3


# How much of a staff's own pace to trust before the league rate. Three
# innings' worth of pseudo-observations: at nine outs recorded the estimate is
# half this game and half the league, which is about where one bad inning stops
# being the whole sample. Without it, a staff that threw 30 in the first would
# be projected for 270.
_PACE_PRIOR_OUTS = 9.0


def _half_state(inning: Optional[int], is_top: Optional[bool],
                inning_state: Optional[str],
                outs: Optional[int]) -> tuple[int, str, int]:
    """(inning, normalised half-state, outs) — the one place this is parsed.

    Shared so the outs still to come and the outs already recorded can never
    disagree about where the game is.
    """
    n = int(inning or 1)
    o = min(max(int(outs or 0), 0), 3)
    state = (inning_state or "").strip().lower()
    if state not in ("top", "middle", "bottom", "end"):
        state = "top" if (is_top if is_top is not None else True) else "bottom"
    return n, state, o


def _outs_recorded(inning: Optional[int], is_top: Optional[bool],
                   inning_state: Optional[str],
                   outs: Optional[int]) -> tuple[int, int]:
    """(outs the home staff has recorded, outs the away staff has recorded).

    The denominator for a staff's own pitches-per-out tonight. Home pitchers
    record theirs in the tops and away pitchers in the bottoms, so the same
    half-inning asymmetry applies here as to the outs still to come.
    """
    n, state, o = _half_state(inning, is_top, inning_state, outs)
    if state == "top":
        return 3 * (n - 1) + o, 3 * (n - 1)
    if state == "middle":
        return 3 * n, 3 * (n - 1)
    if state == "bottom":
        return 3 * n, 3 * (n - 1) + o
    return 3 * n, 3 * n              # "end" — the whole inning is done


def _pitches_per_out(thrown: Optional[int], outs_recorded: int) -> float:
    """This staff's own rate tonight, shrunk towards the league's.

    A pure league rate ignores that some nights run long — which is the whole
    complaint about an estimate driven only by outs. A pure observed rate
    believes three outs, and three outs is one inning. Shrinking towards the
    league with three innings of prior weight uses tonight where tonight has
    something to say and falls back where it doesn't.
    """
    if thrown is None or outs_recorded <= 0:
        return LEAGUE_PITCHES_PER_OUT
    return ((thrown + _PACE_PRIOR_OUTS * LEAGUE_PITCHES_PER_OUT)
            / (outs_recorded + _PACE_PRIOR_OUTS))


def _outs_left(inning: Optional[int], is_top: Optional[bool],
               inning_state: Optional[str],
               outs: Optional[int]) -> tuple[int, int, bool]:
    """(outs left for the home staff, for the away staff, in_extras).

    Home pitchers work the top halves and away pitchers the bottoms, so the two
    staffs are at different points in the game at every moment — the away staff
    always has one half-inning more ahead of it during a top, and one fewer
    during a bottom.

    `inning_state` is MLB's own label and carries a distinction `is_top` cannot:
    "Middle" means the top is over and the bottom has not begun, "End" means the
    inning is finished. Reading only `is_top` there would leave a half-inning
    either double-counted or missed.
    """
    n, state, o = _half_state(inning, is_top, inning_state, outs)

    if n > REGULATION_INNINGS:
        # Extra innings have no fixed length. Counting the half being played
        # and the one that must follow it is the most that can be said; the
        # payload flags it rather than pretending to a full-game number.
        if state == "top":
            return 3 - o, 3, True
        if state == "middle":
            return 0, 3, True
        if state == "bottom":
            return 0, 3 - o, True
        return 3, 3, True

    full_tops_after = max(0, REGULATION_INNINGS - n)
    if state == "top":
        home = (3 - o) + 3 * full_tops_after
        # The bottom of this inning hasn't started, so the away staff still has
        # it in front of them along with every one after.
        away = 3 * (full_tops_after + 1)
    elif state == "middle":
        home = 3 * full_tops_after
        away = 3 * (full_tops_after + 1)
    elif state == "bottom":
        home = 3 * full_tops_after
        away = (3 - o) + 3 * full_tops_after
    else:                                    # "end" — the inning is over
        home = 3 * full_tops_after
        away = 3 * full_tops_after
    return home, away, False


def _team_pitches(outs_remaining: int, at_bat_remaining: Optional[float],
                  rate: float = LEAGUE_PITCHES_PER_OUT) -> tuple[int, int]:
    """(expected pitches remaining, the league's whole-game reference).

    `rate` is this staff's own pitches per out where the game has shown one,
    which is what stops the estimate being nothing but a count of outs. A
    bullpen running long projects long.

    `at_bat_remaining` is the exact figure from the count model for the staff
    currently on the mound, and it is what makes the counter move between outs.
    Without it the number would only step when an out was recorded — correct,
    but visibly frozen through most of an at-bat.

    The plate appearance under way is expected to produce `LEAGUE_OUTS_PER_PA`
    of an out, so that much is taken off the outs the rate is applied to.
    Double-counting it would add five pitches to every reading.
    """
    outs = max(0, int(outs_remaining))
    if at_bat_remaining is None:
        remaining = outs * rate
    else:
        rest = max(0.0, outs - LEAGUE_OUTS_PER_PA)
        remaining = at_bat_remaining + rest * rate
    return round(remaining), round(OUTS_PER_GAME * LEAGUE_PITCHES_PER_OUT)


@dataclass
class TeamPitches:
    """One pitching staff's countdown to the end of the game."""
    team: str
    side: str                    # "home" | "away"
    # True for the staff currently on the mound — the one the at-bat above is
    # being thrown by, and the one whose number is ticking right now.
    is_pitching: bool
    outs_remaining: int
    expected_remaining: int
    # A nine-inning staff's whole-game figure, so the countdown has a scale to
    # be read against rather than being a bare number.
    expected_total: int
    pct_remaining: float
    # What they have actually thrown, from the box score. None when it couldn't
    # be read — the countdown is an estimate off the innings and does not
    # depend on this, so a missing box score costs the over-run and nothing
    # else.
    thrown: Optional[int] = None
    # Outs this staff has already recorded — the denominator behind `pace`.
    outs_recorded: int = 0
    # Their own pitches per out tonight, shrunk towards the league's. The
    # league figure is 5.41; a staff reading 6.8 is having a long night and the
    # projection follows it rather than insisting on the average.
    pace: float = LEAGUE_PITCHES_PER_OUT
    # Thrown plus expected remaining: where this staff's night actually lands,
    # as opposed to where a league-average one would.
    projected_total: Optional[int] = None
    # How far past the whole-game estimate they already are. The estimate is a
    # league rate, and a staff that walks the park blows through it well before
    # the ninth — at which point counting down towards zero is describing a
    # game that isn't happening. This counts up instead.
    over_estimate: int = 0
    # No outs left to record. Distinct from an over-run and from a countdown
    # that merely reached zero: a home staff is legitimately finished the
    # moment the top of the ninth ends, and "0" there means done, not late.
    complete: bool = False


@dataclass
class NextAtBat:
    """The forecast, plus enough context for a page to caption it honestly."""
    game_id: str
    available: bool
    # "at_plate" — the hitter in the box, forecast from the count he is in.
    # "on_deck" — between innings, where nobody is batting yet, so the next
    #   hitter up is forecast from 0-0.
    subject: str = ""
    batter: str = ""
    pitcher: str = ""
    batter_team: Optional[str] = None
    inning: Optional[int] = None
    is_top_inning: Optional[bool] = None
    outs: Optional[int] = None
    # The count the forecast starts from — the live one when somebody is
    # batting, 0-0 between innings.
    balls: int = 0
    strikes: int = 0
    # Who follows, for context under the forecast.
    on_deck: Optional[str] = None
    in_hole: Optional[str] = None
    # Kept for callers that read it; the subject *is* the current batter now.
    current_batter: Optional[str] = None
    # "season" when the forecast is built on that player's own line, "league"
    # when we hold none and a baseline is standing in. Carried separately from
    # the notes so a page can mark the number itself rather than relying on
    # somebody reading the small print under it.
    batter_profile: str = "season"
    pitcher_profile: str = "season"
    forecast: Optional[dict] = None
    # Both pitching staffs' countdowns to the last out. Populated whenever the
    # game is under way, including when no forecast could be built — the count
    # needs a batter and a pitcher we hold profiles for, but the countdown only
    # needs the inning, and there is no reason to lose it because a reliever
    # isn't in our database.
    team_pitches: list[dict] = field(default_factory=list)
    # True past the ninth, where the remaining length is genuinely unknowable
    # and the countdown covers only the halves that must still be played.
    extra_innings: bool = False
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _name_index(repo, season: int) -> dict[str, Any]:
    """{normalized name: statline} across batters and pitchers.

    The live feed names people; the repository keys them by id. Nothing in
    between exists, so the index is built here. Later seasons win, so a player
    with both a current line and an old one is described by the current one.
    """
    index: dict[str, Any] = {}
    for s in range(season - _FALLBACK_SEASONS + 1, season + 1):
        for row in list(repo.get_batters_for_season(s)) + \
                list(repo.get_pitchers_for_season(s)):
            if getattr(row, "name", ""):
                index[normalize_name(row.name)] = row
    return index


def _league_batter(name: str, season: int):
    """A league-average batting line, for a hitter we hold no season line for.

    About a fifth of lineup slots on a given night belong to somebody without
    one — call-ups, bench bats, anyone under the ingest's plate-appearance
    floor — and every one of them used to produce an empty panel. A league
    baseline is not this player, and the payload says so; it is a far better
    answer than nothing, because the thing being forecast here is how long an
    at-bat runs, which depends much less on who the hitter is than a projection
    of his hits would.

    Deliberately the league's own rates rather than something worse: a call-up
    probably is below average, but inventing a rookie penalty is a claim about
    him that nobody here can support, while the league line is an admitted
    stand-in.
    """
    from .matchup.log5 import league_averages_default
    from .data.models import BatterStatline

    lg = league_averages_default(season)
    return BatterStatline(
        player_id=0, name=name, season=season, team_id="",
        hand="R", pa=0,
        single_rate=lg.single_rate, double_rate=lg.double_rate,
        triple_rate=lg.triple_rate, hr_rate=lg.hr_rate,
        bb_rate=lg.bb_rate, hbp_rate=lg.hbp_rate,
        k_rate=lg.k_rate, ipo_rate=lg.ipo_rate,
        woba=0.320, xwoba=0.320, iso=0.160, babip=0.300,
        platoon_split={"vL": 1.0, "vR": 1.0},
    )


def _league_pitcher(name: str, season: int):
    """A league-average pitching line, for an arm we hold no season line for.

    The same gap on the other side, and it bites hardest exactly when somebody
    wants the panel: a reliever who came up this week is the least familiar
    person in the game.
    """
    from .matchup.log5 import league_averages_default
    from .data.models import PitcherStatline

    lg = league_averages_default(season)
    return PitcherStatline(
        player_id=0, name=name, season=season, team_id="",
        hand="R", role="reliever", bf=0,
        single_allowed=lg.single_rate, double_allowed=lg.double_rate,
        triple_allowed=lg.triple_rate, hr_allowed=lg.hr_rate,
        bb_allowed=lg.bb_rate, hbp_allowed=lg.hbp_rate,
        k_rate=lg.k_rate, ipo_rate=lg.ipo_rate, xfip=4.00,
        platoon_split={"vL": 1.0, "vR": 1.0},
    )


def _lookup(index: dict, name: Optional[str], want: str):
    """The batter or pitcher profile behind a live-feed name, or None.

    `want` guards against the obvious failure of a two-way player and the less
    obvious one of a name collision between a hitter and a pitcher: asking for
    a pitcher and being handed a batting line would produce a forecast built
    from the wrong half of somebody's season.
    """
    if not name:
        return None
    row = index.get(normalize_name(name))
    if row is None:
        return None
    is_pitcher = hasattr(row, "bf")
    if want == "pitcher" and not is_pitcher:
        return None
    if want == "batter" and is_pitcher:
        return None
    return row


def _thrown_by_side(boxscore) -> dict[str, Optional[int]]:
    """{"home"/"away": pitches thrown by that club's staff}, from the box score.

    A team's own `pitchers` list is its staff, and its staff works the other
    club's half-innings — so no crossing over is needed here, only summing.

    Missing pitch counts come back as None rather than as zero. A reliever MLB
    hasn't posted a count for yet would otherwise drag the total down and make
    a staff look fresher than it is, which is the one direction this number
    must not err in.
    """
    out: dict[str, Optional[int]] = {"home": None, "away": None}
    if boxscore is None:
        return out
    for side in ("home", "away"):
        team = getattr(boxscore, side, None)
        rows = getattr(team, "pitchers", None) if team else None
        if not rows:
            continue
        counts = [p.pitches for p in rows if getattr(p, "pitches", None) is not None]
        if counts:
            out[side] = sum(counts)
    return out


#: Distinguishes "fetch the box score yourself" from "there isn't one".
#: Without it, passing None to mean the latter still triggered the fetch —
#: which had unit tests making real network calls to MLB.
_FETCH = object()


def build(repo, game_id: str, season: int, linescore=None,
          park_season: Optional[int] = None, boxscore=_FETCH) -> NextAtBat:
    """Forecast the next plate appearance of a game in progress.

    The Log5 distribution is built exactly as the matchup card builds it —
    same DNA adapters, same league baseline, same park and weather context —
    so the strikeout and walk percentages the pitch panel reports are the
    numbers the rest of the page already shows, not a second opinion of them.
    """
    from .data.sources.linescore import MLBLinescoreSource
    from .gameid import parse as parse_game_id
    from .matchup.adapters import batter_dna_from_statline, pitcher_dna_from_statline
    from .matchup.log5 import league_averages_default, pa_distribution

    out = NextAtBat(game_id=game_id, available=False)

    game_date = parse_game_id(game_id)[0]
    if game_date is None:
        out.reason = "That game id doesn't parse into a date."
        return out

    game = next((g for g in repo.get_schedule(game_date)
                 if g.game_id == game_id), None)
    if game is None:
        out.reason = "That game isn't on the schedule we hold."
        return out

    if linescore is None:
        if not getattr(game, "game_pk", None):
            out.reason = "No live feed id for this game yet."
            return out
        try:
            linescore = MLBLinescoreSource().fetch_linescore(game.game_pk, game_id)
        except Exception as exc:
            out.reason = f"Couldn't reach the live feed — {type(exc).__name__}."
            return out
    if linescore is None:
        out.reason = "The live feed had nothing for this game."
        return out

    sit = linescore.situation
    out.inning = linescore.current_inning
    out.is_top_inning = linescore.is_top_inning
    out.outs = sit.outs
    out.current_batter = sit.batter
    out.in_hole = sit.in_hole
    out.on_deck = sit.on_deck

    # The countdown, computed before anything that can fail. It needs only the
    # inning, so it survives a batter or a reliever we hold no profile for —
    # losing the whole panel because of one unknown name would be a poor trade.
    home_outs, away_outs, extras = _outs_left(
        linescore.current_inning, linescore.is_top_inning,
        linescore.inning_state, sit.outs)
    out.extra_innings = extras
    # During a top half the home staff is on the mound; during a bottom, the
    # away staff. That is the whole of the home-field asymmetry here.
    in_top = (linescore.inning_state or "").strip().lower() == "top" or (
        linescore.inning_state in (None, "")
        and bool(linescore.is_top_inning))

    # Actual pitch counts, for the over-run. Best-effort and entirely optional:
    # the countdown is estimated off the innings, so a box score that can't be
    # read costs the over-run and nothing else.
    if boxscore is _FETCH:
        boxscore = None
        if getattr(game, "game_pk", None):
            try:
                from .data.sources.boxscore import MLBBoxscoreSource

                boxscore = MLBBoxscoreSource().fetch_boxscore(
                    game.game_pk, game_id)
            except Exception:
                boxscore = None
    thrown_by_side = _thrown_by_side(boxscore)

    home_done, away_done = _outs_recorded(
        linescore.current_inning, linescore.is_top_inning,
        linescore.inning_state, sit.outs)

    def _fill_countdown(at_bat_remaining: Optional[float]) -> None:
        rows = []
        for side, team, outs_left, done in (
                ("home", game.home_team_id, home_outs, home_done),
                ("away", game.away_team_id, away_outs, away_done)):
            pitching = (side == "home") == in_top
            thrown = thrown_by_side.get(side)
            rate = _pitches_per_out(thrown, done)
            remaining, total = _team_pitches(
                outs_left, at_bat_remaining if pitching else None, rate)
            projected = (thrown + remaining) if thrown is not None else None
            # The bar reads against this staff's own night where we know it,
            # so a long outing shows as a long outing rather than being
            # measured against an average it has already left behind.
            scale = projected if projected else total
            rows.append(asdict(TeamPitches(
                team=str(team), side=side, is_pitching=pitching,
                outs_remaining=outs_left,
                expected_remaining=remaining,
                expected_total=total,
                pct_remaining=round(100.0 * remaining / scale, 1) if scale else 0.0,
                thrown=thrown,
                outs_recorded=done,
                pace=round(rate, 2),
                projected_total=projected,
                over_estimate=max(0, thrown - total) if thrown is not None else 0,
                complete=outs_left <= 0,
            )))
        out.team_pitches = rows

    _fill_countdown(None)

    if not sit.pitcher:
        # No pitcher named means the game isn't actually in progress — a
        # scheduled game, or one already final. Both are "nothing to forecast"
        # rather than a failure, and the page should say so plainly.
        out.reason = ("No at-bat is in progress. This appears once the game "
                      "starts and a pitcher is on the mound.")
        return out

    # The hitter actually in the box, forecast from the count he is actually
    # in. Those two go together: the batter at the plate is the interesting
    # one, and he is only interesting if the count travels with him. Reporting
    # his whole-plate-appearance strikeout rate while he stands there down 1-2
    # would describe a plate appearance that is no longer happening.
    #
    # Between innings the feed names no batter, and then the on-deck hitter is
    # the next thing to happen — forecast from 0-0, which for him is right.
    if sit.batter:
        subject_name, subject = sit.batter, "at_plate"
        start = (int(sit.balls or 0), int(sit.strikes or 0))
        if not (0 <= start[0] <= 3 and 0 <= start[1] <= 2):
            start = (0, 0)
    elif sit.on_deck:
        subject_name, subject, start = sit.on_deck, "on_deck", (0, 0)
    else:
        out.reason = "The live feed didn't name a hitter."
        return out
    out.subject = subject
    out.batter = subject_name
    out.pitcher = sit.pitcher
    out.balls, out.strikes = start
    out.on_deck = sit.on_deck

    index = _name_index(repo, season)
    b_line = _lookup(index, subject_name, "batter")
    p_line = _lookup(index, sit.pitcher, "pitcher")
    # A missing line is a stand-in rather than a dead panel. Measured against
    # stored lineups, about a fifth of slots on a night belong to somebody we
    # hold nothing for, so refusing them turned one hitter in five into an
    # error message.
    if b_line is None:
        b_line = _league_batter(subject_name, season)
        out.batter_profile = "league"
        out.notes.append(
            f"No season line for {subject_name} yet — a league-average batting "
            f"profile is standing in, so treat this as the shape of a typical "
            f"at-bat rather than his.")
    if p_line is None:
        p_line = _league_pitcher(sit.pitcher, season)
        out.pitcher_profile = "league"
        out.notes.append(
            f"No season line for {sit.pitcher} yet — a league-average pitching "
            f"profile is standing in.")

    out.batter_team = getattr(b_line, "team_id", None) or None

    # Park and weather. Deliberately the pipeline's own builder rather than a
    # second one assembled here: park factors are keyed by home team, weather
    # becomes an HR multiplier through a specific formula, and a private copy
    # of that logic would drift until this panel and the matchup card were
    # quietly describing two different games.
    try:
        from .pipeline import _game_context

        context = _game_context(
            game_id, repo, season, game.home_team_id,
            park_season or season, away_team=game.away_team_id)
    except Exception:
        context = None

    try:
        dist = pa_distribution(
            batter_dna_from_statline(b_line),
            pitcher_dna_from_statline(p_line),
            league_averages_default(season),
            context,
        )
    except Exception as exc:
        out.reason = f"Couldn't build the matchup — {type(exc).__name__}."
        return out

    fc: AtBatForecast = forecast_from_distribution(
        dist,
        batter=subject_name, pitcher=sit.pitcher,
        batter_hand=getattr(b_line, "hand", "R") or "R",
        pitcher_hand=getattr(p_line, "hand", "R") or "R",
        start_count=start,
    )

    out.available = True
    out.forecast = asdict(fc)
    # Refine the pitching staff's number now that the current at-bat has an
    # exact one. This is what makes the counter move between outs rather than
    # stepping five at a time whenever somebody is retired.
    _fill_countdown(fc.expected_pitches)
    if subject == "on_deck":
        out.notes.append(
            "Nobody is at the plate — between innings or mid-change — so this "
            "is the next hitter up, from a fresh count.")
    return out
