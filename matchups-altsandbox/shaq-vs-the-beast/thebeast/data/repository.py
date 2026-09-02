"""Repository interface and SQLite implementation.

The GameRepository Protocol is the only interface the rest of the system sees.
SQLiteRepository is the default implementation; swap in any backend by
implementing the same Protocol without changing callers.

Schema: one table per entity type, keyed by natural PK columns, with a
JSON `data` column for all other fields. This makes schema evolution cheap —
add a field to the dataclass and serialize it; old rows just get None on read.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from .models import (
    BatterStatline,
    GameSchedule,
    LineupCard,
    ParkFactor,
    PitcherStatline,
    WeatherConditions,
)


@runtime_checkable
class GameRepository(Protocol):
    def save_batter(self, b: BatterStatline) -> None: ...
    def get_batter(self, player_id: int, season: int) -> Optional[BatterStatline]: ...
    def save_pitcher(self, p: PitcherStatline) -> None: ...
    def get_pitcher(self, player_id: int, season: int) -> Optional[PitcherStatline]: ...
    def save_schedule(self, s: GameSchedule) -> None: ...
    def get_schedule(self, game_date: date) -> list[GameSchedule]: ...
    def save_lineup(self, lc: LineupCard) -> None: ...
    def get_lineup(self, game_id: str, team_id: str) -> Optional[LineupCard]: ...
    def save_park_factor(self, pf: ParkFactor) -> None: ...
    def get_park_factor(self, venue_id: str, season: int) -> Optional[ParkFactor]: ...
    def save_weather(self, wc: WeatherConditions) -> None: ...
    def get_weather(self, game_id: str) -> Optional[WeatherConditions]: ...


_DDL = """
CREATE TABLE IF NOT EXISTS batter_statlines (
    player_id   INTEGER NOT NULL,
    season      INTEGER NOT NULL,
    data        TEXT    NOT NULL,
    PRIMARY KEY (player_id, season)
);
CREATE TABLE IF NOT EXISTS pitcher_statlines (
    player_id   INTEGER NOT NULL,
    season      INTEGER NOT NULL,
    data        TEXT    NOT NULL,
    PRIMARY KEY (player_id, season)
);
CREATE TABLE IF NOT EXISTS game_schedules (
    game_id     TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    PRIMARY KEY (game_id)
);
CREATE INDEX IF NOT EXISTS idx_game_schedules_date ON game_schedules (date);
CREATE TABLE IF NOT EXISTS lineup_cards (
    game_id     TEXT    NOT NULL,
    team_id     TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    PRIMARY KEY (game_id, team_id)
);
CREATE TABLE IF NOT EXISTS park_factors (
    venue_id    TEXT    NOT NULL,
    season      INTEGER NOT NULL,
    data        TEXT    NOT NULL,
    PRIMARY KEY (venue_id, season)
);
CREATE TABLE IF NOT EXISTS weather_conditions (
    game_id     TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    PRIMARY KEY (game_id)
);
-- One finished game, scored: what the simulation projected against what
-- actually happened, down to every player who appeared. Scoring a game means
-- re-running it and pulling its box score, which is far too slow to do on a
-- page load, so each game is scored once and kept. The rolling report is then
-- an aggregation over these rows and costs nothing to serve.
CREATE TABLE IF NOT EXISTS accuracy_games (
    game_id     TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    scored_at   TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    PRIMARY KEY (game_id)
);
CREATE INDEX IF NOT EXISTS idx_accuracy_games_date ON accuracy_games (date);
"""


def _default_db_path() -> str:
    # Check env var first, then look for ./data/thebeast.db (for repo root), then fall back to ~/.thebeast
    if env_path := os.environ.get("THEBEAST_DB_PATH"):
        return env_path
    if (Path.cwd() / "data" / "thebeast.db").exists():
        return str(Path.cwd() / "data" / "thebeast.db")
    return str(Path.home() / ".thebeast" / "thebeast.db")


class SQLiteRepository:
    """SQLite-backed implementation of GameRepository."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or _default_db_path()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    # ── BatterStatline ────────────────────────────────────────────────────────

    def save_batter(self, b: BatterStatline) -> None:
        data = _batter_to_json(b)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO batter_statlines (player_id, season, data) VALUES (?,?,?)",
                (b.player_id, b.season, data),
            )

    def get_batter(self, player_id: int, season: int) -> Optional[BatterStatline]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM batter_statlines WHERE player_id=? AND season=?",
                (player_id, season),
            ).fetchone()
        return _batter_from_json(row[0]) if row else None

    def get_batters_for_season(self, season: int) -> list[BatterStatline]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM batter_statlines WHERE season=?", (season,)
            ).fetchall()
        return [_batter_from_json(r[0]) for r in rows]

    # ── PitcherStatline ───────────────────────────────────────────────────────

    def save_pitcher(self, p: PitcherStatline) -> None:
        data = _pitcher_to_json(p)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pitcher_statlines (player_id, season, data) VALUES (?,?,?)",
                (p.player_id, p.season, data),
            )

    def get_pitcher(self, player_id: int, season: int) -> Optional[PitcherStatline]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM pitcher_statlines WHERE player_id=? AND season=?",
                (player_id, season),
            ).fetchone()
        return _pitcher_from_json(row[0]) if row else None

    def get_pitchers_for_season(self, season: int) -> list[PitcherStatline]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM pitcher_statlines WHERE season=?", (season,)
            ).fetchall()
        return [_pitcher_from_json(r[0]) for r in rows]

    # ── GameSchedule ──────────────────────────────────────────────────────────

    def save_schedule(self, s: GameSchedule) -> None:
        data = _schedule_to_json(s)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO game_schedules (game_id, date, data) VALUES (?,?,?)",
                (s.game_id, s.date.isoformat(), data),
            )

    def get_schedule(self, game_date: date) -> list[GameSchedule]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM game_schedules WHERE date=?",
                (game_date.isoformat(),),
            ).fetchall()
        return [_schedule_from_json(r[0]) for r in rows]

    def get_schedule_range(self, start: date, end: date) -> list[GameSchedule]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM game_schedules WHERE date BETWEEN ? AND ? ORDER BY date",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [_schedule_from_json(r[0]) for r in rows]

    def get_schedule_dates(self) -> list[str]:
        """Distinct ISO dates that have at least one scheduled game (ascending)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT date FROM game_schedules ORDER BY date"
            ).fetchall()
        return [r[0] for r in rows]

    # ── LineupCard ────────────────────────────────────────────────────────────

    def save_lineup(self, lc: LineupCard) -> None:
        data = _lineup_to_json(lc)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lineup_cards (game_id, team_id, data) VALUES (?,?,?)",
                (lc.game_id, lc.team_id, data),
            )

    def get_lineup(self, game_id: str, team_id: str) -> Optional[LineupCard]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM lineup_cards WHERE game_id=? AND team_id=?",
                (game_id, team_id),
            ).fetchone()
        return _lineup_from_json(row[0]) if row else None

    def get_lineups_for_game(self, game_id: str) -> list[LineupCard]:
        """All lineup cards stored under one game_id (e.g. the roster pseudo-game)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM lineup_cards WHERE game_id=? ORDER BY team_id",
                (game_id,),
            ).fetchall()
        return [_lineup_from_json(r[0]) for r in rows]

    # ── ParkFactor ────────────────────────────────────────────────────────────

    def save_park_factor(self, pf: ParkFactor) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO park_factors (venue_id, season, data) VALUES (?,?,?)",
                (pf.venue_id, pf.season, json.dumps(pf.__dict__)),
            )

    def get_park_factor(self, venue_id: str, season: int) -> Optional[ParkFactor]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM park_factors WHERE venue_id=? AND season=?",
                (venue_id, season),
            ).fetchone()
        if not row:
            return None
        d = json.loads(row[0])
        return ParkFactor(**d)

    # ── WeatherConditions ─────────────────────────────────────────────────────

    def save_weather(self, wc: WeatherConditions) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO weather_conditions (game_id, data) VALUES (?,?)",
                (wc.game_id, json.dumps(wc.__dict__)),
            )

    def get_weather(self, game_id: str) -> Optional[WeatherConditions]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM weather_conditions WHERE game_id=?",
                (game_id,),
            ).fetchone()
        if not row:
            return None
        d = json.loads(row[0])
        return WeatherConditions(**d)

    # ── Scored games (simulation vs. what happened) ───────────────────────────

    def save_accuracy_game(self, game_id: str, game_date: date,
                           scored_at: str, payload: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO accuracy_games "
                "(game_id, date, scored_at, data) VALUES (?,?,?,?)",
                (game_id, game_date.isoformat(), scored_at, json.dumps(payload)),
            )

    def get_accuracy_game(self, game_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM accuracy_games WHERE game_id=?", (game_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def get_accuracy_games(self, start: date, end: date) -> list[dict]:
        """Every scored game in a date window, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM accuracy_games WHERE date BETWEEN ? AND ? "
                "ORDER BY date, game_id",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def latest_accuracy_date(self) -> Optional[date]:
        """The most recent day with anything graded, or None on an empty record.

        What a nightly run measures its window from. Grading only the previous
        day is right when the job ran the previous day too; after a missed run —
        or a cadence change — a fixed one-day window would step over the gap and
        leave it ungraded for good.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(date) FROM accuracy_games").fetchone()
        if not row or not row[0]:
            return None
        try:
            return date.fromisoformat(row[0])
        except ValueError:
            return None

    def earliest_accuracy_date(self) -> Optional[date]:
        """The first day with anything graded — where "lifetime" starts."""
        with self._connect() as conn:
            row = conn.execute("SELECT MIN(date) FROM accuracy_games").fetchone()
        if not row or not row[0]:
            return None
        try:
            return date.fromisoformat(row[0])
        except ValueError:
            return None

    def accuracy_game_ids(self, start: date, end: date) -> set[str]:
        """Which games in a window are already scored — so a rebuild can skip
        them instead of re-simulating work it has already done."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT game_id FROM accuracy_games WHERE date BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return {r[0] for r in rows}


# ─── Serialization helpers ────────────────────────────────────────────────────

def _batter_to_json(b: BatterStatline) -> str:
    d = b.__dict__.copy()
    return json.dumps(d)


def _batter_from_json(raw: str) -> BatterStatline:
    d = json.loads(raw)
    return BatterStatline(**d)


def _pitcher_to_json(p: PitcherStatline) -> str:
    return json.dumps(p.__dict__)


def _pitcher_from_json(raw: str) -> PitcherStatline:
    return PitcherStatline(**json.loads(raw))


def _schedule_to_json(s: GameSchedule) -> str:
    d = s.__dict__.copy()
    d["date"] = s.date.isoformat()
    d["first_pitch"] = s.first_pitch.isoformat() if s.first_pitch else None
    return json.dumps(d)


def _schedule_from_json(raw: str) -> GameSchedule:
    d = json.loads(raw)
    d["date"] = date.fromisoformat(d["date"])
    if d.get("first_pitch"):
        d["first_pitch"] = datetime.fromisoformat(d["first_pitch"])
    return GameSchedule(**d)


def _lineup_to_json(lc: LineupCard) -> str:
    d = lc.__dict__.copy()
    d["confirmed_at"] = lc.confirmed_at.isoformat() if lc.confirmed_at else None
    return json.dumps(d)


def _lineup_from_json(raw: str) -> LineupCard:
    d = json.loads(raw)
    if d.get("confirmed_at"):
        d["confirmed_at"] = datetime.fromisoformat(d["confirmed_at"])
    return LineupCard(**d)
