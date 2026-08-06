"""thebeast CLI — Click command group exposing the full pipeline (F-005).

Commands:
    thebeast fetch    --date YYYY-MM-DD          # F-001: fetch + store data
    thebeast simulate --game-id ID [--n INT]     # F-002+F-003: run simulation
    thebeast bet      --game-id ID [--kelly F]   # F-004: edge + stake sizing
    thebeast run      --date YYYY-MM-DD          # full pipeline for all games

Every command supports `--json` for machine output (human tables by default),
writes errors to stderr, and exits non-zero on any runtime failure.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date, datetime

import click

from ..betting.edge import analyze_moneyline, analyze_totals
from ..betting.odds import MarketOdds
from ..data.repository import SQLiteRepository
from ..pipeline import simulate_matchup


def _repo(ctx: click.Context) -> SQLiteRepository:
    return ctx.obj["repo"]


def _emit(payload: dict | list, human: str, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        click.echo(human)


@click.group()
@click.option("--db", default=None, help="SQLite path (default: $THEBEAST_DB_PATH).")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of tables.")
@click.pass_context
def cli(ctx: click.Context, db: str | None, as_json: bool) -> None:
    """Diamond Analytics Predictor — MLB game simulation & betting edges."""
    ctx.ensure_object(dict)
    ctx.obj["repo"] = SQLiteRepository(db)
    ctx.obj["json"] = as_json


@cli.command()
@click.option("--date", "game_date", required=True, help="Slate date YYYY-MM-DD.")
@click.pass_context
def fetch(ctx: click.Context, game_date: str) -> None:
    """Fetch and store schedule + lineups for a date (F-001)."""
    try:
        d = datetime.strptime(game_date, "%Y-%m-%d").date()
    except ValueError as exc:
        click.echo(f"error: invalid date {game_date!r}: {exc}", err=True)
        raise SystemExit(2)
    try:
        from ..data.sources.schedules import MLBScheduleSource
        source = MLBScheduleSource(_repo(ctx))
        games = source.fetch_schedule(d)
    except Exception as exc:  # network / parse failure
        click.echo(f"error: fetch failed: {exc}", err=True)
        raise SystemExit(1)
    payload = [dataclasses.asdict(g) for g in games]
    _emit(payload, f"Fetched {len(games)} games for {game_date}", ctx.obj["json"])


@cli.command()
@click.option("--game-id", required=True)
@click.option("--n", default=5000, help="Monte Carlo iterations.")
@click.option("--seed", default=None, type=int)
@click.option("--season", default=2024)
@click.pass_context
def simulate(ctx: click.Context, game_id: str, n: int, seed: int | None, season: int) -> None:
    """Run a Monte Carlo simulation for one game (F-002+F-003)."""
    try:
        result, _ = simulate_matchup(game_id, _repo(ctx), n=n, seed=seed, season=season)
    except Exception as exc:
        click.echo(f"error: simulation failed: {exc}", err=True)
        raise SystemExit(1)
    payload = dataclasses.asdict(result)
    human = (
        f"{result.away} @ {result.home}  ({result.n} sims)\n"
        f"  home win prob : {result.home_win_probability:.3f}\n"
        f"  proj score    : {result.home_run_mean:.2f} - {result.away_run_mean:.2f}\n"
        f"  total (mean)  : {result.total_mean:.2f}\n"
        f"  extra innings : {result.extra_inning_pct:.1%}"
    )
    _emit(payload, human, ctx.obj["json"])


@cli.command()
@click.option("--game-id", required=True)
@click.option("--home-ml", type=int, required=True)
@click.option("--away-ml", type=int, required=True)
@click.option("--total-line", type=float, default=8.5)
@click.option("--over-ml", type=int, default=-110)
@click.option("--under-ml", type=int, default=-110)
@click.option("--kelly", default=0.25, help="Kelly fraction (0.25 quarter, 0.5 half).")
@click.option("--n", default=5000)
@click.option("--seed", default=None, type=int)
@click.pass_context
def bet(
    ctx: click.Context, game_id: str, home_ml: int, away_ml: int,
    total_line: float, over_ml: int, under_ml: int, kelly: float,
    n: int, seed: int | None,
) -> None:
    """Simulate then size moneyline + totals edges (F-004)."""
    try:
        result, raw = simulate_matchup(game_id, _repo(ctx), n=n, seed=seed)
        odds = MarketOdds(game_id=game_id, home_ml=home_ml, away_ml=away_ml,
                          total_line=total_line, over_ml=over_ml, under_ml=under_ml)
        edges = analyze_moneyline(result, odds, kelly) + analyze_totals(raw, odds, kelly)
    except Exception as exc:
        click.echo(f"error: bet analysis failed: {exc}", err=True)
        raise SystemExit(1)
    payload = [dataclasses.asdict(e) for e in edges]
    lines = [f"{game_id}  (Kelly {kelly})"]
    for e in edges:
        flag = "BET" if e.recommended_stake_pct > 0 else "—"
        lines.append(
            f"  {e.market:<8} model={e.model_probability:.3f} "
            f"impl={e.implied_probability:.3f} edge={e.edge:+.3f} "
            f"stake={e.recommended_stake_pct:.3%} {flag}"
        )
    _emit(payload, "\n".join(lines), ctx.obj["json"])


@cli.command()
@click.option("--date", "game_date", required=True)
@click.option("--n", default=5000)
@click.option("--seed", default=None, type=int)
@click.pass_context
def run(ctx: click.Context, game_date: str, n: int, seed: int | None) -> None:
    """Run the full pipeline for every game on a date (F-001→F-004)."""
    try:
        d = datetime.strptime(game_date, "%Y-%m-%d").date()
    except ValueError as exc:
        click.echo(f"error: invalid date {game_date!r}: {exc}", err=True)
        raise SystemExit(2)
    repo = _repo(ctx)
    try:
        games = repo.get_schedule(d)
        results = []
        for g in games:
            res, _ = simulate_matchup(
                g.game_id, repo, home_team=g.home_team_id,
                away_team=g.away_team_id, n=n, seed=seed,
            )
            results.append(dataclasses.asdict(res))
    except Exception as exc:
        click.echo(f"error: pipeline run failed: {exc}", err=True)
        raise SystemExit(1)
    human = f"Ran {len(results)} games for {game_date}"
    _emit(results, human, ctx.obj["json"])


@cli.command("fetch-league-history")
@click.option("--seasons", default=None,
              help="Comma-separated seasons (default: this year and the 3 before).")
@click.option("--date", "asof_date", default=None,
              help="Treat this as today YYYY-MM-DD.")
@click.option("--no-windows", is_flag=True,
              help="Daily results only; skip the weekly counting stats.")
@click.pass_context
def fetch_league_history(ctx: click.Context, seasons: str | None,
                         asof_date: str | None, no_windows: bool) -> None:
    """Fetch league-wide history — every final score, several seasons deep.

    This is what lets a trend be measured against baseball rather than against
    our own eighty-game record. Run in CI alongside the scoring job: it needs
    network access to MLB and a git tree to commit the answer into, and the
    deployed Space has neither in any durable form.

    Finished seasons are fetched once and never again. Only the current season
    is re-fetched, so a rerun is cheap.
    """
    from ..league_history import refresh as refresh_history

    if asof_date:
        try:
            asof = datetime.strptime(asof_date, "%Y-%m-%d").date()
        except ValueError as exc:
            click.echo(f"error: invalid date {asof_date!r}: {exc}", err=True)
            raise SystemExit(2)
    else:
        asof = date.today()

    if seasons:
        try:
            want = [int(s) for s in seasons.split(",") if s.strip()]
        except ValueError as exc:
            click.echo(f"error: invalid seasons {seasons!r}: {exc}", err=True)
            raise SystemExit(2)
    else:
        want = [asof.year - i for i in range(4)]

    try:
        stats = refresh_history(want, asof=asof, windows=not no_windows)
    except Exception as exc:
        click.echo(f"error: league history fetch failed: {exc}", err=True)
        raise SystemExit(1)

    human = "\n".join([
        f"League history: {stats['games']:,} games across seasons "
        f"{', '.join(str(s) for s in stats['seasons'])}",
        f"  fetched this run: "
        f"{', '.join(str(s) for s in stats['fetched']) or 'nothing new'}",
        f"  record: {stats['days']} day(s), {stats['windows']} weekly window(s)",
    ])
    _emit(stats, human, ctx.obj["json"])


@cli.command("score-accuracy")
@click.option("--date", "end_date", default=None,
              help="Window end date YYYY-MM-DD (default: yesterday).")
@click.option("--days", default=7, type=int,
              help="Days of schedule to look back over. Already-graded games "
                   "are skipped, so a nightly run grades just the day before.")
@click.option("--n", default=1500, help="Simulations per game.")
@click.option("--season", default=None, type=int, help="Statline season.")
@click.option("--limit", default=None, type=int,
              help="Cap how many games to score this run.")
@click.option("--force", is_flag=True, help="Re-score games already scored.")
@click.pass_context
def score_accuracy(ctx: click.Context, end_date: str | None, days: int, n: int,
                   season: int | None, limit: int | None, force: bool) -> None:
    """Grade finished games against their real box scores.

    Run in CI rather than in the deployed app: the Space's filesystem is
    rebuilt from the image on every deploy, so anything it writes is erased by
    the next push. The runner has the statline database, network access to MLB
    and a git tree to commit the answer into, which is what makes the record
    durable.

    Writes `data/accuracy/scored.jsonl`, which the app loads on startup.
    """
    from datetime import timedelta

    from ..accuracy import export_scored, import_scored, load_report, refresh_window

    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError as exc:
            click.echo(f"error: invalid date {end_date!r}: {exc}", err=True)
            raise SystemExit(2)
    else:
        end = date.today() - timedelta(days=1)

    repo = _repo(ctx)
    if season is None:
        from ..api.main import CURRENT_SEASON, PARK_SEASON
        season, park_season = CURRENT_SEASON, PARK_SEASON
    else:
        park_season = season

    # Start from whatever the committed record already holds, so a rerun does
    # not re-simulate games that were graded on an earlier run.
    loaded = import_scored(repo)

    # `days` is a lookback over the schedule, not an amount of work. Games
    # already in the record are skipped by id, so on a nightly run the only
    # ungraded day in the span is the previous one and that is all that gets
    # simulated — the other six cost a schedule fetch each and nothing more.
    #
    # Which is exactly why the window is wider than one day. A one-day window
    # grades the previous night and never looks behind it, so a missed run, or
    # a night that was only part-graded, is stranded permanently. That is not
    # hypothetical: the first nightly run under a one-day window graded
    # 2026-08-02 and stepped straight over 2026-08-01, which had nothing.
    last = repo.latest_accuracy_date()
    if last is not None:
        click.echo(f"record ends {last}; looking back {days} days from {end}")
    try:
        stats = refresh_window(repo, end=end, days=days, season=season,
                               park_season=park_season, n=n, limit=limit,
                               force=force)
    except Exception as exc:
        click.echo(f"error: scoring failed: {exc}", err=True)
        raise SystemExit(1)
    written = export_scored(repo)
    report = load_report(repo, end=end, days=days)

    # Drift runs over the *whole* record, not the window: a trend needs more
    # than one window to be a trend, and the point is to catch a bias while it
    # is still small rather than after a window makes it obvious.
    from ..drift import build_drift_report, leading_indicators

    all_games = repo.get_accuracy_games(date(2000, 1, 1), end)
    drift = build_drift_report(all_games)
    leading = leading_indicators(repo, all_games, season)

    # Issue this cycle's forecasts and grade any whose window has now played
    # out. Both happen here rather than on demand because a forecast is only
    # honest if it was written down before its window opened.
    from ..league_history import load as load_history
    from ..trends import refresh as refresh_trends

    history = load_history()
    trends = refresh_trends(all_games, repo, season=season, asof=end,
                            history=history)

    payload = {"loaded_from_record": loaded, "written_to_record": written,
               **stats, "report": report, "drift": drift, "leading": leading,
               "trends": trends}
    o = report["outcomes"]
    lines = [
        f"Scored {stats['newly_scored']} new game(s) "
        f"({stats['already_scored']} already, {stats['not_scoreable']} not "
        f"scoreable) of {stats['scheduled']} scheduled in "
        f"{stats['start']}..{stats['end']}",
        f"  schedule: fetched {stats.get('schedule_rows_fetched', 0)} row(s) "
        f"for the window",
        f"  record: loaded {loaded}, now holds {written}",
        f"  window: {report['window']['games']} scored game(s)",
        f"  winners {o['winner_accuracy_pct']}% · total MAE {o['total_mae']} · "
        f"players graded {len(report['players'])}",
        "",
        f"Drift over the whole record ({drift['games']} games):",
    ]
    for m in drift["metrics"]:
        if m["verdict"] in ("noise", "immaterial", "no data"):
            continue
        ratio = f"  ratio {m['ratio']:.3f}" if "ratio" in m else ""
        wait = (f"  (+{m['more_games_needed']} games to settle)"
                if m.get("more_games_needed") else "")
        lines.append(f"  [{m['verdict']:<9}] {m['metric']:<22}"
                     f"z {m['z']:+6.2f}{ratio}{wait}")
    if not drift["actionable"]:
        lines.append("  nothing actionable")
    if leading.get("available"):
        lines.append("")
        lines.append("Leading indicators (statline rate vs what is being played):")
        for r in leading["rates"]:
            lines.append(f"  {r['stat']:<12} fed {r['statline_rate']:.4f}  "
                         f"played {r['realised_rate']:.4f}  "
                         f"ratio {r['ratio']:.3f}  z {r['z']:+.2f}")
    sc = trends["scorecard"]
    lines.append("")
    lines.append(f"Expected trends: {trends['issued_now']} issued now "
                 f"({trends['league_issued']} about baseball), "
                 f"{sc['open']} open, {sc['graded']} graded")
    if sc["graded"]:
        ov = sc["overall"]
        lines.append(f"  forecast hit rate {ov['hit_rate']:.0%} against an "
                     f"{sc['target_hit_rate']:.0%} band "
                     f"(direction right {ov['direction_rate']:.0%})")

    from ..baseball import recent_trends
    movers = [t for t in recent_trends(all_games, asof=end, history=history,
                                       season=season) if t["moving"]]
    if movers:
        lines.append("")
        lines.append(f"What baseball has been doing "
                     f"({history.game_count:,} games of league history):")
        for t in movers:
            lines.append(f"  {t['headline']}")
    _emit(payload, "\n".join(lines), ctx.obj["json"])


if __name__ == "__main__":
    cli()
