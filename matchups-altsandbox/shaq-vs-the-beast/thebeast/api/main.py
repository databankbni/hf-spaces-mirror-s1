"""thebeast REST API + SPA host — FastAPI (F-006).

All JSON endpoints live under ``/api/*`` (mirroring mrsim); everything else is
served from the compiled SvelteKit bundle in ``web/build`` so the API and the UI
run in one process / one port — the shape Hugging Face's Docker SDK expects.

API:
    GET  /api/health
    GET  /api/dates                          → list[str]  (dates with data)
    GET  /api/games?date=YYYY-MM-DD          → list[GameSchedule]
    GET  /api/lineups?game_id=ID&...         → {home, away}
    POST /api/simulate  {game_id, n, ...}    → GameSimulationResult + histograms
    POST /api/bet       {game_id, odds}      → list[BettingEdge]

OpenAPI docs: /api/_swagger. Malformed bodies → HTTP 422 (Pydantic).
"""
from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..betting.edge import analyze_moneyline, analyze_totals
from ..betting.odds import MarketOdds
from ..data.names import player_name as _player_name, player_names
from ..live import (
    _live_bullpens,
    _live_inning_state,
    _next_batting_slot,
    _starter_pitch_counts,
)
from ..data.repository import SQLiteRepository
from ..pipeline import (
    ensure_lineups,
    resolve_lineups,
    simulate_live_remainder,
    simulate_matchup,
    simulate_matchup_conditioned,
)
from ..simcache import simulate_cached
from ..simulator.state import InningState

app = FastAPI(
    title="Diamond Analytics Predictor",
    version="0.1.0",
    docs_url="/api/_swagger",
    redoc_url="/api/_redoc",
    openapi_url="/api/_openapi.json",
)

@app.middleware("http")
async def _no_store_api(request, call_next):
    """Forbid any layer from holding on to an /api/* response.

    These are all dynamic and only useful if they're current. Without an explicit directive a browser or an
    intervening proxy is free to serve a heuristically cached copy, which for
    an in-game line means showing a price that no longer exists. The compiled
    bundle under /_app is content-hashed and still caches normally; only the
    API is opted out.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


_WEB_DIR = Path(__file__).resolve().parents[2] / "web" / "build"


def get_repo() -> SQLiteRepository:
    return SQLiteRepository()


# The scored-game record is a committed file, not container state: this
# filesystem is rebuilt from the image on every deploy, so anything written
# here at runtime is erased by the next push. Loading it once at import time
# is what puts the accuracy report in front of a visitor at all.
_SCORED_LOADED = False


def _load_scored_record() -> None:
    global _SCORED_LOADED
    if _SCORED_LOADED:
        return
    _SCORED_LOADED = True
    try:
        from ..accuracy import import_scored
        n = import_scored(get_repo())
        if n:
            print(f"[accuracy] loaded {n} scored game(s) from the record")
    except Exception as exc:  # a broken record must not stop the app booting
        print(f"[accuracy] could not load scored record: {exc}")


_load_scored_record()


# ── Request schemas ───────────────────────────────────────────────────────────

CURRENT_SEASON = 2026   # statlines used for upcoming-game predictions
PARK_SEASON = 2023      # park factors are stable year to year

# How long a reader will wait for the slate's simulation before answering from
# whatever is warm. Generous by request — waiting for the real runs beats
# starting duplicates of them — but bounded, so a wedged warm-up degrades into
# a slow answer rather than a hung request.
BEST_BETS_WAIT_SECONDS = 150.0
CHAT_WAIT_SECONDS = 90.0


class SimulateRequest(BaseModel):
    game_id: str
    n: int = Field(default=2000, ge=1, le=200_000)
    seed: Optional[int] = None
    season: int = CURRENT_SEASON
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    # Pipeline knobs surfaced for the /simulate lab page.
    shrink_pa: int = Field(default=200, ge=0, le=2000)
    shrink_bf: int = Field(default=300, ge=0, le=2000)
    use_bullpen: bool = True
    use_context: bool = True
    calibrate: bool = True
    calibrate_totals: bool = True
    # Conditioned run: when both are set, only keep games that finish exactly
    # this final score and average the box score over those (a true, if
    # rejection-sampled, Monte Carlo — not a rescale of the projection).
    target_away: Optional[int] = Field(default=None, ge=0, le=50)
    target_home: Optional[int] = Field(default=None, ge=0, le=50)
    # Per-batter "what-if" rate multipliers, keyed by player_id (as a string in
    # JSON); inner keys among {"hits","home_runs","bb","k"}. Applied to the
    # batter's outcome rates before the sim so the edit dominoes through.
    rate_overrides: Optional[dict[str, dict[str, float]]] = None
    # Same idea for pitchers, keyed by pitcher_id; inner keys among
    # {"hits_allowed","hr_allowed","bb_allowed","k"}.
    pitcher_overrides: Optional[dict[str, dict[str, float]]] = None


class OddsBody(BaseModel):
    home_ml: int
    away_ml: int
    total_line: float = 8.5
    over_ml: int = -110
    under_ml: int = -110


class BetRequest(BaseModel):
    game_id: str
    odds: OddsBody
    kelly_fraction: float = Field(default=0.25, gt=0.0, le=1.0)
    n: int = Field(default=2000, ge=1, le=200_000)
    seed: Optional[int] = None
    season: int = CURRENT_SEASON
    home_team: Optional[str] = None
    away_team: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _histogram(values: np.ndarray) -> dict:
    """Integer-bin a run/total array into {edges, counts} for the SVG charts."""
    if len(values) == 0:
        return {"edges": [0, 1], "counts": [0]}
    lo = int(values.min())
    hi = int(values.max())
    edges = list(range(lo, hi + 2))  # one edge past the last bin
    counts = [int(np.sum(values == v)) for v in range(lo, hi + 1)]
    return {"edges": edges, "counts": counts}


def _base_game_id(game_id: str) -> str:
    """Drop a doubleheader '-g{N}' suffix so team/date parsing sees the base id."""
    return re.sub(r"-g\d+$", "", game_id)


def _teams_from_game_id(game_id: str) -> tuple[Optional[str], Optional[str]]:
    """Parse '<date>-<away>-<home>[-g{N}]' → (home, away); None if it doesn't match."""
    parts = _base_game_id(game_id).rsplit("-", 2)
    if len(parts) == 3:
        _, away, home = parts
        return home, away
    return None, None


# Seasons to walk (newest first) when a player has no statline for the exact
# requested season — a callup/rookie may only have a prior year on file, and a
# real name from last season beats showing a bare id.
def _name_map(repo: SQLiteRepository, ids: list[int], season: int) -> dict[int, str]:
    """{id: name} for the given ids: stored statlines first, then a single
    batched MLB people lookup for whatever's left. Shared with the betting
    pipeline, which needs the same mapping to match book player names."""
    return player_names(repo, ids, season)


def _attach_names(repo: SQLiteRepository, lines: list[dict], season: int) -> list[dict]:
    names = _name_map(repo, [int(l["player_id"]) for l in lines], season)
    for line in lines:
        pid = int(line["player_id"])
        line["name"] = names.get(pid) or str(pid)
    return lines


def _attach_pitcher_names(repo: SQLiteRepository, lines: list[dict], season: int) -> list[dict]:
    """Name pitcher lines; the synthetic team-bullpen (negative id) → 'Bullpen'."""
    names = _name_map(repo, [int(l["player_id"]) for l in lines if int(l["player_id"]) > 0], season)
    for line in lines:
        pid = int(line["player_id"])
        if pid < 0:  # team_bullpen_pid is negative — the aggregate reliever
            line["name"] = "Bullpen"
        elif pid == 0:  # league-average placeholder starter (no probable named yet)
            line["name"] = "Projected starter"
        else:
            line["name"] = names.get(pid) or str(pid)
    return lines


def _attach_lineup_slots(lines: list[dict], home_lineup, away_lineup) -> list[dict]:
    """Tag each player line with its real batting-order slot (1-9).

    The box score was previously displayed sorted by projected PA, which is
    only a correlate of batting order, not the order itself — normal
    simulation variance can shuffle two adjacent hitters, and it gives no
    guarantee the actual leadoff man ends up shown first. This attaches the
    lineup's real slot (its index in LineupCard.batting_order, which is set
    directly from the confirmed MLB card or the roster fallback) so the UI
    can sort by the authoritative order instead of an approximation.
    """
    slot_by_id = {
        pid: i + 1
        for lineup in (home_lineup, away_lineup)
        for i, pid in enumerate(lineup.batting_order)
    }
    for line in lines:
        slot = slot_by_id.get(int(line["player_id"]))
        if slot is not None:
            line["lineup_slot"] = slot
    return lines


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "has_ui": (_WEB_DIR / "index.html").exists()}


@app.get("/api/dates")
def dates() -> list[str]:
    return get_repo().get_schedule_dates()


@app.get("/api/games")
def games(date: str = Query(..., description="Slate date YYYY-MM-DD")) -> list[dict]:
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid date: {date!r}")
    rows = [dataclasses.asdict(g) for g in get_repo().get_schedule(d)]
    # Opening a slate is the signal to simulate it. Doing it here, once,
    # server-side, is what lets the cards, the ranked plays and the assistant
    # all read one set of runs instead of racing to produce three.
    from ..slate import ensure as warm_slate
    warm_slate(get_repo(), d, season=CURRENT_SEASON, park_season=PARK_SEASON)
    return rows


@app.get("/api/slate/status")
def slate_status(date: str = Query(..., description="Slate date YYYY-MM-DD")) -> dict:
    """How far the slate's simulation has got.

    The page polls this so it can say "9 of 15" instead of leaving the cards,
    the ranked plays and the assistant looking broken while the work happens.
    """
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid date: {date!r}")
    from ..slate import status as slate_progress
    progress = slate_progress(d)
    if progress is None:
        return {"date": date, "state": "idle", "total": 0, "done": 0,
                "failed": [], "elapsed_seconds": 0.0}
    return progress.as_dict()


@app.post("/api/slate/rerun")
def slate_rerun(date: str = Query(..., description="Slate date YYYY-MM-DD")) -> dict:
    """Throw this slate's simulations away and start again.

    What "Run new simulation" has to do to mean anything. Clearing the browser's
    copy isn't enough — the runs live here, so without this the button fetched
    the same numbers back and called them new.
    """
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid date: {date!r}")
    repo = get_repo()
    from ..simcache import clear as clear_sims
    from ..slate import ensure as warm_slate, reset as reset_slate
    try:
        dropped = clear_sims({g.game_id for g in repo.get_schedule(d)})
    except Exception:
        dropped = 0
    reset_slate(d)
    progress = warm_slate(repo, d, season=CURRENT_SEASON, park_season=PARK_SEASON)
    return {"dropped": dropped, **progress.as_dict()}


@app.get("/api/games-live")
def games_live(date: str = Query(..., description="Slate date YYYY-MM-DD")) -> list[dict]:
    """Re-fetch one date's schedule from MLB (storing it) before returning it.

    This is how reschedules and newly-announced doubleheaders on any viewed
    date get picked up in real time — the stored `/api/games` read only reflects
    the last fetch. Best-effort: if MLB is unreachable it falls back to whatever
    is already stored, so the page always renders.
    """
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid date: {date!r}")
    repo = get_repo()
    try:
        from ..data.sources.schedules import MLBScheduleSource
        MLBScheduleSource(repo).fetch_schedule(d)
    except Exception:
        pass  # live fetch failed — return whatever's stored
    return [dataclasses.asdict(g) for g in repo.get_schedule(d)]


def _fill_roster(repo: SQLiteRepository, game) -> None:
    """Swap a game's not-yet-posted placeholder batters for the team's roster."""
    from ..data.ingest import ROSTER_GAME_ID
    for team in (game.home_team_id, game.away_team_id):
        lc = repo.get_lineup(game.game_id, team)
        if lc is None or not lc.batting_order:
            continue
        if lc.batting_order[0] >= 9_000_000:  # placeholder marker
            roster = repo.get_lineup(f"{ROSTER_GAME_ID}-{CURRENT_SEASON}", team)
            if roster is not None and roster.batting_order:
                lc.batting_order = roster.batting_order
                repo.save_lineup(lc)


def _ensure_lineups(repo: SQLiteRepository, game_id: str,
                    home: Optional[str], away: Optional[str], season: int) -> None:
    """Roster-back a game's lineups; shared with the betting pipeline."""
    ensure_lineups(repo, game_id, home, away, season)


_UPCOMING_BUDGET_SECONDS = 10.0  # hard wall-clock cap so a stuck host can't hang the page


@app.get("/api/upcoming")
def upcoming(days: int = Query(3, ge=0, le=10)) -> list[dict]:
    """Live MLB schedule for today..+`days`, saved so it is simulatable.

    Pre-lineup games keep their real probable starters; their batting orders are
    filled from each team's current-season roster so predictions use real hitters.

    Bounded by a total wall-clock budget (not just a per-request timeout):
    DNS/connect stalls on a restricted network can exceed a socket timeout in
    aggregate across several dates, and the caller (the matchups page) needs a
    response — even an empty/partial one — well before the user gives up.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
    from datetime import timedelta

    from ..data.sources.schedules import MLBScheduleSource
    repo = get_repo()
    source = MLBScheduleSource(repo)
    today = datetime.utcnow().date()
    out: list[dict] = []
    deadline = time.monotonic() + _UPCOMING_BUDGET_SECONDS

    # No `with` block: shutdown(wait=True) would block this request on a
    # thread stuck past its timeout. wait=False lets the handler return the
    # partial slate immediately; any hung worker just dies on its own later.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        # Start one day back: a caller's local calendar day can trail the
        # server's UTC day by up to a timezone's worth of hours (e.g. an
        # evening West Coast game is already UTC-dated "tomorrow"), so a
        # window starting exactly at UTC-today can miss games the caller
        # would still call "today".
        for i in range(-1, days + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            d = today + timedelta(days=i)
            future = pool.submit(source.fetch_schedule, d)
            try:
                for g in future.result(timeout=remaining):
                    _fill_roster(repo, g)
                    out.append(dataclasses.asdict(g))
            except FutureTimeoutError:
                break  # budget exhausted — stop trying further dates
            except Exception:  # network hiccup for one date shouldn't kill the slate
                continue
    finally:
        pool.shutdown(wait=False)
    return out


import re as _re

_LOG_RE = _re.compile(r"^(Top|Bot) (\d+) \| (\S+) (-?\d+) vs (-?\d+) → (\S+) \((\d+)R, runners=(\d+), outs=(\d+)\)$")


def _format_play_log(repo: SQLiteRepository, log: list[str], season: int) -> list[dict]:
    """Parse the engine's play-log strings into named, UI-friendly entries."""
    out: list[dict] = []
    names: dict[int, str] = {}

    def name(pid: int) -> str:
        if pid not in names:
            if pid <= 0:
                names[pid] = _player_name(repo, pid, season) or "League-avg P"
            else:
                names[pid] = _player_name(repo, pid, season) or str(pid)
        return names[pid]

    for line in log:
        m = _LOG_RE.match(line)
        if not m:
            continue
        half, inning, team, bid, pid, outcome, runs, runners, outs = m.groups()
        out.append({
            "half": half, "inning": int(inning), "team": team,
            "batter": name(int(bid)), "pitcher": name(int(pid)),
            "outcome": outcome, "runs": int(runs),
            "runners": runners, "outs": int(outs),
        })
    return out


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> dict:
    repo = get_repo()
    home, away = req.home_team, req.away_team
    if home is None or away is None:
        home, away = _teams_from_game_id(req.game_id)
    _ensure_lineups(repo, req.game_id, home, away, req.season)

    # Per-batter what-if edits (JSON keys are strings → int player ids).
    overrides: Optional[dict[int, dict[str, float]]] = None
    if req.rate_overrides:
        overrides = {}
        for pid_str, mults in req.rate_overrides.items():
            try:
                overrides[int(pid_str)] = {k: float(v) for k, v in mults.items()}
            except (ValueError, TypeError):
                continue

    pitcher_ovr: Optional[dict[int, dict[str, float]]] = None
    if req.pitcher_overrides:
        pitcher_ovr = {}
        for pid_str, mults in req.pitcher_overrides.items():
            try:
                pitcher_ovr[int(pid_str)] = {k: float(v) for k, v in mults.items()}
            except (ValueError, TypeError):
                continue

    conditioned = req.target_away is not None and req.target_home is not None
    meta: Optional[dict] = None
    if conditioned:
        result, raw, meta = simulate_matchup_conditioned(
            req.game_id, target_away=req.target_away, target_home=req.target_home,
            repo=repo, home_team=home, away_team=away, seed=req.seed, season=req.season,
            park_season=PARK_SEASON, shrink_pa=req.shrink_pa, shrink_bf=req.shrink_bf,
            use_bullpen=req.use_bullpen, use_context=req.use_context,
            calibrate_totals=req.calibrate_totals, rate_overrides=overrides,
            pitcher_overrides=pitcher_ovr,
        )
    elif overrides or pitcher_ovr:
        # A what-if run is this caller's private question — never cached, and
        # never served to anyone else.
        result, raw = simulate_matchup(
            req.game_id, repo, home_team=home, away_team=away,
            n=req.n, seed=req.seed, season=req.season, park_season=PARK_SEASON,
            shrink_pa=req.shrink_pa, shrink_bf=req.shrink_bf,
            use_bullpen=req.use_bullpen, use_context=req.use_context,
            calibrate=req.calibrate, calibrate_totals=req.calibrate_totals,
            rate_overrides=overrides, pitcher_overrides=pitcher_ovr,
            representative=True,
        )
    else:
        # The plain projection, shared with the best-bets ranker so the card
        # and the bet listed beside it are backed by the same run rather than
        # by two runs that land a percentage point apart.
        result, raw = simulate_cached(
            req.game_id, repo, home_team=home, away_team=away,
            n=req.n, seed=req.seed, season=req.season, park_season=PARK_SEASON,
            shrink_pa=req.shrink_pa, shrink_bf=req.shrink_bf,
            use_bullpen=req.use_bullpen, use_context=req.use_context,
            calibrate=req.calibrate, calibrate_totals=req.calibrate_totals,
            representative=True,
        )
    payload = dataclasses.asdict(result)
    payload["player_lines"] = _attach_names(repo, payload["player_lines"], req.season)
    home_lineup, away_lineup = resolve_lineups(req.game_id, repo, home, away)
    payload["player_lines"] = _attach_lineup_slots(payload["player_lines"], home_lineup, away_lineup)
    payload["pitcher_lines"] = _attach_pitcher_names(repo, payload.get("pitcher_lines", []), req.season)
    payload["histograms"] = {
        "home_runs": _histogram(raw.home_runs),
        "away_runs": _histogram(raw.away_runs),
        "totals": _histogram(raw.totals),
    }
    rep = raw.representative
    payload["representative"] = None if rep is None else {
        "home_score": rep.home_score,
        "away_score": rep.away_score,
        "home_by_inning": rep.home_by_inning,
        "away_by_inning": rep.away_by_inning,
        "extra_innings": rep.extra_innings,
        "play_log": _format_play_log(repo, rep.play_log, req.season),
    }
    if conditioned and meta is not None:
        payload["conditioned"] = {
            "target_away": req.target_away,
            "target_home": req.target_home,
            "matches": meta["matches"],
            "games_run": meta["games_run"],
        }
    # Surface whether each side's lineup is MLB-confirmed or a projected
    # (roster-based) fallback, so the UI can label it rather than present a
    # guessed batting order as if it were the real card.
    payload["lineups"] = {
        "home": _lineup_status(repo, req.game_id, home),
        "away": _lineup_status(repo, req.game_id, away),
    }
    return payload


def _lineup_status(repo: SQLiteRepository, game_id: str, team: Optional[str]) -> dict:
    """{team, confirmed, confirmed_at} for one side's stored lineup."""
    lc = repo.get_lineup(game_id, team) if team else None
    confirmed = bool(lc.confirmed) if lc is not None else False
    at = lc.confirmed_at.isoformat() if (lc is not None and lc.confirmed_at) else None
    return {"team": team, "confirmed": confirmed, "confirmed_at": at}


@app.post("/api/bet")
def bet(req: BetRequest) -> list[dict]:
    home, away = req.home_team, req.away_team
    if home is None or away is None:
        home, away = _teams_from_game_id(req.game_id)
    result, raw = simulate_matchup(
        req.game_id, get_repo(), home_team=home, away_team=away,
        n=req.n, seed=req.seed, season=req.season, park_season=PARK_SEASON,
    )
    odds = MarketOdds(
        game_id=req.game_id, home_ml=req.odds.home_ml, away_ml=req.odds.away_ml,
        total_line=req.odds.total_line, over_ml=req.odds.over_ml,
        under_ml=req.odds.under_ml,
    )
    edges = (analyze_moneyline(result, odds, req.kelly_fraction)
             + analyze_totals(raw, odds, req.kelly_fraction))
    return [dataclasses.asdict(e) for e in edges]


@app.get("/api/availability")
def availability(team: str = Query(..., description="Team abbreviation, e.g. NYY"),
                 season: int = CURRENT_SEASON,
                 report: bool = Query(False, description="Include the full injury list")) -> dict:
    """What the roster check can see for one team, and what it's doing about it.

    Injury filtering is invisible when it works and invisible when it doesn't —
    a lineup with an injured player in it looks the same whether the check ran
    and disagreed or never ran at all. This says which, from wherever the app
    is actually deployed, because statsapi is not reachable from every
    environment this is developed in.
    """
    from ..data.ingest import ROSTER_GAME_ID
    from ..data.names import player_names
    from ..data.sources.availability import MLBAvailabilitySource
    from ..pipeline import available_order

    repo = get_repo()
    source = MLBAvailabilitySource()
    out = source.diagnose(team)

    card = repo.get_lineup(f"{ROSTER_GAME_ID}-{season}", team.strip().upper())
    projected = list(card.batting_order) if card else []
    out["projected"] = projected
    if projected:
        filtered = available_order(repo, team, projected, season)
        removed = [p for p in projected if p not in filtered]
        added = [p for p in filtered if p not in projected]
        names = player_names(repo, projected + filtered, season)
        reasons = source.label_absences(team, removed) if removed else {}
        out["removed"] = [{"player_id": p, "name": names.get(p) or str(p),
                           "reason": reasons.get(p, "not on the active roster")}
                          for p in removed]
        out["promoted"] = [{"player_id": p, "name": names.get(p) or str(p)}
                           for p in added]
        out["lineup"] = [names.get(p) or str(p) for p in filtered]
        # Nothing in a lineup should ever render as a bare id. If one does, the
        # substitution let through a player we can't name — say so here rather
        # than letting it show up as a row of integers on the card.
        out["unnamed_in_lineup"] = [p for p in filtered if not names.get(p)]
    if report:
        out["injury_report"] = source.injury_report(team)
    return out


@app.get("/api/lineups")
def lineups(
    game_id: str = Query(...),
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
) -> dict:
    if home_team is None or away_team is None:
        h, a = _teams_from_game_id(game_id)
        home_team = home_team or h
        away_team = away_team or a
    home, away = resolve_lineups(game_id, get_repo(), home_team, away_team)
    return {"home": dataclasses.asdict(home), "away": dataclasses.asdict(away)}


@app.get("/api/game/{game_id}")
def game_detail(game_id: str) -> dict:
    """One game's schedule entry, live-refreshed — score/inning/status as of now.

    Does a best-effort live re-fetch of that date before reading storage, so
    this always reflects the current game state rather than whatever was
    last cached; falls back to the stored row if the live source fails.
    """
    game_date = _date_from_game_id(game_id)
    if game_date is None:
        raise HTTPException(status_code=422, detail=f"invalid game_id: {game_id!r}")
    repo = get_repo()
    try:
        from ..data.sources.schedules import MLBScheduleSource
        MLBScheduleSource(repo).fetch_schedule(game_date)
    except Exception:
        pass  # live refresh failed — fall through to whatever's stored
    for g in repo.get_schedule(game_date):
        if g.game_id == game_id:
            return dataclasses.asdict(g)
    raise HTTPException(status_code=404, detail=f"no schedule entry for {game_id!r}")


@app.get("/api/game/{game_id}/linescore")
def game_linescore(game_id: str) -> dict:
    """Inning-by-inning box score + live situation for one game.

    Never raises: an empty/default linescore (no innings, no situation) comes
    back if the game has no gamePk yet, or the linescore source is
    unreachable — the box-score/live panel just has nothing to show yet.
    """
    from ..data.sources.linescore import GameLinescore, MLBLinescoreSource

    game_date = _date_from_game_id(game_id)
    if game_date is None:
        raise HTTPException(status_code=422, detail=f"invalid game_id: {game_id!r}")
    repo = get_repo()
    game_pk = next((g.game_pk for g in repo.get_schedule(game_date) if g.game_id == game_id), None)
    result = None
    if game_pk:
        try:
            result = MLBLinescoreSource().fetch_linescore(game_pk, game_id)
        except Exception:
            result = None
    if result is None:
        result = GameLinescore(game_id=game_id)
    return dataclasses.asdict(result)


@app.get("/api/game/{game_id}/boxscore")
def game_boxscore(game_id: str) -> dict:
    """Full per-player batting/pitching lines for one game (real, not simulated).

    Never raises: empty batter/pitcher lists come back if the game has no
    gamePk yet or the box score source is unreachable.
    """
    from ..data.sources.boxscore import GameBoxscore, MLBBoxscoreSource, TeamBoxscore

    game_date = _date_from_game_id(game_id)
    if game_date is None:
        raise HTTPException(status_code=422, detail=f"invalid game_id: {game_id!r}")
    repo = get_repo()
    game_pk = next((g.game_pk for g in repo.get_schedule(game_date) if g.game_id == game_id), None)
    result = None
    if game_pk:
        try:
            result = MLBBoxscoreSource().fetch_boxscore(game_pk, game_id)
        except Exception:
            result = None
    if result is None:
        result = GameBoxscore(game_id=game_id, away=TeamBoxscore([], []), home=TeamBoxscore([], []))
    return dataclasses.asdict(result)


def _date_from_game_id(game_id: str) -> Optional[date]:
    parts = _base_game_id(game_id).rsplit("-", 2)
    if len(parts) != 3:
        return None
    try:
        return datetime.strptime(parts[0], "%Y-%m-%d").date()
    except ValueError:
        return None


# ── Live sim: resume a game in progress and simulate the rest ───────────────

@app.get("/api/game/{game_id}/live-sim")
def game_live_sim(game_id: str, n: int = Query(3000, ge=200, le=20000)) -> dict:
    """Simulate the remainder of an in-progress game from its current state.

    Pulls the live linescore + box score, resumes the simulator at that exact
    inning/half/outs/baserunners with the runs already scored and each side's
    real spot in the batting order, then plays the rest of the game `n` times.

    Returns {"live": false, "reason": ...} when there's nothing to resume (the
    game hasn't started, is already final, or the live feed is unavailable).
    """
    repo = get_repo()
    home, away = _teams_from_game_id(game_id)
    game_date = _date_from_game_id(game_id)
    if game_date is None:
        raise HTTPException(status_code=422, detail=f"invalid game_id: {game_id!r}")

    try:
        from ..data.sources.schedules import MLBScheduleSource
        MLBScheduleSource(repo).fetch_schedule(game_date)
    except Exception:
        pass
    row = next((g for g in repo.get_schedule(game_date) if g.game_id == game_id), None)
    if row is None or not row.game_pk:
        return {"game_id": game_id, "live": False, "reason": "no game data yet"}
    status = (row.status or "").lower()
    if "final" in status:
        return {"game_id": game_id, "live": False, "reason": "game is final"}
    if row.game_pk is None or "preview" in status or "scheduled" in status:
        return {"game_id": game_id, "live": False, "reason": "game hasn't started"}

    from ..data.sources.boxscore import MLBBoxscoreSource
    from ..data.sources.linescore import MLBLinescoreSource
    try:
        linescore = MLBLinescoreSource().fetch_linescore(row.game_pk, game_id)
    except Exception:
        linescore = None
    if linescore is None:
        return {"game_id": game_id, "live": False, "reason": "live feed unavailable"}
    try:
        boxscore = MLBBoxscoreSource().fetch_boxscore(row.game_pk, game_id)
    except Exception:
        boxscore = None

    _ensure_lineups(repo, game_id, home, away, CURRENT_SEASON)
    state = _live_inning_state(home, away, linescore, boxscore)
    if state is None:
        return {"game_id": game_id, "live": False, "reason": "no in-progress state to resume"}

    result, raw = simulate_live_remainder(
        game_id, state, repo=repo, home_team=home, away_team=away, n=n,
        season=CURRENT_SEASON, park_season=PARK_SEASON,
        initial_pitch_counts=_starter_pitch_counts(repo, game_id, home, away, boxscore),
        bullpen_by_team=_live_bullpens(repo, game_id, home, away, boxscore),
    )

    hr, ar = raw.home_runs, raw.away_runs
    home_win = float(np.mean(hr > ar))
    away_win = float(np.mean(ar > hr))
    # The engine plays regulation only, so a simulated "tie" is precisely the
    # game still being level after 9 — i.e. it goes to extra innings. Reported
    # as its own outcome rather than folded into either side's win probability,
    # since the model doesn't simulate what happens in extras.
    extras = float(np.mean(hr == ar))

    # Most likely finals, by how often the sim landed on each exact score.
    pairs, counts = np.unique(np.stack([ar, hr], axis=1), axis=0, return_counts=True)
    order = np.argsort(-counts)[:5]
    likely = [{"away": int(pairs[i][0]), "home": int(pairs[i][1]),
               "pct": round(float(counts[i]) / len(hr) * 100, 1)} for i in order]

    payload = {
        "game_id": game_id, "live": True, "home": home, "away": away, "n": int(result.n),
        "state": {
            "inning": state.inning,
            "half": state.half,
            "outs": state.outs,
            "on_first": bool(state.runners_bitmap & 1),
            "on_second": bool(state.runners_bitmap & 2),
            "on_third": bool(state.runners_bitmap & 4),
            "home_score": int(state.score[home]),
            "away_score": int(state.score[away]),
            "batter": linescore.situation.batter,
            "pitcher": linescore.situation.pitcher,
            "home_due_up_slot": state.batting_position[home] + 1,
            "away_due_up_slot": state.batting_position[away] + 1,
        },
        "home_win_probability": round(home_win, 4),
        "away_win_probability": round(away_win, 4),
        "extras_probability": round(extras, 4),
        "projected_final": {
            "home_mean": round(result.home_run_mean, 2),
            "home_median": result.home_run_median,
            "home_p10": result.home_run_p10, "home_p90": result.home_run_p90,
            "away_mean": round(result.away_run_mean, 2),
            "away_median": result.away_run_median,
            "away_p10": result.away_run_p10, "away_p90": result.away_run_p90,
            "total_mean": round(result.total_mean, 2),
            "total_median": result.total_median,
        },
        "runs_to_come": {
            "home": round(result.home_run_mean - state.score[home], 2),
            "away": round(result.away_run_mean - state.score[away], 2),
        },
        "likely_finals": likely,
    }
    lines = _attach_names(repo, [dict(pl) for pl in result.player_lines], CURRENT_SEASON)
    home_lineup, away_lineup = resolve_lineups(game_id, repo, home, away)
    payload["player_lines"] = _attach_lineup_slots(lines, home_lineup, away_lineup)
    payload["pitcher_lines"] = _attach_pitcher_names(
        repo, [dict(pl) for pl in result.pitcher_lines], CURRENT_SEASON)
    return payload


# ── Post-game accuracy (simulation vs. what actually happened) ──────────────

def _actual_result(repo: SQLiteRepository, game_id: str) -> Optional[dict]:
    """The real final line + box score for a *finished* game, or None.

    Live-refreshes the schedule first so a just-completed game reads as Final.
    Returns {home_runs, away_runs, status, boxscore} where boxscore is the
    parsed MLB box score (or None if that fetch fails — the overall run/winner
    comparison still works without it).
    """
    game_date = _date_from_game_id(game_id)
    if game_date is None:
        return None
    try:
        from ..data.sources.schedules import MLBScheduleSource
        MLBScheduleSource(repo).fetch_schedule(game_date)
    except Exception:
        pass  # fall back to whatever is stored
    row = next((g for g in repo.get_schedule(game_date) if g.game_id == game_id), None)
    if row is None or row.game_pk is None:
        return None
    is_final = "final" in (row.status or "").lower()
    if not is_final or row.home_score is None or row.away_score is None:
        return None
    box = None
    try:
        from ..data.sources.boxscore import MLBBoxscoreSource
        box = MLBBoxscoreSource().fetch_boxscore(row.game_pk, game_id)
    except Exception:
        box = None
    return {
        "home_runs": int(row.home_score),
        "away_runs": int(row.away_score),
        "status": row.status,
        "boxscore": box,
    }


def _dist_accuracy(actual: float, arr) -> dict:
    """Where the real value landed inside the simulated distribution, as
    percentages: its percentile, how central (accurate) that is, and the
    over/under/exact split of sims around it."""
    arr = np.asarray(arr)
    if arr.size == 0:
        return {}
    below = float(np.mean(arr < actual))
    equal = float(np.mean(arr == actual))
    above = float(np.mean(arr > actual))
    percentile = (below + equal / 2) * 100  # mid-rank placement of reality
    # 100% when reality sat at the model's median, falling to 0% at the tails —
    # an intuitive "how well did the forecast centre on what happened" score.
    centrality = 100 * (1 - 2 * abs(percentile / 100 - 0.5))
    return {
        "percentile": round(percentile, 1),
        "centrality_pct": round(centrality, 1),
        "hit_pct": round(equal * 100, 1),
        "over_pct": round(above * 100, 1),
        "under_pct": round(below * 100, 1),
    }


def _range_cmp(actual: float, mean: float, median: float,
               p10: float, p90: float, arr=None) -> dict:
    d = {
        "actual": actual, "mean": round(mean, 2), "median": median,
        "p10": p10, "p90": p90, "within_range": p10 <= actual <= p90,
        "error": round(actual - mean, 2),
    }
    if arr is not None:
        d.update(_dist_accuracy(actual, arr))
    return d


def _box_batter_index(box, side: str) -> dict[int, dict]:
    """{player_id: actual batting line} for one side of a parsed box score."""
    team = getattr(box, side)
    out: dict[int, dict] = {}
    for b in team.batters:
        if b.player_id is not None:
            out[int(b.player_id)] = dataclasses.asdict(b)
    return out


def _ip_to_outs(ip: Optional[str]) -> Optional[float]:
    """MLB innings-pitched string ('6.2' = 6⅓... actually 6 and 2 outs) → outs."""
    if ip is None:
        return None
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole or 0) * 3 + int(frac or 0)
    except (ValueError, TypeError):
        return None


def _box_pitcher_index(box, side: str) -> dict[int, dict]:
    team = getattr(box, side)
    out: dict[int, dict] = {}
    for p in team.pitchers:
        if p.player_id is not None:
            out[int(p.player_id)] = dataclasses.asdict(p)
    return out


@app.get("/api/game/{game_id}/accuracy")
def game_accuracy(game_id: str, n: int = Query(2000, ge=200, le=20000)) -> dict:
    """How well the simulation matched what actually happened — Final games only.

    Two comparisons:
      * prediction: the base (unconditioned) sim's win probability and run
        distribution vs. the real final — did it pick the winner, did the real
        score land inside the projected range, and how often the sim produced
        this exact final (`exact_score_prob`).
      * score_match: a run conditioned on the *actual* final score, so the only
        games kept are the ones that ended exactly as reality did. Their averaged
        player lines are compared to the real box score — i.e. of the sims that
        got the score right, how right did they get the box score.

    Returns {"final": false} for a game that hasn't finished (nothing to score).
    """
    repo = get_repo()
    home, away = _teams_from_game_id(game_id)
    actual = _actual_result(repo, game_id)
    if actual is None:
        return {"game_id": game_id, "final": False}

    _ensure_lineups(repo, game_id, home, away, CURRENT_SEASON)
    a_home = actual["home_runs"]
    a_away = actual["away_runs"]

    # Base (unconditioned) simulation → the honest pre-game prediction.
    result, raw = simulate_matchup(
        game_id, repo, home_team=home, away_team=away, n=n,
        season=CURRENT_SEASON, park_season=PARK_SEASON,
    )
    exact = float(np.mean((raw.home_runs == a_home) & (raw.away_runs == a_away)))
    actual_winner = "home" if a_home > a_away else "away" if a_away > a_home else "tie"
    pred_winner = "home" if result.home_win_probability >= 0.5 else "away"
    winner_prob = (result.home_win_probability if actual_winner == "home"
                   else 1.0 - result.home_win_probability)

    a_total = a_home + a_away
    a_spread = a_home - a_away
    spread_arr = raw.home_runs.astype(np.int64) - raw.away_runs.astype(np.int64)
    home_cmp = _range_cmp(a_home, result.home_run_mean, result.home_run_median,
                          result.home_run_p10, result.home_run_p90, raw.home_runs)
    away_cmp = _range_cmp(a_away, result.away_run_mean, result.away_run_median,
                          result.away_run_p10, result.away_run_p90, raw.away_runs)
    total_cmp = _range_cmp(a_total, result.total_mean, result.total_median,
                           result.total_p10, result.total_p90, raw.totals)
    spread_cmp = _range_cmp(a_spread, result.spread_mean, float(np.median(spread_arr)),
                            float(np.percentile(spread_arr, 10)),
                            float(np.percentile(spread_arr, 90)), spread_arr)

    prediction = {
        "n": result.n,
        "home_win_probability": round(result.home_win_probability, 4),
        "predicted_winner": pred_winner,
        "actual_winner": actual_winner,
        "picked_winner": pred_winner == actual_winner if actual_winner != "tie" else None,
        "winner_prob": round(winner_prob, 4),
        "home_runs": home_cmp,
        "away_runs": away_cmp,
        "total": total_cmp,
        "spread": spread_cmp,
        "spread_mean": round(result.spread_mean, 2),
        "actual_spread": a_spread,
        "exact_score_prob": round(exact, 4),
        # Headline "how accurate was the forecast" percentages, one per market:
        #   winner  — the win probability the model gave the team that won
        #   others  — how centrally reality sat in the simulated distribution
        "accuracy_pct": {
            "winner": round(winner_prob * 100, 1),
            "total": total_cmp.get("centrality_pct", 0.0),
            "spread": spread_cmp.get("centrality_pct", 0.0),
            "home_runs": home_cmp.get("centrality_pct", 0.0),
            "away_runs": away_cmp.get("centrality_pct", 0.0),
        },
    }

    # Conditioned on the real final: keep only the sims that ended this exact
    # score, then compare their averaged box score to reality.
    score_match: Optional[dict] = None
    try:
        cond_result, _cond_raw, meta = simulate_matchup_conditioned(
            game_id, target_away=a_away, target_home=a_home, repo=repo,
            home_team=home, away_team=away, season=CURRENT_SEASON, park_season=PARK_SEASON,
        )
    except Exception:
        cond_result, meta = None, None
    if cond_result is not None and meta is not None and meta.get("matches", 0) > 0:
        lines = _attach_names(repo, [dict(pl) for pl in cond_result.player_lines], CURRENT_SEASON)
        home_lineup, away_lineup = resolve_lineups(game_id, repo, home, away)
        lines = _attach_lineup_slots(lines, home_lineup, away_lineup)
        # The base (unconditioned) projection, to contrast each hitter's overall
        # forecast against how he did in just the reality-matching sims.
        base_by_id = {int(pl["player_id"]): pl for pl in result.player_lines}
        box = actual["boxscore"]
        bat_home = _box_batter_index(box, "home") if box else {}
        bat_away = _box_batter_index(box, "away") if box else {}
        batters = []
        # Accumulators for aggregate accuracy percentages.
        errs = {"hits": [], "home_runs": [], "rbi": []}      # |match_proj - actual|
        act_sum = {"hits": 0.0, "home_runs": 0.0, "rbi": 0.0}
        shift = {"hits": [], "home_runs": [], "rbi": []}     # |base_proj - match_proj|
        match_sum = {"hits": 0.0, "home_runs": 0.0, "rbi": 0.0}
        for pl in lines:
            pid = int(pl["player_id"])
            real = (bat_home if pl["team"] == home else bat_away).get(pid)
            base = base_by_id.get(pid)
            row = {
                "player_id": pid, "name": pl.get("name", str(pid)),
                "team": pl["team"], "lineup_slot": pl.get("lineup_slot"),
                # base = overall prediction; proj = averaged over score-matching sims
                "base_hits": round(base["hits"], 2) if base else None,
                "base_home_runs": round(base["home_runs"], 2) if base else None,
                "base_rbi": round(base["rbi"], 2) if base else None,
                "proj_hits": round(pl["hits"], 2), "proj_home_runs": round(pl["home_runs"], 2),
                "proj_rbi": round(pl["rbi"], 2),
                "actual_hits": None, "actual_home_runs": None, "actual_rbi": None,
            }
            for stat in ("hits", "home_runs", "rbi"):
                match_sum[stat] += pl[stat]
                if base is not None:
                    shift[stat].append(abs(base[stat] - pl[stat]))
            if real is not None:
                row["actual_hits"] = real.get("hits")
                row["actual_home_runs"] = real.get("home_runs")
                row["actual_rbi"] = real.get("rbi")
                for stat in ("hits", "home_runs", "rbi"):
                    av = real.get(stat)
                    if av is not None:
                        errs[stat].append(abs(pl[stat] - av))
                        act_sum[stat] += av
            batters.append(row)
        batters.sort(key=lambda r: (r["lineup_slot"] is None, r["lineup_slot"] or 99))
        mae = {k: round(sum(v) / len(v), 2) for k, v in errs.items() if v}

        def _acc_pct(err_list, denom_total):
            # 100% when the summed miss is zero; scales the miss against the size
            # of what actually happened so HR (small counts) aren't overstated.
            if not err_list:
                return None
            base = max(denom_total, len(err_list))  # avoid div-by-0 / over-credit
            return round(max(0.0, 100.0 * (1.0 - sum(err_list) / base)), 1)

        batter_accuracy_pct = {
            k: _acc_pct(errs[k], act_sum[k]) for k in ("hits", "home_runs", "rbi")
            if errs[k]
        }
        base_vs_match_pct = {
            k: _acc_pct(shift[k], match_sum[k]) for k in ("hits", "home_runs", "rbi")
            if shift[k]
        }
        score_match = {
            "target_home": a_home, "target_away": a_away,
            "matches": meta["matches"], "games_run": meta["games_run"],
            "match_rate": round(meta["matches"] / meta["games_run"], 4) if meta["games_run"] else 0.0,
            "batters": batters,
            "batter_mae": mae,
            # % accuracy of the score-matched box score vs. the real one, per stat
            "batter_accuracy_pct": batter_accuracy_pct,
            # % agreement between the overall prediction and the score-matched
            # sims (how much conditioning on the real final moved each line)
            "base_vs_match_pct": base_vs_match_pct,
            "has_boxscore": box is not None,
        }

    return {
        "game_id": game_id, "final": True,
        "home": home, "away": away,
        "actual": {"home_runs": a_home, "away_runs": a_away,
                   "total": a_home + a_away, "winner": actual_winner,
                   "status": actual["status"]},
        "prediction": prediction,
        "score_match": score_match,
    }


# ── Rolling accuracy report (simulation vs. reality, across the slate) ──────

# How far back the rolling report *reads*. This is a display window over
# scorecards already on disk, so it costs an aggregation, not a simulation.
ACCURACY_WINDOW_DAYS = 5

# How far back a refresh *looks* for something to grade. Games already in the
# record are skipped by id, so this is a search span rather than an amount of
# work: on a healthy record the only ungraded night in it is the previous one.
# A one-day span would grade last night and never look behind it, which turns
# any missed run into a permanent hole — as one did, on 2026-08-01.
ACCURACY_GRADE_DAYS = 7


def _accuracy_end_date(raw: Optional[str]) -> date:
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
    return date.today()


@app.get("/api/accuracy/report")
def accuracy_report(
    date: Optional[str] = Query(None, description="Window end date YYYY-MM-DD; defaults to today"),
    days: int = Query(ACCURACY_WINDOW_DAYS, ge=1, le=60,
                      description="How many days of graded games the report reads"),
    refresh: bool = Query(False, description="Score any finished games not yet scored"),
    grade_days: int = Query(ACCURACY_GRADE_DAYS, ge=1, le=60,
                            description="How many days back a refresh grades"),
    n: int = Query(1500, ge=200, le=5000, description="Sims per game when scoring"),
    limit: int = Query(30, ge=1, le=200, description="Max games to score in one call"),
) -> dict:
    """How close the simulations came to what actually happened.

    Served from stored per-game scorecards, so a page load is an aggregation
    rather than a slate of Monte Carlo. `refresh=true` grades any finished game
    that hasn't been graded yet — the nightly job's business, capped by `limit`
    so a backlog gets worked through over several runs instead of timing out on
    one.

    Reading and grading take separate windows on purpose, and they mean
    different things. `days` is how much of the record to aggregate. `grade_days`
    is how far back to *look* for an ungraded game — a search span, not an
    amount of work, since anything already graded is skipped by id. On a healthy
    record the only ungraded night inside it is the previous one.
    """
    from ..accuracy import load_report, refresh_window

    repo = get_repo()
    end = _accuracy_end_date(date)
    refreshed = None
    if refresh:
        refreshed = refresh_window(
            repo, end=end, days=grade_days, season=CURRENT_SEASON,
            park_season=PARK_SEASON, n=n, limit=limit,
            name_lookup=lambda ids: _name_map(repo, ids, CURRENT_SEASON))
    report = load_report(repo, end=end, days=days)
    report["refreshed"] = refreshed
    return report


@app.get("/api/trends")
def trends_report(
    days: int = Query(60, ge=7, le=365,
                      description="How much of the record informs the forecasts"),
) -> dict:
    """What baseball has been doing lately, and where it should land next week.

    This week is read straight off the finished box scores. Next week comes out
    of the committed forecast record rather than being recomputed here, because
    a forecast is only worth grading if it was written down before its window
    opened — the scheduled job issues them, this only reports them.
    """
    from datetime import timedelta

    from ..drift import build_drift_report
    from ..trends import report

    repo = get_repo()
    end = date.today()
    games = repo.get_accuracy_games(end - timedelta(days=days), end)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "record_games": len(games),
        **report(games, asof=end),
        "drift": build_drift_report(games),
    }


class ChatRequest(BaseModel):
    """One turn of conversation. The client resends the history each time —
    the server holds no session, so a reload starts clean and nothing about a
    conversation outlives the tab it happened in."""
    messages: list[dict] = Field(default_factory=list)


@app.get("/api/chat/status")
def chat_status() -> dict:
    """Whether the chat panel should render at all.

    The homepage asks before drawing anything, so an unconfigured deployment
    shows no chat rather than a box that errors when you type in it.
    """
    from ..chat import MODEL, available, key_looks_wrong
    from ..slate import status as slate_progress

    ok = available()
    # The assistant answers from the slate's simulations. Until those exist it
    # has nothing to read, and asking anyway would put it back to simulating
    # games one at a time — which is exactly what it is here to avoid. So the
    # panel knows to wait rather than discovering it the slow way.
    progress = slate_progress(datetime.utcnow().date())
    return {
        "available": ok,
        "model": MODEL if ok else None,
        # A key can be present and still be rejected. This is a shape check
        # only — confirming a key really works costs a live API call, and
        # billing the owner to render a panel is not a trade worth making.
        "key_suspect": key_looks_wrong(),
        "slate_ready": progress is None or not progress.running,
        "slate": progress.as_dict() if progress is not None else None,
    }


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Talk to Claude about the simulations, streamed back as it is written.

    Server-sent events rather than a single JSON reply: a question that needs a
    simulation can take a few seconds, and watching the answer arrive — with a
    note of which lookup is running — is the difference between a conversation
    and a spinner.
    """
    from ..chat import MAX_CHARS, available, rate_limited, stream_reply

    if not available():
        raise HTTPException(
            status_code=503,
            detail="Chat is not configured: set ANTHROPIC_API_KEY on the Space.")

    msgs = [m for m in req.messages
            if m.get("role") in ("user", "assistant") and m.get("content")]
    if not msgs or msgs[-1].get("role") != "user":
        raise HTTPException(status_code=422, detail="Last message must be from the user.")
    for m in msgs:
        if isinstance(m.get("content"), str) and len(m["content"]) > MAX_CHARS:
            raise HTTPException(status_code=422, detail="Message is too long.")

    who = (request.client.host if request.client else "anon")
    if rate_limited(who):
        raise HTTPException(status_code=429,
                            detail="Too many messages just now — give it a minute.")

    # Everything the assistant knows about tonight it reads from the slate's
    # simulations. Answering before they exist means it either has nothing or
    # goes and runs games itself, one at a time, which is what it is here to
    # avoid. The panel disables its input on the same signal; this is the
    # server-side half, since the panel can be stale by a poll interval.
    from ..slate import status as slate_progress
    progress = slate_progress(datetime.utcnow().date())
    if progress is not None and progress.running:
        raise HTTPException(
            status_code=409,
            detail=(f"Simulating tonight's slate — {progress.done} of "
                    f"{progress.total} games. The assistant answers from those "
                    f"simulations, so it opens when they finish."))

    repo = get_repo()

    def events():
        try:
            for event in stream_reply(msgs, repo, CURRENT_SEASON):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            # The stream has already started, so a raised exception would just
            # truncate silently. Send the failure as an event the panel renders.
            yield ("data: " + json.dumps(
                {"type": "error", "message": f"{type(exc).__name__}: {exc}"})
                + "\n\n")

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/accuracy/game/{game_id}")
def accuracy_game_detail(game_id: str) -> dict:
    """One game's full scorecard — every player, projected against actual."""
    from ..accuracy import score_and_store

    repo = get_repo()
    stored = repo.get_accuracy_game(game_id)
    if stored is not None:
        return stored
    scored = score_and_store(
        repo, game_id, season=CURRENT_SEASON, park_season=PARK_SEASON,
        name_lookup=lambda ids: _name_map(repo, ids, CURRENT_SEASON))
    if scored is None:
        raise HTTPException(404, "game is not finished, or has no box score yet")
    return scored


# ── Best bets (player props vs. our simulation) ─────────────────────────────

@app.get("/api/best-bets")
def best_bets(
    date: Optional[str] = Query(None, description="Slate date YYYY-MM-DD; defaults to today"),
    refresh: bool = Query(False, description="Also discard this slate's cached simulations"),
    n: int = Query(2000, ge=200, le=4000),
    live: bool = Query(True, description="Include games already in progress"),
) -> dict:
    """Markets where our simulation disagrees with the posted price, best first.

    Rebuilt on every request: prices move, lineups get confirmed and live games
    change by the inning, so a cached ranking goes wrong quietly. What makes
    that affordable is that the expensive half — the simulations — is shared
    with the matchup cards through the sim cache, so a rebuild normally costs
    a props fetch and some arithmetic rather than a fresh slate of Monte Carlo.

    Plays come back tagged with a `category` (game_line, pitcher_prop,
    batter_prop, live) and capped per category, so no one family can crowd the
    others out of the panel.
    """
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=422, detail=f"invalid date: {date!r}")
    else:
        day = datetime.utcnow().date()

    repo = get_repo()
    # Re-check the schedule so a slate added or moved today is included, and so
    # a game that has since started is seen as live rather than as pregame.
    try:
        from ..data.sources.schedules import MLBScheduleSource
        MLBScheduleSource(repo).fetch_schedule(day)
    except Exception:
        pass

    from ..slate import ensure as warm_slate, reset as reset_slate, wait as wait_slate

    if refresh:
        # A re-run has to genuinely re-run: drop this slate's cached
        # simulations so the rebuild reflects confirmed lineups and current
        # game state rather than replaying what was simulated earlier. The
        # warm-up state goes with them — a slate marked ready with nothing
        # behind it would let every reader straight through to an empty cache.
        from ..simcache import clear as clear_sims
        try:
            clear_sims({g.game_id for g in repo.get_schedule(day)})
        except Exception:
            pass
        reset_slate(day)

    # The simulations come first, always. This used to race them and simulate
    # games itself; then it waited but built anyway when the wait ran out, which
    # meant a slow slate produced a ranking over whatever half of it happened to
    # be done. Ranking by edge across a partial slate is not a smaller answer,
    # it's a wrong one — the plays it can see are ranked against each other and
    # the ones it can't are silently absent.
    warm_slate(repo, day, season=CURRENT_SEASON, park_season=PARK_SEASON)
    progress = wait_slate(day, timeout=BEST_BETS_WAIT_SECONDS)

    if progress is not None and progress.running:
        # Still going. Say so and let the caller come back rather than pricing
        # a fraction of the slate.
        return {"date": day.isoformat(), "ready": False,
                "slate": progress.as_dict(), "bets": [], "notes": [
                    f"Simulating the slate — {progress.done} of "
                    f"{progress.total} games. Ranked plays are built from "
                    f"those simulations, so they wait for all of them."],
                "games_considered": progress.total, "games_priced": 0,
                "props_available": False,
                "generated_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds")}

    from ..betting.best_bets import build_best_bets
    report = build_best_bets(repo, day, n=n, season=CURRENT_SEASON,
                             park_season=PARK_SEASON, live=live)
    payload = dataclasses.asdict(report)
    payload["cached"] = False
    payload["ready"] = True
    if progress is not None:
        payload["slate"] = progress.as_dict()
        if progress.failed:
            # Built over what did simulate — but a game missing from the ranking
            # because it never ran must not look like a game with no edge in it.
            payload.setdefault("notes", []).append(
                f"{len(progress.failed)} game(s) could not be simulated and are "
                f"not represented here: {', '.join(progress.failed)}")
    return payload


@app.get("/api/props-probe")
def props_probe(sport: str = Query("mlb")) -> dict:
    """What the props feed actually returns, verbatim-ish.

    Sleeper's `/lines/available` is public but undocumented and unreachable
    from the machine this parser was written on, so the field names it reads
    are informed guesses. This reports reachability, how many lines came back
    and the keys present on a sample, so the parser can be corrected against
    the real response instead of guessed at twice.
    """
    from ..data.sources.sleeper import SleeperPropsSource

    src = SleeperPropsSource()
    out = src.probe(sport)
    try:
        parsed = src.fetch_props(sport)
    except Exception as e:
        out["parse_error"] = f"{type(e).__name__}: {e}"[:200]
        return out
    out["parsed"] = len(parsed)
    out["parsed_sample"] = [dataclasses.asdict(p) for p in parsed[:5]]
    return out


@app.get("/api/team-lines-probe")
def team_lines_probe(sport: str = Query("mlb")) -> dict:
    """Where Sleeper's team markets live — moneyline, spread, total.

    The props endpoint we use returns only player over/unders, so the team
    picks come from somewhere else. This tries the plausible variations and
    reports what each answered, so the parser is written against a response
    that exists rather than a guessed URL.
    """
    from ..data.sources.sleeper import SleeperPropsSource

    return SleeperPropsSource().discover_picks_api(sport)


# ── Players & teams (statline browser + team aggregates) ────────────────────

def _batter_row(b) -> dict:
    return {
        "player_id": b.player_id, "name": b.name or str(b.player_id),
        "season": b.season, "team": b.team_id, "hand": b.hand, "pa": b.pa,
        "woba": b.woba, "xwoba": b.xwoba, "iso": b.iso, "babip": b.babip,
        "hr_rate": b.hr_rate, "k_rate": b.k_rate, "bb_rate": b.bb_rate,
        "single_rate": b.single_rate, "double_rate": b.double_rate,
        "triple_rate": b.triple_rate, "hbp_rate": b.hbp_rate,
        "ipo_rate": b.ipo_rate, "platoon_split": b.platoon_split,
        "sprint_speed_ft_s": getattr(b, "sprint_speed_ft_s", None),
    }


def _pitcher_row(p) -> dict:
    from ..data.sources.fangraphs import compute_fip
    return {
        "player_id": p.player_id, "name": p.name or str(p.player_id),
        "season": p.season, "team": p.team_id, "hand": p.hand, "role": p.role,
        "bf": p.bf, "fip": p.xfip if p.xfip > 0 else compute_fip(p),
        "hr_allowed": p.hr_allowed, "k_rate": p.k_rate, "bb_allowed": p.bb_allowed,
        "single_allowed": p.single_allowed, "double_allowed": p.double_allowed,
        "triple_allowed": p.triple_allowed, "hbp_allowed": p.hbp_allowed,
        "ipo_rate": p.ipo_rate, "platoon_split": p.platoon_split,
    }


def _roster_team_map(repo: SQLiteRepository, season: int) -> dict[int, str]:
    """player_id → team abbr, derived from the stored per-team rosters."""
    from ..data.ingest import ROSTER_GAME_ID
    out: dict[int, str] = {}
    for c in repo.get_lineups_for_game(f"{ROSTER_GAME_ID}-{season}"):
        for pid in c.batting_order:
            out[pid] = c.team_id
    return out


@app.get("/api/players")
def players(
    season: int = Query(CURRENT_SEASON),
    kind: str = Query("batters", pattern="^(batters|pitchers)$"),
) -> list[dict]:
    """All stored statlines for a season (bullpen aggregates excluded)."""
    repo = get_repo()
    team_of = _roster_team_map(repo, season)
    if kind == "batters":
        rows = [_batter_row(b) for b in repo.get_batters_for_season(season)
                if b.player_id > 0]
    else:
        rows = [_pitcher_row(p) for p in repo.get_pitchers_for_season(season)
                if p.player_id > 0]
    for r in rows:
        r["team"] = r["team"] or team_of.get(r["player_id"], "")
    return rows


@app.get("/api/player/{player_id}")
def player_detail(player_id: int) -> dict:
    """Every stored season for one player, batting and pitching."""
    repo = get_repo()
    batting: list[dict] = []
    pitching: list[dict] = []
    for season in range(2020, CURRENT_SEASON + 1):
        b = repo.get_batter(player_id, season)
        if b is not None:
            batting.append(_batter_row(b))
        p = repo.get_pitcher(player_id, season)
        if p is not None:
            pitching.append(_pitcher_row(p))
    if not batting and not pitching:
        raise HTTPException(status_code=404, detail=f"no statlines for player {player_id}")
    name = (batting or pitching)[-1]["name"]
    return {"player_id": player_id, "name": name,
            "batting": batting, "pitching": pitching}


@app.get("/api/player/{player_id}/gamelog")
def player_gamelog(
    player_id: int,
    season: int = Query(CURRENT_SEASON),
    group: str = Query("hitting", pattern="^(hitting|pitching)$"),
) -> dict:
    """Per-game season log (live entries flagged). Empty list if unavailable —
    never raises, so the player page degrades gracefully."""
    from ..data.sources.player_gamelog import MLBGameLogSource
    try:
        entries = MLBGameLogSource().fetch_game_log(player_id, season, group)
    except Exception:
        entries = []
    return {
        "player_id": player_id, "season": season, "group": group,
        "games": [dataclasses.asdict(e) for e in entries],
    }


def _team_aggregate(repo: SQLiteRepository, team: str, season: int) -> Optional[dict]:
    """PA-weighted lineup rates + bullpen quality + park factor for one team."""
    from ..data.ingest import ROSTER_GAME_ID, team_bullpen_pid
    from ..data.sources.fangraphs import compute_fip

    roster = repo.get_lineup(f"{ROSTER_GAME_ID}-{season}", team)
    if roster is None or not roster.batting_order:
        return None
    batters = [b for b in (repo.get_batter(pid, season) for pid in roster.batting_order)
               if b is not None]
    if not batters:
        return None

    total_pa = sum(b.pa for b in batters)
    def wavg(attr: str) -> float:
        return sum(getattr(b, attr) * b.pa for b in batters) / total_pa

    speeds = [b.sprint_speed_ft_s for b in batters
              if getattr(b, "sprint_speed_ft_s", None) is not None]
    pen = repo.get_pitcher(team_bullpen_pid(team), season)
    pf = repo.get_park_factor(team, PARK_SEASON)

    return {
        "team": team,
        "lineup_woba": wavg("woba"), "lineup_xwoba": wavg("xwoba"),
        "lineup_iso": wavg("iso"), "lineup_k_rate": wavg("k_rate"),
        "lineup_bb_rate": wavg("bb_rate"), "lineup_hr_rate": wavg("hr_rate"),
        "sprint_speed": sum(speeds) / len(speeds) if speeds else None,
        "bullpen_fip": (pen.xfip if pen.xfip > 0 else compute_fip(pen)) if pen else None,
        "bullpen_k_rate": pen.k_rate if pen else None,
        "park_runs_factor": pf.runs_factor if pf else None,
        "roster": [_batter_row(b) for b in batters],
    }


@app.get("/api/teams")
def teams(season: int = Query(CURRENT_SEASON)) -> list[str]:
    """Team abbreviations that have a stored roster for `season`."""
    from ..data.ingest import ROSTER_GAME_ID
    cards = get_repo().get_lineups_for_game(f"{ROSTER_GAME_ID}-{season}")
    return [c.team_id for c in cards]


@app.get("/api/team/{abbr}")
def team_detail(abbr: str, season: int = Query(CURRENT_SEASON)) -> dict:
    agg = _team_aggregate(get_repo(), abbr.upper(), season)
    if agg is None:
        raise HTTPException(status_code=404, detail=f"no roster stored for {abbr}")
    return agg


@app.get("/api/teamstats")
def teamstats(season: int = Query(CURRENT_SEASON)) -> list[dict]:
    """Aggregates for every team (roster list omitted) with league-wide ranks.

    Rank 1 = best: highest wOBA/ISO/BB%/speed, lowest lineup K%, lowest
    bullpen FIP. Used by the matchup preview comparison and the teams page.
    """
    from ..data.ingest import ROSTER_GAME_ID
    repo = get_repo()
    cards = repo.get_lineups_for_game(f"{ROSTER_GAME_ID}-{season}")
    aggs = []
    for c in cards:
        a = _team_aggregate(repo, c.team_id, season)
        if a is not None:
            a.pop("roster", None)
            aggs.append(a)

    higher_better = ["lineup_woba", "lineup_xwoba", "lineup_iso",
                     "lineup_bb_rate", "lineup_hr_rate", "sprint_speed"]
    lower_better = ["lineup_k_rate", "bullpen_fip"]
    for key in higher_better + lower_better:
        vals = [(a[key], a["team"]) for a in aggs if a[key] is not None]
        vals.sort(reverse=key in higher_better)
        ranks = {team: i + 1 for i, (_, team) in enumerate(vals)}
        for a in aggs:
            a[f"{key}_rank"] = ranks.get(a["team"])
    return aggs


# ── SPA hosting (mounted last so /api/* always wins) ──────────────────────────

if (_WEB_DIR / "index.html").exists():
    # Built asset bundle (hashed JS/CSS) lives under /_app.
    if (_WEB_DIR / "_app").exists():
        app.mount("/_app", StaticFiles(directory=_WEB_DIR / "_app"), name="assets")

    # index.html must never be cached: it references hashed JS/CSS bundles that
    # change every deploy, so a stale cached shell would point at 404'd bundles
    # and render blank. The hashed assets themselves are safe to cache forever.
    _NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

    def _index() -> FileResponse:
        return FileResponse(_WEB_DIR / "index.html", headers=_NO_CACHE)

    @app.get("/")
    def _spa_root() -> FileResponse:
        return _index()

    @app.get("/{path:path}")
    def _spa_catch_all(path: str) -> FileResponse:
        """Serve a real static file if present, else the SPA shell (client routing)."""
        candidate = _WEB_DIR / path
        if candidate.is_file():
            return FileResponse(candidate)
        return _index()
