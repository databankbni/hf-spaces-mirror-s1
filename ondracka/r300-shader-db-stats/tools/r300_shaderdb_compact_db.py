#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavel Ondračka
"""Build the compact SQLite database used by the web viewer."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "results" / "shaderdb-history.sqlite"
DEFAULT_OUTPUT = ROOT / "results" / "shaderdb-web.sqlite"
DEFAULT_START = "17cea74b8cd3b1a56d923edeb40772b3e8b18ab2"
DEFAULT_EXCLUDE_COMMITS = (
    "2173843e119ea5cddb571ed9cee962bab36698ab",
    "b55836a74dfabfe22b0210a24500b44b39e99069",
    "cbfc225e2bda2c8627a4580fa3a9b63bfb7133e0",
    "d314f1243fe2510032e779290db124b0e4f0d71e",
)
DEFAULT_DROP_STATS = ("sinst", "vinst", "predicate", "flowcontrol", "tex")
WIDE_STATS = ("consts", "cycles", "instructions", "lits", "loops", "omod", "presub", "temps")


def sql_objects(con: sqlite3.Connection, object_type: str) -> list[str]:
    rows = con.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = ? AND sql IS NOT NULL AND name != 'sqlite_sequence'
        ORDER BY name
        """,
        (object_type,),
    )
    return [row[0] for row in rows]


def history_rows(mesa_repo: Path, start_sha: str, end: str) -> list[tuple[str, int, str, str, str, str]]:
    fmt = "%H%x1f%cI%x1f%aN <%aE>%x1f%B%x1e"
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(mesa_repo),
            "log",
            "--first-parent",
            "--reverse",
            f"--format={fmt}",
            f"{start_sha}^..{end}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    rows: list[tuple[str, int, str, str, str, str]] = []
    text = proc.stdout.decode("utf-8", errors="replace")
    for order, raw in enumerate(text.split("\x1e")):
        raw = raw.strip("\n")
        if not raw:
            continue
        sha, commit_date, author, message = raw.split("\x1f", 3)
        message = message.strip()
        subject = message.splitlines()[0] if message else ""
        rows.append((sha, order, commit_date, author, subject, message))
    return rows


def source_has_table(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone() is not None


def relative_shader_path_sql(alias: str) -> str:
    return f"""
        CASE
            WHEN substr({alias}.shader_path, 1, length('shaders/' || {alias}.app || '/')) =
                 'shaders/' || {alias}.app || '/'
            THEN substr({alias}.shader_path, length('shaders/' || {alias}.app || '/') + 1)
            WHEN substr({alias}.shader_path, 1, 8) = 'shaders/'
            THEN substr({alias}.shader_path, 9)
            ELSE {alias}.shader_path
        END
    """


def shader_stats_view_sql() -> str:
    selects = []
    for stat in WIDE_STATS:
        selects.append(
            f"""
            SELECT sv.run_id, a.name AS app,
                   'shaders/' || a.name || '/' || s.path AS shader_path,
                   s.stage, '{stat}' AS stat, sv.{stat} AS value
            FROM shader_stat_values sv
            JOIN shaders s ON s.id = sv.shader_id
            JOIN apps a ON a.id = s.app_id
            """
        )
    return "CREATE VIEW shader_stats AS\n" + "\nUNION ALL\n".join(selects)


def parse_commit_args(values: list[str]) -> list[str]:
    commits: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw_commit in value.split(","):
            commit = raw_commit.strip()
            if commit and commit not in seen:
                commits.append(commit)
                seen.add(commit)
    return commits


def build_compact_db(
    source: Path,
    output: Path,
    start_sha: str,
    mesa_repo: Path | None,
    end: str,
    drop_stats: list[str],
    exclude_commits: list[str],
) -> dict[str, int]:
    tmp = output.with_name(f".{output.name}.tmp")
    if tmp.exists():
        tmp.unlink()

    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as src:
        table_sql = sql_objects(src, "table")
        index_sql = sql_objects(src, "index")

    history = history_rows(mesa_repo, start_sha, end) if mesa_repo is not None else []

    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(tmp) as dst:
        dst.execute("PRAGMA journal_mode = WAL")
        dst.execute("PRAGMA foreign_keys = OFF")
        for sql in table_sql:
            dst.execute(sql)
        dst.execute(
            """
            CREATE TABLE history_commits(
                sha TEXT PRIMARY KEY,
                first_parent_order INTEGER NOT NULL,
                commit_date TEXT NOT NULL,
                author TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        if history:
            dst.executemany(
                """
                INSERT INTO history_commits(
                    sha, first_parent_order, commit_date, author, subject, message
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                history,
            )
        dst.execute("ATTACH DATABASE ? AS src", (str(source.resolve()),))
        dst.execute("CREATE TEMP TABLE keep_commits(sha TEXT PRIMARY KEY)")
        dst.execute("CREATE TEMP TABLE drop_stats(stat TEXT PRIMARY KEY)")
        dst.execute("CREATE TEMP TABLE exclude_commits(sha TEXT PRIMARY KEY)")
        dst.executemany(
            "INSERT INTO drop_stats(stat) VALUES (?)",
            [(stat,) for stat in drop_stats],
        )
        dst.executemany(
            "INSERT INTO exclude_commits(sha) VALUES (?)",
            [(commit,) for commit in exclude_commits],
        )
        dst.execute(
            """
            DELETE FROM history_commits
            WHERE sha IN (SELECT sha FROM exclude_commits)
            """
        )
        if history:
            dst.execute(
                """
                INSERT OR IGNORE INTO keep_commits(sha)
                SELECT DISTINCT cp.to_sha
                FROM src.change_points cp
                JOIN main.history_commits h_to ON h_to.sha = cp.to_sha
                JOIN main.history_commits h_from ON h_from.sha = cp.from_sha
                """
            )
        else:
            dst.execute(
                """
                INSERT OR IGNORE INTO keep_commits(sha)
                SELECT DISTINCT to_sha FROM src.change_points
                """
            )
        dst.execute("INSERT OR IGNORE INTO keep_commits(sha) VALUES (?)", (start_sha,))
        dst.execute(
            """
            DELETE FROM keep_commits
            WHERE sha IN (SELECT sha FROM exclude_commits)
            """
        )

        dst.execute(
            """
            INSERT INTO commits
            SELECT c.*
            FROM src.commits c
            JOIN keep_commits k ON k.sha = c.sha
            """
        )
        dst.execute(
            """
            INSERT INTO runs
            SELECT r.*
            FROM src.runs r
            JOIN keep_commits k ON k.sha = r.commit_sha
            WHERE r.shader_selection = 'shaders' AND r.status = 'ok'
            """
        )
        dst.execute(
            """
            INSERT INTO shader_stats
            SELECT ss.*
            FROM src.shader_stats ss
            JOIN main.runs r ON r.id = ss.run_id
            LEFT JOIN drop_stats ds ON ds.stat = ss.stat
            WHERE ds.stat IS NULL
            """
        )
        dst.execute(
            """
            INSERT INTO shader_failures
            SELECT sf.*
            FROM src.shader_failures sf
            JOIN main.runs r ON r.id = sf.run_id
            """
        )
        dst.execute(
            """
            INSERT INTO change_points
            SELECT cp.*
            FROM src.change_points cp
            JOIN main.commits c ON c.sha = cp.to_sha
            LEFT JOIN main.history_commits h_to ON h_to.sha = cp.to_sha
            LEFT JOIN main.history_commits h_from ON h_from.sha = cp.from_sha
            LEFT JOIN exclude_commits ex_to ON ex_to.sha = cp.to_sha
            LEFT JOIN exclude_commits ex_from ON ex_from.sha = cp.from_sha
            WHERE ex_to.sha IS NULL
              AND ex_from.sha IS NULL
              AND (
                   (SELECT count(*) FROM main.history_commits) = 0
                   OR (h_to.sha IS NOT NULL AND h_from.sha IS NOT NULL)
              )
            """
        )
        for sql in index_sql:
            dst.execute(sql)
        dst.execute(
            """
            CREATE INDEX IF NOT EXISTS shader_stats_run_stat_lookup
                ON shader_stats(run_id, stat, shader_path, stage)
            """
        )
        dst.execute("PRAGMA foreign_keys = ON")
        counts = {
            "commits": dst.execute("SELECT count(*) FROM commits").fetchone()[0],
            "history_commits": dst.execute("SELECT count(*) FROM history_commits").fetchone()[0],
            "runs": dst.execute("SELECT count(*) FROM runs").fetchone()[0],
            "shader_stats": dst.execute("SELECT count(*) FROM shader_stats").fetchone()[0],
            "shader_failures": dst.execute("SELECT count(*) FROM shader_failures").fetchone()[0],
            "change_points": dst.execute("SELECT count(*) FROM change_points").fetchone()[0],
            "dropped_stats": len(drop_stats),
        }

    tmp.replace(output)
    return counts


def build_compact_db_v2(
    source: Path,
    output: Path,
    start_sha: str,
    mesa_repo: Path | None,
    end: str,
    drop_stats: list[str],
    keep_source_runs: bool,
    exclude_commits: list[str],
) -> dict[str, int]:
    tmp = output.with_name(f".{output.name}.tmp")
    if tmp.exists():
        tmp.unlink()

    history = history_rows(mesa_repo, start_sha, end) if mesa_repo is not None else []
    rel_path = relative_shader_path_sql("ss")
    stat_columns = ", ".join(WIDE_STATS)
    stat_values = ", ".join(
        f"max(CASE WHEN ss.stat = '{stat}' THEN ss.value END) AS {stat}"
        for stat in WIDE_STATS
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(tmp) as dst:
        dst.execute("PRAGMA journal_mode = WAL")
        dst.execute("PRAGMA foreign_keys = OFF")
        dst.executescript(
            """
            CREATE TABLE commits (
                sha TEXT PRIMARY KEY,
                author_date TEXT NOT NULL,
                subject TEXT NOT NULL
            );

            CREATE TABLE runs (
                id INTEGER PRIMARY KEY,
                commit_sha TEXT NOT NULL,
                target TEXT NOT NULL,
                gpu_id TEXT NOT NULL,
                shader_selection TEXT NOT NULL,
                normalizer_version TEXT NOT NULL,
                status TEXT NOT NULL,
                return_code INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_s REAL NOT NULL,
                stats_count INTEGER NOT NULL DEFAULT 0,
                stats_fingerprint TEXT NOT NULL DEFAULT '',
                raw_output_path TEXT NOT NULL,
                stderr_path TEXT NOT NULL,
                build_log_path TEXT NOT NULL,
                run_command TEXT NOT NULL,
                UNIQUE(commit_sha, target, shader_selection, normalizer_version)
            );

            CREATE TABLE apps (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE shaders (
                id INTEGER PRIMARY KEY,
                app_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                stage TEXT NOT NULL,
                UNIQUE(app_id, path, stage)
            );

            CREATE TABLE shader_stat_values (
                run_id INTEGER NOT NULL,
                shader_id INTEGER NOT NULL,
                consts INTEGER NOT NULL,
                cycles INTEGER NOT NULL,
                instructions INTEGER NOT NULL,
                lits INTEGER NOT NULL,
                loops INTEGER NOT NULL,
                omod INTEGER NOT NULL,
                presub INTEGER NOT NULL,
                temps INTEGER NOT NULL,
                PRIMARY KEY(run_id, shader_id)
            ) WITHOUT ROWID;

            CREATE TABLE shader_failures (
                run_id INTEGER NOT NULL,
                shader_path TEXT NOT NULL,
                return_code INTEGER NOT NULL,
                stderr_path TEXT NOT NULL,
                PRIMARY KEY(run_id, shader_path)
            ) WITHOUT ROWID;

            CREATE TABLE change_points (
                id INTEGER PRIMARY KEY,
                start_sha TEXT NOT NULL,
                end_sha TEXT NOT NULL,
                mode TEXT NOT NULL,
                from_sha TEXT NOT NULL,
                to_sha TEXT NOT NULL,
                target_set TEXT NOT NULL,
                shader_selection TEXT NOT NULL,
                normalizer_version TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                UNIQUE(start_sha, end_sha, mode, from_sha, to_sha, target_set,
                       shader_selection, normalizer_version)
            );

            CREATE TABLE history_commits(
                sha TEXT PRIMARY KEY,
                first_parent_order INTEGER NOT NULL,
                commit_date TEXT NOT NULL,
                author TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL
            );
            """
        )
        dst.execute("ATTACH DATABASE ? AS src", (str(source.resolve()),))
        dst.execute("CREATE TEMP TABLE keep_commits(sha TEXT PRIMARY KEY)")
        dst.execute("CREATE TEMP TABLE drop_stats(stat TEXT PRIMARY KEY)")
        dst.execute("CREATE TEMP TABLE exclude_commits(sha TEXT PRIMARY KEY)")
        dst.executemany(
            "INSERT INTO drop_stats(stat) VALUES (?)",
            [(stat,) for stat in drop_stats],
        )
        dst.executemany(
            "INSERT INTO exclude_commits(sha) VALUES (?)",
            [(commit,) for commit in exclude_commits],
        )
        if history:
            dst.executemany(
                """
                INSERT INTO history_commits(
                    sha, first_parent_order, commit_date, author, subject, message
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                history,
            )
        else:
            src_has_history = dst.execute(
                """
                SELECT 1
                FROM src.sqlite_master
                WHERE type = 'table' AND name = 'history_commits'
                """
            ).fetchone() is not None
            if src_has_history:
                history_columns = [
                    str(row[1]) for row in dst.execute("PRAGMA src.table_info(history_commits)")
                ]
                if "author" in history_columns:
                    dst.execute(
                        """
                        INSERT INTO history_commits(
                            sha, first_parent_order, commit_date, author, subject, message
                        )
                        SELECT sha, first_parent_order, commit_date, author, subject, message
                        FROM src.history_commits
                        """
                    )
                else:
                    dst.execute(
                        """
                        INSERT INTO history_commits(
                            sha, first_parent_order, commit_date, author, subject, message
                        )
                        SELECT sha, first_parent_order, commit_date, '', subject, message
                        FROM src.history_commits
                        """
                    )
        dst.execute(
            """
            DELETE FROM history_commits
            WHERE sha IN (SELECT sha FROM exclude_commits)
            """
        )

        if dst.execute("SELECT count(*) FROM history_commits").fetchone()[0]:
            dst.execute(
                """
                INSERT OR IGNORE INTO keep_commits(sha)
                SELECT DISTINCT cp.to_sha
                FROM src.change_points cp
                JOIN main.history_commits h_to ON h_to.sha = cp.to_sha
                JOIN main.history_commits h_from ON h_from.sha = cp.from_sha
                """
            )
        else:
            dst.execute(
                """
                INSERT OR IGNORE INTO keep_commits(sha)
                SELECT DISTINCT to_sha FROM src.change_points
                """
            )
        dst.execute("INSERT OR IGNORE INTO keep_commits(sha) VALUES (?)", (start_sha,))
        if keep_source_runs:
            dst.execute(
                """
                INSERT OR IGNORE INTO keep_commits(sha)
                SELECT DISTINCT commit_sha
                FROM src.runs
                WHERE shader_selection = 'shaders' AND status = 'ok'
                """
            )
        dst.execute(
            """
            DELETE FROM keep_commits
            WHERE sha IN (SELECT sha FROM exclude_commits)
            """
        )

        dst.execute(
            """
            INSERT INTO commits
            SELECT c.*
            FROM src.commits c
            JOIN keep_commits k ON k.sha = c.sha
            """
        )
        dst.execute(
            """
            INSERT INTO runs
            SELECT r.*
            FROM src.runs r
            JOIN keep_commits k ON k.sha = r.commit_sha
            WHERE r.shader_selection = 'shaders' AND r.status = 'ok'
            """
        )
        dst.execute(
            """
            INSERT INTO apps(id, name)
            SELECT row_number() OVER (ORDER BY app), app
            FROM (
                SELECT DISTINCT ss.app AS app
                FROM src.shader_stats ss
                JOIN main.runs r ON r.id = ss.run_id
                LEFT JOIN drop_stats ds ON ds.stat = ss.stat
                WHERE ds.stat IS NULL
            )
            """
        )
        dst.execute(
            f"""
            INSERT INTO shaders(id, app_id, path, stage)
            SELECT row_number() OVER (ORDER BY a.name, keys.path, keys.stage),
                   a.id, keys.path, keys.stage
            FROM (
                SELECT DISTINCT ss.app AS app, {rel_path} AS path, ss.stage AS stage
                FROM src.shader_stats ss
                JOIN main.runs r ON r.id = ss.run_id
                LEFT JOIN drop_stats ds ON ds.stat = ss.stat
                WHERE ds.stat IS NULL
            ) keys
            JOIN apps a ON a.name = keys.app
            """
        )
        dst.execute(
            f"""
            INSERT INTO shader_stat_values(run_id, shader_id, {stat_columns})
            SELECT ss.run_id, sh.id, {stat_values}
            FROM src.shader_stats ss
            JOIN main.runs r ON r.id = ss.run_id
            JOIN apps a ON a.name = ss.app
            JOIN shaders sh
              ON sh.app_id = a.id
             AND sh.path = {rel_path}
             AND sh.stage = ss.stage
            LEFT JOIN drop_stats ds ON ds.stat = ss.stat
            WHERE ds.stat IS NULL
            GROUP BY ss.run_id, sh.id
            """
        )
        dst.execute(
            """
            INSERT INTO shader_failures
            SELECT sf.*
            FROM src.shader_failures sf
            JOIN main.runs r ON r.id = sf.run_id
            """
        )
        dst.execute(
            """
            INSERT INTO change_points
            SELECT cp.*
            FROM src.change_points cp
            JOIN main.commits c ON c.sha = cp.to_sha
            LEFT JOIN main.history_commits h_to ON h_to.sha = cp.to_sha
            LEFT JOIN main.history_commits h_from ON h_from.sha = cp.from_sha
            LEFT JOIN exclude_commits ex_to ON ex_to.sha = cp.to_sha
            LEFT JOIN exclude_commits ex_from ON ex_from.sha = cp.from_sha
            WHERE ex_to.sha IS NULL
              AND ex_from.sha IS NULL
              AND (
                   (SELECT count(*) FROM main.history_commits) = 0
                   OR (h_to.sha IS NOT NULL AND h_from.sha IS NOT NULL)
              )
            """
        )
        dst.execute("CREATE TEMP TABLE needed_history(sha TEXT PRIMARY KEY)")
        dst.execute(
            """
            INSERT OR IGNORE INTO needed_history(sha)
            SELECT commit_sha FROM runs
            """
        )
        dst.execute(
            """
            INSERT OR IGNORE INTO needed_history(sha)
            SELECT from_sha FROM change_points
            """
        )
        dst.execute(
            """
            INSERT OR IGNORE INTO needed_history(sha)
            SELECT to_sha FROM change_points
            """
        )
        dst.execute(
            """
            DELETE FROM history_commits
            WHERE sha NOT IN (SELECT sha FROM needed_history)
            """
        )
        dst.execute(shader_stats_view_sql())
        dst.executescript(
            """
            CREATE INDEX runs_commit_lookup
                ON runs(commit_sha, target, shader_selection, normalizer_version);
            CREATE INDEX shaders_app_stage_lookup
                ON shaders(app_id, stage, path, id);
            CREATE INDEX shaders_path_stage_lookup
                ON shaders(path, stage, app_id, id);
            CREATE INDEX shader_stat_values_shader_run_lookup
                ON shader_stat_values(shader_id, run_id);
            """
        )
        dst.execute("PRAGMA foreign_keys = ON")
        counts = {
            "commits": dst.execute("SELECT count(*) FROM commits").fetchone()[0],
            "history_commits": dst.execute("SELECT count(*) FROM history_commits").fetchone()[0],
            "runs": dst.execute("SELECT count(*) FROM runs").fetchone()[0],
            "apps": dst.execute("SELECT count(*) FROM apps").fetchone()[0],
            "shaders": dst.execute("SELECT count(*) FROM shaders").fetchone()[0],
            "shader_stat_values": dst.execute(
                "SELECT count(*) FROM shader_stat_values"
            ).fetchone()[0],
            "shader_stats_view_rows": dst.execute("SELECT count(*) FROM shader_stats").fetchone()[0],
            "shader_failures": dst.execute("SELECT count(*) FROM shader_failures").fetchone()[0],
            "change_points": dst.execute("SELECT count(*) FROM change_points").fetchone()[0],
            "dropped_stats": len(drop_stats),
        }

    tmp.replace(output)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--schema-version", type=int, choices=(1, 2), default=1)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument(
        "--exclude-commit",
        action="append",
        default=[],
        help="commit SHA to exclude from the compact DB; may be repeated or comma-separated",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="do not apply the built-in compact DB commit exclusions",
    )
    parser.add_argument(
        "--drop-stats",
        default=",".join(DEFAULT_DROP_STATS),
        help="comma-separated shader_stats.stat names to omit from the compact DB",
    )
    parser.add_argument("--mesa-repo", type=Path, default=ROOT / "mesa")
    parser.add_argument("--end", default="HEAD")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="do not embed Mesa first-parent commit metadata",
    )
    parser.add_argument(
        "--keep-source-runs",
        action="store_true",
        help="v2 only: keep every ok shader run already present in the source DB",
    )
    args = parser.parse_args(argv)

    if not args.source.exists():
        parser.error(f"source database does not exist: {args.source}")
    mesa_repo = None if args.no_history else args.mesa_repo
    if mesa_repo is not None and not mesa_repo.exists():
        parser.error(f"Mesa repository does not exist: {mesa_repo}")

    drop_stats = [stat.strip() for stat in args.drop_stats.split(",") if stat.strip()]
    exclude_commits = []
    if not args.no_default_excludes:
        exclude_commits.extend(DEFAULT_EXCLUDE_COMMITS)
    exclude_commits.extend(parse_commit_args(args.exclude_commit))
    exclude_commits = parse_commit_args(exclude_commits)
    if args.start in exclude_commits:
        parser.error(f"start commit cannot be excluded: {args.start}")
    if args.schema_version == 1:
        counts = build_compact_db(
            args.source,
            args.output,
            args.start,
            mesa_repo,
            args.end,
            drop_stats,
            exclude_commits,
        )
    else:
        counts = build_compact_db_v2(
            args.source,
            args.output,
            args.start,
            mesa_repo,
            args.end,
            drop_stats,
            args.keep_source_runs,
            exclude_commits,
        )
    print(f"Wrote {args.output}")
    for name, value in counts.items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
