from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .settings import settings


class VendorCommandError(RuntimeError):
    pass


def script_path(name: str) -> Path:
    path = settings.vendor_dir / name
    if not path.exists():
        # Try relative to project root when launched by uvicorn from /app.
        alt = Path.cwd() / settings.vendor_dir / name
        if alt.exists():
            return alt
        raise FileNotFoundError(f"vendor script not found: {name}")
    return path


def run_json_command(args: list[str], stdin_obj: dict | None = None, timeout: int = 90) -> dict:
    stdin_text = json.dumps(stdin_obj, ensure_ascii=False) if stdin_obj is not None else None
    proc = subprocess.run(
        args,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise VendorCommandError(
            f"command failed rc={proc.returncode}: {' '.join(args)}\nSTDERR={proc.stderr[-2000:]}\nSTDOUT={proc.stdout[-1000:]}"
        )
    out = proc.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise VendorCommandError(f"JSON parse failed: {exc}; stdout_tail={out[-2000:]}") from exc


def fetch_titan007(match_id: str, company_ids: str | None = None, compact: bool = False, raw: bool = False) -> dict:
    company = company_ids or settings.default_company_ids
    args = [
        settings.python_bin,
        str(script_path("fetch_titan007_odds.py")),
        str(match_id),
        "--company",
        company,
    ]
    if compact:
        args.append("--compact")
    if raw:
        args.append("--raw")
    return run_json_command(args, timeout=120)


def multi_company_analyze(raw_fetch: dict) -> dict:
    return run_json_command(
        [settings.python_bin, str(script_path("multi_company_analyzer.py"))],
        stdin_obj=raw_fetch,
        timeout=60,
    )


def extract_multi_company(raw_fetch: dict) -> dict:
    # extract_multi_company.py prints a table plus "--- JSON ---" block; parse tail.
    proc = subprocess.run(
        [settings.python_bin, str(script_path("extract_multi_company.py"))],
        input=json.dumps(raw_fetch, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise VendorCommandError(f"extract failed rc={proc.returncode}: {proc.stderr[-2000:]}")
    marker = "--- JSON ---"
    if marker not in proc.stdout:
        raise VendorCommandError(f"extract output missing JSON marker: {proc.stdout[-2000:]}")
    json_part = proc.stdout.split(marker, 1)[1].strip()
    return {"rows": json.loads(json_part)}


def kline_summary(match_id: str) -> dict:
    args = [
        settings.python_bin,
        str(script_path("plot_water_kline.py")),
        str(match_id),
        "--market",
        "both",
    ]
    # Default is compact mode in the exported script.
    return run_json_command(args, timeout=120)
