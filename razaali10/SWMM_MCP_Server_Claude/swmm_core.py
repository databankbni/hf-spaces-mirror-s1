"""Crash-isolated deterministic OpenSWMM simulation core.

The OpenSWMM engine is a native extension.  It is never loaded into the
long-lived Streamlit process.  Each simulation runs in a short-lived worker
process and returns only serialisable Python data.
"""
from __future__ import annotations

import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class SwmmWorkerError(RuntimeError):
    """Raised when the isolated OpenSWMM worker cannot complete."""



def run_swmm(
    inp_path: str | Path,
    rpt_path: str | Path | None = None,
    out_path: str | Path | None = None,
    timeout_s: int = 900,
) -> dict[str, Any]:
    """Run OpenSWMM in an isolated subprocess.

    Isolation prevents a native OpenSWMM segmentation fault from terminating
    Streamlit.  The worker deliberately uses ``os._exit`` after serialising its
    result so native-library finalisers cannot crash the parent application.
    """
    inp = Path(inp_path).resolve()
    if not inp.is_file():
        raise FileNotFoundError(f"SWMM input file not found: {inp}")

    rpt = Path(rpt_path).resolve() if rpt_path else inp.with_suffix(".rpt")
    out = Path(out_path).resolve() if out_path else inp.with_suffix(".out")
    worker = Path(__file__).with_name("swmm_worker.py")
    if not worker.is_file():
        raise FileNotFoundError(f"OpenSWMM worker not found: {worker}")

    fd, result_name = tempfile.mkstemp(prefix="swmm_result_", suffix=".pkl")
    os.close(fd)
    result_file = Path(result_name)

    worker_python = os.environ.get("SWMM_WORKER_PYTHON", "/opt/swmm-venv/bin/python")
    if not Path(worker_python).is_file():
        raise FileNotFoundError(
            f"Isolated OpenSWMM interpreter not found: {worker_python}"
        )

    cmd = [
        worker_python,
        "-u",
        str(worker),
        "--inp", str(inp),
        "--rpt", str(rpt),
        "--out", str(out),
        "--result", str(result_file),
    ]

    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        payload = None
        if result_file.exists() and result_file.stat().st_size:
            with result_file.open("rb") as f:
                payload = pickle.load(f)

        if isinstance(payload, dict) and payload.get("ok"):
            results = payload["results"]
            results.setdefault("metadata", {})["worker_stdout"] = completed.stdout[-4000:]
            results["metadata"]["worker_stderr"] = completed.stderr[-4000:]
            results["metadata"]["worker_exit_code"] = completed.returncode
            return results

        detail = ""
        if isinstance(payload, dict):
            detail = payload.get("error", "")
        if not detail:
            detail = completed.stderr.strip() or completed.stdout.strip()
        if completed.returncode in (-11, 139):
            detail = (
                "The OpenSWMM worker encountered a native segmentation fault. "
                "The Streamlit process remained protected. " + detail
            ).strip()
        raise SwmmWorkerError(
            f"OpenSWMM worker failed with exit code {completed.returncode}. {detail}".strip()
        )
    except subprocess.TimeoutExpired as exc:
        raise SwmmWorkerError(
            f"OpenSWMM simulation exceeded the {timeout_s}-second timeout."
        ) from exc
    finally:
        result_file.unlink(missing_ok=True)
