"""Re-pull `inference-provider-capabilities.jsonl` from the HF Inference Providers catalog.

The snapshot next to this script is dated data (see the `.md`): the repo convention is to
re-pull whenever it is more than ~7 days old, because provider capability booleans, prices,
and even whole `(model, provider)` routes churn week to week.

What it does: fetch the catalog's backing endpoint (the same one the HF Inference Providers
page reads), keep only `status: "live"` provider rows, flatten each to one record, stamp every
record with the pull date, and write the JSONL sorted by model id (case-insensitively) then
provider — the stable order the file has always used, so a re-pull diffs cleanly.

It writes the DATA only. The `.md`'s prose — snapshot date, row/model counts, the provider
capability table, the notable-gaps bullets, the cheapest-routes table — is hand-maintained;
`--summary` prints the recomputed numbers to paste in, and `--diff` reports what changed
against the committed snapshot so the drift is easy to write up.

    python refresh-capabilities.py --diff --summary      # pull + report (writes the JSONL)
    python refresh-capabilities.py --dry-run --diff      # report only, write nothing
    python refresh-capabilities.py --retrieved 2026-07-27  # override the stamp (default: today)

Needs no API key — the catalog endpoint is public.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
OUT = _HERE / "inference-provider-capabilities.jsonl"
ENDPOINT = "https://router.huggingface.co/v1/models"
SOURCE = "https://huggingface.co/inference/models"

# Record field order — frozen so a re-pull produces a minimal diff. Documented in the .md.
FIELDS = ("model", "owned_by", "provider", "context_length", "input_price_per_mtok",
          "output_price_per_mtok", "supports_tools", "supports_structured_output",
          "is_model_author", "retrieved", "source", "endpoint")


def _price(v: Any) -> float | None:
    """USD per 1M tokens as the catalog reports it, rounded to kill float noise
    (the endpoint returns e.g. 0.9299999999999999 for a $0.93 route)."""
    return None if v is None else round(float(v), 6)


def fetch(endpoint: str = ENDPOINT) -> list[dict[str, Any]]:
    with urllib.request.urlopen(endpoint, timeout=120) as resp:
        return json.load(resp)["data"]


def flatten(models: list[dict[str, Any]], retrieved: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in models:
        for p in m.get("providers") or []:
            if p.get("status") != "live":
                continue
            pricing = p.get("pricing") or {}
            rows.append({
                "model": m["id"],
                "owned_by": m.get("owned_by"),
                "provider": p.get("provider"),
                "context_length": p.get("context_length"),
                "input_price_per_mtok": _price(pricing.get("input")),
                "output_price_per_mtok": _price(pricing.get("output")),
                # Absent/None reads as "the provider doesn't expose it" — coerce so the
                # column is a clean boolean for consumers that filter on it.
                "supports_tools": bool(p.get("supports_tools")),
                "supports_structured_output": bool(p.get("supports_structured_output")),
                "is_model_author": bool(p.get("is_model_author")),
                "retrieved": retrieved,
                "source": SOURCE,
                "endpoint": endpoint_of(m),
            })
    rows.sort(key=lambda r: (r["model"].lower(), r["provider"]))
    return rows


def endpoint_of(_model: dict[str, Any]) -> str:
    return ENDPOINT


def _read_committed() -> list[dict[str, Any]]:
    if not OUT.exists():
        return []
    return [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line.strip()]


def report_diff(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> None:
    """What changed vs the committed snapshot, keyed by (model, provider) and ignoring
    the `retrieved` stamp (which changes on every pull by construction)."""
    def index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        return {(r["model"], r["provider"]): {k: v for k, v in r.items() if k != "retrieved"} for r in rows}

    o, n = index(old), index(new)
    prev_date = old[0].get("retrieved") if old else "(none)"
    added, removed = sorted(n.keys() - o.keys()), sorted(o.keys() - n.keys())
    flipped = [(k, {f: (o[k][f], n[k][f]) for f in o[k] if o[k][f] != n[k][f]})
               for k in sorted(o.keys() & n.keys()) if o[k] != n[k]]
    print(f"\n--- drift vs committed snapshot ({prev_date}) ---")
    print(f"{len(added)} added, {len(removed)} removed, {len(flipped)} changed "
          f"({len(o)} -> {len(n)} rows)")
    for k in added:
        print(f"  + {k[0]} @ {k[1]}")
    for k in removed:
        print(f"  - {k[0]} @ {k[1]}")
    for k, d in flipped:
        print(f"  ~ {k[0]} @ {k[1]}: " + ", ".join(f"{f} {a}->{b}" for f, (a, b) in d.items()))


def report_summary(rows: list[dict[str, Any]]) -> None:
    """Recompute the hand-maintained numbers in the .md so they can be pasted in."""
    both = [r for r in rows if r["supports_tools"] and r["supports_structured_output"]]
    tools_only = [r for r in rows if r["supports_tools"] and not r["supports_structured_output"]]
    print(f"\n--- .md summary numbers ---")
    print(f"Rows: {len(rows)} live (model, provider) pairs across "
          f"{len({r['model'] for r in rows})} models and {len({r['provider'] for r in rows})} providers.")
    print(f"Both tools + structured output: {len(both)} provider rows across "
          f"{len({r['model'] for r in both})} models. Tools-only: {len(tools_only)} rows.")

    profile: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        e = profile[r["provider"]]
        e[0] += 1
        e[1] += bool(r["supports_tools"])
        e[2] += bool(r["supports_tools"] and r["supports_structured_output"])
    print("\n| Provider | live rows | tools | tools **+** structured output |")
    print("| --- | ---: | ---: | ---: |")
    # Same ordering as the .md: both-capable providers first (most structured-output
    # routes), then the tools-only ones (most tool routes), then the capability-less
    # bulk host — so the table reads as a capability ranking, not a volume ranking.
    both_capable = sorted((p for p, e in profile.items() if e[2]), key=lambda p: -profile[p][2])
    rest = sorted((p for p, e in profile.items() if not e[2] and e[1]), key=lambda p: -profile[p][1])
    none = sorted((p for p, e in profile.items() if not e[1]), key=lambda p: -profile[p][0])
    for p in [*both_capable, *rest, *none]:
        live, t, b = profile[p]
        print(f"| {p} | {live} | {t} | {b if b else '**0**'} |")

    cheapest: dict[str, dict[str, Any]] = {}
    for r in both:
        if r["input_price_per_mtok"] is None:
            continue
        cur = cheapest.get(r["model"])
        if cur is None or r["input_price_per_mtok"] < cur["input_price_per_mtok"]:
            cheapest[r["model"]] = r
    print("\n| Model | Cheapest both-capable provider | Context | $ In / Out (1M) |")
    print("| --- | --- | ---: | --- |")
    for r in sorted(cheapest.values(), key=lambda r: r["input_price_per_mtok"])[:5]:
        ctx = f"{round((r['context_length'] or 0) / 1000)}K" if r["context_length"] else "?"
        print(f"| {r['model']} | {r['provider']} | {ctx} | "
              f"{r['input_price_per_mtok']} / {r['output_price_per_mtok']} |")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--retrieved", default=date.today().isoformat(),
                    help="snapshot date to stamp on every record (default: today)")
    ap.add_argument("--dry-run", action="store_true", help="don't write the JSONL")
    ap.add_argument("--diff", action="store_true", help="report drift vs the committed snapshot")
    ap.add_argument("--summary", action="store_true", help="print the .md's hand-maintained numbers")
    args = ap.parse_args()

    old = _read_committed()
    rows = flatten(fetch(), args.retrieved)
    if args.diff:
        report_diff(old, rows)
    if args.summary:
        report_summary(rows)
    if args.dry_run:
        print(f"\n(dry run — {len(rows)} rows not written)")
        return 0
    OUT.write_text("".join(json.dumps({k: r[k] for k in FIELDS}, separators=(",", ":"),
                                      ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"\nWrote {len(rows)} rows to {OUT} (retrieved {args.retrieved}).")
    print("Now update inference-provider-capabilities.md by hand: snapshot date, row/model "
          "counts, provider table, notable-gaps bullets, cheapest-routes table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
