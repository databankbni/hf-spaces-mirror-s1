"""CLI smoke tests (F-005) — click.testing.CliRunner, synthetic data only."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from thebeast.cli.main import cli


@pytest.fixture
def runner(tmp_path) -> CliRunner:
    return CliRunner(env={"THEBEAST_DB_PATH": str(tmp_path / "test.db")})


class TestSimulate:
    def test_human_output(self, runner: CliRunner) -> None:
        res = runner.invoke(cli, ["simulate", "--game-id", "g1", "--n", "50", "--seed", "1"])
        assert res.exit_code == 0, res.output
        assert "home win prob" in res.output

    def test_json_output(self, runner: CliRunner) -> None:
        res = runner.invoke(
            cli, ["--json", "simulate", "--game-id", "g1", "--n", "50", "--seed", "1"]
        )
        assert res.exit_code == 0, res.output
        payload = json.loads(res.output)
        assert payload["game_id"] == "g1"
        assert 0.0 <= payload["home_win_probability"] <= 1.0


class TestBet:
    def test_finds_value_bet(self, runner: CliRunner) -> None:
        res = runner.invoke(cli, [
            "--json", "bet", "--game-id", "g1", "--home-ml", "+150",
            "--away-ml", "-170", "--n", "200", "--seed", "1",
        ])
        assert res.exit_code == 0, res.output
        edges = json.loads(res.output)
        markets = {e["market"] for e in edges}
        assert {"home_ml", "away_ml", "over", "under"} <= markets


class TestErrors:
    def test_bad_date_nonzero_exit_and_stderr(self, runner: CliRunner) -> None:
        res = runner.invoke(cli, ["fetch", "--date", "not-a-date"])
        assert res.exit_code == 2
        assert "invalid date" in res.stderr

    def test_help_documents_commands(self, runner: CliRunner) -> None:
        res = runner.invoke(cli, ["--help"])
        assert res.exit_code == 0
        for cmd in ("fetch", "simulate", "bet", "run"):
            assert cmd in res.output
