"""Integration tests for thebeast.data — runs against real fixtures, no mocks
of internal code. External HTTP calls (pybaseball, MLB Stats API) are stubbed
at the network boundary only."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from thebeast.data.models import (
    BatterStatline,
    GameSchedule,
    LineupCard,
    ParkFactor,
    PitcherStatline,
    WeatherConditions,
)
from thebeast.data.repository import SQLiteRepository


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "thebeast_test.db")


@pytest.fixture
def repo(db_path: str) -> SQLiteRepository:
    return SQLiteRepository(db_path)


@pytest.fixture
def sample_batter() -> BatterStatline:
    return BatterStatline(
        player_id=621566,
        name="Juan Soto",
        season=2023,
        team_id="NYY",
        hand="L",
        pa=650,
        single_rate=0.153,
        double_rate=0.047,
        triple_rate=0.003,
        hr_rate=0.048,
        bb_rate=0.201,
        hbp_rate=0.009,
        k_rate=0.181,
        ipo_rate=0.358,
        woba=0.406,
        xwoba=0.388,
        iso=0.219,
        babip=0.322,
        platoon_split={"vL": 0.95, "vR": 1.03},
    )


@pytest.fixture
def sample_pitcher() -> PitcherStatline:
    return PitcherStatline(
        player_id=477132,
        name="Gerrit Cole",
        season=2023,
        team_id="NYY",
        hand="R",
        role="starter",
        bf=720,
        single_allowed=0.120,
        double_allowed=0.038,
        triple_allowed=0.002,
        hr_allowed=0.028,
        bb_allowed=0.055,
        hbp_allowed=0.007,
        k_rate=0.290,
        ipo_rate=0.460,
        xfip=2.63,
        platoon_split={"vL": 1.05, "vR": 0.96},
    )


@pytest.fixture
def sample_schedule() -> GameSchedule:
    return GameSchedule(
        game_id="2024/04/01-NYY-BOS",
        date=date(2024, 4, 1),
        home_team_id="BOS",
        away_team_id="NYY",
        venue_id="fenway",
        first_pitch=datetime(2024, 4, 1, 19, 5, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_lineup(sample_schedule: GameSchedule) -> LineupCard:
    return LineupCard(
        game_id=sample_schedule.game_id,
        team_id="NYY",
        batting_order=[621566, 545361, 596019, 642715, 670712, 592518, 605141, 453569, 543877],
        starter_id=477132,
        bullpen_ids=[668227, 641154],
        confirmed=True,
        confirmed_at=datetime(2024, 4, 1, 17, 0, tzinfo=timezone.utc),
    )


# ─── Repository: BatterStatline ───────────────────────────────────────────────

class TestBatterStatline:
    def test_round_trip(self, repo: SQLiteRepository, sample_batter: BatterStatline) -> None:
        repo.save_batter(sample_batter)
        fetched = repo.get_batter(sample_batter.player_id, sample_batter.season)
        assert fetched is not None
        assert fetched.player_id == sample_batter.player_id
        assert fetched.name == sample_batter.name
        assert abs(fetched.bb_rate - sample_batter.bb_rate) < 1e-9
        assert fetched.platoon_split == sample_batter.platoon_split

    def test_outcome_rates_sum_to_one(self, sample_batter: BatterStatline) -> None:
        total = (
            sample_batter.single_rate + sample_batter.double_rate
            + sample_batter.triple_rate + sample_batter.hr_rate
            + sample_batter.bb_rate + sample_batter.hbp_rate
            + sample_batter.k_rate + sample_batter.ipo_rate
        )
        assert abs(total - 1.0) < 1e-6

    def test_missing_returns_none(self, repo: SQLiteRepository) -> None:
        assert repo.get_batter(999999, 2023) is None

    def test_idempotent_save(self, repo: SQLiteRepository, sample_batter: BatterStatline) -> None:
        repo.save_batter(sample_batter)
        repo.save_batter(sample_batter)  # second save should upsert
        # Only one row should exist
        conn = sqlite3.connect(repo.path)
        count = conn.execute(
            "SELECT COUNT(*) FROM batter_statlines WHERE player_id=? AND season=?",
            (sample_batter.player_id, sample_batter.season),
        ).fetchone()[0]
        conn.close()
        assert count == 1


# ─── Repository: PitcherStatline ──────────────────────────────────────────────

class TestPitcherStatline:
    def test_round_trip(self, repo: SQLiteRepository, sample_pitcher: PitcherStatline) -> None:
        repo.save_pitcher(sample_pitcher)
        fetched = repo.get_pitcher(sample_pitcher.player_id, sample_pitcher.season)
        assert fetched is not None
        assert fetched.role == "starter"
        assert abs(fetched.xfip - sample_pitcher.xfip) < 1e-9

    def test_missing_returns_none(self, repo: SQLiteRepository) -> None:
        assert repo.get_pitcher(999999, 2023) is None


# ─── Repository: GameSchedule ─────────────────────────────────────────────────

class TestGameSchedule:
    def test_round_trip(self, repo: SQLiteRepository, sample_schedule: GameSchedule) -> None:
        repo.save_schedule(sample_schedule)
        games = repo.get_schedule(date(2024, 4, 1))
        assert len(games) == 1
        g = games[0]
        assert g.game_id == sample_schedule.game_id
        assert g.home_team_id == "BOS"
        assert g.away_team_id == "NYY"

    def test_date_filter(self, repo: SQLiteRepository, sample_schedule: GameSchedule) -> None:
        repo.save_schedule(sample_schedule)
        assert repo.get_schedule(date(2024, 4, 2)) == []


# ─── Repository: LineupCard ───────────────────────────────────────────────────

class TestLineupCard:
    def test_round_trip(self, repo: SQLiteRepository, sample_lineup: LineupCard) -> None:
        repo.save_lineup(sample_lineup)
        fetched = repo.get_lineup(sample_lineup.game_id, sample_lineup.team_id)
        assert fetched is not None
        assert fetched.batting_order == sample_lineup.batting_order
        assert fetched.starter_id == sample_lineup.starter_id
        assert fetched.confirmed is True

    def test_unconfirmed_then_confirmed(
        self, repo: SQLiteRepository, sample_lineup: LineupCard
    ) -> None:
        unconfirmed = LineupCard(
            game_id=sample_lineup.game_id,
            team_id=sample_lineup.team_id,
            batting_order=sample_lineup.batting_order,
            starter_id=sample_lineup.starter_id,
            bullpen_ids=sample_lineup.bullpen_ids,
            confirmed=False,
            confirmed_at=None,
        )
        repo.save_lineup(unconfirmed)
        fetched = repo.get_lineup(unconfirmed.game_id, unconfirmed.team_id)
        assert fetched is not None
        assert fetched.confirmed is False

        repo.save_lineup(sample_lineup)  # upsert with confirmed=True
        fetched2 = repo.get_lineup(sample_lineup.game_id, sample_lineup.team_id)
        assert fetched2 is not None
        assert fetched2.confirmed is True


# ─── Repository: ParkFactor ───────────────────────────────────────────────────

class TestParkFactor:
    def test_round_trip(self, repo: SQLiteRepository) -> None:
        pf = ParkFactor(venue_id="fenway", season=2023, runs_factor=1.08, hr_factor=0.92, hits_factor=1.04)
        repo.save_park_factor(pf)
        fetched = repo.get_park_factor("fenway", 2023)
        assert fetched is not None
        assert abs(fetched.hr_factor - 0.92) < 1e-9

    def test_missing_returns_none(self, repo: SQLiteRepository) -> None:
        assert repo.get_park_factor("nowhere", 2023) is None


# ─── Repository: WeatherConditions ────────────────────────────────────────────

class TestWeatherConditions:
    def test_round_trip(self, repo: SQLiteRepository) -> None:
        wc = WeatherConditions(
            game_id="2024/04/01-NYY-BOS",
            temperature_f=58.0,
            wind_mph=12.0,
            wind_direction_deg=270.0,
            humidity_pct=55.0,
        )
        repo.save_weather(wc)
        fetched = repo.get_weather("2024/04/01-NYY-BOS")
        assert fetched is not None
        assert fetched.temperature_f == 58.0
