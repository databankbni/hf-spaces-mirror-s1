"""CLI entry point for the betting module (Constitution Article II).

    python -m thebeast.betting analyze --game-id <id> \
        --model-prob 0.55 --home-ml -150 --away-ml +130 [--kelly 0.25]

Takes a model win probability (e.g. from `thebeast simulate`) and market odds,
and prints the home/away moneyline BettingEdges as JSON.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .edge import evaluate_market


def _cmd_analyze(args: argparse.Namespace) -> int:
    p_home = args.model_prob
    edges = [
        evaluate_market(args.game_id, "home_ml", p_home, args.n_sims,
                        args.home_ml, args.kelly),
        evaluate_market(args.game_id, "away_ml", 1.0 - p_home, args.n_sims,
                        args.away_ml, args.kelly),
    ]
    json.dump([dataclasses.asdict(e) for e in edges], sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thebeast.betting")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze moneyline edge")
    analyze.add_argument("--game-id", required=True)
    analyze.add_argument("--model-prob", type=float, required=True,
                         help="Model home win probability (0..1)")
    analyze.add_argument("--home-ml", type=int, required=True)
    analyze.add_argument("--away-ml", type=int, required=True)
    analyze.add_argument("--kelly", type=float, default=0.25,
                         help="Kelly fraction (0.25 quarter, 0.5 half)")
    analyze.add_argument("--n-sims", type=int, default=5000)
    analyze.set_defaults(func=_cmd_analyze)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
