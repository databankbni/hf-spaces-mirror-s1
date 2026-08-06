"""Rank a slate's player props by the edge our simulation sees.

Every game is simulated first, then the posted prop prices are fetched and
compared against the model. Simulating first means the ranking never depends on
the order two feeds answered in, and the same cached run backs both the matchup
card and the bet listed beside it.

Markets covered, in the two families the UI shows side by side:

  pitcher_prop strikeouts, outs, hits/walks/earned runs allowed
  batter_prop  hits, total bases, HR, RBI, walks, strikeouts, singles/doubles

Game lines — moneyline, run line, total — are deliberately not priced. The only
feed reachable for them served a pregame number all game long, so a live price
could not be told apart from a stale one; rather than keep shipping a figure
that looked actionable and wasn't, they were removed outright. Sleeper carries
no team markets, so there is nothing to put in their place.

Each family carries both pregame plays and plays on games already in progress.
A live one is priced off a simulation that resumes from the current inning,
score and baserunners, and is flagged `is_live` so the UI can mark it.

Props are priced off the per-player distributions the simulator keeps —
P(stat ≥ line) — not off a projected mean, since a mean cannot answer an
over/under. The vig is left in deliberately, so a reported edge is the
conservative one.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import date as date_type
from typing import Optional

import numpy as np

from .edge import evaluate_market
from .odds import american_to_implied

# The only source props come from — never the game-line book ESPN attributed
# this game's moneyline/total to, which is a different feed entirely.
_PROPS_BOOK = "Sleeper"

PROPS_NOTE = (
    "No player props were priced: the props feed returned nothing reachable "
    "for this slate."
)

# How each prop stat reads in the selection text.
_PROP_LABEL = {
    "hits": "hits", "singles": "singles", "doubles": "doubles",
    "triples": "triples", "home_runs": "HR", "rbi": "RBI", "bb": "walks",
    "k": "strikeouts", "total_bases": "total bases", "outs": "outs recorded",
    "hits_allowed": "hits allowed", "bb_allowed": "walks allowed",
    "runs_allowed": "earned runs",
}


@dataclass
class BestBet:
    game_id: str
    away: str
    home: str
    first_pitch: Optional[str]
    market: str            # home_ml | away_ml | over | under | home_rl | away_rl
    selection: str         # human-readable, e.g. "BOS ML" or "Over 8.5"
    price: int             # American odds actually being offered
    line: Optional[float]  # total or run line, where the market has one
    book: Optional[str]
    model_probability: float
    implied_probability: float
    edge: float            # model probability minus the vig-inclusive implied
    expected_value: float  # profit per unit staked
    kelly_pct: float       # recommended stake, fractional Kelly
    ci_low: float
    ci_high: float
    lineups_confirmed: bool
    n_sims: int
    # Which panel this belongs in: pitcher_prop | batter_prop. A live game's
    # props keep their natural family — a live strikeout prop is still a
    # pitcher prop — and are flagged with `is_live` instead, so each panel
    # shows both the pregame and the in-progress version of its own market.
    category: str = "batter_prop"
    is_live: bool = False
    # True when this actually clears the minimum edge and sizes a stake. Plays
    # below the bar are still listed — an empty panel says nothing about the
    # slate — but must not be presented as recommendations.
    has_edge: bool = False
    # Set on player props only; None on the game markets above.
    player: Optional[str] = None
    stat: Optional[str] = None


@dataclass
class BestBetsReport:
    date: str
    generated_at: str
    games_considered: int
    games_priced: int
    bets: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    props_available: bool = False
    live_games: int = 0
    # {category: how many plays cleared the bar}, so the UI can tell "nothing
    # qualified" apart from "this market family wasn't available at all".
    counts: dict = field(default_factory=dict)
    # {category: how many were priced at all}, which is what distinguishes an
    # empty panel (no props quoted) from a full one where nothing qualified.
    priced_counts: dict = field(default_factory=dict)


def _prop_probs(hist: dict, line: float) -> tuple[float, float, int]:
    """(p_over, p_under, decided_n) for a player prop at `line`.

    `hist` is {value: games}. A whole-number line can be landed on exactly,
    which most books push; those games are dropped from the denominator, so
    over and under do not sum to 1 there. Half-point lines have no pushes and
    the two do sum to 1.
    """
    total = sum(hist.values())
    if not total:
        return 0.0, 0.0, 0
    pushes = sum(c for v, c in hist.items() if float(v) == line)
    n = (total - pushes) or total
    p_over = sum(c for v, c in hist.items() if v > line) / n
    p_under = sum(c for v, c in hist.items() if v < line) / n
    return p_over, p_under, n


def _prop_targets(repo, raw, season: int) -> dict[tuple[str, str], tuple[str, dict]]:
    """{(side, normalized name): (display name, {stat: histogram})} for one game.

    Keyed by side as well as name because a two-way player has both a batting
    and a pitching distribution, and a prop names which one it means. Only
    players the simulation actually produced a distribution for appear here, so
    a prop on someone who isn't starting finds no match and is skipped rather
    than being priced off nothing.
    """
    from ..data.names import normalize_name, player_names

    ids = [pid for _t, pid in raw.batter_hist]
    ids += [pid for _t, pid in raw.pitcher_hist if pid > 0]
    names = player_names(repo, ids, season)

    out: dict[tuple[str, str], tuple[str, dict]] = {}
    for key, hists in raw.batter_hist.items():
        nm = names.get(key[1])
        if nm:
            out[("batter", normalize_name(nm))] = (nm, hists)
    for key, hists in raw.pitcher_hist.items():
        # Ids ≤ 0 are the placeholder starter and the synthetic bullpen — no
        # real player to match a prop against.
        nm = names.get(key[1]) if key[1] > 0 else None
        if nm:
            out[("pitcher", normalize_name(nm))] = (nm, hists)
    return out


# Which box-score field carries the stat a live prop is quoted on. A live prop
# is a bet on the *final* number, so pricing it needs what the player has
# already banked plus a simulation of what's left. Stats the box score doesn't
# break out (singles, doubles, total bases) are absent on purpose — without a
# running count there is nothing to add the remainder to, so those props are
# skipped live rather than priced off the remainder alone, which would badly
# understate them.
_LIVE_BATTER_FIELD = {
    "hits": "hits", "home_runs": "home_runs", "rbi": "rbi",
    "bb": "walks", "k": "strikeouts",
}
_LIVE_PITCHER_FIELD = {
    "k": "strikeouts", "hits_allowed": "hits_allowed",
    "bb_allowed": "walks_allowed", "runs_allowed": "earned_runs",
}


def _outs_from_ip(ip) -> Optional[int]:
    """Outs recorded from an innings-pitched string ("5.2" = 5 innings 2 outs)."""
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole) * 3 + int(frac or 0)
    except (TypeError, ValueError):
        return None


def _accumulated(box, side: str, stat: str) -> dict[str, int]:
    """{normalized player name: stat already recorded} from a live box score."""
    from ..data.names import normalize_name

    out: dict[str, int] = {}
    if box is None:
        return out
    for team in (box.home, box.away):
        if team is None:
            continue
        if side == "batter":
            field = _LIVE_BATTER_FIELD.get(stat)
            rows = team.batters
        else:
            field = _LIVE_PITCHER_FIELD.get(stat)
            rows = team.pitchers
        for row in rows or ():
            if not row.name:
                continue
            if side == "pitcher" and stat == "outs":
                val = _outs_from_ip(row.innings_pitched)
            elif field is None:
                val = None
            else:
                val = getattr(row, field, None)
            if val is not None:
                out[normalize_name(row.name)] = int(val)
    return out


def _live_state_for(repo, game_row, game_id: str, home: str, away: str):
    """(initial_state, pitch_counts, bullpens, boxscore) for an in-progress game.

    All-None when the game can't be resumed — no live feed, not actually under
    way, or the linescore doesn't describe a resumable state.
    """
    from ..data.sources.boxscore import MLBBoxscoreSource
    from ..data.sources.linescore import MLBLinescoreSource
    from ..live import _live_bullpens, _live_inning_state, _starter_pitch_counts

    if not getattr(game_row, "game_pk", None):
        return None, None, None, None
    try:
        linescore = MLBLinescoreSource().fetch_linescore(game_row.game_pk, game_id)
    except Exception:
        return None, None, None, None
    if linescore is None:
        return None, None, None, None
    try:
        box = MLBBoxscoreSource().fetch_boxscore(game_row.game_pk, game_id)
    except Exception:
        box = None
    state = _live_inning_state(home, away, linescore, box)
    if state is None:
        return None, None, None, None
    return (state,
            _starter_pitch_counts(repo, game_id, home, away, box),
            _live_bullpens(repo, game_id, home, away, box),
            box)


def _smooth(p: float, n: int) -> float:
    """Laplace-corrected probability: (k+1)/(n+2) for k = p*n successes.

    A Monte Carlo estimate straight from counts can come back as exactly 0 or
    1, and both are lies about a finite sample. 2000 sims with no failures does
    not mean the event is certain — it means the true probability is somewhere
    above roughly 99.85%, which is a different claim.

    Reporting that as 100% is not just cosmetic. Edge is `p - implied`, and
    Kelly is `edge / (1 - implied)`, so p = 1 makes those two expressions equal
    and the stake pins to the cap no matter how short the price: a -5000 shot
    was being recommended at the full 25% of bankroll. Adding one phantom
    success and one phantom failure keeps the estimate honest at the extremes
    and moves nothing in the middle — at n = 2000 the correction is under a
    twentieth of a percentage point until p is already near 0 or 1.
    """
    if n <= 0:
        return p
    return (p * n + 1.0) / (n + 2.0)


def _prop_category(side: str) -> str:
    return "pitcher_prop" if side == "pitcher" else "batter_prop"


def _select(plays: list, limit: int) -> list:
    """The best `limit` plays, but never all of one kind when both exist.

    Straight top-by-edge would routinely show a panel of nothing but pregame
    plays — there are simply more of them — and the live ones, which are the
    most time-sensitive thing on the page, would never surface. So if the top
    slice happens to be all pregame (or all live) while the other kind exists,
    the weakest of it gives up its seat to the best of the other.

    At a limit of one there is no seat to give up, so the best play wins
    outright.
    """
    chosen = plays[:limit]
    if limit < 2 or len(plays) <= limit:
        return chosen
    # `chosen` is non-empty, so it already holds one of the two kinds and at
    # most one of these branches can fire.
    for want_live in (True, False):
        if any(b.is_live is want_live for b in chosen):
            continue
        pool = [b for b in plays if b.is_live is want_live]
        if pool:
            chosen = chosen[:-1] + [pool[0]]
    chosen.sort(key=lambda b: (-b.edge, -b.model_probability))
    return chosen


def build_best_bets(
    repo,
    day: date_type,
    *,
    n: int = 2000,
    seed: Optional[int] = 7,
    kelly_fraction: float = 0.25,
    min_edge: float = 0.02,
    season: int = 2026,
    park_season: int = 2023,
    budget_seconds: float = 240.0,
    props: bool = True,
    live: bool = True,
    per_category: int = 5,
) -> BestBetsReport:
    """Simulate the slate, then rank every market that's priced against it.

    Order matters and is deliberate: **simulate first, compare second**. Games
    are simulated whether or not a book has posted them, so the ranking never
    depends on which feed answered first, and — because the run goes through
    the shared cache — the number backing a listed bet is the identical run
    behind that game's matchup card, not a second opinion of it.

    Games already under way are included when `live` is set. Those are priced
    against a simulation that resumes from the current inning, score and
    baserunners, so a live moneyline is judged on the game that's left rather
    than on a pregame projection that the first six innings already refuted.

    `n`/`seed` default to what the matchup cards request, which is what lets
    the two share a cached run. Bounded by a wall-clock budget so a full slate
    can't run unbounded on a small host; whatever was priced before the budget
    ran out is returned.
    """
    from ..data.sources.sleeper import SleeperPropsSource
    from ..pipeline import ensure_lineups, simulate_live_remainder
    from ..simcache import simulate_cached

    deadline = time.monotonic() + budget_seconds
    notes: list[str] = []
    games = list(repo.get_schedule(day))

    def state_of(g) -> str:
        st = (getattr(g, "status", "") or "").lower()
        if "final" in st or "completed" in st or "game over" in st:
            return "final"
        if not st or "preview" in st or "scheduled" in st or "pre-game" in st:
            return "pregame"
        return "live"

    # ── 1. Simulate ──────────────────────────────────────────────────────────
    # Everything actionable, before a single price is looked at.
    sims: dict[str, tuple] = {}       # game_id → (result, raw)  [pregame]
    live_sims: dict[str, tuple] = {}  # game_id → (result, raw, boxscore)
    live_count = 0
    live_unresolved = 0
    for g in games:
        if time.monotonic() >= deadline:
            notes.append("Stopped early: simulation budget reached.")
            break
        st = state_of(g)
        if st == "final":
            continue
        # Roster-back the lineups before simulating. Without this a game with
        # no posted card simulates a synthetic nine of placeholder ids, which
        # no prop can ever be matched to — the panel then comes back empty for
        # a reason that looks nothing like the cause.
        try:
            ensure_lineups(repo, g.game_id, g.home_team_id, g.away_team_id, season)
        except Exception:
            pass
        if st == "live":
            if not live:
                continue
            state, pitch_counts, bullpens, box = _live_state_for(
                repo, g, g.game_id, g.home_team_id, g.away_team_id)
            if state is None:
                # No resumable state, so a live prop on this game can't be
                # priced: the prop is on the final number and we'd have no way
                # to credit what the player has already banked. Pricing it off
                # a full-game run instead would understate every one of them.
                # Counted so an empty panel can say why.
                live_unresolved += 1
                continue
            try:
                res, raw = simulate_live_remainder(
                    g.game_id, state, repo=repo, home_team=g.home_team_id,
                    away_team=g.away_team_id, n=n, season=season,
                    park_season=park_season, initial_pitch_counts=pitch_counts,
                    bullpen_by_team=bullpens,
                )
            except Exception:
                continue
            live_sims[g.game_id] = (res, raw, box)
            live_count += 1
            continue
        try:
            # Shared with the matchup card for this game — whoever asks first
            # pays for it, the other gets the same arrays back.
            sims[g.game_id] = simulate_cached(
                g.game_id, repo, home_team=g.home_team_id,
                away_team=g.away_team_id, n=n, seed=seed, season=season,
                park_season=park_season)
        except Exception:
            continue

    # ── 2. Fetch the prices ──────────────────────────────────────────────────
    # Keyed by game state as well as player: a pregame quote and an in-game
    # quote on the same player are different markets and need different
    # simulations, so a live prop must never be priced off a full-game run.
    props_by_key: dict[tuple[bool, str, str], list] = {}
    props_fetched = 0
    props_live = 0
    if props:
        try:
            for pr in SleeperPropsSource().fetch_props():
                props_fetched += 1
                props_live += 1 if pr.is_live else 0
                props_by_key.setdefault(
                    (pr.is_live, pr.side, pr.player_key), []).append(pr)
        except Exception:
            props_by_key = {}

    bets: list[BestBet] = []
    props_priced = 0

    # ── 3. Compare ───────────────────────────────────────────────────────────
    for g in games:
        gid = g.game_id
        is_live = gid in live_sims
        if is_live:
            result, raw, live_box = live_sims[gid]
        elif gid in sims:
            result, raw = sims[gid]
            live_box = None
        else:
            continue

        confirmed = False
        try:
            lc = repo.get_lineup(gid, g.home_team_id)
            confirmed = bool(lc and lc.confirmed)
        except Exception:
            pass

        fp = getattr(g, "first_pitch", None)
        common = dict(
            game_id=gid, away=g.away_team_id, home=g.home_team_id,
            first_pitch=str(fp) if fp else None,
            book=_PROPS_BOOK,
            lineups_confirmed=confirmed,
        )

        def add(market: str, selection: str, p: float, n_sims: int,
                price: int, line: Optional[float], player: Optional[str] = None,
                stat: Optional[str] = None, category: str = "batter_prop") -> None:
            p = _smooth(p, n_sims)
            e = evaluate_market(gid, market, p, n_sims, price, kelly_fraction)
            bets.append(BestBet(
                market=market, selection=selection, price=price, line=line,
                model_probability=round(p, 4),
                implied_probability=round(e.implied_probability, 4),
                edge=round(e.edge, 4),
                expected_value=round(e.expected_value, 4),
                kelly_pct=round(e.recommended_stake_pct * 100, 2),
                ci_low=round(e.confidence_interval_95[0], 4),
                ci_high=round(e.confidence_interval_95[1], 4),
                n_sims=n_sims, player=player, stat=stat,
                category=category, is_live=is_live, **common,
            ))

        # Player props, off the per-player distributions this same simulation
        # produced, so a prop and the total it implies can never disagree.
        if props_by_key:
            targets = _prop_targets(repo, raw, season)
            for (side, key), target in targets.items():
                for prop in props_by_key.get((is_live, side, key), ()):
                    hist = target[1].get(prop.stat)
                    if not hist:
                        continue  # stat the simulator doesn't distribute
                    line_val = prop.line
                    if is_live:
                        # The prop is on the game's final number, but this
                        # simulation only covers what's left — so the line has
                        # to come down by what the player already has.
                        banked = _accumulated(live_box, side, prop.stat).get(key)
                        if banked is None:
                            continue  # no running count → can't shift it honestly
                        line_val = prop.line - banked
                        if line_val < 0:
                            # Already past the line: the over has won and the
                            # under has lost, so there is no bet here. Priced
                            # anyway it reads as a 100% lock with a huge edge
                            # and would head the whole panel.
                            continue
                    p_over, p_under, pn = _prop_probs(hist, line_val)
                    if not pn:
                        continue
                    label = _PROP_LABEL.get(prop.stat, prop.stat)
                    who = target[0]
                    cat = _prop_category(side)
                    if prop.over_price is not None:
                        add("prop_over", f"{who} Over {prop.line:g} {label}",
                            p_over, pn, prop.over_price, prop.line, who, prop.stat,
                            category=cat)
                    if prop.under_price is not None:
                        add("prop_under", f"{who} Under {prop.line:g} {label}",
                            p_under, pn, prop.under_price, prop.line, who, prop.stat,
                            category=cat)
                    props_priced += 1

    # ── 4. Rank, within each family ──────────────────────────────────────────
    # Ranked per category rather than globally: the UI shows the families side
    # by side, and one having fatter edges must not empty the other.
    #
    # Every priced play is ranked, not just the ones clearing `min_edge`. This
    # product's hold is around 15%, so on most slates nothing clears a 2% bar
    # and a filtered panel is simply empty — which says nothing about the slate
    # and reads as broken. Each play instead carries `has_edge`, so the panel
    # can always show the closest ones while marking which are actually worth
    # backing. `counts` stays the number that cleared the bar, so "5 shown,
    # none qualified" is distinguishable from "5 shown, 5 qualified".
    for b in bets:
        b.has_edge = b.edge >= min_edge and b.kelly_pct > 0
    bets.sort(key=lambda b: (-b.edge, -b.model_probability))

    ranked: list[BestBet] = []
    counts: dict[str, int] = {}
    priced_counts: dict[str, int] = {}
    for cat in ("pitcher_prop", "batter_prop"):
        family = [b for b in bets if b.category == cat]
        counts[cat] = sum(1 for b in family if b.has_edge)
        priced_counts[cat] = len(family)
        ranked.extend(_select(family, per_category))
    ranked.sort(key=lambda b: (-b.edge, -b.model_probability))

    priced = len(sims) + len(live_sims)
    if ranked and not any(b.has_edge for b in ranked):
        notes.append(
            "Nothing cleared the minimum edge; the closest plays are shown so "
            "the slate can be judged, but none is a recommendation.")
    if props_priced:
        notes.append(f"{props_priced} player props priced against our per-player "
                     f"simulated distributions ({props_fetched} quoted by "
                     f"{_PROPS_BOOK}).")
    elif props:
        notes.append(PROPS_NOTE)
    notes.append(
        f"Player props only, from {_PROPS_BOOK}. Team markets are not priced: "
        "the endpoint serving them has not been identified.")
    if live_count:
        notes.append(f"{live_count} game(s) in progress priced off a simulation of "
                     f"the remaining innings ({props_live} live props quoted).")
    if live_unresolved:
        notes.append(
            f"{live_unresolved} game(s) in progress had no resumable state, so "
            "their live props could not be priced — a live prop needs the "
            "current box score to know what the player has already banked.")

    from datetime import datetime, timezone
    return BestBetsReport(
        date=day.isoformat(),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        games_considered=len(games),
        games_priced=priced,
        bets=[asdict(b) for b in ranked],
        notes=notes,
        props_available=props_priced > 0,
        live_games=live_count,
        counts=counts,
        priced_counts=priced_counts,
    )
