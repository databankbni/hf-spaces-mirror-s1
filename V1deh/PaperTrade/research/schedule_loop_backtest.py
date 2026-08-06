#!/usr/bin/env python3
"""Schedule loop_backtest.py to start once after N hours (macOS launchd)."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import plistlib
import subprocess
import sys
from pathlib import Path


def _pick_python(repo_root: Path) -> str:
    venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _write_plist(plist_path: Path, label: str, run_at: dt.datetime, repo_root: Path, reset: bool) -> dict:
    python_bin = _pick_python(repo_root)
    script_path = repo_root / "research" / "loop_backtest.py"

    args = [python_bin, str(script_path)]
    if reset:
        args.append("--reset")

    payload = {
        "Label": label,
        "ProgramArguments": args,
        "WorkingDirectory": str(repo_root),
        "StartCalendarInterval": {
            "Year": run_at.year,
            "Month": run_at.month,
            "Day": run_at.day,
            "Hour": run_at.hour,
            "Minute": run_at.minute,
        },
        "RunAtLoad": False,
        "StandardOutPath": "/tmp/papertrade_loop_backtest_delayed.log",
        "StandardErrorPath": "/tmp/papertrade_loop_backtest_delayed.err",
    }

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as f:
        plistlib.dump(payload, f)

    return {
        "python": python_bin,
        "script": str(script_path),
        "stdout": payload["StandardOutPath"],
        "stderr": payload["StandardErrorPath"],
    }


def _launch_load(plist_path: Path) -> tuple[bool, str]:
    uid = os.getuid()
    target = f"gui/{uid}"

    subprocess.run(
        ["launchctl", "bootout", target, str(plist_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    bootstrap = subprocess.run(
        ["launchctl", "bootstrap", target, str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if bootstrap.returncode == 0:
        return True, "bootstrap"

    legacy = subprocess.run(
        ["launchctl", "load", "-w", str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if legacy.returncode == 0:
        return True, "load"

    err = (bootstrap.stderr or "").strip() or (legacy.stderr or "").strip() or "unknown launchctl error"
    return False, err


def main() -> int:
    parser = argparse.ArgumentParser(description="Schedule loop_backtest.py after a delay")
    parser.add_argument("--hours", type=float, default=5.0, help="Delay before running loop_backtest (default: 5)")
    parser.add_argument("--reset", action="store_true", help="Pass --reset to loop_backtest.py")
    parser.add_argument("--label", default="com.papertrade.loopbacktest.once", help="launchd label")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    run_at = dt.datetime.now() + dt.timedelta(hours=args.hours)
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{args.label}.plist"

    details = _write_plist(plist_path, args.label, run_at, repo_root, args.reset)
    ok, method_or_err = _launch_load(plist_path)

    if not ok:
        print(f"FAILED to load launch agent: {method_or_err}")
        return 1

    print("Scheduled delayed loop backtest")
    print(f"label={args.label}")
    print(f"plist={plist_path}")
    print(f"run_at_local={run_at.strftime('%Y-%m-%d %H:%M')}")
    print(f"python={details['python']}")
    print(f"script={details['script']}")
    print(f"stdout={details['stdout']}")
    print(f"stderr={details['stderr']}")
    print(f"load_method={method_or_err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
