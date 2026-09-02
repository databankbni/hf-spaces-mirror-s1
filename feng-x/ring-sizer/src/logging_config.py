"""Shared logging setup and phase-timing context manager.

Usage:
    from src.logging_config import configure_logging, log_phase

    configure_logging()  # call once at entry point (CLI, web demo, scripts)
    logger = logging.getLogger(__name__)

    timings: Dict[str, float] = {}
    with log_phase("hand_segment", timings):
        ...

The single canonical format is `[phase] <name>: <ms> ms`, emitted via the
module-level logger (so web demo / HF Space / scripts all see structured
output with consistent prefixes).
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once. Safe to call multiple times."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _configured = True


@contextmanager
def log_phase(name: str, totals: Optional[Dict[str, float]] = None):
    """Time a pipeline phase and log `[phase] name: X ms` on exit.

    When ``totals`` is passed, elapsed milliseconds are accumulated under
    ``name`` so the caller can emit a summary at the end of the run.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        logger.info("[phase] %s: %.1f ms", name, dt_ms)
        if totals is not None:
            totals[name] = totals.get(name, 0.0) + dt_ms


def log_phase_summary(totals: Dict[str, float]) -> None:
    """Log a sorted summary of accumulated phase timings."""
    if not totals:
        return
    total_ms = sum(totals.values())
    logger.info("[phase] ===== summary (total %.1f ms) =====", total_ms)
    for name, ms in sorted(totals.items(), key=lambda kv: -kv[1]):
        pct = (ms / total_ms * 100.0) if total_ms > 0 else 0.0
        logger.info("[phase]   %-28s %8.1f ms  (%5.1f%%)", name, ms, pct)
