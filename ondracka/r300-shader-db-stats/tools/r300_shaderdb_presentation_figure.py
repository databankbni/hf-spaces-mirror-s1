#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavel Ondračka
"""Build presentation-oriented PDF figures from the compact shader-db."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "results" / ".matplotlib"))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator

import r300_shaderdb_web as web


def parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def fmt_int(value: float) -> str:
    return f"{value:,.0f}"


def series_points(db: Path, target: str, stat: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    history = web.HistoryOrder.load_from_db(db)
    if history is None:
        raise SystemExit(f"{db} does not contain history_commits metadata")

    with web.connect(db) as con:
        data = web.query_series(
            con,
            {"targets": [target], "stats": [stat], "granularity": ["commit"]},
            history,
        )

    wanted_id = f"{target}:{stat}"
    series = next((item for item in data["series"] if item["id"] == wanted_id), None)
    if series is None:
        raise SystemExit(f"no series named {wanted_id} in {db}")

    points = [point for point in series["points"] if not point.get("boundary")]
    points.sort(key=lambda point: (int(point.get("order", 0)), str(point["date"])))
    return points, data["query"]


def make_figure(db: Path, output: Path, target: str, stat: str) -> None:
    points, _query = series_points(db, target, stat)
    if len(points) < 2:
        raise SystemExit("need at least two points for a timeline figure")

    dates = [parse_iso(str(point["date"])) for point in points]
    values = [float(point["value"]) for point in points]

    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.labelsize": 21,
            "axes.titlesize": 17,
            "xtick.labelsize": 18,
            "ytick.labelsize": 18,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "text.color": "black",
            "axes.labelcolor": "black",
            "xtick.color": "black",
            "ytick.color": "black",
        }
    )

    fig, ax = plt.subplots(figsize=(11.4, 6.2), constrained_layout=True)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    line_color = "#166b8f"
    marker_color = "#8fd1e8"
    ax.plot(
        dates,
        values,
        color=line_color,
        linewidth=2.4,
        marker="o",
        markersize=5.2,
        markerfacecolor=marker_color,
        markeredgecolor=line_color,
        markeredgewidth=0.9,
        zorder=3,
    )

    value_range = max(values) - min(values)
    pad = max(1200.0, value_range * 0.075)
    ax.set_ylim(min(values) - pad, max(values) + pad)
    x_pad = timedelta(days=45)
    ax.set_xlim(dates[0] - x_pad, dates[-1] + x_pad)

    ax.set_xlabel("Mesa mainline commit date", color="black", labelpad=10)
    ax.set_ylabel("R5xx instructions", color="black", labelpad=10)

    ax.yaxis.set_major_locator(MaxNLocator(nbins=7, integer=True))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: fmt_int(value)))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(1, 7)))

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("black")
        spine.set_linewidth(1.15)

    ax.tick_params(axis="both", which="major", colors="black", width=1.0, length=5)
    ax.tick_params(axis="x", which="minor", colors="black", width=0.8, length=3)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="pdf", facecolor="white")
    png_output = output.with_suffix(".png")
    fig.savefig(png_output, dpi=180, facecolor="white")
    plt.close(fig)
    print(output)
    print(png_output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "results" / "shaderdb-web.sqlite")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results" / "figures" / "r5xx-instructions-timeline.pdf",
    )
    parser.add_argument("--target", default="r5xx")
    parser.add_argument("--stat", default="instructions")
    args = parser.parse_args()

    make_figure(args.db, args.output, args.target, args.stat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
