#!/usr/bin/env python3
"""Viewer for experiment runs: terminal chat, static HTML export, or live server.

Usage:
    .venv/bin/python viz.py [run_dir] [--notes] [--project] [--all]   # terminal
    .venv/bin/python viz.py --serve [--port 7788]   # local dashboard, all runs
    .venv/bin/python viz.py --html                  # static study pages + every run

The server renders pages on the fly from runs/ (sidebar to switch runs, social
prompts per agent, live refresh while a run is in progress). --html writes the
same pages statically (study views, report.html per run, and the trace index).
"""

import argparse
import html as html_mod
import json
import re
import shutil
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib
import yaml

ROOT = Path(__file__).resolve().parent
COLORS = ["\033[36m", "\033[35m", "\033[33m", "\033[32m"]  # cyan magenta yellow green
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
V2_PROTOCOL = "v2-shared-evidence"

INSTANCE_NOTES = {
    "bargaining-01": (
        "Channels created early variety, then the Nash channel filled with "
        "compromise arguments; the flat stream kept clearer public poles."
    ),
    "bargaining-02": (
        "Both topologies ended with one Nash holdout while the other agents "
        "clustered around the compromise."
    ),
    "bargaining-03": (
        "The amount of final diversity tied, but channels organized it into "
        "more clearly separated lens-specific positions."
    ),
    "bargaining-04": (
        "All three Nash-home agents were nudged toward sum welfare. Both arms "
        "lost the Nash pole, and channels converged completely on x=24."
    ),
    "bargaining-05": (
        "Channels retained a local neighborhood around the optimum while the "
        "flat stream converged exactly; the original opposing sum anchor did not survive."
    ),
}


def latest_run_dir():
    runs = sorted((ROOT / "runs").glob("*/"), key=lambda p: p.stat().st_mtime)
    if not runs:
        raise SystemExit("no runs found under runs/")
    return runs[-1]


def load_board(run_dir):
    msgs = []
    paths = list((run_dir / "boards").glob("*/*.json"))
    if not paths:  # compatibility with the upstream single-board format
        paths = list((run_dir / "board").glob("*.json"))
    for f in sorted(paths):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        msgs.append({
            "epoch": f.stat().st_mtime,
            "agent": data.get("agent", f.stem.split("-", 1)[-1]),
            "content": str(data.get("content", "")).strip(),
            "id": data.get("id", f.stem),
            "round": data.get("round"),
            "phase": data.get("phase"),
            "channel": data.get("channel", f.parent.name),
            "lens": data.get("lens"),
            "candidate_x": data.get("candidate_x"),
            "action": data.get("action"),
            "confidence": data.get("confidence"),
        })
    return sorted(msgs, key=lambda m: (m.get("round") or 0, m.get("id") or ""))


def is_board_post(block, agent):
    """True if this tool call creates a board message file for `agent`.

    Agents post with the Write tool or with write-ish Bash (heredoc, python).
    """
    inp = block.get("input") or {}
    if block["name"] == "Write":
        path = str(inp.get("file_path", ""))
        return f"-{agent}.json" in path or path.endswith("OUTBOX.json")
    if block["name"] == "Bash":
        cmd = str(inp.get("command", ""))
        writeish = any(t in cmd for t in (">", "with open", "write_text", "tee "))
        return writeish and (f"-{agent}.json" in cmd or "OUTBOX.json" in cmd)
    return False


def load_windows(run_dir, agent):
    """Cost windows per structured outbox: [(tool_calls, output_tokens), ...].

    A window ends at (and includes) the assistant step that posts a message to
    the board, so composing cost is attributed to the message it produced.
    Per-step tokens start as chars/4 estimates and are rescaled to sum to the
    query's true output_tokens once its ResultMessage arrives; the per-message
    split remains approximate either way (hence the ~ in the display).
    """
    log = run_dir / "logs" / f"{agent}.jsonl"
    if not log.exists():
        return []
    # logs of finished runs never change; avoid re-parsing (and re-reading over
    # a network mount on the Space) on every page view
    stat = log.stat()
    cache_key = (str(log), stat.st_mtime_ns, stat.st_size)
    if cache_key in _windows_cache:
        return _windows_cache[cache_key]
    steps = []  # one per API call: {id, wake, tools, post, tokens}
    for line in log.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        data = d.get("data", {})
        if d.get("type") == "AssistantMessage":
            mid = data.get("message_id")
            if not steps or steps[-1]["id"] != mid:  # blocks stream one per log entry
                steps.append({"id": mid, "wake": d.get("wake") or d.get("query"), "tools": 0,
                              "post": False, "tokens": 0})
            s = steps[-1]
            for b in data.get("content", []):
                if not isinstance(b, dict):
                    continue
                if "name" in b:
                    s["tools"] += 1
                    s["tokens"] += len(json.dumps(b.get("input") or {})) // 4
                    if is_board_post(b, agent):
                        s["post"] = True
                else:
                    s["tokens"] += len(str(b.get("text") or b.get("thinking") or "")) // 4
        elif d.get("type") == "ResultMessage":
            total = (data.get("usage") or {}).get("output_tokens") or 0
            wake = d.get("wake") or d.get("query")
            wake_steps = [s for s in steps if s["wake"] == wake]
            estimated = sum(s["tokens"] for s in wake_steps)
            if total and estimated:
                for s in wake_steps:
                    s["tokens"] = round(s["tokens"] * total / estimated)
    windows, tools, tokens = [], 0, 0
    for s in steps:
        tools += s["tools"]
        tokens += s["tokens"]
        if s["post"]:
            windows.append((tools, tokens))
            tools, tokens = 0, 0
    _windows_cache[cache_key] = windows
    return windows


_windows_cache = {}


def fmt_tokens(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _metric(value):
    return f"{float(value):.3f}" if isinstance(value, (int, float)) else "—"


def _mean(values):
    usable = [float(v) for v in values if isinstance(v, (int, float))]
    return sum(usable) / len(usable) if usable else None


def _run_replicate(run_id):
    match = re.search(r"--(\d+)$", run_id)
    return match.group(1) if match else "01"


def _evaluation_metrics(evaluation):
    """Flatten the v2 evaluation fields used by the study-level pages."""
    diversity = evaluation.get("diversity") or {}
    end_round = diversity.get("end_round") or {}
    chosen = (evaluation.get("outcome") or {}).get("chosen") or {}
    crossover = ((evaluation.get("crossover") or {}).get("outcomes") or {})
    manipulation = ((evaluation.get("crossover") or {}).get("manipulation") or {})

    def outcome(name, field="intent_to_treat_difference"):
        return (crossover.get(name) or {}).get(field)

    return {
        "primary": diversity.get("end_of_deliberation_effective_candidates"),
        "phase": diversity.get("crossover_phase_effective_candidates"),
        "final": (diversity.get("final_recommendations") or {}).get(
            "effective_candidates"
        ),
        "survival": (diversity.get("candidate_survival") or {}).get(
            "bin_survival_rate"
        ),
        "within": end_round.get("within_lens_mean_effective_candidates"),
        "separation": end_round.get("between_lens_mean_separation"),
        "collapse": 1.0 if (diversity.get("collapse") or {}).get("collapsed") else 0.0,
        "regret": chosen.get("compromise_regret"),
        "crossover_itt": outcome("message_candidate_effective_count"),
        "crossover_span_itt": outcome("message_candidate_span"),
        "final_breadth_itt": outcome("final_candidate_effective_count"),
        "final_span_itt": outcome("final_candidate_span"),
        "nudged_cross": manipulation.get("nudged_cross_lens_rate"),
        "control_cross": manipulation.get("not_nudged_cross_lens_rate"),
    }


def study_summary(runs_root):
    """Aggregate complete v2 runs and their matched channel/flat pairs."""
    rows = []
    for meta in list_runs(runs_root):
        evaluation = meta.get("evaluation") or {}
        if evaluation.get("protocol_version") != V2_PROTOCOL:
            continue
        rows.append({
            "meta": meta,
            "evaluation": evaluation,
            "instance": evaluation.get("instance") or meta["id"].split("--", 1)[0],
            "replicate": _run_replicate(meta["id"]),
            "condition": evaluation.get("condition") or meta["conditions"],
            "metrics": _evaluation_metrics(evaluation),
        })

    conditions = {}
    metric_names = (
        "primary", "phase", "final", "survival", "within", "separation",
        "collapse", "regret", "crossover_itt", "crossover_span_itt",
        "final_breadth_itt", "final_span_itt", "nudged_cross", "control_cross",
    )
    for condition in ("channels", "flat"):
        selected = [row for row in rows if row["condition"] == condition]
        conditions[condition] = {
            "runs": len(selected),
            **{
                name: _mean([row["metrics"].get(name) for row in selected])
                for name in metric_names
            },
        }

    grouped = {}
    for row in rows:
        grouped.setdefault((row["instance"], row["replicate"]), {})[
            row["condition"]
        ] = row
    pairs = []
    for (instance, replicate), matched in sorted(grouped.items()):
        if not {"channels", "flat"}.issubset(matched):
            continue
        channel = matched["channels"]
        flat = matched["flat"]
        deltas = {}
        for name in metric_names:
            c_value = channel["metrics"].get(name)
            f_value = flat["metrics"].get(name)
            deltas[name] = (
                c_value - f_value
                if isinstance(c_value, (int, float)) and isinstance(f_value, (int, float))
                else None
            )
        pairs.append({
            "instance": instance,
            "replicate": replicate,
            "channels": channel,
            "flat": flat,
            "deltas": deltas,
            "evidence_match": (
                channel["evaluation"].get("shared_evidence_sha256")
                == flat["evaluation"].get("shared_evidence_sha256")
            ),
        })

    paired = {
        name: _mean([pair["deltas"].get(name) for pair in pairs])
        for name in metric_names
    }
    return {
        "rows": rows,
        "conditions": conditions,
        "pairs": pairs,
        "paired": paired,
        "runs": len(rows),
        "instances": len({row["instance"] for row in rows}),
        "messages": sum(row["meta"].get("n_msgs", 0) for row in rows),
    }


# ---------------------------------------------------------------- terminal view

def print_chat(run_dir, msgs, agents):
    width = min(shutil.get_terminal_size().columns, 110)
    body_w = max(40, width - 34)
    color = {a: COLORS[i % len(COLORS)] for i, a in enumerate(agents)}
    windows = {a: load_windows(run_dir, a) for a in agents}
    n_posted = {a: 0 for a in agents}

    for m in msgs:
        a = m["agent"]
        indent = " " * 24 * (agents.index(a) % 2 if a in agents else 0)
        agent_windows = windows.get(a, [])
        i = n_posted.get(a, 0)
        tools, tokens = agent_windows[i] if i < len(agent_windows) else (0, 0)
        n_posted[a] = i + 1
        ts = datetime.fromtimestamp(m["epoch"]).strftime("%H:%M:%S")
        route = f"{m.get('channel')} · {m.get('lens')} · x={m.get('candidate_x')}"
        print(f"{indent}{color.get(a, '')}{BOLD}{a}{RESET} {DIM}{route} · {ts} · "
              f"{tools} tool calls · ~{fmt_tokens(tokens)} out-tokens since last msg{RESET}")
        for line in m["content"].splitlines() or [""]:
            for chunk in textwrap.wrap(line, body_w) or [""]:
                print(f"{indent}  {chunk}")
        print()


def print_file(title, path):
    print(f"\n{BOLD}── {title} " + "─" * 30 + RESET)
    print(path.read_text().strip() if path.exists() else f"{DIM}(not written){RESET}")


# ------------------------------------------------------------------- html view

CSS = """
:root {
  --bg:#eef1f3; --panel:#ffffff; --panel-2:#f5f8f9; --border:#d7dee3;
  --text:#10161b; --muted:#6a757d; --accent:#0e7c86;
  --go:#178236; --danger:#b3453f;
  --mono:'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
}
[data-theme='dark'] {
  --bg:#0b0f13; --panel:#11181e; --panel-2:#141c23; --border:#222b34;
  --text:#e7eef1; --muted:#6a757d; --accent:#2bb3bd;
  --go:#2ea043; --danger:#c96a63;
}
* { box-sizing:border-box }
html { height:100% }
body { margin:0; min-height:100%; background:var(--bg); color:var(--text);
  font:13px/1.55 'Geist', system-ui, -apple-system, sans-serif; }
a { color:inherit; text-decoration:none }
.mono { font-family:var(--mono); font-size:11px }
.muted { color:var(--muted) }
::-webkit-scrollbar { width:8px; height:8px }
::-webkit-scrollbar-thumb { background:var(--border); border-radius:8px }
:focus-visible { outline:2px solid color-mix(in srgb, var(--accent) 45%, transparent);
  outline-offset:1px; }

aside { position:fixed; top:0; bottom:0; left:0; width:280px; overflow-y:auto;
  background:var(--panel); border-right:1px solid var(--border);
  display:flex; flex-direction:column; }
.brand { padding:14px 16px; border-bottom:1px solid var(--border);
  font-weight:600; font-size:13px; letter-spacing:-0.01em; display:flex;
  align-items:center; justify-content:space-between; }
nav { flex:1; padding:8px }
.nav-label { font-family:var(--mono); font-size:10.5px; text-transform:uppercase;
  letter-spacing:.06em; color:var(--muted); padding:10px 10px 4px; }
.run-item { display:block; padding:8px 10px; border-radius:6px; margin-bottom:2px;
  border:1px solid transparent; transition:border-color .12s ease-out,
  background-color .12s ease-out; }
.run-item:hover { border-color:var(--border); background:var(--panel-2) }
.run-item.active { background:color-mix(in srgb, var(--accent) 10%, transparent);
  border-color:color-mix(in srgb, var(--accent) 30%, transparent); }
.run-name { font-weight:500; font-size:12.5px; display:flex; align-items:center;
  gap:6px; }
.run-sub { margin-top:2px; padding-left:14px }
.dot { width:8px; height:8px; border-radius:50%; flex:none; background:var(--muted) }
.o-agreed { background:var(--go) } .o-running { background:var(--accent) }
.o-stuck, .o-stalled { background:var(--danger) }

main { margin-left:280px; padding:28px 34px 72px; max-width:1180px }
h1 { font-size:15px; font-weight:600; letter-spacing:-0.01em; margin:0 }
h2 { font-size:11px; font-weight:600; letter-spacing:.06em; text-transform:uppercase;
  color:var(--muted); margin:26px 0 10px; }
.stage-head { display:flex; align-items:center; gap:12px; margin-bottom:18px;
  flex-wrap:wrap; }
.chip { display:inline-flex; align-items:center; gap:6px; padding:2px 9px;
  border-radius:4px; border:1px solid var(--border); background:var(--panel);
  font-family:var(--mono); font-size:11px; }
.chip .dot { width:7px; height:7px }
.chip.o-running .dot { animation:breathe 2s ease-in-out infinite }

.pane { background:var(--panel); border:1px solid var(--border); border-radius:10px;
  padding:14px 16px; }
.agents { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));
  gap:10px; }
.agent-head { display:flex; align-items:baseline; gap:8px; margin-bottom:6px }
.tag { display:inline-block; padding:1px 7px; border-radius:4px;
  background:var(--panel-2); border:1px solid var(--border);
  font-family:var(--mono); font-size:11px; font-weight:500; }

.chat { display:flex; flex-direction:column; gap:10px }
.msg { max-width:86%; background:var(--panel); border:1px solid var(--border);
  border-radius:8px; padding:10px 14px; animation:rise .14s ease-out both; }
.msg.right { align-self:flex-end; background:var(--panel-2) }
.msg-head { display:flex; align-items:baseline; gap:8px; margin-bottom:4px }

details { border:1px solid var(--border); border-radius:8px; background:var(--panel);
  padding:8px 12px; margin-top:8px; }
details[open] { padding-bottom:12px }
summary { cursor:pointer; font-family:var(--mono); font-size:11px;
  color:var(--muted); transition:color .12s ease-out; }
summary:hover { color:var(--text) }
details .md, details pre { margin-top:8px }

.md a { color:var(--accent) } .md a:hover { text-decoration:underline }
.md { font-size:12.5px } .md > :first-child { margin-top:0 }
.md > :last-child { margin-bottom:0 }
.md p, .md ul, .md ol { margin:6px 0 } .md li { margin:2px 0 }
.md h1, .md h2, .md h3 { font-size:12.5px; letter-spacing:0; text-transform:none;
  color:var(--text); margin:12px 0 4px; }
.md code { font-family:var(--mono); font-size:11px; background:var(--panel-2);
  border:1px solid var(--border); border-radius:4px; padding:0 4px; }
.md pre { background:var(--panel-2); border:1px solid var(--border);
  border-radius:6px; padding:10px 12px; overflow-x:auto; }
.md pre code { background:none; border:none; padding:0 }
.md table { border-collapse:collapse } .md th, .md td { border:1px solid var(--border);
  padding:4px 8px; font-size:12px; }
pre.raw { font-family:var(--mono); font-size:11px; white-space:pre-wrap;
  overflow-wrap:break-word; margin:0; }

table.index { width:100%; border-collapse:collapse;
  font-variant-numeric:tabular-nums; }
.index th, .index td { text-align:left; padding:7px 10px;
  border-bottom:1px solid var(--border); font-size:12.5px; }
.index th { font-family:var(--mono); font-size:10.5px; text-transform:uppercase;
  letter-spacing:.06em; color:var(--muted); font-weight:500; }
.index tr:last-child td { border-bottom:none }
.index td .dot { display:inline-block; margin-right:6px }

.loadbar { position:fixed; top:0; left:280px; right:0; height:2px; z-index:20;
  opacity:0; pointer-events:none; overflow:hidden;
  transition:opacity .12s ease-out; }
.loadbar::before { content:""; display:block; height:100%; width:30%;
  background:var(--accent); border-radius:2px;
  animation:slide 1.1s ease-in-out infinite; }
body.loading .loadbar { opacity:1; transition-delay:.15s }

.icon-btn { width:30px; height:30px; display:inline-flex; align-items:center;
  justify-content:center; border-radius:6px; border:1px solid var(--border);
  background:var(--panel); color:var(--muted); cursor:pointer; font-size:13px;
  transition:border-color .12s ease-out, color .12s ease-out; }
.icon-btn:hover { border-color:var(--muted); color:var(--text) }

.hero { position:relative; overflow:hidden; padding:34px 36px; border-radius:16px;
  color:#f4fbfc; background:#102a31; border:1px solid #24464d; }
.hero::after { content:""; position:absolute; width:280px; height:280px;
  border-radius:50%; right:-110px; top:-120px;
  background:radial-gradient(circle, rgba(43,179,189,.28), rgba(43,179,189,0) 68%); }
.eyebrow { font-family:var(--mono); font-size:10.5px; text-transform:uppercase;
  letter-spacing:.12em; color:#82d7dc; margin-bottom:14px; }
.hero h1 { max-width:720px; font-size:36px; line-height:1.08; letter-spacing:-.04em;
  font-weight:600; color:#f7fcfd; }
.hero .lede { max-width:760px; margin:16px 0 0; color:#bfd0d4;
  font-size:15px; line-height:1.65; }
.hero-meta { position:relative; z-index:1; display:flex; flex-wrap:wrap; gap:8px;
  margin-top:24px; }
.hero-meta .chip { color:#d8e7e9; background:rgba(255,255,255,.05);
  border-color:rgba(255,255,255,.14); }

.section-head { display:flex; align-items:flex-end; justify-content:space-between;
  gap:20px; margin:34px 0 12px; }
.section-head h2 { margin:0; }
.section-head p { max-width:620px; margin:0; color:var(--muted); font-size:12px; }
.stat-grid { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr));
  gap:10px; margin-top:12px; }
.stat-card { padding:15px 16px; border:1px solid var(--border); border-radius:10px;
  background:var(--panel); }
.stat-value { font-size:23px; line-height:1.1; letter-spacing:-.03em;
  font-variant-numeric:tabular-nums; }
.stat-label { margin-top:6px; color:var(--muted); font-family:var(--mono);
  font-size:10.5px; }
.setup-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.condition-card { position:relative; overflow:hidden; padding:20px;
  border:1px solid var(--border); border-radius:12px; background:var(--panel); }
.condition-card::before { content:""; position:absolute; left:0; top:0; bottom:0;
  width:4px; background:var(--muted); }
.condition-card.channels::before { background:var(--accent); }
.condition-card h3, .definition-card h3, .lens-card h3 { margin:0 0 7px;
  font-size:14px; letter-spacing:-.01em; }
.condition-card p, .definition-card p, .lens-card p { margin:0; color:var(--muted); }
.condition-card ul { margin:12px 0 0; padding-left:18px; }
.condition-card li { margin:5px 0; }
.lens-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:10px; }
.lens-card { padding:15px 16px; background:var(--panel-2); border:1px solid var(--border);
  border-radius:9px; }
.lens-card .tag { margin-bottom:9px; }
.protocol { display:grid; grid-template-columns:repeat(6, 1fr); gap:7px;
  counter-reset:phase; }
.protocol-step { min-height:104px; padding:12px; border:1px solid var(--border);
  border-radius:9px; background:var(--panel); }
.protocol-step::before { counter-increment:phase; content:counter(phase, decimal-leading-zero);
  display:block; margin-bottom:12px; color:var(--accent); font-family:var(--mono);
  font-size:10px; }
.protocol-step strong { display:block; font-size:12px; }
.protocol-step span { display:block; margin-top:5px; color:var(--muted); font-size:11px; }

.result-table .metric-title { font-weight:600; }
.result-table .metric-purpose { display:block; color:var(--muted); font-size:11px;
  margin-top:2px; }
.result-table td { vertical-align:top; }
.result-table td.num { font-family:var(--mono); font-variant-numeric:tabular-nums; }
.delta { display:inline-flex; align-items:center; justify-content:center; min-width:56px;
  padding:2px 7px; border-radius:4px; border:1px solid var(--border);
  font-family:var(--mono); font-size:10.5px; }
.delta.positive { color:var(--accent); border-color:color-mix(in srgb, var(--accent) 42%, var(--border));
  background:color-mix(in srgb, var(--accent) 9%, transparent); }
.delta.negative { color:#a7592f; border-color:color-mix(in srgb, #c26a38 38%, var(--border));
  background:color-mix(in srgb, #c26a38 9%, transparent); }
.delta.neutral { color:var(--muted); background:var(--panel-2); }
.takeaway { display:grid; grid-template-columns:auto 1fr; gap:14px; align-items:start;
  margin-top:12px; padding:16px 18px; border-radius:10px;
  border:1px solid color-mix(in srgb, var(--accent) 35%, var(--border));
  background:color-mix(in srgb, var(--accent) 7%, var(--panel)); }
.takeaway-mark { width:28px; height:28px; display:grid; place-items:center;
  border-radius:50%; color:var(--accent); background:var(--panel); border:1px solid var(--border);
  font-family:var(--mono); font-size:11px; }
.takeaway strong { display:block; margin-bottom:3px; }
.takeaway p { margin:0; color:var(--muted); }
.caveat { border-left:3px solid #c58a2c; padding:11px 14px; background:var(--panel-2);
  color:var(--muted); border-radius:0 8px 8px 0; }
.cta-row { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
.btn { display:inline-flex; align-items:center; min-height:36px; padding:0 13px;
  border-radius:7px; border:1px solid var(--border); background:var(--panel);
  font-weight:500; transition:border-color .12s ease-out, transform .12s ease-out; }
.btn:hover { border-color:var(--accent); transform:translateY(-1px); }
.btn.primary { color:white; background:var(--accent); border-color:var(--accent); }

.pair-list { display:flex; flex-direction:column; gap:10px; }
.pair-card { padding:16px 18px; border:1px solid var(--border); border-radius:10px;
  background:var(--panel); }
.pair-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.pair-head h3 { margin:0; font-size:13px; }
.pair-note { margin:8px 0 0; color:var(--muted); }
.trajectory { display:grid; grid-template-columns:72px repeat(4, minmax(56px, 1fr));
  gap:6px; align-items:center; margin-top:12px; }
.trajectory-label { font-family:var(--mono); font-size:10.5px; color:var(--muted); }
.round-cell { position:relative; overflow:hidden; padding:7px 8px; border-radius:5px;
  border:1px solid var(--border); font-family:var(--mono); font-size:10.5px;
  font-variant-numeric:tabular-nums; background:var(--panel-2); }
.round-cell::before { content:""; position:absolute; left:0; bottom:0; height:2px;
  width:var(--level); background:var(--accent); }
.round-head { text-align:center; color:var(--muted); font-family:var(--mono);
  font-size:9.5px; text-transform:uppercase; letter-spacing:.05em; }
.candidate-line { margin-top:9px; font-family:var(--mono); font-size:10.5px;
  color:var(--muted); }
.candidate-line b { color:var(--text); font-weight:500; }

.metric-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; }
.definition-card { padding:17px 18px; border:1px solid var(--border); border-radius:10px;
  background:var(--panel); }
.definition-card .metric-meta { display:flex; gap:6px; flex-wrap:wrap; margin:10px 0; }
.formula { margin:11px 0; padding:9px 11px; border-radius:6px; background:var(--panel-2);
  border:1px solid var(--border); font-family:var(--mono); font-size:11px; }
.definition-card dl { display:grid; grid-template-columns:82px 1fr; gap:5px 10px;
  margin:12px 0 0; }
.definition-card dt { font-family:var(--mono); color:var(--muted); font-size:10px; }
.definition-card dd { margin:0; font-size:11.5px; }
.trace-intro { display:grid; grid-template-columns:1fr auto; gap:20px; align-items:center;
  margin-bottom:12px; }
.trace-intro p { margin:5px 0 0; color:var(--muted); }
.pair-link { display:inline-flex; margin-left:6px; color:var(--accent); font-family:var(--mono);
  font-size:10.5px; }

@keyframes rise { from { opacity:0; transform:translateY(3px) } }
@keyframes slide { from { transform:translateX(-110%) }
  to { transform:translateX(343%) } }
@keyframes breathe { 50% { opacity:.45 } }
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after { animation:none !important; transition:none !important }
}
@media (max-width:900px) {
  aside { position:relative; width:100%; max-height:260px; border-right:0;
    border-bottom:1px solid var(--border); }
  main { margin-left:0; padding:20px 18px 56px; }
  .loadbar { left:0; }
  .stat-grid { grid-template-columns:repeat(2, 1fr); }
  .protocol { grid-template-columns:repeat(3, 1fr); }
}
@media (max-width:620px) {
  .hero { padding:26px 22px; }
  .hero h1 { font-size:29px; }
  .setup-grid, .lens-grid, .metric-grid { grid-template-columns:1fr; }
  .protocol { grid-template-columns:repeat(2, 1fr); }
  .section-head { align-items:flex-start; flex-direction:column; gap:6px; }
  .index { display:block; overflow-x:auto; }
  .trajectory { grid-template-columns:62px repeat(4, minmax(52px, 1fr)); }
}
"""

JS = """
const saved = localStorage.getItem('viz-theme');
const sysDark = matchMedia('(prefers-color-scheme: dark)').matches;
document.documentElement.dataset.theme = saved || (sysDark ? 'dark' : 'light');
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('viz-theme', next);
}
// client-side navigation: swap main+sidebar in place instead of full reloads
async function load(href, push) {
  if (push) document.body.classList.add('loading');
  try {
    const doc = new DOMParser().parseFromString(
      await (await fetch(href)).text(), 'text/html');
    document.querySelector('main').innerHTML = doc.querySelector('main').innerHTML;
    document.querySelector('aside').innerHTML = doc.querySelector('aside').innerHTML;
    document.title = doc.title;
    document.body.dataset.running = doc.body.dataset.running;
    if (push) { history.pushState({}, '', href); scrollTo(0, 0); }
    wire();
  } catch (e) { location.href = href; }
  finally { document.body.classList.remove('loading'); }
}
function wire() {
  document.querySelectorAll('a[href^="/"]').forEach(a => {
    a.onclick = e => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || a.target === '_blank') return;
      e.preventDefault(); load(a.href, true);
    };
  });
}
window.onpopstate = () => load(location.href, false);
wire();
setInterval(() => {
  if (document.body.dataset.running === '1') load(location.href, false);
}, 15000);
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600'
         '&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet"'
         ' media="print" onload="this.media=\'all\'">')


def esc(s):
    return html_mod.escape(str(s))


def md_render(text):
    body = md_lib.markdown(text, extensions=["fenced_code", "tables", "sane_lists"])
    return f'<div class="md">{body}</div>'


def run_meta(run_dir):
    """Summary dict for the sidebar and index."""
    cfg = yaml.safe_load((run_dir / "config.snapshot.yaml").read_text())
    stats_path = run_dir / "stats.json"
    stats = json.loads(stats_path.read_text()) if stats_path.exists() else None
    evaluation_path = run_dir / "evaluation.json"
    evaluation = json.loads(evaluation_path.read_text()) if evaluation_path.exists() else None
    outcome = stats["outcome"] if stats else "running"
    messages = load_board(run_dir)
    return {
        "id": run_dir.name, "dir": run_dir, "cfg": cfg, "stats": stats,
        "evaluation": evaluation,
        "outcome": outcome,
        "n_msgs": len(messages),
        "cost": sum(a.get("cost_usd") or 0
                    for a in (stats or {}).get("agents", {}).values()),
        "duration": (stats or {}).get("duration_seconds"),
        "protocol": cfg.get("protocol_version", "v1-gated"),
        "conditions": cfg.get("condition", "legacy"),
    }


_runs_cache = {"root": None, "at": 0.0, "value": None}


def list_runs(runs_root, ttl=10.0):
    now = time.monotonic()
    if _runs_cache["root"] == str(runs_root) and now - _runs_cache["at"] < ttl:
        return _runs_cache["value"]
    metas = []
    for d in sorted(runs_root.glob("*/"), reverse=True):
        if (d / "config.snapshot.yaml").exists():
            try:
                metas.append(run_meta(d))
            except Exception:
                continue
    _runs_cache.update(root=str(runs_root), at=now, value=metas)
    return metas


def page(title, sidebar, content, running=False):
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)}</title>{FONTS}<style>{CSS}</style></head>'
            f'<body data-running="{1 if running else 0}">'
            f'<div class="loadbar"></div>'
            f'<aside>{sidebar}</aside><main>{content}</main>'
            f'<script>{JS}</script></body></html>')


def list_reports(meta_dir):
    reports = []
    if not meta_dir.is_dir():
        return reports
    for f in sorted(meta_dir.glob("*.md"), reverse=True):
        if f.name.lower() == "readme.md":
            continue
        title = f.stem
        for line in f.read_text().splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        reports.append({"stem": f.stem, "title": title, "path": f})
    return reports


def sidebar_html(metas, reports, active_id):
    items = [f'<div class="brand"><a href="/overview.html">channel-ablation</a>'
             f'<button class="icon-btn" onclick="toggleTheme()" '
             f'title="toggle theme" aria-label="toggle theme">◐</button></div><nav>']
    items.append('<div class="nav-label">Study</div>')
    for stem, title, href in (
        ("overview", "Overview", "/overview.html"),
        ("results", "Results deep dive", "/results.html"),
        ("metrics", "Metric definitions", "/metrics.html"),
        ("runs-index", "Trace explorer", "/runs/index.html"),
    ):
        active = " active" if stem == active_id else ""
        items.append(
            f'<a class="run-item{active}" href="{href}">'
            f'<span class="run-name">{esc(title)}</span></a>'
        )
    if reports:
        items.append('<div class="nav-label">Reports</div>')
        for r in reports:
            active = " active" if r["stem"] == active_id else ""
            items.append(
                f'<a class="run-item{active}" href="/reports/{esc(r["stem"])}.html">'
                f'<span class="run-name">{esc(r["title"])}</span></a>')
    items.append('<div class="nav-label">Individual traces</div>')
    for m in metas:
        active = " active" if m["id"] == active_id else ""
        items.append(
            f'<a class="run-item{active}" href="/runs/{esc(m["id"])}/report.html">'
            f'<span class="run-name"><span class="dot o-{esc(m["outcome"])}"></span>'
            f'{esc(m["id"])}</span>'
            f'<div class="run-sub mono muted">{m["n_msgs"]} msgs · '
            f'{esc(m["protocol"])} · {esc(m["conditions"])} · '
            f'${m["cost"]:.2f}</div></a>')
    items.append('</nav>')
    return "".join(items)


def autolink(html, runs_root):
    """Link run ids and prompt paths wherever they appear in rendered HTML."""
    for m in list_runs(runs_root):
        html = re.sub(
            rf'(?<![\w/-]){re.escape(m["id"])}(?![\w-])',
            f'<a href="/runs/{m["id"]}/report.html">{m["id"]}</a>', html)
    html = re.sub(
        r'(?<![\w/-])prompts/([\w-]+)/([\w-]+)\.md(?![\w-])',
        r'<a href="/prompts/\1/\2.html">prompts/\1/\2.md</a>', html)
    return html


def render_report_page(md_path, runs_root):
    reports = list_reports(md_path.parent)
    content = autolink(md_render(md_path.read_text()), runs_root)
    body = (f'<div class="stage-head"><h1>Report</h1>'
            f'<span class="mono muted">{esc(md_path.name)}</span></div>'
            f'<div class="pane">{content}</div>')
    return page(md_path.stem, sidebar_html(list_runs(runs_root), reports,
                                           md_path.stem), body)


def render_prompt_page(md_path, runs_root):
    meta_dir = runs_root.parent / "meta-analysis"
    body = (f'<div class="stage-head"><h1>Social prompt</h1>'
            f'<span class="mono muted">{esc(md_path.parent.name)}/{esc(md_path.name)}'
            f'</span></div><div class="pane">{md_render(md_path.read_text())}</div>')
    return page(md_path.stem, sidebar_html(list_runs(runs_root),
                                           list_reports(meta_dir), None), body)


def _signed(value):
    if not isinstance(value, (int, float)):
        return "—"
    if abs(value) < 0.0005:
        return "0.000"
    return f"{value:+.3f}"


def _delta_class(value, neutral_threshold=0.0005):
    if not isinstance(value, (int, float)) or abs(value) < neutral_threshold:
        return "neutral"
    return "positive" if value > 0 else "negative"


def _readout(metric, delta):
    if not isinstance(delta, (int, float)):
        return "Not available"
    if metric == "primary" and abs(delta) < 0.1:
        return "No durable advantage"
    if metric == "regret":
        if abs(delta) < 0.0005:
            return "Same solution quality"
        return "Channels have more regret" if delta > 0 else "Channels have less regret"
    if metric == "final" and abs(delta) < 0.01:
        return "Same private convergence"
    if metric == "survival":
        return "Channels retain more" if delta > 0 else "Channels retain fewer"
    return "Channels higher" if delta > 0 else ("Flat higher" if delta < 0 else "Tied")


def _result_rows(summary):
    channels = summary["conditions"].get("channels", {})
    flat = summary["conditions"].get("flat", {})
    definitions = (
        ("primary", "Final-round diversity", "Primary: distinct candidates still live at the end"),
        ("phase", "Crossover-phase diversity", "Secondary: breadth across both crossover rounds"),
        ("survival", "Candidate survival", "Fraction of crossover bins that remain in the last round"),
        ("within", "Within-lens diversity", "Whether each viewpoint still contains alternatives"),
        ("final", "Private final diversity", "Variation in agents' private recommendations"),
        ("regret", "Compromise regret", "Quality gap from the known best answer; lower is better"),
    )
    rows = []
    for name, title, purpose in definitions:
        delta = summary["paired"].get(name)
        rows.append(
            '<tr>'
            f'<td><span class="metric-title">{esc(title)}</span>'
            f'<span class="metric-purpose">{esc(purpose)}</span></td>'
            f'<td class="num">{_metric(channels.get(name))}</td>'
            f'<td class="num">{_metric(flat.get(name))}</td>'
            f'<td><span class="delta {_delta_class(delta, 0.1 if name == "primary" else 0.0005)}">'
            f'{esc(_signed(delta))}</span></td>'
            f'<td>{esc(_readout(name, delta))}</td></tr>'
        )
    return "".join(rows)


def render_overview_page(runs_root):
    metas = list_runs(runs_root)
    reports = list_reports(runs_root.parent / "meta-analysis")
    summary = study_summary(runs_root)
    channels = summary["conditions"].get("channels", {})
    flat = summary["conditions"].get("flat", {})
    primary_delta = summary["paired"].get("primary")
    phase_delta = summary["paired"].get("phase")
    survival_delta = summary["paired"].get("survival")
    agents = 6

    content = f'''
    <section class="hero">
      <div class="eyebrow">Multi-agent collaboration experiment · v2 shared evidence</div>
      <h1>Do opinionated channels preserve useful diversity?</h1>
      <p class="lede">We compare one shared discussion stream with two separate feeds
      organized around opposing analytical lenses. The goal is to learn whether channels
      keep multiple promising positions alive—or merely create temporary activity before
      the agents converge.</p>
      <div class="hero-meta">
        <span class="chip">{summary["instances"]} bargaining instances</span>
        <span class="chip">{agents} Claude Sonnet 5 agents</span>
        <span class="chip">{summary["runs"]} completed runs</span>
        <span class="chip">{summary["messages"]} public messages</span>
      </div>
    </section>

    <div class="stat-grid">
      <div class="stat-card"><div class="stat-value">{_signed(primary_delta)}</div>
        <div class="stat-label">final diversity · channels − flat</div></div>
      <div class="stat-card"><div class="stat-value">{_signed(phase_delta)}</div>
        <div class="stat-label">crossover diversity · channels − flat</div></div>
      <div class="stat-card"><div class="stat-value">{_signed(survival_delta)}</div>
        <div class="stat-label">candidate survival · channels − flat</div></div>
      <div class="stat-card"><div class="stat-value">0</div>
        <div class="stat-label">quality regret in either condition</div></div>
    </div>

    <div class="section-head"><h2>Experimental setup</h2>
      <p>Only the communication topology changes inside each matched pair. Agents,
      evidence, utilities, prompts, timing, and synthesis are held fixed.</p></div>
    <div class="setup-grid">
      <article class="condition-card">
        <span class="tag">Flat control</span><h3>One globally visible stream</h3>
        <p>Both viewpoints appear as message tags in the same feed, so every agent sees
        every argument throughout deliberation.</p>
        <ul><li>No information boundaries between lenses</li>
        <li>Agents may switch the lens attached to each post</li>
        <li>Tests whether a shared context can sustain adversarial reasoning</li></ul>
      </article>
      <article class="condition-card channels">
        <span class="tag">Channels treatment</span><h3>Two opinionated feeds</h3>
        <p>Agents begin in a home channel. Posting through the other lens subscribes them
        to that feed from the following round.</p>
        <ul><li>Sum-welfare and Nash-welfare arguments are separated</li>
        <li>Facts remain shared; only discussion topology changes</li>
        <li>Tests whether structure protects alternative lines of reasoning</li></ul>
      </article>
    </div>
    <div class="lens-grid">
      <article class="lens-card"><span class="tag">sum-welfare</span>
        <h3>Maximize aggregate benefit</h3><p>Agents build the strongest case for total
        utility and identify when protecting a small loss creates a larger aggregate cost.
        Every post must name a candidate policy.</p></article>
      <article class="lens-card"><span class="tag">nash-welfare</span>
        <h3>Avoid sacrificing low-utility groups</h3><p>Agents use balanced utility to expose
        severe individual losses hidden by a healthy aggregate score. Every post must name
        a candidate policy.</p></article>
    </div>

    <div class="section-head"><h2>Agent incentives and information flow</h2>
      <p>Three agents start under each lens. Half receive a frozen, randomized prompt to
      argue from the opposite lens during crossover.</p></div>
    <div class="protocol">
      <div class="protocol-step"><strong>Private baseline</strong><span>Each agent reasons
        from one constituency before seeing the group.</span></div>
      <div class="protocol-step"><strong>Shared evidence</strong><span>All six utility curves
        are published identically to both conditions.</span></div>
      <div class="protocol-step"><strong>Home rounds</strong><span>Two synchronous rounds
        build the strongest case for each assigned lens.</span></div>
      <div class="protocol-step"><strong>Crossover</strong><span>Three agents are encouraged
        to pressure-test the opposite viewpoint for two rounds.</span></div>
      <div class="protocol-step"><strong>Private final</strong><span>Agents record their own
        recommendation before seeing the full synthesis.</span></div>
      <div class="protocol-step"><strong>Synthesis</strong><span>One agent integrates the
        record; all six independently review the decision.</span></div>
    </div>

    <div class="section-head"><h2>High-level results</h2>
      <p>Values are means over the five matched v2 instances. Deltas are channels minus
      flat within each matched instance.</p></div>
    <div class="pane"><table class="index result-table">
      <tr><th>Outcome</th><th>Channels</th><th>Flat</th><th>Paired Δ</th><th>Readout</th></tr>
      {_result_rows(summary)}
    </table></div>
    <div class="takeaway"><div class="takeaway-mark">Δ</div><div>
      <strong>Channels create exploration, not persistence.</strong>
      <p>They increased candidate diversity during crossover in four of five instances,
      but retained fewer of those candidates and produced essentially no final-round
      advantage. Both conditions always found the exact known optimum.</p></div></div>
    <div class="caveat" style="margin-top:12px"><strong>Preliminary block.</strong>
      Model sampling is unseeded and this is one five-instance replication. Near-zero mean
      effect is not evidence of equivalence; the preregistration requires another complete
      block before inferential claims.</div>
    <div class="cta-row"><a class="btn primary" href="/results.html">Explore the results</a>
      <a class="btn" href="/metrics.html">Understand the metrics</a>
      <a class="btn" href="/runs/index.html">Inspect agent traces</a></div>
    '''
    return page("Channel ablation · overview", sidebar_html(metas, reports, "overview"),
                content)


def _round_values(row):
    rounds = ((row["evaluation"].get("diversity") or {}).get("rounds") or {})
    return [
        (rounds.get(str(index)) or {}).get("effective_candidates")
        for index in range(1, 5)
    ]


def _trajectory_html(label, values):
    cells = [f'<div class="trajectory-label">{esc(label)}</div>']
    for value in values:
        width = min(100, max(0, float(value or 0) / 6 * 100))
        cells.append(
            f'<div class="round-cell" style="--level:{width:.1f}%">{_metric(value)}</div>'
        )
    return "".join(cells)


def _final_candidates(row):
    messages = load_board(row["meta"]["dir"])
    final_round = max((m.get("round") or 0 for m in messages), default=0)
    return sorted(
        [m.get("candidate_x") for m in messages if m.get("round") == final_round],
        key=lambda value: (value is None, value),
    )


def render_results_page(runs_root):
    metas = list_runs(runs_root)
    reports = list_reports(runs_root.parent / "meta-analysis")
    summary = study_summary(runs_root)
    channels = summary["conditions"].get("channels", {})
    flat = summary["conditions"].get("flat", {})
    pair_cards = []
    for pair in summary["pairs"]:
        delta = pair["deltas"].get("primary")
        instance = pair["instance"]
        channel_values = _round_values(pair["channels"])
        flat_values = _round_values(pair["flat"])
        channel_candidates = ", ".join(str(v) for v in _final_candidates(pair["channels"]))
        flat_candidates = ", ".join(str(v) for v in _final_candidates(pair["flat"]))
        pair_cards.append(f'''
        <article class="pair-card">
          <div class="pair-head"><h3>{esc(instance)} · replicate {esc(pair["replicate"])}</h3>
            <span class="delta {_delta_class(delta, 0.1)}">primary Δ {esc(_signed(delta))}</span></div>
          <p class="pair-note">{esc(INSTANCE_NOTES.get(instance, "Matched topology comparison."))}</p>
          <div class="trajectory">
            <div></div><div class="round-head">Round 1</div><div class="round-head">Round 2</div>
            <div class="round-head">Round 3</div><div class="round-head">Round 4</div>
            {_trajectory_html("channels", channel_values)}
            {_trajectory_html("flat", flat_values)}
          </div>
          <div class="candidate-line"><b>Final public candidates</b> · channels
            [{esc(channel_candidates)}] · flat [{esc(flat_candidates)}]</div>
          <div class="cta-row">
            <a class="btn" href="/runs/{esc(pair["channels"]["meta"]["id"])}/report.html">Channel trace</a>
            <a class="btn" href="/runs/{esc(pair["flat"]["meta"]["id"])}/report.html">Flat trace</a>
          </div>
        </article>''')

    exact = sum(
        1 for row in summary["rows"]
        if isinstance(row["metrics"].get("regret"), (int, float))
        and abs(row["metrics"]["regret"]) < 1e-12
    )
    content = f'''
    <div class="stage-head"><h1>Results deep dive</h1>
      <span class="mono muted">{len(summary["pairs"])} matched pairs · channels − flat</span></div>
    <div class="takeaway"><div class="takeaway-mark">01</div><div>
      <strong>The temporal effect is more consistent than the terminal effect.</strong>
      <p>Channels raised crossover-phase diversity by {_signed(summary["paired"].get("phase"))}
      on average, yet the final-round effect shrank to {_signed(summary["paired"].get("primary"))}.
      Candidate survival moved {_signed(summary["paired"].get("survival"))}.</p></div></div>

    <div class="section-head"><h2>Condition-level outcomes</h2>
      <p>The primary question is persistence at round 4; phase diversity shows the search
      trajectory that precedes it.</p></div>
    <div class="pane"><table class="index result-table">
      <tr><th>Outcome</th><th>Channels</th><th>Flat</th><th>Paired Δ</th><th>Readout</th></tr>
      {_result_rows(summary)}</table></div>

    <div class="section-head"><h2>Instance trajectories</h2>
      <p>Effective candidate count by synchronous round. The thin bar is scaled against
      the six-agent maximum; exact candidate values show what the metric compresses.</p></div>
    <div class="pair-list">{"".join(pair_cards)}</div>

    <div class="section-head"><h2>Does crossover diversify individual agents?</h2>
      <p>Intention-to-treat values compare the three agents encouraged to use the other
      lens with the three unencouraged agents, averaged across runs.</p></div>
    <div class="pane"><table class="index result-table">
      <tr><th>Within-agent outcome</th><th>Channels ITT</th><th>Flat ITT</th><th>Interpretation</th></tr>
      <tr><td><span class="metric-title">Message candidate diversity</span>
        <span class="metric-purpose">How evenly an agent explored candidate bins</span></td>
        <td class="num">{_signed(channels.get("crossover_itt"))}</td>
        <td class="num">{_signed(flat.get("crossover_itt"))}</td>
        <td>Positive during discussion; larger in flat</td></tr>
      <tr><td><span class="metric-title">Message candidate span</span>
        <span class="metric-purpose">Distance between an agent's lowest and highest candidate</span></td>
        <td class="num">{_signed(channels.get("crossover_span_itt"))}</td>
        <td class="num">{_signed(flat.get("crossover_span_itt"))}</td>
        <td>Agents travel farther under both topologies</td></tr>
      <tr><td><span class="metric-title">Final credible-set diversity</span>
        <span class="metric-purpose">Breadth retained in the private final artifact</span></td>
        <td class="num">{_signed(channels.get("final_breadth_itt"))}</td>
        <td class="num">{_signed(flat.get("final_breadth_itt"))}</td>
        <td>Almost none of the exploration persists</td></tr>
      <tr><td><span class="metric-title">Unencouraged crossing rate</span>
        <span class="metric-purpose">Manipulation check, not a diversity outcome</span></td>
        <td class="num">{_metric(channels.get("control_cross"))}</td>
        <td class="num">{_metric(flat.get("control_cross"))}</td>
        <td>Controls switch lenses more often in channels</td></tr>
    </table></div>

    <div class="section-head"><h2>Quality and limitations</h2></div>
    <div class="setup-grid">
      <div class="condition-card channels"><span class="tag">Quality ceiling</span>
        <h3>{exact} of {summary["runs"]} groups found the exact optimum</h3>
        <p>There is no observed diversity–quality tradeoff. Because the evaluator is exact
        and all factual evidence is shared, this task may be too solvable to reveal whether
        exploration improves the answer.</p></div>
      <div class="condition-card"><span class="tag">Inference boundary</span>
        <h3>One unseeded block</h3><p>Messages and agents are not independent channel-treatment
        samples. The experiment needs another complete five-instance replication before
        making a stable causal claim.</p></div>
    </div>
    <div class="cta-row"><a class="btn primary" href="/runs/index.html">Inspect the traces</a>
      <a class="btn" href="/metrics.html">Metric definitions</a></div>
    '''
    return page("Channel ablation · results", sidebar_html(metas, reports, "results"),
                content)


def render_metrics_page(runs_root):
    metas = list_runs(runs_root)
    reports = list_reports(runs_root.parent / "meta-analysis")
    summary = study_summary(runs_root)
    channels = summary["conditions"].get("channels", {})
    flat = summary["conditions"].get("flat", {})

    cards = (
        ("Primary", "End-of-deliberation effective candidates",
         "Are multiple policy positions still live in the final discussion round?",
         "Bin candidate x values to the nearest 5, compute their proportions pᵦ, then Nₑff = exp(−Σ pᵦ log pᵦ).",
         "Higher means more distinct, more evenly represented candidates.",
         "Local variations can score as diversity even after the original opposing anchors disappear.",
         channels.get("primary"), flat.get("primary")),
        ("Trajectory", "Crossover-phase effective candidates",
         "Did the topology broaden search while agents pressure-tested the other lens?",
         "The same effective-count calculation pooled across both crossover rounds.",
         "Higher means broader exploration during the intervention.",
         "It can reward transient churn that does not survive to the end.",
         channels.get("phase"), flat.get("phase")),
        ("Persistence", "Candidate-bin survival",
         "How much of the candidate set generated at crossover remains live?",
         "Intersection of round-3 and round-4 candidate bins divided by round-3 bins.",
         "Higher means alternatives persist rather than flash and disappear.",
         "It tracks bins, not whether the argument supporting a candidate survived.",
         channels.get("survival"), flat.get("survival")),
        ("Structure", "Within-lens diversity",
         "Does each viewpoint contain alternatives, rather than one fixed position?",
         "Effective candidate count is computed per lens in round 4, then averaged.",
         "Higher means richer search inside each viewpoint.",
         "A lens with only one message can make the unweighted average unstable.",
         channels.get("within"), flat.get("within")),
        ("Structure", "Between-lens separation",
         "Do the two labels still correspond to substantively different positions?",
         "Absolute distance between the round-4 mean candidate under each lens.",
         "Higher means the two camps remain positionally distinct.",
         "Partly induced by the opposing charters, so it is a mechanism check rather than the primary outcome.",
         channels.get("separation"), flat.get("separation")),
        ("Private belief", "Final recommendation diversity",
         "Do agents retain different conclusions after deliberation but before synthesis?",
         "Effective candidate count over the six private final recommendations.",
         "Higher means disagreement survives at the individual-decision level.",
         "Convergence can be desirable when agents integrate evidence correctly.",
         channels.get("final"), flat.get("final")),
        ("Failure mode", "Collapse detector",
         "Did the group settle too early into one concentrated candidate bin?",
         "Two consecutive complete rounds below 1.5 effective candidates with at least 80% endorsement concentration.",
         "Lower is better; a detected collapse is a warning, not automatically a wrong answer.",
         "A collapse that happens only in the final round will not trigger the two-round rule.",
         channels.get("collapse"), flat.get("collapse")),
        ("Quality", "Compromise regret",
         "Did preserving—or losing—diversity change solution quality?",
         "Known maximum harmonic-mean score minus the score at the chosen policy.",
         "Lower is better; zero means the exact optimum was selected.",
         "The current task has a strong ceiling effect because agents can compute the evaluator exactly.",
         channels.get("regret"), flat.get("regret")),
        ("Nested intervention", "Crossover message-diversity ITT",
         "Does being encouraged to use the opposite lens broaden each agent's search?",
         "Mean within-agent message effective count for nudged agents minus unencouraged agents.",
         "Positive means the encouragement increased explored candidate diversity.",
         "Voluntary crossing by controls weakens the first stage, especially in channels.",
         channels.get("crossover_itt"), flat.get("crossover_itt")),
    )
    rendered = []
    for family, name, question, formula, direction, caveat, channel_value, flat_value in cards:
        rendered.append(f'''
        <article class="definition-card"><span class="tag">{esc(family)}</span>
          <h3>{esc(name)}</h3><p>{esc(question)}</p>
          <div class="formula">{esc(formula)}</div>
          <div class="metric-meta"><span class="chip">channels {_metric(channel_value)}</span>
            <span class="chip">flat {_metric(flat_value)}</span></div>
          <dl><dt>Direction</dt><dd>{esc(direction)}</dd>
            <dt>Watch for</dt><dd>{esc(caveat)}</dd></dl>
        </article>''')
    content = f'''
    <div class="stage-head"><h1>Metric definitions</h1>
      <span class="mono muted">what each measure detects—and what it misses</span></div>
    <div class="pane" style="margin-bottom:12px">
      <div class="eyebrow" style="color:var(--accent)">Shared diversity primitive</div>
      <h1 style="font-size:22px">Effective candidate count</h1>
      <p class="muted">Most diversity outcomes use entropy expressed as an intuitive number
      of equally common candidates. Six evenly represented bins score 6; one unanimous bin
      scores 1. Candidate policies are binned to the nearest five points before counting.</p>
      <div class="formula">N<sub>eff</sub> = exp(−Σ<sub>b</sub> p<sub>b</sub> log p<sub>b</sub>)</div>
    </div>
    <div class="metric-grid">{"".join(rendered)}</div>
    <div class="caveat" style="margin-top:14px"><strong>Unit of inference.</strong>
      The run is the unit for the channels treatment. Agent messages are observations, not
      independent treatment replicates. Crossover encouragement uses the agent as its unit.</div>
    <div class="cta-row"><a class="btn primary" href="/results.html">Apply metrics to results</a>
      <a class="btn" href="/runs/index.html">Inspect source traces</a></div>
    '''
    return page("Channel ablation · metrics", sidebar_html(metas, reports, "metrics"),
                content)


def render_run_page(run_dir, runs_root):
    metas = list_runs(runs_root)
    reports = list_reports(runs_root.parent / "meta-analysis")
    meta = next((m for m in metas if m["id"] == run_dir.name), None) or run_meta(run_dir)
    cfg, stats, outcome = meta["cfg"], meta["stats"], meta["outcome"]
    evaluation = meta.get("evaluation")
    agents = [a["name"] for a in cfg["agents"]]
    msgs = load_board(run_dir)
    windows = {a: load_windows(run_dir, a) for a in agents}

    head_meta = f'{meta["n_msgs"]} msgs'
    if stats:
        head_meta = (f'{stats["duration_seconds"]:.0f}s · {head_meta}'
                     f' · ${meta["cost"]:.2f}')
    parts = [f'<div class="stage-head"><h1>{esc(run_dir.name)}</h1>'
             f'<span class="chip o-{esc(outcome)}"><span class="dot o-{esc(outcome)}">'
             f'</span>{esc(outcome)}</span>'
             f'<span class="mono muted">{head_meta}</span></div>',
             f'<div class="mono muted">protocol: {esc(meta["protocol"])} · '
             f'condition: {esc(meta["conditions"])}</div>',
             f'<h2>Task</h2><div class="pane">{md_render(cfg["task"].strip())}</div>']

    if evaluation and meta["protocol"] == V2_PROTOCOL:
        instance = evaluation.get("instance")
        replicate = _run_replicate(meta["id"])
        counterpart = next((
            candidate for candidate in metas
            if candidate["id"] != meta["id"]
            and (candidate.get("evaluation") or {}).get("instance") == instance
            and candidate["protocol"] == meta["protocol"]
            and candidate["conditions"] != meta["conditions"]
            and _run_replicate(candidate["id"]) == replicate
        ), None)
        compare_link = (
            f'<a class="btn" href="/runs/{esc(counterpart["id"])}/report.html">'
            f'Open matched {esc(counterpart["conditions"])} trace</a>'
            if counterpart else ""
        )
        parts.insert(2,
            '<div class="cta-row">'
            '<a class="btn" href="/results.html">Back to study results</a>'
            f'{compare_link}</div>'
        )

    evidence = run_dir / "shared" / "EVIDENCE.md"
    if evidence.exists():
        parts.append(
            f'<h2>Common evidence</h2><div class="pane">'
            f'{md_render(evidence.read_text().strip())}</div>'
        )

    parts.append('<h2>Agents</h2><div class="agents">')
    for spec in cfg["agents"]:
        a = spec["name"]
        s = (stats or {}).get("agents", {}).get(a, {})
        tokens = s.get("tokens", {})
        line = (f'{esc(spec.get("model") or "?")} · '
                f'{esc(spec.get("home_lens", "?"))} home · '
                f'{"crossover" if spec.get("crossover_nudge") else "no nudge"} · '
                f'{sum(1 for m in msgs if m["agent"] == a)} msgs · '
                f'{s.get("phase_queries", "–")} phase queries · '
                f'{fmt_tokens(tokens.get("output_tokens", 0))} out-tok'
                + (f' · ${s["cost_usd"]:.2f}' if s.get("cost_usd") else ""))
        social_path = run_dir / "agents" / a / "social_prompt.md"
        if not social_path.exists():  # fall back for runs predating the snapshot
            social_path = ROOT / spec["social_prompt"]
        social = (md_render(social_path.read_text().strip()) if social_path.exists()
                  else '<span class="mono muted">(not captured)</span>')
        parts.append(
            f'<div class="pane"><div class="agent-head"><span class="tag">{esc(a)}'
            f'</span><span class="mono muted">{line}</span></div>'
            f'<details><summary>social prompt</summary>{social}</details></div>')
    parts.append('</div>')

    parts.append('<h2>Conversation</h2><div class="chat">')
    n_posted = {a: 0 for a in agents}
    for m in msgs:
        a = m["agent"]
        i = agents.index(a) if a in agents else 0
        side = " right" if i % 2 else ""
        w = windows.get(a, [])
        tools, tokens = w[n_posted[a]] if n_posted.get(a, 0) < len(w) else (0, 0)
        n_posted[a] = n_posted.get(a, 0) + 1
        ts = datetime.fromtimestamp(m["epoch"]).strftime("%H:%M:%S")
        route = (f'{esc(m.get("id"))} · {esc(m.get("phase"))} · '
                 f'{esc(m.get("channel"))} · {esc(m.get("lens"))} · '
                 f'x={esc(m.get("candidate_x"))} · {esc(m.get("action"))}')
        parts.append(
            f'<div class="msg{side}"><div class="msg-head"><span class="tag">{esc(a)}'
            f'</span><span class="mono muted">{route} · {ts} · {tools} tool calls · '
            f'~{fmt_tokens(tokens)} out-tok</span></div>{md_render(m["content"])}</div>')
    parts.append('</div>')

    if evaluation:
        diversity = evaluation["diversity"]
        chosen = evaluation["outcome"].get("chosen") or {}
        primary = diversity.get("end_of_deliberation_effective_candidates")
        if not isinstance(primary, (int, float)):
            primary = diversity.get("late_effective_candidates")
        phase_diversity = diversity.get("crossover_phase_effective_candidates")
        if not isinstance(phase_diversity, (int, float)):
            phase_diversity = diversity.get("late_effective_candidates")
        final_diversity = (diversity.get("final_recommendations") or {}).get(
            "effective_candidates"
        )
        survival = (diversity.get("candidate_survival") or {}).get("bin_survival_rate")
        end_round = diversity.get("end_round") or {}
        crossover_itt = (
            ((evaluation.get("crossover") or {}).get("outcomes") or {})
            .get("message_candidate_effective_count", {})
            .get("intent_to_treat_difference")
        )
        if not isinstance(crossover_itt, (int, float)):
            crossover_itt = (evaluation.get("crossover") or {}).get(
                "intent_to_treat_difference"
            )
        parts.append(
            '<h2>Evaluation</h2><div class="pane"><table class="index">'
            f'<tr><th>primary / end diversity</th><td>{esc(_metric(primary))}</td></tr>'
            f'<tr><th>crossover-phase diversity</th><td>{esc(_metric(phase_diversity))}</td></tr>'
            f'<tr><th>final recommendation diversity</th><td>{esc(_metric(final_diversity))}</td></tr>'
            f'<tr><th>candidate survival</th><td>{esc(_metric(survival))}</td></tr>'
            f'<tr><th>within-lens diversity</th><td>{esc(_metric(end_round.get("within_lens_mean_effective_candidates")))}</td></tr>'
            f'<tr><th>between-lens separation</th><td>{esc(_metric(end_round.get("between_lens_mean_separation")))}</td></tr>'
            f'<tr><th>crossover message-diversity ITT</th><td>{esc(_metric(crossover_itt))}</td></tr>'
            f'<tr><th>collapsed</th><td>{esc(diversity["collapse"].get("collapsed"))}</td></tr>'
            f'<tr><th>chosen x</th><td>{esc(chosen.get("x", "—"))}</td></tr>'
            f'<tr><th>compromise regret</th><td>{esc(chosen.get("compromise_regret", "—"))}</td></tr>'
            '</table></div>'
        )
    project = run_dir / "shared" / "PROJECT.md"
    if project.exists():
        parts.append(f'<h2>PROJECT.md</h2><div class="pane">'
                     f'{md_render(project.read_text().strip())}</div>')
    parts.append('<h2>Per-agent artifacts</h2>')
    for a in agents:
        for artifact in ("INITIAL.json", "FINAL.json", "REVIEW.json"):
            path = run_dir / "agents" / a / artifact
            if path.exists():
                parts.append(f'<details><summary>{esc(artifact)} · {esc(a)}</summary>'
                             f'<pre class="raw">{esc(path.read_text().strip())}</pre>'
                             f'</details>')

    return page(run_dir.name, sidebar_html(metas, reports, run_dir.name),
                "".join(parts), running=outcome == "running")


def render_index_page(runs_root):
    metas = list_runs(runs_root)
    reports = list_reports(runs_root.parent / "meta-analysis")
    rows = []
    for m in metas:
        duration = f'{m["duration"]:.0f}' if m["duration"] is not None else "–"
        evaluation = m.get("evaluation") or {}
        diversity = evaluation.get("diversity") or {}
        chosen = (evaluation.get("outcome") or {}).get("chosen") or {}
        primary = diversity.get("end_of_deliberation_effective_candidates")
        if not isinstance(primary, (int, float)):
            primary = diversity.get("late_effective_candidates")
        final = (diversity.get("final_recommendations") or {}).get(
            "effective_candidates"
        )
        regret = chosen.get("compromise_regret")
        row = (
            f'<tr><td><span class="dot o-{esc(m["outcome"])}"></span>'
            f'<a href="/runs/{esc(m["id"])}/report.html">{esc(m["id"])}</a></td>'
            f'<td class="mono">{esc(m["outcome"])}</td>'
            f'<td class="mono">{esc(m["protocol"])}</td>'
            f'<td class="mono">{esc(m["conditions"])}</td>'
            f'<td>{m["n_msgs"]}</td>'
            + (f'<td>{primary:.2f}</td>' if isinstance(primary, (int, float)) else '<td>–</td>')
            + (f'<td>{final:.2f}</td>' if isinstance(final, (int, float)) else '<td>–</td>')
            + (f'<td>{regret:.3f}</td>' if isinstance(regret, (int, float)) else '<td>–</td>')
            + f'<td>{duration}</td><td>${m["cost"]:.2f}</td></tr>'
        )
        rows.append(row)
    content = ('<div class="trace-intro"><div><h1>Trace explorer</h1>'
               '<p>Open any run to inspect every round, candidate, lens, message, private '
               'artifact, synthesis, and review. Use matched channel/flat traces to compare '
               'the same bargaining instance.</p></div>'
               '<a class="btn" href="/results.html">Back to results</a></div>'
               '<div class="caveat" style="margin-bottom:12px"><strong>Suggested reading order.</strong> '
               'Compare rounds 1–2 to see home-lens formation, rounds 3–4 to see crossover '
               'and convergence, then inspect FINAL.json to separate public role-play from '
               'private belief.</div>'
               '<div class="pane"><table class="index"><tr><th>run</th><th>outcome'
               '</th><th>protocol</th><th>condition</th><th>msgs</th><th>end diversity</th>'
               '<th>final diversity</th><th>regret</th>'
               '<th>secs</th><th>cost</th></tr>'
               + "".join(rows) + '</table></div>')
    running = any(m["outcome"] == "running" for m in metas)
    return page("channel-ablation · traces", sidebar_html(metas, reports, "runs-index"),
                content, running)


def export_static(runs_root):
    for m in list_runs(runs_root):
        (m["dir"] / "report.html").write_text(render_run_page(m["dir"], runs_root))
        print(f'wrote {m["dir"] / "report.html"}')
    (runs_root / "index.html").write_text(render_index_page(runs_root))
    print(f'wrote {runs_root / "index.html"}')
    for name, renderer in (
        ("overview.html", render_overview_page),
        ("results.html", render_results_page),
        ("metrics.html", render_metrics_page),
    ):
        path = runs_root.parent / name
        path.write_text(renderer(runs_root))
        print(f"wrote {path}")


# ---------------------------------------------------------------------- server

def serve(runs_root, port, open_browser=True):
    import functools
    import http.server
    import urllib.parse
    import webbrowser

    runs_root = runs_root.resolve()

    class Handler(http.server.SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive: no per-click TCP setup

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            # relative sidebar links assume the /runs/... layout, so never
            # render pages at other URLs -- redirect to the canonical one
            if path in ("/", "/index.html"):
                self.send_response(302)
                self.send_header("Location", "/overview.html")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path in ("/runs", "/runs/"):
                self.send_response(302)
                self.send_header("Location", "/runs/index.html")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/overview.html":
                return self._html(render_overview_page(runs_root))
            if path == "/results.html":
                return self._html(render_results_page(runs_root))
            if path == "/metrics.html":
                return self._html(render_metrics_page(runs_root))
            if path == "/runs/index.html":
                return self._html(render_index_page(runs_root))
            m = re.match(r"^/runs/([^/]+)/(report\.html)?$", path)
            if m and (runs_root / m.group(1)).is_dir():
                return self._html(render_run_page(runs_root / m.group(1), runs_root))
            m = re.match(r"^/reports/([\w.-]+)\.html$", path)
            if m:
                md = runs_root.parent / "meta-analysis" / f"{m.group(1)}.md"
                if md.is_file():
                    return self._html(render_report_page(md, runs_root))
            m = re.match(r"^/prompts/([\w-]+)/([\w-]+)\.html$", path)
            if m:
                md = runs_root.parent / "prompts" / m.group(1) / f"{m.group(2)}.md"
                if md.is_file():
                    return self._html(render_prompt_page(md, runs_root))
            super().do_GET()

        def _html(self, body):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    handler = functools.partial(Handler, directory=str(runs_root.parent))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    url = f"http://localhost:{port}/"
    print(f"serving {runs_root} at {url}  (ctrl-c to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


# ------------------------------------------------------------------------ main

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", default=None)
    parser.add_argument("--notes", action="store_true", help="show agents' private notes")
    parser.add_argument("--project", action="store_true", help="show shared PROJECT.md")
    parser.add_argument("--all", action="store_true", help="show everything")
    parser.add_argument("--serve", action="store_true", help="run the live dashboard")
    parser.add_argument("--port", type=int, default=7788)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--html", action="store_true",
                        help="static export: report.html for every run + runs/index.html")
    args = parser.parse_args()

    runs_root = ROOT / "runs"
    if args.serve:
        return serve(runs_root, args.port, open_browser=not args.no_browser)
    if args.html:
        return export_static(runs_root)

    run_dir = Path(args.run_dir) if args.run_dir else latest_run_dir()
    cfg = yaml.safe_load((run_dir / "config.snapshot.yaml").read_text())
    agents = [a["name"] for a in cfg["agents"]]
    stats_path = run_dir / "stats.json"
    outcome = (json.loads(stats_path.read_text()).get("outcome")
               if stats_path.exists() else "running")

    print(f"{BOLD}run:{RESET} {run_dir.name}   {BOLD}outcome:{RESET} {outcome}")
    print(f"{BOLD}task:{RESET} {cfg['task'].strip()}\n")
    print_chat(run_dir, load_board(run_dir), agents)

    if args.project or args.all:
        print_file("PROJECT.md", run_dir / "shared" / "PROJECT.md")
    if args.notes or args.all:
        for a in agents:
            print_file(f"notes · {a}", run_dir / "agents" / a / "notes.md")


if __name__ == "__main__":
    main()
