"""Terminal-only decorative output for `measure_finger.py` CLI.

Anything with emoji, ASCII headers, or "press-release" phrasing belongs
here. `src/` production code and the web demo use the `logger` from
`src.logging_config` instead so log streams stay clean and structured.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def print_image_loaded(path: str, shape: tuple) -> None:
    print(f"Loaded image: {path} ({shape[1]}x{shape[0]})")


def print_skip_card_warning() -> None:
    print("TESTING MODE: Skipping card detection (using dummy scale factor)")


def print_result_path(path: str) -> None:
    print(f"Results saved to: {path}")


def print_single_result(result: Dict[str, Any]) -> None:
    """One-screen summary after a successful single-finger measurement."""
    if result.get("fail_reason"):
        print(f"Measurement failed: {result['fail_reason']}")
        return
    print(f"Finger diameter: {result['finger_outer_diameter_cm']} cm")
    if result.get("raw_diameter_cm"):
        print(f"  (raw: {result['raw_diameter_cm']} cm, calibrated)")
    rec = result.get("ring_size")
    if rec:
        print(f"Ring size: best match {rec['best_match']}, recommended {rec['range_min']}-{rec['range_max']}")
    print(f"Confidence: {result['confidence']}")


def print_multi_result(result: Dict[str, Any]) -> None:
    """One-screen summary after a multi-finger measurement."""
    if result.get("fail_reason"):
        print(f"Measurement failed: {result['fail_reason']}")
        return
    print("\n=== Multi-Finger Results ===")
    print(
        f"Fingers: {result.get('fingers_succeeded', 0)}/"
        f"{result.get('fingers_measured', 0)} succeeded"
    )
    for fn, pf in result.get("per_finger", {}).items():
        if pf.get("status") == "ok":
            print(
                f"  {fn.capitalize()}: {pf['diameter_cm']:.2f}cm "
                f"-> Size {pf['best_match']} "
                f"(range {pf['range'][0]}-{pf['range'][1]})"
            )
        else:
            print(f"  {fn.capitalize()}: FAILED ({pf.get('fail_reason', 'unknown')})")
    if result.get("overall_best_size"):
        print(f"\nOverall Best Size: {result['overall_best_size']}")
        print(f"Recommended Range: {result['overall_range_min']}-{result['overall_range_max']}")


def print_error(message: str) -> None:
    import sys
    print(f"Error: {message}", file=sys.stderr)
