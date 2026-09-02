from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

NOOP_EPS = 0.002
MOTION_EPS = 0.004
JANK_MIN_CHANGE = 0.008
CONCENTRATION_LIMIT = 0.60
ACTIVE_RATIO_LIMIT = 0.50
STALL_GAP_MS = 250
WORK_WIDTH = 320


@dataclass
class VisualAnalysis:
    frames: int
    total_change: float
    diffs: List[float]
    motion_frames: int
    active_ratio: float
    concentration: float
    max_freeze_run: int
    max_gap_ms: float
    no_op: bool
    stepped: bool
    instant: bool
    stalled: bool

    def as_evidence(self) -> Dict[str, object]:
        return {
            "frames": self.frames,
            "total_change": round(self.total_change, 5),
            "motion_frames": self.motion_frames,
            "active_ratio": round(self.active_ratio, 3),
            "concentration": round(self.concentration, 3),
            "max_freeze_run": self.max_freeze_run,
            "max_gap_ms": round(self.max_gap_ms, 1),
        }


def _to_gray(frame: np.ndarray) -> np.ndarray:
    arr = frame
    if arr.ndim == 3:
        if cv2 is not None:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        else:
            arr = arr.mean(axis=2)
    arr = arr.astype(np.float32)
    if arr.max() > 1.5:
        arr = arr / 255.0
    h, w = arr.shape[:2]
    if w > WORK_WIDTH and cv2 is not None:
        scale = WORK_WIDTH / float(w)
        arr = cv2.resize(arr, (WORK_WIDTH, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return arr


def load_frames(paths: Sequence[str]) -> List[np.ndarray]:
    if cv2 is None:
        raise RuntimeError("opencv is required to load frames from disk")
    out = []
    for p in paths:
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            out.append(img)
    return out


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    ga, gb = _to_gray(a), _to_gray(b)
    if ga.shape != gb.shape:
        h = min(ga.shape[0], gb.shape[0])
        w = min(ga.shape[1], gb.shape[1])
        ga, gb = ga[:h, :w], gb[:h, :w]
    return float(np.abs(ga - gb).mean())


def analyze_burst(frames: Sequence[np.ndarray], timestamps_ms: Optional[Sequence[float]] = None) -> VisualAnalysis:
    n = len(frames)
    if n < 2:
        return VisualAnalysis(n, 0.0, [], 0, 0.0, 0.0, 0, 0.0, True, False, False, False)

    diffs = [mean_abs_diff(frames[i], frames[i + 1]) for i in range(n - 1)]
    total_change = mean_abs_diff(frames[0], frames[-1])
    motion = [d for d in diffs if d > MOTION_EPS]
    motion_frames = len(motion)
    active_ratio = motion_frames / float(len(diffs))
    ordered = sorted(diffs, reverse=True)
    denom = sum(diffs)
    concentration = (sum(ordered[:2]) / denom) if denom > 0 else 0.0

    moving_idx = [i for i, d in enumerate(diffs) if d > MOTION_EPS]
    max_freeze_run = 0
    if len(moving_idx) >= 2:
        for a, b in zip(moving_idx, moving_idx[1:]):
            max_freeze_run = max(max_freeze_run, b - a - 1)

    max_gap_ms = 0.0
    if timestamps_ms and len(timestamps_ms) == n:
        gaps = [timestamps_ms[i + 1] - timestamps_ms[i] for i in range(n - 1)]
        max_gap_ms = float(max(gaps)) if gaps else 0.0

    no_op = total_change < NOOP_EPS and motion_frames == 0
    instant = (not no_op) and motion_frames <= 1
    stepped = (
        not no_op
        and motion_frames >= 2
        and total_change >= JANK_MIN_CHANGE
        and concentration >= CONCENTRATION_LIMIT
        and active_ratio <= ACTIVE_RATIO_LIMIT
    )
    stalled = max_gap_ms >= STALL_GAP_MS

    return VisualAnalysis(
        frames=n, total_change=total_change, diffs=diffs, motion_frames=motion_frames,
        active_ratio=active_ratio, concentration=concentration, max_freeze_run=max_freeze_run,
        max_gap_ms=max_gap_ms, no_op=no_op, stepped=stepped, instant=instant, stalled=stalled,
    )


class VisualOracle:

    source = "visual"

    def inspect(self, step: int, frames: Sequence[np.ndarray],
                timestamps_ms: Optional[Sequence[float]] = None) -> List["object"]:
        from ..models import Signal
        a = analyze_burst(frames, timestamps_ms)
        signals: List[Signal] = []
        if a.no_op:
            signals.append(Signal(self.source, "no_op",
                                  "the screen did not change at all after this action",
                                  step, "notable", a.as_evidence()))
        if a.stepped:
            signals.append(Signal(
                self.source, "stepped_animation",
                ("transition advanced in {0} discrete jumps with {1} still frame(s) in between; "
                 "{2:.0%} of all pixel change arrived in 2 frames").format(
                    a.motion_frames, a.max_freeze_run, a.concentration),
                step, "hard", a.as_evidence()))
        if a.stalled:
            signals.append(Signal(self.source, "capture_stall",
                                  "screen capture stalled for {0:.0f} ms, the page was likely blocked".format(a.max_gap_ms),
                                  step, "notable", a.as_evidence()))
        return signals
