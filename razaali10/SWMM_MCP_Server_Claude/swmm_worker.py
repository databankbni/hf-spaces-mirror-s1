"""One-shot OpenSWMM worker.  Do not import this module from Streamlit."""
from __future__ import annotations

import argparse
import os
import pickle
import traceback
from pathlib import Path
from typing import Any

import numpy as np


def _as_float_list(values: Any) -> list[float]:
    return np.asarray(values, dtype=float).copy().tolist()


def _enum_name(value: Any) -> str:
    return getattr(value, "name", str(value))


def _safe_float(getter, default: float = 0.0) -> float:
    try:
        return float(getter())
    except Exception:
        return default


def simulate(inp_path: str, rpt_path: str, out_path: str) -> dict[str, Any]:
    from openswmm.engine import Solver

    node_ts: dict[str, dict[str, Any]] = {}
    link_ts: dict[str, dict[str, Any]] = {}
    sub_ts: dict[str, dict[str, Any]] = {}
    times: list[Any] = []
    warnings: list[dict[str, Any]] = []

    with Solver(inp_path, rpt_path, out_path) as solver:
        solver.set_warning_callback(
            lambda code, message: warnings.append(
                {"code": int(code), "message": str(message)}
            )
        )

        nodes = solver.nodes
        links = solver.links
        subs = solver.subcatchments

        node_ids = [str(nodes.get_id(i)) for i in range(len(nodes))]
        link_ids = [str(links.get_id(i)) for i in range(len(links))]
        sub_ids = [str(subs.get_id(i)) for i in range(len(subs))]

        for node in nodes:
            node_ts[str(node.id)] = {
                "depth": [], "flooding": [], "inflow": [], "head": [],
                "outflow": [], "volume": [],
                "invert_elevation": float(node.invert_elev),
                "full_depth": float(node.max_depth),
            }

        for link in links:
            geom1 = 0.0
            try:
                geom1 = float(link.xsect.geom1)
            except Exception:
                try:
                    geom1 = float(link.xsect.geometry[0])
                except Exception:
                    pass
            link_ts[str(link.id)] = {
                "flow": [], "depth": [], "velocity": [], "volume": [],
                "capacity": [], "length": float(link.length),
                "roughness": float(link.roughness), "diameter": geom1,
            }

        for sub in subs:
            sub_ts[str(sub.id)] = {"runoff": [], "rainfall": [], "infil": []}

        for _elapsed in solver.steps():
            times.append(solver.current_datetime)

            node_values = {
                "depth": _as_float_list(nodes.depths),
                "flooding": _as_float_list(nodes.overflows),
                "inflow": _as_float_list(nodes.inflows),
                "head": _as_float_list(nodes.heads),
                "outflow": _as_float_list(nodes.outflows),
                "volume": _as_float_list(nodes.volumes),
            }
            for i, node_id in enumerate(node_ids):
                for key, values in node_values.items():
                    node_ts[node_id][key].append(values[i])

            link_values = {
                "flow": _as_float_list(links.flows),
                "depth": _as_float_list(links.depths),
                "velocity": _as_float_list(links.velocities),
                "volume": _as_float_list(links.volumes),
                "capacity": _as_float_list(links.capacities),
            }
            for i, link_id in enumerate(link_ids):
                for key, values in link_values.items():
                    link_ts[link_id][key].append(values[i])

            if sub_ids:
                sub_values = {
                    "runoff": _as_float_list(subs.runoffs),
                    "rainfall": _as_float_list(subs.rainfalls),
                    "infil": _as_float_list(subs.infils),
                }
                for i, sub_id in enumerate(sub_ids):
                    for key, values in sub_values.items():
                        sub_ts[sub_id][key].append(values[i])

        # Recompute link velocity as |flow| / (volume / length).
        # Rationale: the bulk `links.velocities` API array was found to
        # disagree with the engine's own .rpt Link Flow Summary (5-12% on
        # circular pipes; understated up to ~6x on IRREGULAR transect
        # channels), while |Q|*L/volume reproduces the .rpt values to ~1%
        # for both pipes and channels (validated against a SWMM 5.0.022
        # reference run of the same model). The raw API series is kept as
        # "velocity_api" for auditability. Zero-length links (OUTLET/DUMMY)
        # carry no meaningful velocity and are reported as zero.
        for link_id in link_ids:
            ts = link_ts[link_id]
            length = float(ts.get("length", 0.0) or 0.0)
            flows = ts["flow"]
            volumes = ts["volume"]
            ts["velocity_api"] = ts["velocity"]
            if length > 0.0:
                derived = []
                for q, vol in zip(flows, volumes):
                    if vol > 1e-9:
                        v = abs(q) * length / vol
                        derived.append(v if np.isfinite(v) else 0.0)
                    else:
                        derived.append(0.0)
                ts["velocity"] = derived
            else:
                ts["velocity"] = [0.0] * len(flows)

        mb = solver.mass_balance
        diag = mb.routing_diagnostics
        metadata = {
            "flow_units": _enum_name(solver.flow_units),
            "system_units": str(solver.unit_system),
            # OpenSWMM returns continuity errors as fractions; the .rpt and
            # every downstream consumer (UI banner, report thresholds,
            # calgary_rules continuity_*_pct) express them in PERCENT.
            # Convert at the source so a -1.93% error reads as -1.93, not
            # -0.0193 (which silently defeated the 0.5/1.0% thresholds).
            "runoff_error": float(mb.runoff_continuity_error) * 100.0,
            "flow_error": float(mb.routing_continuity_error) * 100.0,
            "quality_error": _safe_float(lambda: mb.quality_continuity_error) * 100.0,
            "start_time": solver.start_datetime,
            "end_time": solver.end_datetime,
            "routing_steps": int(diag.n_steps),
            "not_converged_steps": int(diag.n_steps_not_converged),
            "pct_not_converged": float(diag.pct_not_converged),
            "avg_routing_step_s": float(diag.avg_time_step),
            "warnings": warnings,
            "report_path": rpt_path,
            "output_path": out_path,
        }

    return {
        "node_ts": node_ts,
        "link_ts": link_ts,
        "sub_ts": sub_ts,
        "times": times,
        "metadata": metadata,
    }


def write_payload(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inp", required=True)
    parser.add_argument("--rpt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    result_path = Path(args.result)

    try:
        results = simulate(args.inp, args.rpt, args.out)
        write_payload(result_path, {"ok": True, "results": results})
        # Bypass Python/native-extension finalisers.  This is intentional.
        os._exit(0)
    except BaseException as exc:
        write_payload(result_path, {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        })
        os._exit(1)


if __name__ == "__main__":
    main()
