"""Does as-of recent form add discrimination? (thebeast-qze)

For a sample of 2024 holdout games, build each player's DNA two ways and score
both with team bullpens, same sims/seed:

  prior   : 2023 full-season statline (the team-bullpen baseline)
  blended : 2023 prior shrunk toward the player's as-of 2024 form (PAs in the
            `window` days before the game), so recent PAs take over as they pile
            up — the principled "recent form" model.

Reports AUC for each; the delta is the recent-form effect, isolated.

  uv run python scripts/recent_form.py --window 45 --prior-k 120 --sample 800 --n 400
"""
from __future__ import annotations

import argparse
import json
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from thebeast.data.ingest import _bucket, fetch_statcast_range, team_bullpen_pid
from thebeast.data.repository import SQLiteRepository
from thebeast.matchup.adapters import batter_dna_from_statline, pitcher_dna_from_statline
from thebeast.matchup.dna import OUTCOMES, BatterDNA, PitcherDNA, synthetic_batter, synthetic_pitcher
from thebeast.matchup.log5 import league_averages_default, pa_distribution
from thebeast.simulator.aggregate import aggregate, run_games

LOCAL = Path(__file__).resolve().parent.parent / "local_data"
DB = str(LOCAL / "thebeast.db")
PRED = LOCAL / "predictions.jsonl"
SEASON_PRIOR = 2023
LEAGUE = league_averages_default(SEASON_PRIOR)
_LG = dict(zip(OUTCOMES, LEAGUE.as_tuple()))


def load_statcast() -> dict:
    """Group 2024 PA-level Statcast by batter and pitcher: id → (date_ord[], bucket_code[])."""
    df = fetch_statcast_range("2024-03-28", "2024-09-30")
    df = df[df["events"].notna()].copy()
    df["code"] = df["events"].map(_bucket).map({o: i for i, o in enumerate(OUTCOMES)})
    df["ord"] = pd.to_datetime(df["game_date"]).map(lambda t: t.toordinal())
    out = {"batter": {}, "pitcher": {}}
    for key in ("batter", "pitcher"):
        g = df[[key, "ord", "code"]].sort_values("ord")
        for pid, sub in g.groupby(key):
            out[key][int(pid)] = (sub["ord"].to_numpy(), sub["code"].to_numpy())
    return out


def asof_counts(grouped: dict, pid: int, game_ord: int, window: int):
    """Bucket counts for a player's PAs in [game_ord-window, game_ord)."""
    if pid not in grouped:
        return None
    ords, codes = grouped[pid]
    lo = np.searchsorted(ords, game_ord - window, "left")
    hi = np.searchsorted(ords, game_ord, "left")
    if hi <= lo:
        return None
    return np.bincount(codes[lo:hi], minlength=8)


def _blend(prior_rates: dict, counts, k: float) -> dict:
    """Shrink as-of counts toward the prior rate with k pseudo-observations."""
    n = float(counts.sum())
    out = {o: (counts[i] + prior_rates[o] * k) / (n + k) for i, o in enumerate(OUTCOMES)}
    tot = sum(out.values())
    return {o: v / tot for o, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=45)
    ap.add_argument("--prior-k", type=float, default=120)
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--n", type=int, default=400)
    args = ap.parse_args()

    repo = SQLiteRepository(DB)
    print("fetching 2024 statcast …", flush=True)
    sc = load_statcast()

    games = [json.loads(l) for l in PRED.read_text().splitlines() if l.strip()]
    rng = np.random.default_rng(0)
    sample = [games[i] for i in rng.permutation(len(games))[:args.sample]]

    def prior_batter(pid: int) -> BatterDNA:
        s = repo.get_batter(pid, SEASON_PRIOR)
        if s is not None:
            return batter_dna_from_statline(s)
        d = synthetic_batter(); d.player_id = pid; return d

    def prior_pitcher(pid: int) -> PitcherDNA:
        s = repo.get_pitcher(pid, SEASON_PRIOR)
        if s is not None:
            return pitcher_dna_from_statline(s)
        d = synthetic_pitcher(); d.player_id = pid; return d

    def blended_batter(pid: int, gord: int) -> BatterDNA:
        base = prior_batter(pid)
        c = asof_counts(sc["batter"], pid, gord, args.window)
        if c is None:
            return base
        pr = dict(zip(OUTCOMES, base.as_tuple()))
        b = _blend(pr, c, args.prior_k)
        return BatterDNA(player_id=pid, season=2024, hand=base.hand, pa=int(c.sum()),
                         single_rate=b["single"], double_rate=b["double"], triple_rate=b["triple"],
                         hr_rate=b["hr"], bb_rate=b["bb"], hbp_rate=b["hbp"],
                         k_rate=b["k"], ipo_rate=b["ipo"], platoon_mult=dict(base.platoon_mult))

    def blended_pitcher(pid: int, gord: int) -> PitcherDNA:
        base = prior_pitcher(pid)
        c = asof_counts(sc["pitcher"], pid, gord, args.window)
        if c is None:
            return base
        pr = dict(zip(OUTCOMES, base.as_tuple()))
        b = _blend(pr, c, args.prior_k)
        return PitcherDNA(player_id=pid, season=2024, hand=base.hand, bf=int(c.sum()), role=base.role,
                          single_allowed=b["single"], double_allowed=b["double"], triple_allowed=b["triple"],
                          hr_allowed=b["hr"], bb_allowed=b["bb"], hbp_allowed=b["hbp"],
                          k_rate=b["k"], ipo_rate=b["ipo"], platoon_mult=dict(base.platoon_mult))

    def win_prob(g: dict, gord: int, mode: str) -> float | None:
        _, a, h = g["game_id"].rsplit("-", 2)  # '<date>-<away>-<home>'
        hl = repo.get_lineup(g["game_id"], h)
        al = repo.get_lineup(g["game_id"], a)
        if hl is None or al is None:
            return None
        bdna, pdna = {}, {}
        for lc in (hl, al):
            pen_id = team_bullpen_pid(lc.team_id)
            for bid in lc.batting_order:
                bdna[bid] = blended_batter(bid, gord) if mode == "blended" else prior_batter(bid)
            pdna[lc.starter_id] = blended_pitcher(lc.starter_id, gord) if mode == "blended" else prior_pitcher(lc.starter_id)
            pdna[pen_id] = prior_pitcher(pen_id)  # team bullpen (2023) for both modes
        dists = {(bid, pid): pa_distribution(bd, pdna[pid], LEAGUE)
                 for bid, bd in bdna.items() for pid in pdna}
        from dataclasses import replace
        hl2 = replace(hl, bullpen_ids=[team_bullpen_pid(hl.team_id)])
        al2 = replace(al, bullpen_ids=[team_bullpen_pid(al.team_id)])
        raw = run_games(hl2, al2, dists, n=args.n, seed=7)
        return aggregate(g["game_id"], h, a, raw).home_win_probability

    y, p_prior, p_blend = [], [], []
    for i, g in enumerate(sample, 1):
        gord = date.fromisoformat(g["game_id"][:10]).toordinal()
        wp = win_prob(g, gord, "prior")
        wb = win_prob(g, gord, "blended")
        if wp is None or wb is None:
            continue
        y.append(1 if g["home_won"] else 0)
        p_prior.append(wp); p_blend.append(wb)
        if i % 200 == 0:
            print(f"  {i}/{len(sample)}", flush=True)

    y = np.array(y)
    print(f"\n=== RECENT FORM (window={args.window}d, prior_k={args.prior_k}, "
          f"n={args.n}, {len(y)} games) ===")
    print(f"  prior-only   AUC : {roc_auc_score(y, p_prior):.4f}")
    print(f"  recent-blend AUC : {roc_auc_score(y, p_blend):.4f}")
    print(f"  mean |Δ win prob|: {np.abs(np.array(p_blend)-np.array(p_prior)).mean():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
