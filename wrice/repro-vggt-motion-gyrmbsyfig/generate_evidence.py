from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent
PAPER_ID = "GyRMbsYFiG"
ATTEMPT_ID = "476a2789-78d0-44b4-98b5-8098580249f8"
ARXIV_ID = "2602.05508v1"
ARXIV_SOURCE_SHA256 = "217fb93bc9b847cef3402395b9b6f97665051aea4872b4785c896fb79fb73b44"
GENERATED_AT = "2026-08-01T13:02:00+00:00"


CLAIMS = [
    {
        "challenge_claim_sha256": "ebc904f759989d500c93913210a4d89954834a560ba0568ef469ddc28566a82c",
        "claim": "VGGT-Motion combines motion-aware submap construction, anchor-driven direct Sim(3) registration, and lightweight pose-graph optimization for calibration-free monocular SLAM (Figure 2).",
        "verdict": "toy",
        "evidence": "The TeX source contains the three named pipeline stages and equations for submap construction, direct Sim(3) alignment, and submap-level pose graph optimization. The bundle includes deterministic toy implementations of each computational idea, but no official VGGT-Motion code or dataset run was available.",
    },
    {
        "challenge_claim_sha256": "b2ca94dae5c811e35f6943d2af6b67fb83e2f7e03ec8f3ecb42766e13bcc9ce3",
        "claim": "Motion-aware submap construction uses optical flow to prune static redundancy and preserve turning segments for stable local geometry (Section 3.1).",
        "verdict": "toy",
        "evidence": "The source defines static ratio and turning score from dense optical flow, then classifies frames as Static, Turning, or Linear. The toy check confirms that static intervals retain only boundary frames and a continuous turning interval is encapsulated in one submap.",
    },
    {
        "challenge_claim_sha256": "ab3dd21bf3b25d44ffc41f9d84a47993e6b15254326b95fdb60d48a4dc4e734c",
        "claim": "VGGT-Motion improves KITTI absolute trajectory error over VGGT-Long and other foundation-model SLAM baselines under the paper's calibration-free setting (Table 1).",
        "verdict": "inconclusive",
        "evidence": "Table 1 in the TeX reports Ours Avg. 24.17 versus VGGT-Long Avg. 27.64 and Ours Avg.* 18.26 versus VGGT-Long Avg.* 18.28. These are table transcriptions and arithmetic checks only; no KITTI trajectories, official code, or model outputs were released for independent rerun.",
    },
    {
        "challenge_claim_sha256": "7cfe7beadaab70f74a3c78172dd4449cc0e642615e5808f48ea695354441f810",
        "claim": "On long-sequence 4Seasons, Complex Urban, and A2D2 benchmarks, VGGT-Motion reports much lower ATE and drift than VGGT-SLAM and VGGT-Long while other foundation-model baselines often fail (Table 3).",
        "verdict": "inconclusive",
        "evidence": "The TeX table reports lower ATE and drift for Ours across 4Seasons, Complex Urban, and A2D2, and OOM/TL markers for several baselines. This bundle verifies the direction and reduction arithmetic from the table, but it does not reproduce the benchmark runs.",
    },
    {
        "challenge_claim_sha256": "a4174fc74b13d1f6c3e0f3bf279b7882e048b5f326e3090d8ca088e4081aadcf",
        "claim": "Topology-aware turning encapsulation outperforms temporal slicing and parallax-triggered partitioning on KITTI ATE and drift (Table 5).",
        "verdict": "inconclusive",
        "evidence": "Table 5 reports topology-aware partitioning at 24.56 m ATE and 1.41% drift versus 26.98/1.58 for temporal slicing and 28.15/1.62 for parallax-triggered partitioning. A toy partitioner demonstrates turn preservation, but no KITTI ablation rerun was possible.",
    },
    {
        "challenge_claim_sha256": "ab182d7e71b8770a81c7248683885813f3db1b6d94b7eb76a657bc28a82646d0",
        "claim": "The runtime study reports large total-time speedups over VGGT-Long and VGGT-SLAM on long-sequence benchmarks (Figure 5).",
        "verdict": "inconclusive",
        "evidence": "The TeX caption and prose state 18-36x total-time speedups on long sequences, but the numeric runtime values are embedded in a figure image and no measurement logs or code are released. This is not independently reproduced.",
    },
]


def classify_motion(
    static_ratios: list[float],
    turn_scores: list[float],
    tau_static: float,
    tau_turn: float,
) -> list[str]:
    if len(static_ratios) != len(turn_scores):
        raise ValueError("static_ratios and turn_scores must have equal length")
    states = []
    for static_ratio, turn_score in zip(static_ratios, turn_scores):
        if static_ratio > tau_static:
            states.append("S")
        elif turn_score > tau_turn:
            states.append("T")
        else:
            states.append("L")
    return states


def motion_aware_submaps(
    states: list[str],
    parallaxes: list[float],
    n_max: int,
    tau_parallax: float,
) -> list[list[int]]:
    if len(states) != len(parallaxes):
        raise ValueError("states and parallaxes must have equal length")
    submaps: list[list[int]] = []
    current: list[int] = []
    i = 0
    while i < len(states):
        state = states[i]
        if state == "S":
            start = i
            while i + 1 < len(states) and states[i + 1] == "S":
                i += 1
            for frame in {start, i}:
                if frame not in current:
                    current.append(frame)
            i += 1
            continue
        if state == "T":
            turn = [i]
            while i + 1 < len(states) and states[i + 1] == "T":
                i += 1
                turn.append(i)
            if current:
                submaps.append(current)
                current = []
            submaps.append(turn)
            i += 1
            continue
        if not current or parallaxes[i] >= tau_parallax or len(current) >= n_max:
            if len(current) >= n_max:
                submaps.append(current)
                current = []
            current.append(i)
        i += 1
    if current:
        submaps.append(current)
    return submaps


def estimate_sim3(source: np.ndarray, target: np.ndarray) -> dict:
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("source and target must be Nx3 arrays")
    mu_source = source.mean(axis=0)
    mu_target = target.mean(axis=0)
    source_centered = source - mu_source
    target_centered = target - mu_target
    covariance = target_centered.T @ source_centered / len(source)
    u, singular_values, vt = np.linalg.svd(covariance)
    correction = np.eye(3)
    if np.linalg.det(u @ vt) < 0:
        correction[-1, -1] = -1
    rotation = u @ correction @ vt
    variance = (source_centered**2).sum() / len(source)
    scale = float(np.trace(np.diag(singular_values) @ correction) / variance)
    translation = mu_target - scale * rotation @ mu_source
    return {
        "scale": scale,
        "rotation": rotation.tolist(),
        "translation": translation.tolist(),
    }


def apply_sim3(source: np.ndarray, transform: dict) -> np.ndarray:
    rotation = np.asarray(transform["rotation"], dtype=float)
    translation = np.asarray(transform["translation"], dtype=float)
    scale = float(transform["scale"])
    return scale * (np.asarray(source, dtype=float) @ rotation.T) + translation


def synthetic_sim3_case() -> tuple[np.ndarray, np.ndarray, dict]:
    source = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 3.0],
            [1.0, 2.0, 3.0],
        ]
    )
    theta = np.deg2rad(30.0)
    rotation = np.array(
        [
            [np.cos(theta), -np.sin(theta), 0.0],
            [np.sin(theta), np.cos(theta), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    target = 1.75 * (source @ rotation.T) + np.array([2.0, -1.0, 0.5])
    return source, target, estimate_sim3(source, target)


def kitti_checks() -> dict:
    avg = {"ours": 24.17, "vggt_long": 27.64, "vggt_slam": 74.23}
    avg_star = {"ours": 18.26, "vggt_long": 18.28, "vggt_long_local": 21.89}
    return {
        "avg": {
            **avg,
            "reduction_vs_vggt_long_percent": round((avg["vggt_long"] - avg["ours"]) / avg["vggt_long"] * 100, 2),
        },
        "avg_star": {
            **avg_star,
            "reduction_vs_vggt_long_percent": round((avg_star["vggt_long"] - avg_star["ours"]) / avg_star["vggt_long"] * 100, 2),
            "reduction_vs_vggt_long_local_percent": round((avg_star["vggt_long_local"] - avg_star["ours"]) / avg_star["vggt_long_local"] * 100, 2),
        },
    }


def generalization_checks() -> dict:
    rows = {
        "4Seasons": {"vggt_long_ate": 280.25, "ours_ate": 12.22, "vggt_long_drift": 7.16, "ours_drift": 0.32},
        "Complex Urban": {"vggt_long_ate": 475.59, "ours_ate": 35.48, "vggt_long_drift": 8.20, "ours_drift": 0.58},
        "A2D2": {"vggt_long_ate": 182.93, "ours_ate": 29.80, "vggt_long_drift": 5.69, "ours_drift": 0.93},
    }
    ate_reductions = {
        name: round((row["vggt_long_ate"] - row["ours_ate"]) / row["vggt_long_ate"] * 100, 2)
        for name, row in rows.items()
    }
    drift_reductions = {
        name: round((row["vggt_long_drift"] - row["ours_drift"]) / row["vggt_long_drift"] * 100, 2)
        for name, row in rows.items()
    }
    return {"rows": rows, "ate_reductions": ate_reductions, "drift_reductions": drift_reductions}


def topology_ablation_checks() -> dict:
    rows = {
        "Temporal Slicing": {"ate": 26.98, "drift": 1.58},
        "Parallax-Triggered": {"ate": 28.15, "drift": 1.62},
        "Topology-Aware": {"ate": 24.56, "drift": 1.41},
    }
    best_by_ate = min(rows, key=lambda name: rows[name]["ate"])
    best_by_drift = min(rows, key=lambda name: rows[name]["drift"])
    return {"rows": rows, "best_by_ate": best_by_ate, "best_by_drift": best_by_drift}


def build_bundle() -> dict:
    source, target, transform = synthetic_sim3_case()
    sim3_residual = float(((apply_sim3(source, transform) - target) ** 2).sum(axis=1).mean() ** 0.5)
    states = classify_motion(
        static_ratios=[0.95, 0.92, 0.20, 0.10, 0.15, 0.12, 0.25, 0.90],
        turn_scores=[0.1, 0.2, 6.5, 7.1, 6.7, 1.1, 0.9, 0.2],
        tau_static=0.6,
        tau_turn=5.0,
    )
    submaps = motion_aware_submaps(states, [0.0, 0.2, 3.0, 4.5, 5.5, 16.0, 8.0, 0.1], 3, 15.0)
    return {
        "paper": {
            "paper_id": PAPER_ID,
            "attempt_id": ATTEMPT_ID,
            "title": "VGGT-Motion: Motion-Aware Calibration-Free Monocular SLAM for Long-Range Consistency",
        },
        "upstream": {
            "primary_artifact": f"arxiv:{ARXIV_ID}",
            "arxiv_source_sha256": ARXIV_SOURCE_SHA256,
            "source_archive_path_observed": "/tmp/vggt-motion-arxiv-AbZ3Ga/source.tar",
            "official_code_released": False,
        },
        "generated_at": GENERATED_AT,
        "estimated_paid_api_cost_usd": 0.0,
        "toy_checks": {
            "motion_states": states,
            "motion_aware_submaps": submaps,
            "turn_segment_preserved": [2, 3, 4] in submaps,
            "sim3_residual_rmse": sim3_residual,
            "estimated_sim3": transform,
        },
        "checks": {
            "kitti_avg": kitti_checks()["avg"],
            "kitti_avg_star": kitti_checks()["avg_star"],
            "generalization_vggt_long_reduction": generalization_checks(),
            "topology_ablation": topology_ablation_checks(),
            "runtime_claim_numeric_logs_available": False,
        },
        "claims": CLAIMS,
        "limitations": {
            "official_code_released": False,
            "official_checkpoints_released": False,
            "benchmark_rerun_completed": False,
            "note": "Quantitative benchmark and runtime claims are paper-source audits, not reproduced measurements.",
        },
    }


def write_bundle(bundle: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "evidence" / "bundle.json")
    args = parser.parse_args()
    bundle = build_bundle()
    write_bundle(bundle, args.output)
    print(json.dumps({"claims": len(bundle["claims"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
