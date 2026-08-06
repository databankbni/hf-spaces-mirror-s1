#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavel Ondračka
"""
Collect r300 shader-db statistics across Mesa history.

The collector intentionally keeps generated state outside the Mesa checkout:
it uses a separate git worktree, stores raw shader-db output on disk, and
indexes parsed stats in SQLite for later visualization.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
from typing import Iterable


START_FLOOR = "d4b6d03408a800926e5ffcb6a5fb2df39a59154e"
NORMALIZER_VERSION = "r300-current-stats-v1"
SHADOWRECT_PRECOMPILE_FIX = "c38023a9b2c90a0d8321428d5001914ec65823a9"

TARGETS = {
    "r3xx": "RV370",
    "r4xx": "RV410",
    "r5xx": "RV515",
}

DEFAULT_MESON_OPTIONS = [
    "-Dgallium-drivers=r300",
    "-Dvulkan-drivers=",
    "-Dplatforms=x11",
    "-Dgbm=enabled",
    "-Degl=enabled",
    "-Dglx=disabled",
    "-Dllvm=disabled",
    "-Dbuild-tests=false",
    "-Dtools=drm-shim",
]

STAT_NAME_ALIASES = {
    "inst": "instructions",
}

DEFAULT_RELEVANT_PATHS = [
    "include",
    "meson.build",
    "src/meson.build",
    "src/compiler",
    "src/mesa",
    "src/gallium/auxiliary",
    "src/gallium/drivers/r300",
    "src/gallium/frontends/dri",
    "src/gallium/include",
    "src/gallium/targets/dri",
    "src/gallium/winsys/radeon",
    "src/util",
]

DEFAULT_GUIDED_GREP = r"(?=.*\br300\b)(?=.*shader[- ]?db)"


def log(msg: str) -> None:
    print(msg, flush=True)


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    append: bool = False,
    timeout: float | None = None,
    memory_limit_mb: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    stdout = subprocess.PIPE
    stderr = subprocess.PIPE
    out_handle = None
    err_handle = None
    try:
        if stdout_path:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            out_handle = stdout_path.open("ab" if append else "wb")
            stdout = out_handle
        if stderr_path:
            if stdout_path and stderr_path == stdout_path:
                stderr = subprocess.STDOUT
            else:
                stderr_path.parent.mkdir(parents=True, exist_ok=True)
                err_handle = stderr_path.open("ab" if append else "wb")
                stderr = err_handle
        preexec_fn = None
        if memory_limit_mb:
            memory_limit = memory_limit_mb * 1024 * 1024

            def set_memory_limit() -> None:
                resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

            preexec_fn = set_memory_limit

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                preexec_fn=preexec_fn,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(cmd, 124, exc.output, exc.stderr)
    finally:
        if out_handle:
            out_handle.close()
        if err_handle:
            err_handle.close()

    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
    return proc


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = run_cmd(["git", "-C", str(repo), *args], check=check)
    if proc.stdout is None:
        return ""
    return proc.stdout.decode("utf-8", errors="replace").strip()


def resolve_commit(repo: Path, rev: str) -> str:
    return git(repo, "rev-parse", f"{rev}^{{commit}}")


def commit_metadata(repo: Path, sha: str) -> dict[str, str]:
    fmt = "%H%x00%aI%x00%s"
    out = git(repo, "show", "-s", f"--format={fmt}", sha)
    full_sha, date, subject = out.split("\x00", 2)
    return {"sha": full_sha, "author_date": date, "subject": subject}


def first_parent(repo: Path, sha: str) -> str | None:
    out = git(repo, "rev-list", "--parents", "-n", "1", sha)
    fields = out.split()
    if len(fields) < 2:
        return None
    return fields[1]


def ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS commits (
            sha TEXT PRIMARY KEY,
            author_date TEXT NOT NULL,
            subject TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            UNIQUE(commit_sha, target, shader_selection, normalizer_version),
            FOREIGN KEY(commit_sha) REFERENCES commits(sha)
        );

        CREATE TABLE IF NOT EXISTS shader_stats (
            run_id INTEGER NOT NULL,
            app TEXT NOT NULL,
            shader_path TEXT NOT NULL,
            stage TEXT NOT NULL,
            stat TEXT NOT NULL,
            value INTEGER NOT NULL,
            PRIMARY KEY(run_id, shader_path, stage, stat),
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS shader_failures (
            run_id INTEGER NOT NULL,
            shader_path TEXT NOT NULL,
            return_code INTEGER NOT NULL,
            stderr_path TEXT NOT NULL,
            PRIMARY KEY(run_id, shader_path),
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS change_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        CREATE INDEX IF NOT EXISTS shader_stats_lookup
            ON shader_stats(shader_path, stage, stat);
        CREATE INDEX IF NOT EXISTS shader_stats_app_lookup
            ON shader_stats(app, stage, stat);
        CREATE INDEX IF NOT EXISTS shader_stats_run_stat_lookup
            ON shader_stats(run_id, stat, shader_path, stage);
        CREATE INDEX IF NOT EXISTS runs_commit_lookup
            ON runs(commit_sha, target, shader_selection, normalizer_version);
        """
    )
    return con


def insert_commit(con: sqlite3.Connection, meta: dict[str, str]) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO commits(sha, author_date, subject)
        VALUES (?, ?, ?)
        """,
        (meta["sha"], meta["author_date"], meta["subject"]),
    )


def shader_app(shader_path: str) -> str:
    parts = Path(shader_path).parts
    if len(parts) >= 2 and parts[0] == "shaders":
        return parts[1]
    if len(parts) >= 1:
        return parts[0]
    return ""


def parse_shaderdb_output(raw_path: Path) -> list[tuple[str, str, str, str, int]]:
    rows: list[tuple[str, str, str, str, int]] = []
    line_re = re.compile(r"^(?P<shader>\S+) - (?P<stage>.*?) shader: (?P<stats>.*)$")

    with raw_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            match = line_re.match(line)
            if not match:
                continue

            shader = match.group("shader")
            stage = match.group("stage")
            stats = match.group("stats")
            app = shader_app(shader)

            for item in stats.split(", "):
                parts = item.strip().split()
                if len(parts) != 2:
                    continue
                value_s, name = parts
                if not value_s.isdecimal():
                    continue
                name = STAT_NAME_ALIASES.get(name, name)
                rows.append((app, shader, stage, name, int(value_s)))

    return rows


def parse_finished_shaders(raw_path: Path, err_path: Path) -> set[str]:
    finished: set[str] = set()
    stat_re = re.compile(r"^(?P<shader>\S+) - .*? shader: ")
    skip_re = re.compile(r"^SKIP: (?P<shader>\S+) ")

    if raw_path.exists():
        with raw_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                match = stat_re.match(line)
                if match:
                    finished.add(match.group("shader"))

    if err_path.exists():
        with err_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                match = skip_re.match(line)
                if match:
                    finished.add(match.group("shader"))

    return finished


def parse_crashed_shaders(err_path: Path) -> list[str]:
    crashed: list[str] = []
    if not err_path.exists():
        return crashed

    in_crash_list = False
    with err_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if "=> CRASHED <= while processing these shaders:" in stripped:
                in_crash_list = True
                continue
            if not in_crash_list:
                continue
            if not stripped:
                if crashed:
                    break
                continue
            crashed.append(stripped)
    return crashed


def fingerprint_stats(rows: Iterable[tuple[str, str, str, str, int]]) -> str:
    h = hashlib.sha256()
    for app, shader, stage, stat, value in sorted(rows):
        del app
        h.update(shader.encode())
        h.update(b"\0")
        h.update(stage.encode())
        h.update(b"\0")
        h.update(stat.encode())
        h.update(b"\0")
        h.update(str(value).encode())
        h.update(b"\n")
    return h.hexdigest()


def fingerprint_failures(rows: Iterable[tuple[str, int]]) -> str:
    h = hashlib.sha256()
    for shader, return_code in sorted(rows):
        h.update(shader.encode())
        h.update(b"\0")
        h.update(str(return_code).encode())
        h.update(b"\n")
    return h.hexdigest()


def store_run(
    con: sqlite3.Connection,
    *,
    commit_sha: str,
    target: str,
    gpu_id: str,
    shader_selection: str,
    status: str,
    return_code: int,
    started_at: str,
    finished_at: str,
    duration_s: float,
    raw_output_path: Path,
    stderr_path: Path,
    build_log_path: Path,
    run_command: list[str],
    rows: list[tuple[str, str, str, str, int]],
    failures: list[tuple[str, int, Path]] | None = None,
) -> int:
    existing = con.execute(
        """
        SELECT id FROM runs
        WHERE commit_sha = ? AND target = ? AND shader_selection = ?
          AND normalizer_version = ?
        """,
        (commit_sha, target, shader_selection, NORMALIZER_VERSION),
    ).fetchone()
    if existing:
        con.execute("DELETE FROM runs WHERE id = ?", (existing[0],))

    fp = fingerprint_stats(rows)
    cur = con.execute(
        """
        INSERT INTO runs(
            commit_sha, target, gpu_id, shader_selection, normalizer_version,
            status, return_code, started_at, finished_at, duration_s,
            stats_count, stats_fingerprint, raw_output_path, stderr_path,
            build_log_path, run_command
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            commit_sha,
            target,
            gpu_id,
            shader_selection,
            NORMALIZER_VERSION,
            status,
            return_code,
            started_at,
            finished_at,
            duration_s,
            len(rows),
            fp,
            str(raw_output_path),
            str(stderr_path),
            str(build_log_path),
            json.dumps(run_command),
        ),
    )
    run_id = cur.lastrowid
    con.executemany(
        """
        INSERT INTO shader_stats(run_id, app, shader_path, stage, stat, value)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(run_id, *row) for row in rows],
    )
    if failures:
        con.executemany(
            """
            INSERT INTO shader_failures(run_id, shader_path, return_code, stderr_path)
            VALUES (?, ?, ?, ?)
            """,
            [(run_id, shader, rc, str(stderr)) for shader, rc, stderr in failures],
        )
    return run_id


def run_fingerprint(
    con: sqlite3.Connection,
    commit_sha: str,
    target: str,
    shader_selection: str,
) -> str | None:
    row = con.execute(
        """
        SELECT id, stats_fingerprint FROM runs
        WHERE commit_sha = ? AND target = ? AND shader_selection = ?
          AND normalizer_version = ? AND status = 'ok'
        """,
        (commit_sha, target, shader_selection, NORMALIZER_VERSION),
    ).fetchone()
    if not row:
        return None

    failures = con.execute(
        """
        SELECT shader_path, return_code
        FROM shader_failures
        WHERE run_id = ?
        ORDER BY shader_path, return_code
        """,
        (row[0],),
    ).fetchall()
    h = hashlib.sha256()
    h.update(row[1].encode())
    h.update(b"\0")
    h.update(fingerprint_failures(failures).encode())
    return h.hexdigest()


def combined_fingerprint(
    con: sqlite3.Connection,
    commit_sha: str,
    targets: list[str],
    shader_selection: str,
) -> str | None:
    h = hashlib.sha256()
    for target in targets:
        fp = run_fingerprint(con, commit_sha, target, shader_selection)
        if fp is None:
            return None
        h.update(target.encode())
        h.update(b"\0")
        h.update(fp.encode())
        h.update(b"\n")
    return h.hexdigest()


def has_all_runs(
    con: sqlite3.Connection,
    commit_sha: str,
    targets: list[str],
    shader_selection: str,
) -> bool:
    return combined_fingerprint(con, commit_sha, targets, shader_selection) is not None


def ensure_worktree(mesa_repo: Path, worktree: Path, sha: str) -> None:
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if not (worktree / ".git").exists():
        log(f"Creating Mesa worktree at {worktree}")
        run_cmd(["git", "-C", str(mesa_repo), "worktree", "add", "--detach", str(worktree), sha])
    else:
        top = git(worktree, "rev-parse", "--show-toplevel")
        if Path(top).resolve() != worktree.resolve():
            raise RuntimeError(f"{worktree} is not the expected git worktree root")

    run_cmd(["git", "-C", str(worktree), "checkout", "--detach", "--force", sha])
    run_cmd(["git", "-C", str(worktree), "clean", "-fdq"])


def replace_stats_struct(header_text: str) -> str:
    new_struct = """struct rc_program_stats {
   enum rc_program_type type;
   unsigned num_cycles;
   unsigned num_consts;
   unsigned num_insts;
   unsigned num_fc_insts;
   unsigned num_tex_insts;
   unsigned num_rgb_insts;
   unsigned num_alpha_insts;
   unsigned num_pred_insts;
   unsigned num_presub_ops;
   unsigned num_temp_regs;
   unsigned num_omod_ops;
   unsigned num_inline_literals;
   unsigned num_loops;
};"""
    return re.sub(r"struct rc_program_stats \{.*?\};", new_struct, header_text, flags=re.S)


def normalized_stats_block(debug_func: str) -> str:
    return f"""static int
stats_inst_has_three_diff_temp_srcs(struct rc_instruction *inst)
{{
   return inst->U.I.SrcReg[0].File == RC_FILE_TEMPORARY &&
          inst->U.I.SrcReg[1].File == RC_FILE_TEMPORARY &&
          inst->U.I.SrcReg[2].File == RC_FILE_TEMPORARY &&
          inst->U.I.SrcReg[0].Index != inst->U.I.SrcReg[1].Index &&
          inst->U.I.SrcReg[1].Index != inst->U.I.SrcReg[2].Index &&
          inst->U.I.SrcReg[0].Index != inst->U.I.SrcReg[2].Index;
}}

static void
reg_count_callback(void *userdata, struct rc_instruction *inst, rc_register_file file,
                   unsigned int index, unsigned int mask)
{{
   struct rc_program_stats *s = userdata;
   if (file == RC_FILE_TEMPORARY || (s->type == RC_FRAGMENT_PROGRAM && file == RC_FILE_INPUT))
      (int)index > s->num_temp_regs ? s->num_temp_regs = index : 0;
   if (file == RC_FILE_INLINE)
      s->num_inline_literals++;
   if (file == RC_FILE_CONSTANT && index + 1 > s->num_consts)
      s->num_consts = index + 1;
}}

void
rc_get_stats(struct radeon_compiler *c, struct rc_program_stats *s)
{{
   struct rc_instruction *tmp;
   memset(s, 0, sizeof(*s));
   s->type = c->type;
   unsigned ip = 0;
   int last_begintex = -1;

   for (tmp = c->Program.Instructions.Next; tmp != &c->Program.Instructions;
        tmp = tmp->Next, ip++) {{
      const struct rc_opcode_info *info;
      rc_for_all_reads_mask(tmp, reg_count_callback, s);
      if (tmp->Type == RC_INSTRUCTION_NORMAL) {{
         info = rc_get_opcode_info(tmp->U.I.Opcode);
         if (info->Opcode == RC_OPCODE_BEGIN_TEX) {{
            const struct rc_opcode_info *next_op = rc_get_opcode_info(tmp->Next->U.I.Opcode);
            struct rc_instruction *second_next_instr = tmp->Next->Next;
            const struct rc_opcode_info *second_next_op;
            if (second_next_instr->Type == RC_INSTRUCTION_NORMAL) {{
               second_next_op = rc_get_opcode_info(second_next_instr->U.I.Opcode);
            }} else {{
               second_next_op = rc_get_opcode_info(second_next_instr->U.P.RGB.Opcode);
            }}
            if (next_op->Opcode != RC_OPCODE_KIL ||
                (second_next_instr->Type == RC_INSTRUCTION_NORMAL && second_next_op->HasTexture)) {{
               s->num_cycles += 30;
               last_begintex = ip;
            }}
            continue;
         }}
         if (info->Opcode == RC_OPCODE_MAD && stats_inst_has_three_diff_temp_srcs(tmp))
            s->num_cycles++;
      }} else {{
         if (tmp->U.P.RGB.Src[RC_PAIR_PRESUB_SRC].Used)
            s->num_presub_ops++;
         if (tmp->U.P.Alpha.Src[RC_PAIR_PRESUB_SRC].Used)
            s->num_presub_ops++;
         if (tmp->U.P.Alpha.Opcode != RC_OPCODE_NOP)
            s->num_alpha_insts++;
         if (tmp->U.P.RGB.Opcode != RC_OPCODE_NOP)
            s->num_rgb_insts++;
         if (tmp->U.P.RGB.Omod != RC_OMOD_MUL_1 && tmp->U.P.RGB.Omod != RC_OMOD_DISABLE)
            s->num_omod_ops++;
         if (tmp->U.P.Alpha.Omod != RC_OMOD_MUL_1 && tmp->U.P.Alpha.Omod != RC_OMOD_DISABLE)
            s->num_omod_ops++;
         if (tmp->U.P.Nop)
            s->num_cycles++;
         if (tmp->U.P.SemWait && c->is_r500 && last_begintex != -1) {{
            unsigned distance = ip - last_begintex;
            s->num_cycles -= distance < 30 ? distance : 30;
            last_begintex = -1;
         }}
         info = rc_get_opcode_info(tmp->U.P.RGB.Opcode);
      }}
      if (info->IsFlowControl) {{
         s->num_fc_insts++;
         if (info->Opcode == RC_OPCODE_BGNLOOP)
            s->num_loops++;
      }}
      if (c->type == RC_VERTEX_PROGRAM)
         if (strstr(info->Name, "PRED") != NULL)
            s->num_pred_insts++;

      if (info->HasTexture)
         s->num_tex_insts++;
      s->num_insts++;
      s->num_cycles++;
   }}
   s->num_temp_regs++;
}}

static void
print_stats(struct radeon_compiler *c)
{{
   struct rc_program_stats s;

   rc_get_stats(c, &s);

   {debug_func}(
      c->debug, SHADER_INFO,
      "%s shader: %u inst, %u vinst, %u sinst, %u predicate, %u flowcontrol, "
      "%u loops, %u tex, %u presub, %u omod, %u temps, %u consts, %u lits, %u cycles",
      c->type == RC_VERTEX_PROGRAM ? "VS" : "FS", s.num_insts, s.num_rgb_insts, s.num_alpha_insts,
      s.num_pred_insts, s.num_fc_insts, s.num_loops, s.num_tex_insts, s.num_presub_ops,
      s.num_omod_ops, s.num_temp_regs, s.num_consts, s.num_inline_literals, s.num_cycles);
}}

"""


def apply_stats_normalizer(worktree: Path) -> None:
    c_path = worktree / "src/gallium/drivers/r300/compiler/radeon_compiler.c"
    h_path = worktree / "src/gallium/drivers/r300/compiler/radeon_compiler.h"
    c_text = c_path.read_text()
    h_text = h_path.read_text()

    debug_func = "util_debug_message" if "util_debug_message" in c_text else "pipe_debug_message"

    if "#include <string.h>" not in c_text:
        c_text = c_text.replace("#include <stdlib.h>\n", "#include <stdlib.h>\n#include <string.h>\n")

    c_text, replacements = re.subn(
        r"static (?:void|bool)\s+stats_inst_has_three_diff_temp_srcs.*?static const char \*shader_name",
        normalized_stats_block(debug_func) + "static const char *shader_name",
        c_text,
        flags=re.S,
    )
    if replacements == 0:
        c_text, replacements = re.subn(
            r"static void\s+reg_count_callback.*?static const char \*shader_name",
            normalized_stats_block(debug_func) + "static const char *shader_name",
            c_text,
            flags=re.S,
        )
    if replacements != 1:
        raise RuntimeError(f"Could not rewrite r300 stats block in {c_path}")

    c_text = re.sub(
        r"(rc_run_compiler_passes\(c, list\);\n\n)(\s*)print_stats\(c\);",
        r"\1\2if (!c->Error)\n\2   print_stats(c);",
        c_text,
    )

    h_text = replace_stats_struct(h_text)

    c_path.write_text(c_text)
    h_path.write_text(h_text)


def apply_history_build_fixes(worktree: Path) -> None:
    """Patch historical Meson wiring needed for build-tree shader-db runs."""
    r300_state = worktree / "src/gallium/drivers/r300/r300_state.c"
    if r300_state.exists():
        state_text = r300_state.read_text()
        old = (
            "        if (info.sampler_targets[i] == TGSI_TEXTURE_SHADOW1D ||\n"
            "            info.sampler_targets[i] == TGSI_TEXTURE_SHADOW2D) {\n"
        )
        new = (
            "        if (info.sampler_targets[i] == TGSI_TEXTURE_SHADOW1D ||\n"
            "            info.sampler_targets[i] == TGSI_TEXTURE_SHADOW2D ||\n"
            "            info.sampler_targets[i] == TGSI_TEXTURE_SHADOWRECT) {\n"
        )
        if old in state_text and "TGSI_TEXTURE_SHADOWRECT) {" not in state_text:
            r300_state.write_text(state_text.replace(old, new, 1))

    amd_shim = worktree / "src/amd/drm-shim/radeon_noop_drm_shim.c"
    meson_path = worktree / "src/meson.build"
    amd_meson_path = worktree / "src/amd/meson.build"
    if amd_shim.exists() and meson_path.exists() and amd_meson_path.exists():
        meson_text = meson_path.read_text()
        old = "if with_gallium_radeonsi or with_amd_vk"
        new = "if with_gallium_radeonsi or with_amd_vk or with_tools.contains('drm-shim')"
        if old in meson_text and new not in meson_text:
            meson_path.write_text(meson_text.replace(old, new, 1))

        amd_text = amd_meson_path.read_text()
        if "subdir('addrlib')\nsubdir('common')" in amd_text:
            amd_text, replacements = re.subn(
                r"(inc_amd = include_directories\('\.'\)\n\n)"
                r"subdir\('addrlib'\)\nsubdir\('common'\)\n"
                r"(.*?)\n\nif with_tools\.contains\('drm-shim'\)\n"
                r"  subdir\('drm-shim'\)\nendif\n",
                r"\1"
                r"if with_tools.contains('drm-shim')\n"
                r"  subdir('drm-shim')\n"
                r"endif\n\n"
                r"if with_gallium_radeonsi or with_amd_vk\n"
                r"subdir('addrlib')\n"
                r"subdir('common')\n"
                r"\2\n"
                r"endif\n",
                amd_text,
                count=1,
                flags=re.S,
            )
            if replacements:
                amd_meson_path.write_text(amd_text)

    r300_algebraic = worktree / "src/gallium/drivers/r300/compiler/r300_nir_algebraic.py"
    r300_vs_h = worktree / "src/gallium/drivers/r300/r300_vs.h"
    if r300_algebraic.exists() and r300_vs_h.exists():
        algebraic_text = r300_algebraic.read_text()
        vs_text = r300_vs_h.read_text()
        if (
            "r300_transform_vs_trig_input" in algebraic_text
            and "r300_transform_vs_trig_input" not in vs_text
        ):
            vs_text = vs_text.replace(
                "extern bool r300_transform_trig_input(struct nir_shader *shader);\n",
                "extern bool r300_transform_trig_input(struct nir_shader *shader);\n"
                "extern bool r300_transform_vs_trig_input(struct nir_shader *shader);\n",
            )
            r300_vs_h.write_text(vs_text)

    nir_from_ssa = worktree / "src/compiler/nir/nir_from_ssa.c"
    nir_builder_h = worktree / "src/compiler/nir/nir_builder.h"
    if nir_from_ssa.exists() and nir_builder_h.exists():
        nir_text = nir_from_ssa.read_text()
        old = "   nir_builder b;\n   nir_builder_init(&b, state->impl);\n"
        new = "   nir_builder b = nir_builder_create(state->impl);\n"
        if old in nir_text and "nir_builder_create(nir_function_impl *impl)" in nir_builder_h.read_text():
            nir_from_ssa.write_text(nir_text.replace(old, new, 1))

    texstorage = worktree / "src/mesa/main/texstorage.c"
    texstorage_attribs_xml = worktree / "src/mapi/glapi/gen/EXT_texture_storage_compression.xml"
    if texstorage.exists() and texstorage_attribs_xml.exists():
        texstorage_text = texstorage.read_text()
        if (
            "TexStorageAttribs2DEXT" in texstorage_attribs_xml.read_text()
            and "_mesa_TexStorageAttribs2DEXT(" not in texstorage_text
            and "texstorage_no_error(GLuint dims" in texstorage_text
        ):
            texstorage.write_text(
                texstorage_text
                + """

void GLAPIENTRY
_mesa_TexStorageAttribs2DEXT_no_error(GLenum target, GLsizei levels,
                                      GLenum internalFormat, GLsizei width,
                                      GLsizei height, const GLint *attrib_list)
{
   (void) attrib_list;
   texstorage_no_error(2, target, levels, internalFormat, width, height, 1,
                       "glTexStorageAttribs2DEXT");
}


void GLAPIENTRY
_mesa_TexStorageAttribs2DEXT(GLenum target, GLsizei levels,
                             GLenum internalFormat, GLsizei width,
                             GLsizei height, const GLint *attrib_list)
{
   (void) attrib_list;
   texstorage_error(2, target, levels, internalFormat, width, height, 1,
                    "glTexStorageAttribs2DEXT");
}


void GLAPIENTRY
_mesa_TexStorageAttribs3DEXT_no_error(GLenum target, GLsizei levels,
                                      GLenum internalFormat, GLsizei width,
                                      GLsizei height, GLsizei depth,
                                      const GLint *attrib_list)
{
   (void) attrib_list;
   texstorage_no_error(3, target, levels, internalFormat, width, height, depth,
                       "glTexStorageAttribs3DEXT");
}


void GLAPIENTRY
_mesa_TexStorageAttribs3DEXT(GLenum target, GLsizei levels,
                             GLenum internalFormat, GLsizei width,
                             GLsizei height, GLsizei depth,
                             const GLint *attrib_list)
{
   (void) attrib_list;
   texstorage_error(3, target, levels, internalFormat, width, height, depth,
                    "glTexStorageAttribs3DEXT");
}
"""
            )


def meson_setup_command(build_dir: Path, source_dir: Path, meson_options: list[str]) -> list[str]:
    return [
        "meson",
        "setup",
        str(build_dir),
        str(source_dir),
        "--wrap-mode=nofallback",
        *meson_options,
    ]


def meson_setup_requires_llvm(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    text = log_path.read_text(errors="replace")
    return (
        "Feature llvm cannot be disabled" in text
        and "R300 Gallium driver requires LLVM" in text
    )


def run_meson_setup_with_retry(cmd: list[str], log_path: Path) -> None:
    proc = run_cmd(cmd, stdout_path=log_path, stderr_path=log_path, append=True, check=False)
    if proc.returncode == 0:
        return

    if "-Dllvm=disabled" in cmd and meson_setup_requires_llvm(log_path):
        retry_cmd = ["-Dllvm=enabled" if arg == "-Dllvm=disabled" else arg for arg in cmd]
        append_text(
            log_path,
            "\nRetrying Meson with -Dllvm=enabled because this revision "
            "requires LLVM for r300.\n",
        )
        retry_proc = run_cmd(
            retry_cmd,
            stdout_path=log_path,
            stderr_path=log_path,
            append=True,
            check=False,
        )
        if retry_proc.returncode == 0:
            return
        raise subprocess.CalledProcessError(retry_proc.returncode, retry_cmd)

    raise subprocess.CalledProcessError(proc.returncode, cmd)


def ensure_dri_driver_links(build_dir: Path) -> None:
    dri_dir = build_dir / "src/gallium/targets/dri"
    if not dri_dir.exists():
        return

    target = dri_dir / "libgallium_dri.so"
    if not target.exists():
        return

    for driver in ["r300_dri.so", "radeon_dri.so"]:
        link = dri_dir / driver
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(target.name)


def shader_arg_for_run(shader_db: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(shader_db).as_posix()
    except ValueError:
        return str(path)


def resolve_shader_inputs(shader_db: Path, shader_paths: list[str]) -> list[str]:
    shaders: list[str] = []
    for shader_path in shader_paths:
        path = Path(shader_path)
        if not path.is_absolute():
            path = shader_db / path

        if path.is_dir():
            shaders.extend(shader_arg_for_run(shader_db, p) for p in sorted(path.rglob("*.shader_test")))
        elif path.is_file():
            shaders.append(shader_arg_for_run(shader_db, path))
        else:
            shaders.append(shader_path)

    return sorted(dict.fromkeys(shaders))


def append_file(dst: Path, src: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("ab") as out, src.open("rb") as inp:
        shutil.copyfileobj(inp, out)


def append_text(dst: Path, text: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("ab") as out:
        out.write(text.encode("utf-8", errors="replace"))


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def run_shaderdb_command(
    args: argparse.Namespace,
    env: dict[str, str],
    shader_paths: list[str],
    stdout_path: Path,
    stderr_path: Path,
    jobs: int,
) -> subprocess.CompletedProcess:
    cmd = [
        str(args.shader_db / "run"),
        "-j",
        str(jobs),
        "-o",
        "r300",
        *shader_paths,
    ]
    return run_cmd(
        cmd,
        cwd=args.shader_db,
        env=env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout=args.shader_timeout,
        memory_limit_mb=args.shader_memory_mb,
        check=False,
    )


def collect_shaderdb_output(
    args: argparse.Namespace,
    env: dict[str, str],
    raw: Path,
    err: Path,
) -> tuple[list[tuple[str, str, str, str, int]], int, list[tuple[str, int, Path]]]:
    shader_inputs = resolve_shader_inputs(args.shader_db, args.shader_path)
    if not shader_inputs:
        raise RuntimeError(f"no shader-db inputs found for {args.shader_path}")

    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("")
    err.write_text("")

    failures: list[tuple[str, int, Path]] = []
    batch_dir = raw.parent / f"{raw.stem}-batches"
    if batch_dir.exists():
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True, exist_ok=True)
    batch_counter = 0
    failure_shaders: dict[str, tuple[int, Path]] = {}

    def next_batch_paths() -> tuple[Path, Path]:
        nonlocal batch_counter
        batch_counter += 1
        batch_id = f"{batch_counter:05d}"
        return batch_dir / f"{batch_id}.txt", batch_dir / f"{batch_id}.err"

    def run_batch(shader_batch: list[str], jobs: int) -> tuple[subprocess.CompletedProcess, Path, Path]:
        batch_raw, batch_err = next_batch_paths()
        jobs = min(jobs, max(1, len(shader_batch)))

        proc = run_shaderdb_command(args, env, shader_batch, batch_raw, batch_err, jobs)
        if proc.returncode == 124 and args.shader_timeout is not None:
            append_text(
                batch_err,
                f"\nTIMEOUT: shader-db batch exceeded {args.shader_timeout:.1f}s\n",
            )
        return proc, batch_raw, batch_err

    def record_failure(shader: str, rc: int, batch_err: Path) -> None:
        if shader in failure_shaders:
            return
        failure_shaders[shader] = (rc, batch_err)
        failures.append((shader, rc, batch_err))
        append_text(err, f"\nBLACKLIST shader-db shader: {shader} rc={rc}\n")
        append_file(err, batch_err)

    def find_bad_shaders(shader_batch: list[str]) -> None:
        remaining = list(shader_batch)
        while remaining:
            probe = remaining[:args.shader_probe_chunk_size]
            proc, batch_raw, batch_err = run_batch(probe, 1)
            if proc.returncode == 0:
                remaining = remaining[len(probe):]
                batch_raw.unlink(missing_ok=True)
                batch_err.unlink(missing_ok=True)
                continue

            finished = parse_finished_shaders(batch_raw, batch_err)
            remaining = [shader for shader in remaining if shader not in finished]
            crashed = [shader for shader in parse_crashed_shaders(batch_err) if shader in remaining]
            candidates = [shader for shader in probe if shader in remaining]
            bad = crashed[0] if len(crashed) == 1 else (candidates[0] if candidates else None)

            if bad is None:
                append_text(
                    err,
                    f"\nFAILED shader-db discovery batch rc={proc.returncode}; "
                    "could not identify shader\n",
                )
                append_file(err, batch_err)
                batch_raw.unlink(missing_ok=True)
                return

            record_failure(bad, proc.returncode, batch_err)
            remaining = [shader for shader in remaining if shader != bad]
            batch_raw.unlink(missing_ok=True)

    initial_proc, initial_raw, initial_err = run_batch(shader_inputs, args.shader_jobs)
    if initial_proc.returncode == 0:
        append_file(raw, initial_raw)
        append_file(err, initial_err)
        initial_raw.unlink(missing_ok=True)
        initial_err.unlink(missing_ok=True)
        rows = parse_shaderdb_output(raw)
        return rows, 0, failures

    finished = parse_finished_shaders(initial_raw, initial_err)
    discovery_inputs = [shader for shader in shader_inputs if shader not in finished]
    append_text(
        err,
        f"\nInitial shader-db batch failed rc={initial_proc.returncode}; "
        f"probing {len(discovery_inputs)} unfinished shader(s) with -j1\n",
    )
    append_file(err, initial_err)
    find_bad_shaders(discovery_inputs)
    initial_raw.unlink(missing_ok=True)
    initial_err.unlink(missing_ok=True)

    rc = 255 if failures else 0
    while True:
        raw.write_text("")
        final_failed = False
        good_shaders = [shader for shader in shader_inputs if shader not in failure_shaders]

        if not good_shaders:
            break

        for shader_batch in chunks(good_shaders, args.shader_chunk_size):
            proc, batch_raw, batch_err = run_batch(shader_batch, args.shader_jobs)
            if proc.returncode == 0:
                append_file(raw, batch_raw)
                append_file(err, batch_err)
                batch_raw.unlink(missing_ok=True)
                batch_err.unlink(missing_ok=True)
                continue

            append_text(
                err,
                f"\nClean shader-db batch failed rc={proc.returncode}; "
                f"probing {len(shader_batch)} shader(s) with -j1\n",
            )
            append_file(err, batch_err)
            failures_before = len(failure_shaders)
            find_bad_shaders(shader_batch)
            keep_batch_err = False
            if len(failure_shaders) == failures_before:
                fallback = next((shader for shader in shader_batch if shader not in failure_shaders), None)
                if fallback is not None:
                    record_failure(fallback, proc.returncode, batch_err)
                    keep_batch_err = True
            batch_raw.unlink(missing_ok=True)
            if not keep_batch_err:
                batch_err.unlink(missing_ok=True)
            rc = proc.returncode
            final_failed = True
            break

        if not final_failed:
            break

    rows = parse_shaderdb_output(raw)
    return rows, rc, failures


def build_mesa(args: argparse.Namespace, sha: str) -> Path:
    build_dir = args.build_dir
    log_path = args.results_dir / "logs" / sha / "build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("")

    if not build_dir.exists():
        cmd = meson_setup_command(build_dir, args.worktree, args.meson_option)
        log(f"Configuring Mesa build for {sha[:12]}")
        run_meson_setup_with_retry(cmd, log_path)
    else:
        cmd = ["meson", "setup", "--reconfigure", str(build_dir), *args.meson_option]
        log(f"Reconfiguring Mesa build for {sha[:12]}")
        proc = run_cmd(cmd, stdout_path=log_path, stderr_path=log_path, append=True, check=False)
        if proc.returncode != 0:
            cmd = ["meson", "setup", "--wipe", str(build_dir), str(args.worktree),
                   "--wrap-mode=nofallback", *args.meson_option]
            run_meson_setup_with_retry(cmd, log_path)

    cmd = ["ninja", "-C", str(build_dir)]
    if args.build_jobs:
        cmd.extend(["-j", str(args.build_jobs)])
    log(f"Building Mesa for {sha[:12]}")
    run_cmd(cmd, stdout_path=log_path, stderr_path=log_path, append=True)
    ensure_dri_driver_links(build_dir)
    return log_path


def runtime_env(args: argparse.Namespace, gpu_id: str) -> dict[str, str]:
    env = os.environ.copy()
    build = args.build_dir
    ld_paths = [
        build / "src/mapi/shared-glapi",
        build / "src/mapi/es2api",
        build / "src/mapi/es1api",
        build / "src/glx",
        build / "src/egl",
        build / "src/gbm",
        build / "src/gallium/targets/dri",
    ]
    existing_ld = env.get("LD_LIBRARY_PATH")
    env["LD_LIBRARY_PATH"] = ":".join(str(p) for p in ld_paths if p.exists())
    if existing_ld:
        env["LD_LIBRARY_PATH"] += f":{existing_ld}"

    build_shim = build / "src/amd/drm-shim/libradeon_noop_drm_shim.so"
    shim = build_shim if build_shim.exists() else args.shim
    preload = str(shim)
    if env.get("LD_PRELOAD"):
        preload = f"{preload}:{env['LD_PRELOAD']}"
    env["LD_PRELOAD"] = preload

    env["MESA_LOADER_DRIVER_OVERRIDE"] = "r300"
    env["RADEON_GPU_ID"] = gpu_id
    env["LIBGL_DRIVERS_PATH"] = str(build / "src/gallium/targets/dri")
    env["GBM_BACKENDS_PATH"] = ":".join(
        [
            str(build / "src/gbm/backends/dri"),
            str(build / "src/gallium/targets/dri"),
        ]
    )
    env["__EGL_VENDOR_LIBRARY_DIRS"] = str(build / "src/egl")
    env["MESA_SHADER_CACHE_DISABLE"] = "true"
    env["MESA_GLSL_CACHE_DISABLE"] = "true"
    env["GALLIUM_THREAD"] = "0"
    return env


def collect_revision(args: argparse.Namespace, rev: str) -> None:
    mesa_repo = args.mesa_repo
    sha = resolve_commit(mesa_repo, rev)
    if git(mesa_repo, "merge-base", "--is-ancestor", START_FLOOR, sha, check=False) == "":
        proc = run_cmd(["git", "-C", str(mesa_repo), "merge-base", "--is-ancestor", START_FLOOR, sha],
                       check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"{sha} is before required floor {START_FLOOR}")

    con = ensure_db(args.db)
    with con:
        insert_commit(con, commit_metadata(mesa_repo, sha))

    ensure_worktree(mesa_repo, args.worktree, sha)
    if args.normalize_stats:
        log(f"Applying current r300 stats normalizer to {sha[:12]}")
        apply_stats_normalizer(args.worktree)
    apply_history_build_fixes(args.worktree)

    build_log = args.results_dir / "logs" / sha / "build.log"
    if not args.skip_build:
        build_log = build_mesa(args, sha)

    for target in args.targets:
        if not args.force and run_fingerprint(con, sha, target, args.shader_selection) is not None:
            log(f"Skipping shader-db {target} for {sha[:12]} (already in DB)")
            continue

        gpu_id = TARGETS[target]
        raw = args.results_dir / "raw" / sha / f"{target}.txt"
        err = args.results_dir / "raw" / sha / f"{target}.err"
        cmd = [
            str(args.shader_db / "run"),
            "-j",
            str(args.shader_jobs),
            "-o",
            "r300",
            *args.shader_path,
        ]
        env = runtime_env(args, gpu_id)

        log(f"Running shader-db {target} ({gpu_id}) for {sha[:12]}")
        start = time.monotonic()
        started_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        rows, return_code, failures = collect_shaderdb_output(args, env, raw, err)
        finished_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
        duration = time.monotonic() - start

        status = "ok" if rows or failures else "fail"
        with con:
            run_id = store_run(
                con,
                commit_sha=sha,
                target=target,
                gpu_id=gpu_id,
                shader_selection=args.shader_selection,
                status=status,
                return_code=return_code,
                started_at=started_at,
                finished_at=finished_at,
                duration_s=duration,
                raw_output_path=raw,
                stderr_path=err,
                build_log_path=build_log,
                run_command=cmd,
                rows=rows,
                failures=failures,
            )
        log(
            f"Stored run {run_id}: {target} rc={return_code} "
            f"stats={len(rows)} failures={len(failures)} duration={duration:.1f}s"
        )
        if status != "ok":
            raise RuntimeError(f"shader-db run failed for {sha[:12]} {target}; see {err}")


def target_list(value: str) -> list[str]:
    targets = [v.strip().lower() for v in value.split(",") if v.strip()]
    bad = [t for t in targets if t not in TARGETS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown target(s): {', '.join(bad)}")
    return targets


def ensure_revision_runs(args: argparse.Namespace, con: sqlite3.Connection, sha: str) -> None:
    if has_all_runs(con, sha, args.targets, args.shader_selection):
        return
    collect_revision(args, sha)


def rev_list_first_parent(
    repo: Path,
    start: str,
    end: str,
    relevant_paths: list[str] | None = None,
) -> list[str]:
    start_sha = resolve_commit(repo, start)
    end_sha = resolve_commit(repo, end)
    cmd = ["rev-list", "--first-parent", "--reverse", f"{start_sha}..{end_sha}"]
    if relevant_paths:
        cmd.extend(["--", *relevant_paths])
    out = git(repo, *cmd)
    commits = [start_sha]
    if out:
        commits.extend(out.splitlines())
    if commits[-1] != end_sha:
        commits.append(end_sha)
    return commits


def selected_relevant_paths(args: argparse.Namespace) -> list[str] | None:
    if args.path_prune == "off":
        return None
    return args.relevant_path


def selected_interval_commits(
    selected_commits: list[str],
    full_index: dict[str, int],
    start_sha: str,
    end_sha: str,
) -> list[str]:
    start_idx = full_index[start_sha]
    end_idx = full_index[end_sha]
    interval = [
        sha for sha in selected_commits
        if start_idx <= full_index[sha] <= end_idx
    ]
    if not interval or interval[0] != start_sha:
        interval.insert(0, start_sha)
    if interval[-1] != end_sha:
        interval.append(end_sha)

    deduped: list[str] = []
    seen: set[str] = set()
    for sha in interval:
        if sha not in seen:
            deduped.append(sha)
            seen.add(sha)
    return deduped


def logged_shaderdb_candidates(
    repo: Path,
    start_sha: str,
    end_sha: str,
    pattern: str,
) -> list[str]:
    rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    fmt = "%H%x00%B%x1e"
    out = git(
        repo,
        "log",
        "--first-parent",
        "--reverse",
        "--extended-regexp",
        "--regexp-ignore-case",
        "--grep=shader[- ]?db",
        f"--format={fmt}",
        f"{start_sha}..{end_sha}",
    )
    candidates: list[str] = []
    seen: set[str] = set()
    for record in out.split("\x1e"):
        record = record.strip()
        if not record or "\x00" not in record:
            continue
        sha, message = record.split("\x00", 1)
        sha = sha.strip()
        if sha not in seen and rx.search(message):
            candidates.append(sha)
            seen.add(sha)
    return candidates


def record_change(
    con: sqlite3.Connection,
    args: argparse.Namespace,
    *,
    start_sha: str,
    end_sha: str,
    mode: str,
    from_sha: str,
    to_sha: str,
) -> None:
    con.execute(
        """
        INSERT OR IGNORE INTO change_points(
            start_sha, end_sha, mode, from_sha, to_sha, target_set,
            shader_selection, normalizer_version, discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            start_sha,
            end_sha,
            mode,
            from_sha,
            to_sha,
            ",".join(args.targets),
            args.shader_selection,
            NORMALIZER_VERSION,
            _dt.datetime.now(_dt.timezone.utc).isoformat(),
        ),
    )


def discover_bisect_interval(
    args: argparse.Namespace,
    con: sqlite3.Connection,
    commits: list[str],
    start_idx: int,
    end_idx: int,
    *,
    start_sha: str,
    end_sha: str,
    mode: str,
) -> list[tuple[str, str]]:
    if start_idx >= end_idx:
        return []

    ensure_revision_runs(args, con, commits[start_idx])
    ensure_revision_runs(args, con, commits[end_idx])

    base_idx = start_idx
    changes: list[tuple[str, str]] = []

    while base_idx < end_idx:
        base_sha = commits[base_idx]
        base_fp = combined_fingerprint(con, base_sha, args.targets, args.shader_selection)
        end_fp = combined_fingerprint(con, commits[end_idx], args.targets, args.shader_selection)
        if base_fp == end_fp:
            if base_idx == start_idx:
                log(
                    f"Skipping unchanged interval "
                    f"{commits[start_idx][:12]}..{commits[end_idx][:12]}"
                )
            break

        lo = base_idx + 1
        hi = end_idx
        while lo < hi:
            mid = (lo + hi) // 2
            mid_sha = commits[mid]
            ensure_revision_runs(args, con, mid_sha)
            mid_fp = combined_fingerprint(con, mid_sha, args.targets, args.shader_selection)
            if mid_fp == base_fp:
                lo = mid + 1
            else:
                hi = mid

        change_idx = lo
        from_sha = commits[change_idx - 1]
        to_sha = commits[change_idx]
        ensure_revision_runs(args, con, to_sha)
        with con:
            record_change(
                con,
                args,
                start_sha=start_sha,
                end_sha=end_sha,
                mode=mode,
                from_sha=from_sha,
                to_sha=to_sha,
            )
        changes.append((from_sha, to_sha))
        log(f"Change point: {from_sha[:12]} -> {to_sha[:12]}")
        base_idx = change_idx

    return changes


def discover_bisect(args: argparse.Namespace) -> None:
    con = ensure_db(args.db)
    commits = rev_list_first_parent(
        args.mesa_repo,
        args.start,
        args.end,
        selected_relevant_paths(args),
    )
    start_sha = commits[0]
    end_sha = commits[-1]
    if args.path_prune == "off":
        log(f"First-parent range has {len(commits)} commits")
    else:
        log(
            f"Path-pruned first-parent range has {len(commits)} commits "
            f"({len(args.relevant_path)} relevant path roots)"
        )

    changes = discover_bisect_interval(
        args,
        con,
        commits,
        0,
        len(commits) - 1,
        start_sha=start_sha,
        end_sha=end_sha,
        mode="bisect",
    )

    log(f"Discovered {len(changes)} cumulative change point(s)")
    if not changes:
        log("No endpoint-visible stat changes found.")


def discover_guided_log(args: argparse.Namespace) -> None:
    con = ensure_db(args.db)
    full_commits = rev_list_first_parent(args.mesa_repo, args.start, args.end, None)
    full_index = {sha: i for i, sha in enumerate(full_commits)}
    commits = rev_list_first_parent(
        args.mesa_repo,
        args.start,
        args.end,
        selected_relevant_paths(args),
    )
    start_sha = full_commits[0]
    end_sha = full_commits[-1]
    candidates = [
        sha for sha in logged_shaderdb_candidates(
            args.mesa_repo,
            start_sha,
            end_sha,
            args.guided_grep,
        )
        if sha in full_index and full_index[sha] > 0
    ]
    log(
        f"Path-pruned first-parent range has {len(commits)} selected commits "
        f"from {len(full_commits)} total; "
        f"{len(candidates)} guided shader-db candidate(s)"
    )

    if not candidates:
        log("No guided candidates found; falling back to plain bisect.")
        discover_bisect(args)
        return

    anchor_sha = start_sha
    changes: list[tuple[str, str]] = []
    ensure_revision_runs(args, con, anchor_sha)

    for candidate_sha in candidates:
        candidate_idx = full_index[candidate_sha]
        if candidate_idx <= full_index[anchor_sha]:
            continue

        parent_sha = first_parent(args.mesa_repo, candidate_sha)
        if parent_sha is None or parent_sha not in full_index:
            continue
        if full_index[parent_sha] < full_index[anchor_sha]:
            continue

        log(
            f"Guided candidate {candidate_sha[:12]} "
            f"(parent {parent_sha[:12]})"
        )

        ensure_revision_runs(args, con, parent_sha)
        anchor_fp = combined_fingerprint(
            con, anchor_sha, args.targets, args.shader_selection
        )
        parent_fp = combined_fingerprint(con, parent_sha, args.targets, args.shader_selection)
        if anchor_fp != parent_fp:
            interval = selected_interval_commits(
                commits, full_index, anchor_sha, parent_sha
            )
            changes.extend(
                discover_bisect_interval(
                    args,
                    con,
                    interval,
                    0,
                    len(interval) - 1,
                    start_sha=start_sha,
                    end_sha=end_sha,
                    mode="guided-log",
                )
            )
        else:
            log(
                f"Skipping unchanged guided interval "
                f"{anchor_sha[:12]}..{parent_sha[:12]}"
            )

        ensure_revision_runs(args, con, candidate_sha)
        parent_fp = combined_fingerprint(con, parent_sha, args.targets, args.shader_selection)
        candidate_fp = combined_fingerprint(
            con, candidate_sha, args.targets, args.shader_selection
        )
        if parent_fp != candidate_fp:
            with con:
                record_change(
                    con,
                    args,
                    start_sha=start_sha,
                    end_sha=end_sha,
                    mode="guided-log",
                    from_sha=parent_sha,
                    to_sha=candidate_sha,
                )
            changes.append((parent_sha, candidate_sha))
            log(f"Change point: {parent_sha[:12]} -> {candidate_sha[:12]}")
        else:
            log(f"Logged candidate {candidate_sha[:12]} did not change the fingerprint")

        anchor_sha = candidate_sha

    if full_index[anchor_sha] < full_index[end_sha]:
        interval = selected_interval_commits(commits, full_index, anchor_sha, end_sha)
        changes.extend(
            discover_bisect_interval(
                args,
                con,
                interval,
                0,
                len(interval) - 1,
                start_sha=start_sha,
                end_sha=end_sha,
                mode="guided-log-tail",
            )
        )

    log(f"Discovered {len(changes)} guided change point(s)")
    if not changes:
        log("No guided stat changes found.")


def discover_scan(args: argparse.Namespace) -> None:
    con = ensure_db(args.db)
    commits = rev_list_first_parent(
        args.mesa_repo,
        args.start,
        args.end,
        selected_relevant_paths(args),
    )
    start_sha = commits[0]
    end_sha = commits[-1]
    log(f"Scanning {len(commits)} selected first-parent commits")

    previous = commits[0]
    ensure_revision_runs(args, con, previous)
    previous_fp = combined_fingerprint(con, previous, args.targets, args.shader_selection)
    changes = 0

    for sha in commits[1:]:
        ensure_revision_runs(args, con, sha)
        fp = combined_fingerprint(con, sha, args.targets, args.shader_selection)
        if fp != previous_fp:
            with con:
                record_change(
                    con,
                    args,
                    start_sha=start_sha,
                    end_sha=end_sha,
                    mode="scan",
                    from_sha=previous,
                    to_sha=sha,
                )
            log(f"Change point: {previous[:12]} -> {sha[:12]}")
            changes += 1
        previous = sha
        previous_fp = fp

    log(f"Discovered {changes} exact change point(s)")


def first_parent_order(repo: Path, start: str, end: str) -> dict[str, int]:
    commits = rev_list_first_parent(repo, start, end, None)
    return {sha: index for index, sha in enumerate(commits)}


def rerun_change_commits_before(args: argparse.Namespace) -> None:
    con = ensure_db(args.db)
    start_sha = resolve_commit(args.mesa_repo, args.start)
    before_sha = resolve_commit(args.mesa_repo, args.before)
    order = first_parent_order(args.mesa_repo, start_sha, args.end)
    if before_sha not in order:
        raise RuntimeError(f"{before_sha} is not in first-parent range {start_sha}..{args.end}")

    before_order = order[before_sha]
    rows = con.execute(
        """
        SELECT DISTINCT to_sha
        FROM change_points
        WHERE shader_selection = ?
          AND normalizer_version = ?
          AND target_set = ?
        ORDER BY to_sha
        """,
        (args.shader_selection, NORMALIZER_VERSION, ",".join(args.targets)),
    ).fetchall()

    commits = {start_sha}
    for (sha,) in rows:
        if sha in order and order[sha] < before_order:
            commits.add(sha)

    ordered = sorted(commits, key=order.__getitem__)
    log(
        f"Rerunning {len(ordered)} change commit(s) before {before_sha[:12]} "
        f"with {SHADOWRECT_PRECOMPILE_FIX[:12]} normalized"
    )
    if args.dry_run:
        for sha in ordered:
            log(sha)
        return

    args.force = True
    for index, sha in enumerate(ordered, 1):
        log(f"Rerun {index}/{len(ordered)}: {sha[:12]}")
        collect_revision(args, sha)


def summarize(args: argparse.Namespace) -> None:
    con = ensure_db(args.db)
    rows = con.execute(
        """
        SELECT c.author_date, substr(r.commit_sha, 1, 12), r.target,
               r.status, r.stats_count, COUNT(f.shader_path), r.duration_s, c.subject
        FROM runs r
        JOIN commits c ON c.sha = r.commit_sha
        LEFT JOIN shader_failures f ON f.run_id = r.id
        WHERE r.shader_selection = ? AND r.normalizer_version = ?
        GROUP BY r.id
        ORDER BY c.author_date, r.commit_sha, r.target
        """,
        (args.shader_selection, NORMALIZER_VERSION),
    ).fetchall()
    for date, sha, target, status, count, failures, duration, subject in rows:
        print(
            f"{date[:10]} {sha} {target:4} {status:4} "
            f"stats={count:7} failures={failures:4} {duration:8.1f}s  {subject}"
        )


def self_test() -> None:
    sample = Path("/tmp/r300-shaderdb-history-sample.txt")
    sample.write_text(
        "shaders/app/foo.shader_test - FS shader: 3 inst, 2 vinst, 1 sinst, "
        "0 predicate, 0 flowcontrol, 0 loops, 1 tex, 0 presub, 0 omod, "
        "2 temps, 1 consts, 0 lits, 33 cycles\n"
        "Thread 0 took 0.01 seconds and compiled 1 shaders with 0 context switches\n"
    )
    rows = parse_shaderdb_output(sample)
    assert len(rows) == 13, rows
    assert ("app", "shaders/app/foo.shader_test", "FS", "instructions", 3) in rows
    assert fingerprint_stats(rows) == fingerprint_stats(list(reversed(rows)))
    failures = [("shaders/app/b.shader_test", 124), ("shaders/app/a.shader_test", -9)]
    assert fingerprint_failures(failures) == fingerprint_failures(list(reversed(failures)))
    assert fingerprint_failures(failures) != fingerprint_failures(failures[:1])
    sample.unlink()
    print("self-test passed")


def default_shim(root: Path) -> Path:
    candidates = [
        root / "mesa/build/src/amd/drm-shim/libradeon_noop_drm_shim.so",
        Path("/home/ondracka/graphics/install/lib64/libradeon_noop_drm_shim.so"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def add_common_args(parser: argparse.ArgumentParser) -> None:
    root = Path.cwd()
    parser.add_argument("--mesa-repo", type=Path, default=root / "mesa")
    parser.add_argument("--shader-db", type=Path, default=root / "shader-db")
    parser.add_argument("--worktree", type=Path, default=root / "worktrees/mesa-history")
    parser.add_argument("--build-dir", type=Path, default=root / "worktrees/mesa-history-build")
    parser.add_argument("--results-dir", type=Path, default=root / "results")
    parser.add_argument("--db", type=Path, default=root / "results/shaderdb-history.sqlite")
    parser.add_argument("--shim", type=Path, default=default_shim(root))
    parser.add_argument("--targets", type=target_list, default=list(TARGETS))
    parser.add_argument("--shader-path", action="append", default=None)
    parser.add_argument("--shader-jobs", type=int, default=max(1, min((os.cpu_count() or 4), 16)))
    parser.add_argument("--shader-timeout", type=float, default=60.0)
    parser.add_argument("--shader-memory-mb", type=int, default=2048)
    parser.add_argument("--shader-chunk-size", type=int, default=512)
    parser.add_argument("--shader-probe-chunk-size", type=int, default=128)
    parser.add_argument("--build-jobs", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--meson-option", action="append", default=list(DEFAULT_MESON_OPTIONS))
    parser.add_argument(
        "--path-prune",
        choices=["on", "off"],
        default="on",
        help="limit discovery commit candidates to paths relevant to r300 shader-db",
    )
    parser.add_argument(
        "--relevant-path",
        action="append",
        default=None,
        help="path root kept by discovery path pruning; repeat to override defaults",
    )
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--force", action="store_true", help="rerun and replace existing DB rows")
    parser.add_argument("--no-normalize-stats", dest="normalize_stats", action="store_false")
    parser.set_defaults(normalize_stats=True)


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    args.mesa_repo = args.mesa_repo.resolve()
    args.shader_db = args.shader_db.resolve()
    args.worktree = args.worktree.resolve()
    args.build_dir = args.build_dir.resolve()
    args.results_dir = args.results_dir.resolve()
    args.db = args.db.resolve()
    args.shim = args.shim.resolve()
    if args.shader_path is None:
        args.shader_path = ["shaders"]
    args.shader_selection = ",".join(args.shader_path)
    if args.shader_timeout <= 0:
        args.shader_timeout = None
    if args.shader_memory_mb <= 0:
        args.shader_memory_mb = None
    if args.relevant_path is None:
        args.relevant_path = list(DEFAULT_RELEVANT_PATHS)
    if args.shader_chunk_size <= 0:
        args.shader_chunk_size = len(resolve_shader_inputs(args.shader_db, args.shader_path))
    if args.shader_probe_chunk_size <= 0:
        args.shader_probe_chunk_size = 1
    if not args.shim.exists():
        raise FileNotFoundError(f"radeon noop shim not found: {args.shim}")
    if not (args.shader_db / "run").exists():
        raise FileNotFoundError(f"shader-db run binary not found: {args.shader_db / 'run'}")
    return args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="build and run one Mesa revision")
    add_common_args(collect)
    collect.add_argument("rev")

    discover = sub.add_parser("discover", help="find stat-changing commits")
    add_common_args(discover)
    discover.add_argument("--start", default=START_FLOOR)
    discover.add_argument("--end", default="HEAD")
    discover.add_argument("--mode", choices=["bisect", "scan", "guided-log"], default="bisect")
    discover.add_argument(
        "--guided-grep",
        default=DEFAULT_GUIDED_GREP,
        help="Python regex used to select shader-db log-message candidates",
    )

    rerun_before = sub.add_parser(
        "rerun-changes-before",
        help="rerun collected change commits before a fix commit",
    )
    add_common_args(rerun_before)
    rerun_before.add_argument("--start", default="17cea74b8cd3b1a56d923edeb40772b3e8b18ab2")
    rerun_before.add_argument("--end", default="HEAD")
    rerun_before.add_argument("--before", default=SHADOWRECT_PRECOMPILE_FIX)
    rerun_before.add_argument("--dry-run", action="store_true")

    summary = sub.add_parser("summary", help="print collected runs")
    add_common_args(summary)

    test = sub.add_parser("self-test", help="run parser self-test")

    args = parser.parse_args(argv)
    if args.command == "self-test":
        self_test()
        return 0

    args = normalize_args(args)
    if args.command == "collect":
        collect_revision(args, args.rev)
    elif args.command == "discover":
        if args.mode == "bisect":
            discover_bisect(args)
        elif args.mode == "scan":
            discover_scan(args)
        else:
            discover_guided_log(args)
    elif args.command == "rerun-changes-before":
        rerun_change_commits_before(args)
    elif args.command == "summary":
        summarize(args)
    else:
        parser.error(f"unhandled command {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
