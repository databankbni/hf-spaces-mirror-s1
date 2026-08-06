#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavel Ondračka
"""Serve an interactive r300 shader-db history viewer."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import mimetypes
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sqlite3
import subprocess
import statistics
import sys
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "results" / "shaderdb-history.sqlite"
DEFAULT_WEB = ROOT / "web"
DEFAULT_MESA_REPO = ROOT / "mesa"
DEFAULT_START = "17cea74b8cd3b1a56d923edeb40772b3e8b18ab2"
TARGETS = ("r3xx", "r4xx", "r5xx")
DEFAULT_STATS = ("instructions", "temps", "cycles")
LOST_GAINED_DELTA_STAT = "lost/gained delta"
REPORT_STAT_ORDER = ("instructions", "temps", "cycles", "consts", "lits", "loops", "omod", "presub")
WIDE_STATS = ("consts", "cycles", "instructions", "lits", "loops", "omod", "presub", "temps")
TARGET_PRIORITY = {"r3xx": 0, "r4xx": 1, "r5xx": 2}
MAX_POST_BYTES = 4 * 1024 * 1024
IN_CHUNK = 800


class ResponseError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class QueryCache:
    def __init__(self, max_entries: int = 64):
        self.max_entries = max_entries
        self.entries: OrderedDict[tuple[object, ...], object] = OrderedDict()

    def get(self, key: tuple[object, ...]) -> object | None:
        if key not in self.entries:
            return None
        value = self.entries.pop(key)
        self.entries[key] = value
        return value

    def put(self, key: tuple[object, ...], value: object) -> None:
        if key in self.entries:
            self.entries.pop(key)
        self.entries[key] = value
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)


class HistoryOrder:
    def __init__(self, commits: dict[str, dict[str, object]]):
        self.commits = commits

    @classmethod
    def load_from_db(cls, db: Path) -> "HistoryOrder | None":
        uri = f"file:{db.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as con:
            con.row_factory = sqlite3.Row
            table = con.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'history_commits'
                """
            ).fetchone()
            if table is None:
                return None
            columns = {
                str(row["name"])
                for row in con.execute("PRAGMA table_info(history_commits)")
            }
            author_expr = "author" if "author" in columns else "'' AS author"
            rows = con.execute(
                f"""
                SELECT sha, first_parent_order, commit_date, {author_expr}, subject, message
                FROM history_commits
                ORDER BY first_parent_order
                """
            ).fetchall()
        if not rows:
            return None
        return cls(
            {
                row["sha"]: {
                    "order": row["first_parent_order"],
                    "date": row["commit_date"],
                    "author": row["author"],
                    "subject": row["subject"],
                    "message": row["message"],
                }
                for row in rows
            }
        )

    @classmethod
    def load(cls, repo: Path, start: str, end: str = "HEAD") -> "HistoryOrder":
        fmt = "%H%x1f%cI%x1f%aN <%aE>%x1f%B%x1e"
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "log",
                "--first-parent",
                "--reverse",
                f"--format={fmt}",
                f"{start}^..{end}",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        commits: dict[str, dict[str, object]] = {}
        text = proc.stdout.decode("utf-8", errors="replace")
        for order, raw in enumerate(text.split("\x1e")):
            raw = raw.strip("\n")
            if not raw:
                continue
            sha, commit_date, author, message = raw.split("\x1f", 3)
            message = message.strip()
            subject = message.splitlines()[0] if message else ""
            commits[sha] = {
                "order": order,
                "date": commit_date,
                "author": author,
                "subject": subject,
                "message": message,
            }
        return cls(commits)

    def has(self, sha: str) -> bool:
        return sha in self.commits

    def order(self, sha: str) -> int:
        item = self.commits.get(sha)
        if item is None:
            return 10**12
        return int(item["order"])

    def date(self, sha: str, fallback: str) -> str:
        item = self.commits.get(sha)
        if item is None:
            return fallback
        return str(item["date"])

    def subject(self, sha: str, fallback: str) -> str:
        item = self.commits.get(sha)
        if item is None:
            return fallback
        return str(item["subject"])

    def author(self, sha: str, fallback: str = "") -> str:
        item = self.commits.get(sha)
        if item is None:
            return fallback
        return str(item.get("author") or fallback)

    def message(self, sha: str, fallback: str) -> str:
        item = self.commits.get(sha)
        if item is None:
            return fallback
        return str(item["message"])

    def sort_key(self, sha: str, fallback_date: str = "", fallback_id: int = 0) -> tuple[int, str, int]:
        return (self.order(sha), fallback_date, fallback_id)


def connect(db: Path) -> sqlite3.Connection:
    # A normal read-only connection sees WAL updates from the active collector.
    uri = f"file:{db}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30.0)
    con.row_factory = sqlite3.Row
    # Keep the main DB read-only via mode=ro, but allow temporary tables for
    # per-request query planning on compact v2 databases.
    con.execute("PRAGMA temp_store = MEMORY")
    return con


def csv_values(qs: dict[str, list[str]], name: str, default: list[str] | None = None) -> list[str]:
    raw = qs.get(name)
    if not raw:
        return list(default or [])
    values: list[str] = []
    for part in raw:
        values.extend(v.strip() for v in part.split(",") if v.strip())
    return values


def one_value(qs: dict[str, list[str]], name: str, default: str = "") -> str:
    values = qs.get(name)
    if not values:
        return default
    return values[-1].strip()


def placeholders(values: list[object]) -> str:
    return ",".join("?" for _ in values)


def add_in_filter(clauses: list[str], params: list[object], column: str, values: list[object]) -> None:
    chunks = [values[i : i + IN_CHUNK] for i in range(0, len(values), IN_CHUNK)]
    clauses.append("(" + " OR ".join(f"{column} IN ({placeholders(chunk)})" for chunk in chunks) + ")")
    for chunk in chunks:
        params.extend(chunk)


def parse_limit(qs: dict[str, list[str]], default: int, maximum: int) -> int:
    raw = one_value(qs, "limit", str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ResponseError(HTTPStatus.BAD_REQUEST, f"invalid limit: {raw}") from exc
    return max(1, min(value, maximum))


def current_db_version(con: sqlite3.Connection) -> int:
    row = con.execute("SELECT coalesce(max(id), 0) AS version FROM runs").fetchone()
    return int(row["version"])


def has_compact_v2_schema(con: sqlite3.Connection) -> bool:
    return con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'shader_stat_values'
        """
    ).fetchone() is not None


def latest_catalog_run_id(con: sqlite3.Connection, history: HistoryOrder) -> int:
    rows = con.execute(
        """
        SELECT id, commit_sha, target
        FROM runs
        WHERE shader_selection = 'shaders' AND status = 'ok'
        """
    ).fetchall()
    if not rows:
        return 0
    best = max(
        rows,
        key=lambda r: (
            history.order(r["commit_sha"]),
            TARGET_PRIORITY.get(r["target"], -1),
            r["id"],
        ),
    )
    return int(best["id"])


def in_date_range(value: str, date_from: str, date_to: str) -> bool:
    day = value[:10]
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def run_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT r.id, r.commit_sha, substr(r.commit_sha, 1, 12) AS sha,
               c.author_date, c.subject, r.target, r.stats_count
        FROM runs r
        JOIN commits c ON c.sha = r.commit_sha
        WHERE r.shader_selection = 'shaders'
        """
    ).fetchall()


def query_meta(con: sqlite3.Connection, history: HistoryOrder) -> dict[str, object]:
    catalog_run_id = latest_catalog_run_id(con, history)
    stats = [
        r["stat"] for r in con.execute(
            "SELECT DISTINCT stat FROM shader_stats WHERE run_id = ? ORDER BY stat",
            (catalog_run_id,),
        )
    ]
    stats.append(LOST_GAINED_DELTA_STAT)
    stages = [
        r["stage"] for r in con.execute(
            "SELECT DISTINCT stage FROM shader_stats WHERE run_id = ? ORDER BY stage",
            (catalog_run_id,),
        )
    ]
    targets = [
        {"id": r["target"], "gpu_id": r["gpu_id"], "runs": r["runs"]}
        for r in con.execute(
            """
            SELECT target, min(gpu_id) AS gpu_id, count(*) AS runs
            FROM runs
            WHERE shader_selection = 'shaders'
            GROUP BY target
            ORDER BY target
            """
        )
    ]
    rows = run_rows(con)
    ordered_rows = [r for r in rows if history.has(r["commit_sha"])]
    range_rows = ordered_rows or rows
    start_row = min(range_rows, key=lambda r: history.sort_key(r["commit_sha"], r["author_date"], r["id"]), default=None)
    end_row = max(range_rows, key=lambda r: history.sort_key(r["commit_sha"], r["author_date"], r["id"]), default=None)
    latest = end_row
    dates = {
        "start_date": history.date(start_row["commit_sha"], start_row["author_date"]) if start_row else "",
        "end_date": history.date(end_row["commit_sha"], end_row["author_date"]) if end_row else "",
        "commits": len({r["commit_sha"] for r in range_rows}),
        "runs": len(rows),
    }
    latest_run = None
    if latest is not None:
        latest_run = {
            "sha": latest["sha"],
            "author_date": latest["author_date"],
            "date": history.date(latest["commit_sha"], latest["author_date"]),
            "author": history.author(latest["commit_sha"]),
            "subject": history.subject(latest["commit_sha"], latest["subject"]),
            "message": history.message(latest["commit_sha"], latest["subject"]),
            "target": latest["target"],
            "stats_count": latest["stats_count"],
        }
    return {
        "stats": stats,
        "default_stats": [s for s in DEFAULT_STATS if s in stats],
        "stages": stages,
        "targets": targets,
        "range": dates,
        "latest_run": latest_run,
        "change_points": con.execute("SELECT count(*) AS n FROM change_points").fetchone()["n"],
    }


def query_apps(con: sqlite3.Connection, qs: dict[str, list[str]], history: HistoryOrder) -> list[dict[str, object]]:
    q = one_value(qs, "q")
    limit = parse_limit(qs, 200, 1000)
    catalog_run_id = latest_catalog_run_id(con, history)
    params: list[object] = [catalog_run_id]
    where = "WHERE run_id = ?"
    if q:
        where += " AND app LIKE ? ESCAPE '\\'"
        params.append(f"%{escape_like(q)}%")
    rows = con.execute(
        f"""
        SELECT app, count(DISTINCT shader_path) AS shaders
        FROM shader_stats
        {where}
        GROUP BY app
        ORDER BY app
        LIMIT ?
        """,
        [*params, limit],
    )
    return [dict(row) for row in rows]


def query_shaders(con: sqlite3.Connection, qs: dict[str, list[str]], history: HistoryOrder) -> list[dict[str, object]]:
    q = one_value(qs, "q")
    app = one_value(qs, "app")
    limit = parse_limit(qs, 200, 1000)
    catalog_run_id = latest_catalog_run_id(con, history)
    clauses: list[str] = ["run_id = ?"]
    params: list[object] = [catalog_run_id]
    if app:
        clauses.append("app = ?")
        params.append(app)
    if q:
        clauses.append("shader_path LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(q)}%")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = con.execute(
        f"""
        SELECT shader_path, min(app) AS app
        FROM shader_stats
        {where}
        GROUP BY shader_path
        ORDER BY shader_path
        LIMIT ?
        """,
        [*params, limit],
    )
    return [dict(row) for row in rows]


def query_shader_tree(con: sqlite3.Connection, history: HistoryOrder) -> dict[str, object]:
    catalog_run_id = latest_catalog_run_id(con, history)
    rows = con.execute(
        """
        SELECT shader_path AS path, min(app) AS app
        FROM shader_stats
        WHERE run_id = ?
        GROUP BY shader_path
        ORDER BY shader_path
        """,
        (catalog_run_id,),
    )
    shaders = [dict(row) for row in rows]
    return {
        "catalog_run_id": catalog_run_id,
        "shaders": shaders,
        "total": len(shaders),
    }


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def iso_to_month(value: str) -> str:
    return value[:7]


def query_changes(con: sqlite3.Connection, qs: dict[str, list[str]], history: HistoryOrder) -> list[dict[str, object]]:
    start = one_value(qs, "from")
    end = one_value(qs, "to")
    rows = con.execute(
        """
        SELECT cp.id, cp.mode,
               substr(cp.from_sha, 1, 12) AS from_short,
               substr(cp.to_sha, 1, 12) AS to_short,
               cp.from_sha, cp.to_sha,
               cf.author_date AS from_date,
               ct.author_date AS to_date,
               ct.subject AS to_subject
        FROM change_points cp
        LEFT JOIN commits cf ON cf.sha = cp.from_sha
        LEFT JOIN commits ct ON ct.sha = cp.to_sha
        ORDER BY cp.id
        """
    ).fetchall()
    changes: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        item = dict(row)
        key = (item["from_sha"], item["to_sha"])
        if key in seen:
            continue
        display_date = history.date(item["to_sha"], item["to_date"] or item["from_date"] or "")
        if not in_date_range(display_date, start, end):
            continue
        seen.add(key)
        item["from_date"] = history.date(item["from_sha"], item["from_date"] or display_date)
        item["to_date"] = display_date
        item["to_author"] = history.author(item["to_sha"])
        item["to_subject"] = history.subject(item["to_sha"], item["to_subject"] or "")
        item["to_message"] = history.message(item["to_sha"], item["to_subject"] or "")
        item["order"] = history.order(item["to_sha"])
        changes.append(item)
    changes.sort(key=lambda item: (item["order"], item["to_date"], item["id"]))
    return changes[:500]


def target_run_rows(
    con: sqlite3.Connection,
    targets: list[str],
) -> list[sqlite3.Row]:
    return con.execute(
        f"""
        SELECT r.id, r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
               c.author_date, c.subject
        FROM runs r
        JOIN commits c ON c.sha = r.commit_sha
        WHERE r.shader_selection = 'shaders'
          AND r.status = 'ok'
          AND r.target IN ({placeholders(targets)})
        ORDER BY r.id, r.target
        """,
        targets,
    ).fetchall()


def sort_run_rows(rows: list[sqlite3.Row], history: HistoryOrder) -> list[sqlite3.Row]:
    return sorted(
        rows,
        key=lambda row: history.sort_key(
            row["commit_sha"],
            history.date(row["commit_sha"], row["author_date"]),
            row["id"],
        ),
    )


def unique_run_rows(rows: list[sqlite3.Row], history: HistoryOrder) -> list[sqlite3.Row]:
    unique: dict[int, sqlite3.Row] = {}
    for row in rows:
        unique[int(row["id"])] = row
    return sort_run_rows(list(unique.values()), history)


def visible_run_rows(
    con: sqlite3.Connection,
    targets: list[str],
    date_from: str,
    date_to: str,
    history: HistoryOrder,
) -> list[sqlite3.Row]:
    rows = target_run_rows(con, targets)
    return [
        row for row in rows
        if in_date_range(history.date(row["commit_sha"], row["author_date"]), date_from, date_to)
    ]


def boundary_run_rows(
    con: sqlite3.Connection,
    targets: list[str],
    date_from: str,
    date_to: str,
    history: HistoryOrder,
) -> list[sqlite3.Row]:
    rows = sort_run_rows(target_run_rows(con, targets), history)
    by_target: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_target.setdefault(row["target"], []).append(row)

    anchors: list[sqlite3.Row] = []
    for target_rows in by_target.values():
        before = None
        after = None
        for row in target_rows:
            day = history.date(row["commit_sha"], row["author_date"])[:10]
            if date_from and day < date_from:
                before = row
            if date_to and day > date_to and after is None:
                after = row
        if before is not None:
            anchors.append(before)
        if after is not None:
            anchors.append(after)
    return unique_run_rows(anchors, history)


def output_run_rows(
    rows: list[sqlite3.Row],
    granularity: str,
    history: HistoryOrder,
) -> list[sqlite3.Row]:
    if granularity != "month":
        return rows

    buckets: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        display_date = history.date(row["commit_sha"], row["author_date"])
        key = (row["target"], iso_to_month(display_date))
        previous = buckets.get(key)
        if previous is None or history.sort_key(
            row["commit_sha"],
            display_date,
            row["id"],
        ) > history.sort_key(
            previous["commit_sha"],
            history.date(previous["commit_sha"], previous["author_date"]),
            previous["id"],
        ):
            buckets[key] = row
    return sorted(
        buckets.values(),
        key=lambda row: history.sort_key(
            row["commit_sha"],
            history.date(row["commit_sha"], row["author_date"]),
            row["id"],
        ),
    )


def changed_points_only(points: list[dict[str, object]]) -> list[dict[str, object]]:
    changed: list[dict[str, object]] = []
    previous: object = None
    have_previous = False
    previous_boundary = False
    for point in points:
        value = point["value"]
        boundary = bool(point.get("boundary"))
        if boundary or previous_boundary or not have_previous or value != previous:
            changed.append(point)
        previous = value
        previous_boundary = boundary
        have_previous = True
    return changed


def higher_is_better(metric: str) -> bool:
    return metric in {"threads", "waves", "maxwaves"}


def format_percent(frac: float) -> str:
    if 0.0 < abs(frac) < 0.0001:
        return "<.01%"
    return f"{frac * 100:.2f}%"


def format_num(value: float) -> str:
    if abs(value - int(value)) < 0.01:
        return str(int(value))
    return f"{value:.2f}"


def change_text(before: float, after: float) -> str:
    suffix = ""
    if before != 0 and after != 0:
        suffix = f" ({format_percent(float(after) / float(before) - 1.0)})"
    return f"{format_num(before)} -> {format_num(after)}{suffix}"


def report_result_line(label: str, before: float, after: float) -> str:
    prefix = f"{label}: "
    return prefix.ljust(50) + change_text(before, after)


def report_stats(changed: list[tuple[tuple[str, str], int, int]]) -> tuple[float, float, int, int, float, float, float, float]:
    absolute = [abs(before - after) for _, before, after in changed]
    relative = [
        0.0 if before == 0 else abs(before - after) / before
        for _, before, after in changed
    ]
    return (
        statistics.mean(absolute),
        statistics.median(absolute),
        min(absolute),
        max(absolute),
        statistics.mean(relative),
        statistics.median(relative),
        min(relative),
        max(relative),
    )


def shader_label(key: tuple[str, str]) -> str:
    shader_path, stage = key
    return f"{shader_path} {stage}"


def preferred_report_stats(available_stats: list[str]) -> list[str]:
    available = set(available_stats)
    ordered = [stat for stat in REPORT_STAT_ORDER if stat in available]
    ordered.extend(sorted(available - set(ordered)))
    return ordered


def resolve_commit_sha(con: sqlite3.Connection, value: str) -> str:
    if not value:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "missing commit")
    rows = con.execute(
        """
        SELECT DISTINCT commit_sha
        FROM runs
        WHERE commit_sha = ? OR commit_sha LIKE ?
        ORDER BY commit_sha
        """,
        (value, f"{value}%"),
    ).fetchall()
    if not rows:
        raise ResponseError(HTTPStatus.NOT_FOUND, f"unknown commit: {value}")
    if len(rows) > 1:
        raise ResponseError(HTTPStatus.BAD_REQUEST, f"ambiguous commit prefix: {value}")
    return str(rows[0]["commit_sha"])


def run_for_commit_target(
    con: sqlite3.Connection,
    commit_sha: str,
    target: str,
    history: HistoryOrder,
) -> dict[str, object] | None:
    row = con.execute(
        """
        SELECT r.id, r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
               c.author_date, c.subject
        FROM runs r
        JOIN commits c ON c.sha = r.commit_sha
        WHERE r.shader_selection = 'shaders'
          AND r.status = 'ok'
          AND r.commit_sha = ?
          AND r.target = ?
        LIMIT 1
        """,
        (commit_sha, target),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["order"] = history.order(item["commit_sha"])
    item["date"] = history.date(item["commit_sha"], item["author_date"])
    item["author"] = history.author(item["commit_sha"])
    item["subject"] = history.subject(item["commit_sha"], item["subject"])
    return item


def previous_run_for_target(
    con: sqlite3.Connection,
    after_run: dict[str, object],
    history: HistoryOrder,
) -> dict[str, object] | None:
    rows = con.execute(
        """
        SELECT r.id, r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
               c.author_date, c.subject
        FROM runs r
        JOIN commits c ON c.sha = r.commit_sha
        WHERE r.shader_selection = 'shaders'
          AND r.status = 'ok'
          AND r.target = ?
        """,
        (after_run["target"],),
    ).fetchall()
    before_rows: list[dict[str, object]] = []
    after_order = int(after_run["order"])
    for row in rows:
        item = dict(row)
        item["order"] = history.order(item["commit_sha"])
        if int(item["order"]) >= after_order:
            continue
        item["date"] = history.date(item["commit_sha"], item["author_date"])
        item["author"] = history.author(item["commit_sha"])
        item["subject"] = history.subject(item["commit_sha"], item["subject"])
        before_rows.append(item)
    if not before_rows:
        return None
    return max(before_rows, key=lambda item: (int(item["order"]), int(item["id"])))


def filtered_shader_results(
    con: sqlite3.Connection,
    run_id: int,
    stages: list[str],
    apps: list[str],
    shader: str,
    shader_paths: list[str],
) -> dict[tuple[str, str], dict[str, int]]:
    clauses = ["ss.run_id = ?"]
    params: list[object] = [run_id]
    if stages:
        clauses.append(f"ss.stage IN ({placeholders(stages)})")
        params.extend(stages)
    if apps:
        clauses.append(f"ss.app IN ({placeholders(apps)})")
        params.extend(apps)
    if shader:
        clauses.append("ss.shader_path LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(shader)}%")
    if shader_paths:
        add_in_filter(clauses, params, "ss.shader_path", shader_paths)

    rows = con.execute(
        f"""
        SELECT ss.shader_path, ss.stage, ss.stat, ss.value
        FROM shader_stats ss
        WHERE {' AND '.join(clauses)}
        ORDER BY ss.shader_path, ss.stage, ss.stat
        """,
        params,
    ).fetchall()
    results: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        key = (row["shader_path"], row["stage"])
        results.setdefault(key, {})[row["stat"]] = int(row["value"])
    return results


def format_target_report(
    target: str,
    before_run: dict[str, object],
    after_run: dict[str, object],
    before: dict[tuple[str, str], dict[str, int]],
    after: dict[tuple[str, str], dict[str, int]],
    stats: list[str],
) -> str:
    lines = [
        f"{target}: {before_run['short_sha']} -> {after_run['short_sha']}",
        f"before: {before_run['short_sha']} {before_run['subject']}",
        f"after:  {after_run['short_sha']} {after_run['subject']}",
        "",
    ]
    summaries: list[
        tuple[
            str,
            int,
            int,
            int,
            int,
            list[tuple[tuple[str, str], int, int]],
            list[tuple[tuple[str, str], int, int]],
            list[tuple[tuple[str, str], int, int, int, int]],
        ]
    ] = []

    for metric in stats:
        total_before = 0
        total_after = 0
        affected_before = 0
        affected_after = 0
        helped: list[tuple[tuple[str, str], int, int]] = []
        hurt: list[tuple[tuple[str, str], int, int]] = []
        changed_with_loops: list[tuple[tuple[str, str], int, int, int, int]] = []

        for key in before:
            if key not in after:
                continue
            if metric not in before[key] or metric not in after[key]:
                continue
            before_count = before[key][metric]
            after_count = after[key][metric]
            if (
                metric != "loops"
                and "loops" in before[key]
                and "loops" in after[key]
                and before[key]["loops"] != after[key]["loops"]
            ):
                if before_count != after_count:
                    changed_with_loops.append(
                        (
                            key,
                            before_count,
                            after_count,
                            before[key]["loops"],
                            after[key]["loops"],
                        )
                    )
                continue

            total_before += before_count
            total_after += after_count
            if before_count == after_count:
                continue
            affected_before += before_count
            affected_after += after_count
            if (after_count > before_count) ^ higher_is_better(metric):
                hurt.append((key, before_count, after_count))
            else:
                helped.append((key, before_count, after_count))

        helped.sort(
            key=lambda item: item[2] if item[1] == 0 else float(item[1] - item[2]) / item[1]
        )
        for key, before_count, after_count in helped:
            lines.append(
                f"{metric} helped:   "
                + report_result_line(shader_label(key), before_count, after_count)
            )
        if helped:
            lines.append("")

        hurt.sort(
            key=lambda item: item[2] if item[1] == 0 else float(item[2] - item[1]) / item[1]
        )
        for key, before_count, after_count in hurt:
            lines.append(
                f"{metric} HURT:   "
                + report_result_line(shader_label(key), before_count, after_count)
            )
        if hurt:
            lines.append("")

        changed_with_loops.sort(
            key=lambda item: item[2] if item[1] == 0 else abs(float(item[2] - item[1]) / item[1]),
            reverse=True,
        )
        for key, before_count, after_count, before_loops, after_loops in changed_with_loops:
            lines.append(
                f"{metric} changed with loops: "
                + report_result_line(shader_label(key), before_count, after_count)
                + f", loops {before_loops} -> {after_loops}"
            )
        if changed_with_loops:
            lines.append("")

        summaries.append(
            (
                metric,
                total_before,
                total_after,
                affected_before,
                affected_after,
                helped,
                hurt,
                changed_with_loops,
            )
        )

    lost = sorted(shader_label(key) for key in before if key not in after)
    gained = sorted(shader_label(key) for key in after if key not in before)
    for label in lost:
        lines.append(f"LOST:   {label}")
    if lost:
        lines.append("")
    for label in gained:
        lines.append(f"GAINED: {label}")
    if gained:
        lines.append("")

    any_metric_change = False
    for (
        metric,
        total_before,
        total_after,
        affected_before,
        affected_after,
        helped,
        hurt,
        changed_with_loops,
    ) in summaries:
        if helped or hurt or changed_with_loops:
            any_metric_change = True
        lines.extend(
            [
                f"total {metric} in shared programs: {change_text(total_before, total_after)}",
                f"{metric} in affected programs: {change_text(affected_before, affected_after)}",
                f"helped: {len(helped)}",
                f"HURT: {len(hurt)}",
            ]
        )
        if changed_with_loops:
            lines.append(f"changed with loops: {len(changed_with_loops)}")

        if len(helped) > 2 or (helped and hurt):
            avg_abs, med_abs, lo_abs, hi_abs, avg_rel, med_rel, lo_rel, hi_rel = report_stats(helped)
            lines.append(
                f"helped stats (abs) min: {lo_abs} max: {hi_abs} avg: {avg_abs:.2f} median: {format_num(med_abs)}"
            )
            lines.append(
                "helped stats (rel) "
                f"min: {format_percent(lo_rel)} max: {format_percent(hi_rel)} "
                f"avg: {format_percent(avg_rel)} median: {format_percent(med_rel)}"
            )

        if len(hurt) > 2 or (hurt and helped):
            avg_abs, med_abs, lo_abs, hi_abs, avg_rel, med_rel, lo_rel, hi_rel = report_stats(hurt)
            lines.append(
                f"HURT stats (abs)   min: {lo_abs} max: {hi_abs} avg: {avg_abs:.2f} median: {format_num(med_abs)}"
            )
            lines.append(
                "HURT stats (rel)   "
                f"min: {format_percent(lo_rel)} max: {format_percent(hi_rel)} "
                f"avg: {format_percent(avg_rel)} median: {format_percent(med_rel)}"
            )
        lines.append("")

    if lost or gained:
        lines.append(f"LOST:   {len(lost)}")
        lines.append(f"GAINED: {len(gained)}")
    elif not any_metric_change:
        lines.append("No changes.")

    return "\n".join(lines).rstrip()


def query_change_report(con: sqlite3.Connection, qs: dict[str, list[str]], history: HistoryOrder) -> dict[str, object]:
    commit_sha = resolve_commit_sha(con, one_value(qs, "commit", one_value(qs, "sha")))
    requested_targets = csv_values(qs, "targets", list(TARGETS))
    targets = [target for target in requested_targets if target in TARGETS]
    if not targets:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "no valid targets selected")

    stages = csv_values(qs, "stages")
    if "stages" in qs and not stages:
        return {
            "commit": commit_sha,
            "short_commit": commit_sha[:12],
            "report": "No stages selected.",
        }
    apps = csv_values(qs, "apps")
    shader = one_value(qs, "shader")
    explicit_shader_paths = "shader_paths" in qs
    shader_paths = csv_values(qs, "shader_paths")
    if explicit_shader_paths and not shader_paths:
        return {
            "commit": commit_sha,
            "short_commit": commit_sha[:12],
            "report": "No shaders selected.",
        }

    catalog_run_id = latest_catalog_run_id(con, history)
    available_stats = [
        row["stat"] for row in con.execute(
            "SELECT DISTINCT stat FROM shader_stats WHERE run_id = ? ORDER BY stat",
            (catalog_run_id,),
        )
    ]
    stats = preferred_report_stats(available_stats)

    sections: list[str] = []
    for target in targets:
        after_run = run_for_commit_target(con, commit_sha, target, history)
        if after_run is None:
            sections.append(f"{target}: no run for {commit_sha[:12]}")
            continue
        before_run = previous_run_for_target(con, after_run, history)
        if before_run is None:
            sections.append(f"{target}: no previous compact run before {after_run['short_sha']}")
            continue

        before = filtered_shader_results(
            con, int(before_run["id"]), stages, apps, shader, shader_paths
        )
        after = filtered_shader_results(
            con, int(after_run["id"]), stages, apps, shader, shader_paths
        )
        sections.append(format_target_report(target, before_run, after_run, before, after, stats))

    return {
        "commit": commit_sha,
        "short_commit": commit_sha[:12],
        "author": history.author(commit_sha),
        "subject": history.subject(commit_sha, ""),
        "message": history.message(commit_sha, ""),
        "targets": targets,
        "report": "\n\n".join(sections),
    }


def query_series_v2(con: sqlite3.Connection, qs: dict[str, list[str]], history: HistoryOrder) -> dict[str, object]:
    available_stats = list(WIDE_STATS)
    requested_stats = csv_values(qs, "stats", [s for s in DEFAULT_STATS if s in available_stats])
    stats = [
        s for s in requested_stats
        if s in available_stats or s == LOST_GAINED_DELTA_STAT
    ]
    if not stats:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "no valid stats selected")
    real_stats = [s for s in stats if s in available_stats]
    include_lost_gained_delta = LOST_GAINED_DELTA_STAT in stats

    requested_targets = csv_values(qs, "targets", list(TARGETS))
    targets = [t for t in requested_targets if t in TARGETS]
    if not targets:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "no valid targets selected")

    granularity = one_value(qs, "granularity", "month")
    if granularity not in {"month", "commit"}:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "granularity must be month or commit")
    aggregate = one_value(qs, "aggregate", "sum")
    aggregate_name = {
        "sum": "sum",
        "avg": "avg",
        "min": "min",
        "max": "max",
    }.get(aggregate)
    if aggregate_name is None:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "aggregate must be sum, avg, min, or max")

    stages = csv_values(qs, "stages")
    if not stages:
        legacy_stage = one_value(qs, "stage", "all")
        if legacy_stage and legacy_stage != "all":
            stages = [legacy_stage]
    if "stages" in qs and not stages:
        return {
            "query": {
                "targets": targets,
                "stats": stats,
                "granularity": granularity,
                "aggregate": aggregate,
                "stages": [],
                "apps": [],
                "shader": "",
                "shader_path_count": None,
                "from": one_value(qs, "from"),
                "to": one_value(qs, "to"),
            },
            "series": [],
            "failures": [],
            "changes": [],
        }

    apps = csv_values(qs, "apps")
    shader = one_value(qs, "shader")

    explicit_shader_paths = "shader_paths" in qs
    shader_paths = csv_values(qs, "shader_paths")
    if explicit_shader_paths and not shader_paths:
        return {
            "query": {
                "targets": targets,
                "stats": stats,
                "granularity": granularity,
                "aggregate": aggregate,
                "stages": stages,
                "apps": apps,
                "shader": shader,
                "shader_path_count": 0,
                "from": one_value(qs, "from"),
                "to": one_value(qs, "to"),
            },
            "series": [],
            "failures": [],
            "changes": [],
        }

    date_from = one_value(qs, "from")
    date_to = one_value(qs, "to")
    visible_runs = visible_run_rows(con, targets, date_from, date_to, history)
    boundary_runs = boundary_run_rows(con, targets, date_from, date_to, history)
    stable_runs = visible_runs or boundary_runs
    if not stable_runs:
        return {
            "query": {
                "targets": targets,
                "stats": stats,
                "granularity": granularity,
                "aggregate": aggregate,
                "stages": stages,
                "apps": apps,
                "shader": shader,
                "shader_path_count": len(shader_paths) if explicit_shader_paths else None,
                "from": date_from,
                "to": date_to,
                "stable_shader_set": True,
                "x_boundary_anchors": False,
            },
            "series": [],
            "failures": [],
            "changes": query_changes(con, qs, history),
        }

    shader_path_expr = "('shaders/' || a.name || '/' || sh.path)"
    shader_clauses: list[str] = []
    shader_params: list[object] = []
    if stages:
        shader_clauses.append(f"sh.stage IN ({placeholders(stages)})")
        shader_params.extend(stages)
    if apps:
        shader_clauses.append(f"a.name IN ({placeholders(apps)})")
        shader_params.extend(apps)
    if shader:
        shader_clauses.append(f"{shader_path_expr} LIKE ? ESCAPE '\\'")
        shader_params.append(f"%{escape_like(shader)}%")
    if shader_paths:
        add_in_filter(shader_clauses, shader_params, shader_path_expr, shader_paths)
    shader_where = f"WHERE {' AND '.join(shader_clauses)}" if shader_clauses else ""

    output_runs = unique_run_rows(
        [*boundary_runs, *output_run_rows(visible_runs, granularity, history)],
        history,
    )
    boundary_run_ids = {int(row["id"]) for row in boundary_runs}
    con.executescript(
        """
        DROP TABLE IF EXISTS temp.series_filtered_shaders;
        DROP TABLE IF EXISTS temp.series_stable_runs;
        DROP TABLE IF EXISTS temp.series_output_runs;
        DROP TABLE IF EXISTS temp.series_stable_keys;
        DROP TABLE IF EXISTS temp.series_stable_counts;
        DROP TABLE IF EXISTS temp.series_range_counts;

        CREATE TEMP TABLE series_filtered_shaders(
            shader_id INTEGER PRIMARY KEY,
            shader_path TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TEMP TABLE series_stable_runs(
            id INTEGER NOT NULL,
            target TEXT NOT NULL,
            PRIMARY KEY(id, target)
        ) WITHOUT ROWID;

        CREATE TEMP TABLE series_output_runs(
            id INTEGER PRIMARY KEY,
            target TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TEMP TABLE series_stable_keys(
            target TEXT NOT NULL,
            shader_id INTEGER NOT NULL,
            PRIMARY KEY(target, shader_id)
        ) WITHOUT ROWID;

        CREATE TEMP TABLE series_stable_counts(
            target TEXT PRIMARY KEY,
            stable_key_count INTEGER NOT NULL,
            stable_shader_count INTEGER NOT NULL
        ) WITHOUT ROWID;

        CREATE TEMP TABLE series_range_counts(
            target TEXT PRIMARY KEY,
            range_key_count INTEGER NOT NULL,
            range_shader_count INTEGER NOT NULL
        ) WITHOUT ROWID;
        """
    )
    con.executemany(
        "INSERT INTO temp.series_stable_runs(id, target) VALUES (?, ?)",
        [(row["id"], row["target"]) for row in stable_runs],
    )
    con.executemany(
        "INSERT INTO temp.series_output_runs(id, target) VALUES (?, ?)",
        [(row["id"], row["target"]) for row in output_runs],
    )
    con.execute(
        f"""
        INSERT INTO temp.series_filtered_shaders(shader_id, shader_path)
        SELECT sh.id, {shader_path_expr}
        FROM shaders sh
        JOIN apps a ON a.id = sh.app_id
        {shader_where}
        """,
        shader_params,
    )
    con.execute(
        """
        INSERT INTO temp.series_stable_keys(target, shader_id)
        WITH target_run_counts AS (
            SELECT target, count(*) AS run_count
            FROM temp.series_stable_runs
            GROUP BY target
        )
        SELECT sr.target, sv.shader_id
        FROM temp.series_stable_runs sr
        JOIN shader_stat_values sv ON sv.run_id = sr.id
        JOIN temp.series_filtered_shaders fs ON fs.shader_id = sv.shader_id
        JOIN target_run_counts trc ON trc.target = sr.target
        GROUP BY sr.target, sv.shader_id, trc.run_count
        HAVING count(*) = trc.run_count
        """
    )
    con.execute(
        """
        INSERT INTO temp.series_range_counts(
            target, range_key_count, range_shader_count
        )
        SELECT sr.target, count(DISTINCT sv.shader_id), count(DISTINCT fs.shader_path)
        FROM temp.series_stable_runs sr
        JOIN shader_stat_values sv ON sv.run_id = sr.id
        JOIN temp.series_filtered_shaders fs ON fs.shader_id = sv.shader_id
        GROUP BY sr.target
        """
    )
    con.execute(
        """
        INSERT INTO temp.series_stable_counts(
            target, stable_key_count, stable_shader_count
        )
        SELECT sk.target, count(*), count(DISTINCT fs.shader_path)
        FROM temp.series_stable_keys sk
        JOIN temp.series_filtered_shaders fs ON fs.shader_id = sk.shader_id
        GROUP BY sk.target
        """
    )

    stable_counts = {
        row["target"]: {
            "stable_key_count": row["stable_key_count"],
            "stable_shader_count": row["stable_shader_count"],
            "range_key_count": row["range_key_count"],
            "range_shader_count": row["range_shader_count"],
            "excluded_key_count": row["range_key_count"] - row["stable_key_count"],
            "excluded_shader_count": row["range_shader_count"] - row["stable_shader_count"],
        }
        for row in con.execute(
            """
            SELECT rc.target,
                   coalesce(sc.stable_key_count, 0) AS stable_key_count,
                   coalesce(sc.stable_shader_count, 0) AS stable_shader_count,
                   rc.range_key_count,
                   rc.range_shader_count
            FROM temp.series_range_counts rc
            LEFT JOIN temp.series_stable_counts sc ON sc.target = rc.target
            ORDER BY rc.target
            """
        )
    }

    if real_stats:
        selects = []
        for stat in real_stats:
            selects.append(
                f"""
                SELECT r.id AS run_id, r.target, r.commit_sha,
                       substr(r.commit_sha, 1, 12) AS short_sha,
                       c.author_date, c.subject, '{stat}' AS stat,
                       {aggregate_name}(sv.{stat}) AS value,
                       tsc.stable_key_count AS row_count,
                       tsc.stable_shader_count AS shader_count,
                       tsc.stable_key_count,
                       tsc.stable_shader_count
                FROM temp.series_output_runs vr
                JOIN runs r ON r.id = vr.id
                JOIN commits c ON c.sha = r.commit_sha
                JOIN temp.series_stable_keys sk ON sk.target = r.target
                JOIN shader_stat_values sv
                  ON sv.run_id = r.id
                 AND sv.shader_id = sk.shader_id
                JOIN temp.series_stable_counts tsc ON tsc.target = r.target
                GROUP BY r.id
                """
            )
        rows = con.execute(
            "\nUNION ALL\n".join(selects) + "\nORDER BY run_id, stat",
        ).fetchall()
    else:
        rows = []

    by_series: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        is_boundary = int(row["run_id"]) in boundary_run_ids
        display_date = history.date(row["commit_sha"], row["author_date"])
        if not is_boundary and not in_date_range(display_date, date_from, date_to):
            continue
        key = (row["target"], row["stat"])
        point = {
            "run_id": row["run_id"],
            "target": row["target"],
            "stat": row["stat"],
            "commit": row["commit_sha"],
            "short_commit": row["short_sha"],
            "date": display_date,
            "author_date": row["author_date"],
            "author": history.author(row["commit_sha"]),
            "order": history.order(row["commit_sha"]),
            "subject": history.subject(row["commit_sha"], row["subject"]),
            "message": history.message(row["commit_sha"], row["subject"]),
            "value": row["value"],
            "row_count": row["row_count"],
            "shader_count": row["shader_count"],
            "stable_key_count": row["stable_key_count"],
            "stable_shader_count": row["stable_shader_count"],
            "boundary": is_boundary,
        }
        by_series.setdefault(key, []).append(point)

    if include_lost_gained_delta:
        lost_gained_rows = con.execute(
            """
            SELECT r.id AS run_id, r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
                   c.author_date, c.subject,
                   count(*) AS present_key_count,
                   count(DISTINCT fs.shader_path) AS shader_count
            FROM temp.series_output_runs vr
            JOIN runs r ON r.id = vr.id
            JOIN commits c ON c.sha = r.commit_sha
            JOIN shader_stat_values sv ON sv.run_id = r.id
            JOIN temp.series_filtered_shaders fs ON fs.shader_id = sv.shader_id
            GROUP BY r.id
            ORDER BY r.id, r.target
            """,
        ).fetchall()
        by_target: dict[str, list[dict[str, object]]] = {}
        for row in lost_gained_rows:
            is_boundary = int(row["run_id"]) in boundary_run_ids
            display_date = history.date(row["commit_sha"], row["author_date"])
            if not is_boundary and not in_date_range(display_date, date_from, date_to):
                continue
            by_target.setdefault(row["target"], []).append(
                {
                    "run_id": row["run_id"],
                    "target": row["target"],
                    "stat": LOST_GAINED_DELTA_STAT,
                    "commit": row["commit_sha"],
                    "short_commit": row["short_sha"],
                    "date": display_date,
                    "author_date": row["author_date"],
                    "author": history.author(row["commit_sha"]),
                    "order": history.order(row["commit_sha"]),
                    "subject": history.subject(row["commit_sha"], row["subject"]),
                    "message": history.message(row["commit_sha"], row["subject"]),
                    "value": row["present_key_count"],
                    "row_count": row["present_key_count"],
                    "shader_count": row["shader_count"],
                    "stable_key_count": None,
                    "stable_shader_count": None,
                    "boundary": is_boundary,
                }
            )
        for target, points in by_target.items():
            points.sort(key=lambda point: (point["order"], point["date"], point["run_id"]))
            baseline_point = next((point for point in points if not point.get("boundary")), None)
            if baseline_point is None and points:
                baseline_point = points[0]
            baseline = int(baseline_point["value"]) if baseline_point else 0
            for point in points:
                point["value"] = int(point["value"]) - baseline
            by_series[(target, LOST_GAINED_DELTA_STAT)] = points

    series: list[dict[str, object]] = []
    for (target, stat), points in sorted(by_series.items()):
        points.sort(key=lambda point: (point["order"], point["date"], point["run_id"]))
        if granularity == "month":
            buckets: dict[str, dict[str, object]] = {}
            for point in points:
                buckets[iso_to_month(str(point["date"]))] = point
            chart_points = [
                {**point, "bucket": month}
                for month, point in sorted(buckets.items())
            ]
        else:
            chart_points = points
        chart_points = changed_points_only(chart_points)
        series.append(
            {
                "id": f"{target}:{stat}",
                "label": f"{target} {stat}",
                "target": target,
                "stat": stat,
                "points": chart_points,
            }
        )

    failure_clauses = [
        "r.shader_selection = 'shaders'",
        f"r.target IN ({placeholders(targets)})",
    ]
    failure_params: list[object] = [*targets]
    if shader_paths:
        add_in_filter(failure_clauses, failure_params, "f.shader_path", shader_paths)

    failure_rows = con.execute(
        f"""
        SELECT r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
               c.author_date, count(f.shader_path) AS failures
        FROM runs r
        JOIN commits c ON c.sha = r.commit_sha
        LEFT JOIN shader_failures f ON f.run_id = r.id
        WHERE {' AND '.join(failure_clauses)}
        GROUP BY r.id
        HAVING failures > 0
        ORDER BY r.id, r.target
        """,
        failure_params,
    ).fetchall()
    failures = []
    for row in failure_rows:
        item = dict(row)
        item["author_date"] = item["author_date"]
        item["date"] = history.date(item["commit_sha"], item["author_date"])
        item["order"] = history.order(item["commit_sha"])
        if in_date_range(item["date"], date_from, date_to):
            failures.append(item)
    failures.sort(key=lambda item: (item["order"], item["date"], item["target"]))

    return {
        "query": {
            "targets": targets,
            "stats": stats,
            "granularity": granularity,
            "aggregate": aggregate,
            "stages": stages,
            "apps": apps,
            "shader": shader,
            "shader_path_count": len(shader_paths) if explicit_shader_paths else None,
            "from": date_from,
            "to": date_to,
            "stable_shader_set": True,
            "stable_counts": stable_counts,
            "x_boundary_anchors": bool(boundary_runs),
        },
        "series": series,
        "failures": failures,
        "changes": query_changes(con, qs, history),
    }


def query_series(con: sqlite3.Connection, qs: dict[str, list[str]], history: HistoryOrder) -> dict[str, object]:
    if has_compact_v2_schema(con):
        return query_series_v2(con, qs, history)

    catalog_run_id = latest_catalog_run_id(con, history)
    available_stats = [
        r["stat"] for r in con.execute(
            "SELECT DISTINCT stat FROM shader_stats WHERE run_id = ?",
            (catalog_run_id,),
        )
    ]
    requested_stats = csv_values(qs, "stats", [s for s in DEFAULT_STATS if s in available_stats])
    stats = [
        s for s in requested_stats
        if s in available_stats or s == LOST_GAINED_DELTA_STAT
    ]
    if not stats:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "no valid stats selected")
    real_stats = [s for s in stats if s in available_stats]
    include_lost_gained_delta = LOST_GAINED_DELTA_STAT in stats

    requested_targets = csv_values(qs, "targets", list(TARGETS))
    targets = [t for t in requested_targets if t in TARGETS]
    if not targets:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "no valid targets selected")

    granularity = one_value(qs, "granularity", "month")
    if granularity not in {"month", "commit"}:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "granularity must be month or commit")
    aggregate = one_value(qs, "aggregate", "sum")
    aggregate_sql = {
        "sum": "sum(ss.value)",
        "avg": "avg(ss.value)",
        "min": "min(ss.value)",
        "max": "max(ss.value)",
    }.get(aggregate)
    if aggregate_sql is None:
        raise ResponseError(HTTPStatus.BAD_REQUEST, "aggregate must be sum, avg, min, or max")

    stages = csv_values(qs, "stages")
    if not stages:
        legacy_stage = one_value(qs, "stage", "all")
        if legacy_stage and legacy_stage != "all":
            stages = [legacy_stage]
    if "stages" in qs and not stages:
        return {
            "query": {
                "targets": targets,
                "stats": stats,
                "granularity": granularity,
                "aggregate": aggregate,
                "stages": [],
                "apps": [],
                "shader": "",
                "shader_path_count": None,
                "from": one_value(qs, "from"),
                "to": one_value(qs, "to"),
            },
            "series": [],
            "failures": [],
            "changes": [],
        }

    apps = csv_values(qs, "apps")
    shader = one_value(qs, "shader")

    explicit_shader_paths = "shader_paths" in qs
    shader_paths = csv_values(qs, "shader_paths")
    if explicit_shader_paths and not shader_paths:
        return {
            "query": {
                "targets": targets,
                "stats": stats,
                "granularity": granularity,
                "aggregate": aggregate,
                "stages": stages,
                "apps": apps,
                "shader": shader,
                "shader_path_count": 0,
                "from": one_value(qs, "from"),
                "to": one_value(qs, "to"),
            },
            "series": [],
            "failures": [],
            "changes": [],
        }

    date_from = one_value(qs, "from")
    date_to = one_value(qs, "to")
    visible_runs = visible_run_rows(con, targets, date_from, date_to, history)
    boundary_runs = boundary_run_rows(con, targets, date_from, date_to, history)
    stable_runs = visible_runs or boundary_runs
    if not stable_runs:
        return {
            "query": {
                "targets": targets,
                "stats": stats,
                "granularity": granularity,
                "aggregate": aggregate,
                "stages": stages,
                "apps": apps,
                "shader": shader,
                "shader_path_count": len(shader_paths) if explicit_shader_paths else None,
                "from": date_from,
                "to": date_to,
                "stable_shader_set": True,
                "x_boundary_anchors": False,
            },
            "series": [],
            "failures": [],
            "changes": query_changes(con, qs, history),
        }

    stable_clauses: list[str] = []
    stable_params: list[object] = []
    if stages:
        stable_clauses.append(f"ss.stage IN ({placeholders(stages)})")
        stable_params.extend(stages)
    if apps:
        stable_clauses.append(f"ss.app IN ({placeholders(apps)})")
        stable_params.extend(apps)
    if shader:
        stable_clauses.append("ss.shader_path LIKE ? ESCAPE '\\'")
        stable_params.append(f"%{escape_like(shader)}%")
    if shader_paths:
        add_in_filter(stable_clauses, stable_params, "ss.shader_path", shader_paths)

    presence_stat = "instructions" if "instructions" in available_stats else stats[0]
    stable_clauses.append("ss.stat = ?")
    stable_params.append(presence_stat)

    stable_where = f"WHERE {' AND '.join(stable_clauses)}" if stable_clauses else ""
    stable_values = ",".join("(?, ?)" for _ in stable_runs)
    stable_run_params: list[object] = []
    for row in stable_runs:
        stable_run_params.extend([row["id"], row["target"]])

    output_runs = unique_run_rows(
        [*boundary_runs, *output_run_rows(visible_runs, granularity, history)],
        history,
    )
    boundary_run_ids = {int(row["id"]) for row in boundary_runs}
    output_values = ",".join("(?, ?)" for _ in output_runs)
    output_run_params: list[object] = []
    for row in output_runs:
        output_run_params.extend([row["id"], row["target"]])

    if real_stats:
        rows = con.execute(
            f"""
            WITH stable_runs(id, target) AS (
                VALUES {stable_values}
            ),
            output_runs(id, target) AS (
                VALUES {output_values}
            ),
            target_run_counts AS (
                SELECT target, count(*) AS run_count
                FROM stable_runs
                GROUP BY target
            ),
            stable_keys AS (
                SELECT vr.target, ss.shader_path, ss.stage
                FROM stable_runs vr
                JOIN shader_stats ss ON ss.run_id = vr.id
                JOIN target_run_counts trc ON trc.target = vr.target
                {stable_where}
                GROUP BY vr.target, ss.shader_path, ss.stage, trc.run_count
                HAVING count(*) = trc.run_count
            ),
            target_stable_counts AS (
                SELECT target,
                       count(*) AS stable_key_count,
                       count(DISTINCT shader_path) AS stable_shader_count
                FROM stable_keys
                GROUP BY target
            )
            SELECT r.id AS run_id, r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
                   c.author_date, c.subject, ss.stat,
                   {aggregate_sql} AS value,
                   count(*) AS row_count,
                   count(DISTINCT ss.shader_path) AS shader_count,
                   tsc.stable_key_count,
                   tsc.stable_shader_count
            FROM output_runs vr
            JOIN runs r ON r.id = vr.id
            JOIN commits c ON c.sha = r.commit_sha
            JOIN shader_stats ss ON ss.run_id = r.id
            JOIN stable_keys sk
              ON sk.target = r.target
             AND sk.shader_path = ss.shader_path
             AND sk.stage = ss.stage
            JOIN target_stable_counts tsc ON tsc.target = r.target
            WHERE ss.stat IN ({placeholders(real_stats)})
            GROUP BY r.id, ss.stat
            ORDER BY r.id, ss.stat
            """,
            [*stable_run_params, *output_run_params, *stable_params, *real_stats],
        ).fetchall()
    else:
        rows = []

    stable_counts: dict[str, dict[str, object]] = {}
    by_series: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        is_boundary = int(row["run_id"]) in boundary_run_ids
        stable_counts.setdefault(
            row["target"],
            {
                "stable_key_count": row["stable_key_count"],
                "stable_shader_count": row["stable_shader_count"],
            },
        )
        display_date = history.date(row["commit_sha"], row["author_date"])
        if not is_boundary and not in_date_range(display_date, date_from, date_to):
            continue
        key = (row["target"], row["stat"])
        point = {
            "run_id": row["run_id"],
            "target": row["target"],
            "stat": row["stat"],
            "commit": row["commit_sha"],
            "short_commit": row["short_sha"],
            "date": display_date,
            "author_date": row["author_date"],
            "author": history.author(row["commit_sha"]),
            "order": history.order(row["commit_sha"]),
            "subject": history.subject(row["commit_sha"], row["subject"]),
            "message": history.message(row["commit_sha"], row["subject"]),
            "value": row["value"],
            "row_count": row["row_count"],
            "shader_count": row["shader_count"],
            "stable_key_count": row["stable_key_count"],
            "stable_shader_count": row["stable_shader_count"],
            "boundary": is_boundary,
        }
        by_series.setdefault(key, []).append(point)

    if include_lost_gained_delta:
        lost_gained_rows = con.execute(
            f"""
            WITH output_runs(id, target) AS (
                VALUES {output_values}
            )
            SELECT r.id AS run_id, r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
                   c.author_date, c.subject,
                   count(*) AS present_key_count,
                   count(DISTINCT ss.shader_path) AS shader_count
            FROM output_runs vr
            JOIN runs r ON r.id = vr.id
            JOIN commits c ON c.sha = r.commit_sha
            JOIN shader_stats ss ON ss.run_id = r.id
            {stable_where}
            GROUP BY r.id
            ORDER BY r.id, r.target
            """,
            [*output_run_params, *stable_params],
        ).fetchall()
        by_target: dict[str, list[dict[str, object]]] = {}
        for row in lost_gained_rows:
            is_boundary = int(row["run_id"]) in boundary_run_ids
            display_date = history.date(row["commit_sha"], row["author_date"])
            if not is_boundary and not in_date_range(display_date, date_from, date_to):
                continue
            by_target.setdefault(row["target"], []).append(
                {
                    "run_id": row["run_id"],
                    "target": row["target"],
                    "stat": LOST_GAINED_DELTA_STAT,
                    "commit": row["commit_sha"],
                    "short_commit": row["short_sha"],
                    "date": display_date,
                    "author_date": row["author_date"],
                    "author": history.author(row["commit_sha"]),
                    "order": history.order(row["commit_sha"]),
                    "subject": history.subject(row["commit_sha"], row["subject"]),
                    "message": history.message(row["commit_sha"], row["subject"]),
                    "value": row["present_key_count"],
                    "row_count": row["present_key_count"],
                    "shader_count": row["shader_count"],
                    "stable_key_count": None,
                    "stable_shader_count": None,
                    "boundary": is_boundary,
                }
            )
        for target, points in by_target.items():
            points.sort(key=lambda point: (point["order"], point["date"], point["run_id"]))
            baseline_point = next((point for point in points if not point.get("boundary")), None)
            if baseline_point is None and points:
                baseline_point = points[0]
            baseline = int(baseline_point["value"]) if baseline_point else 0
            for point in points:
                point["value"] = int(point["value"]) - baseline
            by_series[(target, LOST_GAINED_DELTA_STAT)] = points

    series: list[dict[str, object]] = []
    for (target, stat), points in sorted(by_series.items()):
        points.sort(key=lambda point: (point["order"], point["date"], point["run_id"]))
        if granularity == "month":
            buckets: dict[str, dict[str, object]] = {}
            for point in points:
                buckets[iso_to_month(str(point["date"]))] = point
            chart_points = [
                {**point, "bucket": month}
                for month, point in sorted(buckets.items())
            ]
        else:
            chart_points = points
        chart_points = changed_points_only(chart_points)
        series.append(
            {
                "id": f"{target}:{stat}",
                "label": f"{target} {stat}",
                "target": target,
                "stat": stat,
                "points": chart_points,
            }
        )

    failure_clauses = [
        "r.shader_selection = 'shaders'",
        f"r.target IN ({placeholders(targets)})",
    ]
    failure_params: list[object] = [*targets]
    if shader_paths:
        add_in_filter(failure_clauses, failure_params, "f.shader_path", shader_paths)

    failure_rows = con.execute(
        f"""
        SELECT r.target, r.commit_sha, substr(r.commit_sha, 1, 12) AS short_sha,
               c.author_date, count(f.shader_path) AS failures
        FROM runs r
        JOIN commits c ON c.sha = r.commit_sha
        LEFT JOIN shader_failures f ON f.run_id = r.id
        WHERE {' AND '.join(failure_clauses)}
        GROUP BY r.id
        HAVING failures > 0
        ORDER BY r.id, r.target
        """,
        failure_params,
    ).fetchall()
    failures = []
    for row in failure_rows:
        item = dict(row)
        item["author_date"] = item["author_date"]
        item["date"] = history.date(item["commit_sha"], item["author_date"])
        item["order"] = history.order(item["commit_sha"])
        if in_date_range(item["date"], date_from, date_to):
            failures.append(item)
    failures.sort(key=lambda item: (item["order"], item["date"], item["target"]))

    return {
        "query": {
            "targets": targets,
            "stats": stats,
            "granularity": granularity,
            "aggregate": aggregate,
            "stages": stages,
            "apps": apps,
            "shader": shader,
            "shader_path_count": len(shader_paths) if explicit_shader_paths else None,
            "from": date_from,
            "to": date_to,
            "stable_shader_set": True,
            "stable_counts": stable_counts,
            "x_boundary_anchors": bool(boundary_runs),
        },
        "series": series,
        "failures": failures,
        "changes": query_changes(con, qs, history),
    }


class Handler(BaseHTTPRequestHandler):
    server: "HistoryServer"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self.handle_api(parsed.path, parse_qs(parsed.query))
            else:
                self.handle_static(parsed.path)
        except ResponseError as exc:
            self.write_json({"error": exc.message}, status=exc.status)
        except Exception as exc:  # pragma: no cover - defensive server boundary.
            self.write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                raise ResponseError(HTTPStatus.NOT_FOUND, "not found")
            self.handle_api(parsed.path, self.read_json_query())
        except ResponseError as exc:
            self.write_json({"error": exc.message}, status=exc.status)
        except Exception as exc:  # pragma: no cover - defensive server boundary.
            self.write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {fmt % args}", file=sys.stderr)

    def read_json_query(self) -> dict[str, list[str]]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ResponseError(HTTPStatus.BAD_REQUEST, "invalid Content-Length") from exc
        if length > MAX_POST_BYTES:
            raise ResponseError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body too large")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ResponseError(HTTPStatus.BAD_REQUEST, "invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ResponseError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        qs: dict[str, list[str]] = {}
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, list):
                qs[str(key)] = [str(item) for item in value]
            else:
                qs[str(key)] = [str(value)]
        return qs

    def handle_api(self, path: str, qs: dict[str, list[str]]) -> None:
        with connect(self.server.db_path) as con:
            version = current_db_version(con)
            key = (path, tuple(sorted((k, tuple(v)) for k, v in qs.items())), version)
            cached = self.server.cache.get(key)
            if cached is not None:
                self.write_json(cached)
                return

            if path == "/api/meta":
                payload = query_meta(con, self.server.history)
            elif path == "/api/apps":
                payload = {"apps": query_apps(con, qs, self.server.history)}
            elif path == "/api/shaders":
                payload = {"shaders": query_shaders(con, qs, self.server.history)}
            elif path == "/api/shader-tree":
                payload = query_shader_tree(con, self.server.history)
            elif path == "/api/series":
                payload = query_series(con, qs, self.server.history)
            elif path == "/api/changes":
                payload = {"changes": query_changes(con, qs, self.server.history)}
            elif path == "/api/change-report":
                payload = query_change_report(con, qs, self.server.history)
            elif path == "/api/status":
                payload = {
                    "db_version": version,
                    "runs": con.execute("SELECT count(*) AS n FROM runs").fetchone()["n"],
                    "change_points": con.execute("SELECT count(*) AS n FROM change_points").fetchone()["n"],
                }
            else:
                raise ResponseError(HTTPStatus.NOT_FOUND, "unknown API endpoint")

            self.server.cache.put(key, payload)
            self.write_json(payload)

    def handle_static(self, path: str) -> None:
        if path in {"", "/"}:
            rel = "index.html"
        else:
            rel = unquote(path.lstrip("/"))
        full = (self.server.web_root / rel).resolve()
        web_root = self.server.web_root.resolve()
        if not full.is_file() or web_root not in full.parents and full != web_root:
            raise ResponseError(HTTPStatus.NOT_FOUND, "not found")
        content_type = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
        data = full.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def write_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class HistoryServer(ThreadingHTTPServer):
    def __init__(self, addr: tuple[str, int], db_path: Path, web_root: Path, history: HistoryOrder):
        super().__init__(addr, Handler)
        self.db_path = db_path
        self.web_root = web_root
        self.history = history
        self.cache = QueryCache()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--web-root", type=Path, default=DEFAULT_WEB)
    parser.add_argument("--mesa-repo", type=Path, default=DEFAULT_MESA_REPO)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default="HEAD")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if not args.db.exists():
        parser.error(f"database does not exist: {args.db}")
    if not args.web_root.exists():
        parser.error(f"web root does not exist: {args.web_root}")

    history = HistoryOrder.load_from_db(args.db)
    history_source = f"embedded database history from {args.db}"
    if history is None:
        try:
            history = HistoryOrder.load(args.mesa_repo, args.start, args.end)
        except (OSError, subprocess.CalledProcessError) as exc:
            parser.error(f"failed to read Mesa first-parent history: {exc}")
        history_source = f"Mesa first-parent order from {args.start[:12]} to {args.end}"

    server = HistoryServer((args.host, args.port), args.db.resolve(), args.web_root.resolve(), history)
    print(f"Serving r300 shader-db history at http://{args.host}:{args.port}/")
    print(f"Using database {args.db}")
    print(f"Using {history_source}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
