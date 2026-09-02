"""HDTetris strategy benchmark.

The benchmark intentionally disables training and future search. It measures the board
strategies against identical deterministic 7-bag seeds, so a specialist cannot win by
receiving an easier random stream. Use `python benchmark.py --seeds 10000` locally or
start it from the /benchmark dashboard.
"""
import argparse
import json
import os
import random
import statistics
import time
from concurrent.futures import ProcessPoolExecutor

BENCHMARK_BEAM = max(3, int(os.environ.get("BENCHMARK_BEAM", "6")))


def _percentile(values, percentile):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _column_masks(board, app):
    """Fast row-to-column transpose for the benchmark's immutable board."""
    columns = [0] * app.GRID_W
    positions = app._ROW_BIT_POSITIONS
    for y, row_mask in enumerate(board):
        row_bit = 1 << y
        for x in positions[row_mask]:
            columns[x] |= row_bit
    return tuple(columns)


def _drop(board, columns, info, x, app):
    """Drop one precomputed rotation without constructing engine/grid objects."""
    y = app.GRID_H - info["height"]
    for local_column, local_rows in enumerate(info["occupied_rows_by_column"]):
        column_mask = columns[x + local_column]
        for local_row in local_rows:
            below = column_mask >> (local_row + 1)
            if below:
                y = min(y, (below & -below).bit_length() - 1)

    placed = list(board)
    for row, row_mask in enumerate(info["shifted_masks"][x]):
        placed[y + row] |= row_mask
    full_mask = app._FULL_ROW_MASK
    cleared_rows = [row for row, mask in enumerate(placed) if mask == full_mask]
    remaining = [mask for mask in placed if mask != full_mask]
    return tuple([0] * len(cleared_rows) + remaining), len(cleared_rows), y


def _benchmark_value(board, clears, strategy, app):
    """The same dominant expert signals as the production benchmark proxy."""
    columns = _column_masks(board, app)
    heights = [app.GRID_H - ((column & -column).bit_length() - 1) if column else 0
               for column in columns]
    holes = sum(height - column.bit_count() for height, column in zip(heights, columns))
    bump = sum(abs(heights[i] - heights[i + 1]) for i in range(app.GRID_W - 1))
    weights = strategy["weights"]
    line_bonus = strategy.get("line_bonus", [0, 3, 12, 30, 72])
    lines = line_bonus[min(4, clears)]
    return (lines + weights[0] * (max(heights) / 20.0)
            + weights[4] * (holes / 20.0)
            + weights[8] * (bump / 20.0)
            + weights[9] * (sum(heights) / 200.0)
            + weights[10] * (max(heights) / 20.0))


def _spawn_collision(board, info, x):
    return any(board[row] & row_mask
               for row, row_mask in enumerate(info["shifted_masks"][x]))


def _run_strategy(strategy_id, seeds, max_moves, progress=None):
    os.environ["HDTETRIS_DISABLE_THREADS"] = "1"
    os.environ["HDTETRIS_BENCHMARK_ONLY"] = "1"
    import app

    # Constructing the engine gives the benchmark the exact persisted specialist
    # population, but the actual 10k loop below avoids PyTorch, replay, JSON grids,
    # feature extraction, and per-candidate dictionaries entirely.
    engine = app.TetrisDQNEngine()
    strategy = engine.strategy_population[strategy_id]
    name = strategy.get("name", str(strategy_id))
    placements = []
    spawn_infos = []
    for piece_type, shape in enumerate(app.SHAPES):
        rotations = app.get_rotation_data(shape)
        placements.append(tuple(
            (info, x)
            for info in rotations
            for x in range(app.GRID_W - info["width"] + 1)
        ))
        spawn_infos.append((rotations[0], 3))

    scores = []
    lines = []
    moves_list = []
    topouts = 0
    best_score = -1
    best_seed = 0

    for seed in range(seeds):
        random.seed(seed)
        bag = []

        def draw_piece():
            if not bag:
                bag.extend(range(len(app.SHAPES)))
                random.shuffle(bag)
            return bag.pop()

        current_type = draw_piece()
        next_type = draw_piece()
        board = (0,) * app.GRID_H
        game_over = False
        score = 0
        line_count = 0
        moves = 0

        while not game_over and moves < max_moves:
            columns = _column_masks(board, app)
            candidates = []
            for info, x in placements[current_type]:
                board_after, clears, landing_y = _drop(board, columns, info, x, app)
                # Rank all legal drops with metadata that costs no second board scan,
                # then run the full proxy only on a small, deterministic beam. The gate
                # still compares every strategy on identical seeds while staying cheap
                # enough to run 10,000 seeds on a CPU Space.
                pre_score = clears * 1000 + landing_y
                candidates.append((pre_score, board_after, clears))
            candidates.sort(key=lambda item: item[0], reverse=True)

            if not candidates:
                game_over = True
                break
            scored = [
                (_benchmark_value(board_after, clears, strategy, app), board_after, clears)
                for _, board_after, clears in candidates[:BENCHMARK_BEAM]
            ]
            best = max(scored, key=lambda item: item[0])
            _, board, clears = best
            score += 10 + [0, 100, 300, 500, 800][min(4, clears)]
            line_count += clears
            current_type, next_type = next_type, draw_piece()
            game_over = _spawn_collision(board, spawn_infos[current_type][0], 3)
            moves += 1

        if game_over:
            topouts += 1
        scores.append(int(score))
        lines.append(int(line_count))
        moves_list.append(moves)
        if score > best_score:
            best_score = score
            best_seed = seed
        if progress and (seed + 1) % 100 == 0:
            progress(seed + 1, name)

    return {
        "strategy_id": strategy_id,
        "strategy": name,
        "seeds": seeds,
        "max_moves": max_moves,
        "mean_score": round(statistics.fmean(scores), 2) if scores else 0,
        "median_score": round(statistics.median(scores), 2) if scores else 0,
        "p95_score": round(_percentile(scores, 0.95), 2),
        "max_score": best_score if scores else 0,
        "best_seed": best_seed,
        "mean_lines": round(statistics.fmean(lines), 2) if lines else 0,
        "max_lines": max(lines) if lines else 0,
        "mean_moves": round(statistics.fmean(moves_list), 2) if moves_list else 0,
        "topout_rate": round(topouts / len(scores), 4) if scores else 0,
    }


def _worker(args):
    strategy_id, seeds, max_moves = args
    return _run_strategy(strategy_id, seeds, max_moves)


def run_benchmark(seeds=10000, max_moves=80, workers=1, progress_callback=None):
    """Run every strategy over the same seeds and return a deployment-gate report."""
    os.environ.setdefault("HDTETRIS_DISABLE_THREADS", "1")
    os.environ.setdefault("HDTETRIS_BENCHMARK_ONLY", "1")
    import app

    seeds = max(1, min(10000, int(seeds)))
    max_moves = max(10, min(500, int(max_moves)))
    strategy_count = len(app.TetrisDQNEngine().strategy_population)
    started = time.time()
    results = []

    if workers > 1 and progress_callback is None:
        worker_count = min(max(1, int(workers)), strategy_count)
        with ProcessPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(_worker, [(sid, seeds, max_moves) for sid in range(strategy_count)]))
    else:
        for strategy_id in range(strategy_count):
            def report(done, name, sid=strategy_id):
                if progress_callback:
                    progress_callback(strategy_id * seeds + done,
                                     strategy_count * seeds, name)
            results.append(_run_strategy(strategy_id, seeds, max_moves, report))

    champion = next((r for r in results if r["strategy"] == "CHAMPION"), results[0])
    best_median = max((r["median_score"] for r in results), default=0)
    best_mean = max((r["mean_score"] for r in results), default=0)
    # The champion gate tolerates normal sampling noise but rejects a clearly regressed
    # safe policy before deployment.
    passed = (champion["median_score"] >= best_median * 0.85 and
              champion["mean_score"] >= best_mean * 0.80 and
              champion["topout_rate"] <= 0.98)
    return {
        "schema": 1,
        "status": "passed" if passed else "regressed",
        "seeds_per_strategy": seeds,
        "max_moves": max_moves,
        "strategies": results,
        "champion": champion["strategy"],
        "best_median_score": best_median,
        "best_mean_score": best_mean,
        "duration_seconds": round(time.time() - started, 2),
        "generated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark HDTetris board strategies")
    parser.add_argument("--seeds", type=int, default=10000)
    parser.add_argument("--max-moves", type=int, default=80)
    parser.add_argument("--workers", type=int, default=max(1, min(5, (os.cpu_count() or 1))))
    parser.add_argument("--output", default="benchmark_latest.json")
    args = parser.parse_args()
    result = run_benchmark(args.seeds, args.max_moves, args.workers)
    temp = args.output + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    os.replace(temp, args.output)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
