"""CLI entry point for the matchup module (Constitution Article II).

    python -m thebeast.matchup predict --batter <id> --pitcher <id>

Without a populated Repository this uses synthetic league-average fingerprints,
so it always returns a valid distribution (acceptance criterion F-003).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .dna import synthetic_batter, synthetic_pitcher
from .log5 import league_averages_default, pa_distribution


def _cmd_predict(args: argparse.Namespace) -> int:
    batter = synthetic_batter(hand=args.batter_hand)
    batter.player_id = args.batter
    pitcher = synthetic_pitcher(role=args.pitcher_role)
    pitcher.player_id = args.pitcher
    pitcher.hand = args.pitcher_hand
    league = league_averages_default(season=args.season)
    dist = pa_distribution(batter, pitcher, league)
    json.dump(dataclasses.asdict(dist), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thebeast.matchup")
    sub = parser.add_subparsers(dest="command", required=True)

    predict = sub.add_parser("predict", help="Predict a PA outcome distribution")
    predict.add_argument("--batter", type=int, required=True)
    predict.add_argument("--pitcher", type=int, required=True)
    predict.add_argument("--batter-hand", default="R", choices=["L", "R", "S"])
    predict.add_argument("--pitcher-hand", default="R", choices=["L", "R"])
    predict.add_argument("--pitcher-role", default="starter",
                         choices=["starter", "reliever"])
    predict.add_argument("--season", type=int, default=2024)
    predict.set_defaults(func=_cmd_predict)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
