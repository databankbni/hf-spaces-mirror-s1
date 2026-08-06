"""Preliminary SWMM scenario generation, execution, and comparison.

Rev22.1 intentionally treats generated storms and parameter changes as preliminary
engineering scenarios.  It does not represent generated rainfall as an approved
City of Calgary design storm unless the user supplies and verifies the source.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
import csv
import hashlib
import json
import math
import re
import tempfile
import zipfile

import pandas as pd

from swmm_core import run_swmm


@dataclass
class StormDefinition:
    mode: str = "existing_model"
    name: str = "Existing model rainfall"
    return_period: str = "Model-defined"
    duration_minutes: int = 60
    interval_minutes: int = 5
    total_depth_mm: float | None = None
    peak_position: float = 0.40
    source_status: str = "Existing model input"
    source_reference: str = ""
    selected_timeseries: str = ""


@dataclass
class ScenarioChange:
    object_type: str
    object_id: str
    parameter: str
    old_value: Any = None
    new_value: Any = None
    status: str = "requested"
    note: str = ""


@dataclass
class ScenarioDefinition:
    scenario_id: str
    scenario_name: str
    description: str = ""
    storm: StormDefinition = field(default_factory=StormDefinition)
    imperviousness_overrides: dict[str, float] = field(default_factory=dict)
    conduit_diameter_overrides: dict[str, float] = field(default_factory=dict)
    conduit_roughness_overrides: dict[str, float] = field(default_factory=dict)
    storage_depth_overrides: dict[str, float] = field(default_factory=dict)
    simulation_hours: float | None = None
    review_status: str = "Preliminary"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def safe_scenario_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    return cleaned[:64] or "scenario"


def _split_sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        m = re.match(r"^\s*\[([^]]+)\]\s*$", raw)
        if m:
            current = m.group(1).upper()
            sections.setdefault(current, [])
        elif current is None:
            preamble.append(raw)
        else:
            sections[current].append(raw)
    return preamble, sections


def _join_sections(preamble: list[str], sections: dict[str, list[str]]) -> str:
    out = list(preamble)
    if out and out[-1].strip():
        out.append("")
    for name, lines in sections.items():
        out.append(f"[{name}]")
        out.extend(lines)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _data_tokens(line: str) -> tuple[list[str], str] | None:
    body, sep, comment = line.partition(";")
    if not body.strip() or body.lstrip().startswith(";"):
        return None
    return body.split(), (sep + comment if sep else "")


def _replace_tokens(line: str, tokens: list[str], comment: str) -> str:
    return "  ".join(str(x) for x in tokens) + ((" " + comment) if comment else "")


def _update_named_row(lines: list[str], object_id: str, token_index: int, new_value: Any) -> tuple[list[str], Any, bool]:
    updated: list[str] = []
    old = None
    changed = False
    for line in lines:
        parsed = _data_tokens(line)
        if parsed and parsed[0] and parsed[0][0].casefold() == object_id.casefold():
            tokens, comment = parsed
            if len(tokens) > token_index:
                old = tokens[token_index]
                tokens[token_index] = f"{new_value:g}" if isinstance(new_value, float) else str(new_value)
                line = _replace_tokens(line, tokens, comment)
                changed = True
        updated.append(line)
    return updated, old, changed


def _set_option(lines: list[str], key: str, value: str) -> list[str]:
    result: list[str] = []
    found = False
    for line in lines:
        parsed = _data_tokens(line)
        if parsed and parsed[0][0].upper() == key.upper():
            tokens, comment = parsed
            tokens = [key, value]
            line = _replace_tokens(line, tokens, comment)
            found = True
        result.append(line)
    if not found:
        result.append(f"{key:<20} {value}")
    return result


def chicago_style_incremental_depths(total_depth_mm: float, duration_minutes: int, interval_minutes: int, peak_position: float = 0.4) -> list[float]:
    """Create a preliminary, mass-conserving Chicago-style alternating-block storm.

    This is deliberately labelled preliminary. It is useful for scenario workflow
    testing, but it is not a replacement for a verified municipal IDF-based storm.
    """
    n = max(1, int(math.ceil(duration_minutes / interval_minutes)))
    # Smooth synthetic intensity pattern with a sharp peak and positive tails.
    ranks = list(range(1, n + 1))
    weights = [1.0 / (r ** 0.72) for r in ranks]
    scale = total_depth_mm / sum(weights)
    blocks = [w * scale for w in weights]
    peak_idx = min(n - 1, max(0, round((n - 1) * peak_position)))
    order = [peak_idx]
    offset = 1
    while len(order) < n:
        right = peak_idx + offset
        left = peak_idx - offset
        if right < n:
            order.append(right)
        if left >= 0 and len(order) < n:
            order.append(left)
        offset += 1
    result = [0.0] * n
    for block, idx in zip(sorted(blocks, reverse=True), order):
        result[idx] = block
    # exact conservation after floating-point arithmetic
    result[-1] += total_depth_mm - sum(result)
    return result


def _inject_preliminary_storm(sections: dict[str, list[str]], storm: StormDefinition, scenario_id: str) -> None:
    if storm.total_depth_mm is None:
        raise ValueError("Total storm depth is required for a generated preliminary storm.")
    interval = max(1, int(storm.interval_minutes))
    duration = max(interval, int(storm.duration_minutes))
    series_id = f"SCN_{safe_scenario_id(scenario_id)}_RAIN"
    depths = chicago_style_incremental_depths(float(storm.total_depth_mm), duration, interval, float(storm.peak_position))

    # Replace/add the time series. Values are interval rainfall depths; the gage is VOLUME.
    ts_lines = [ln for ln in sections.get("TIMESERIES", []) if not (_data_tokens(ln) and _data_tokens(ln)[0][0].casefold() == series_id.casefold())]
    start = datetime(2000, 1, 1, 0, 0)
    ts_lines.append(f"; Preliminary scenario storm: {storm.name}; source status: {storm.source_status}")
    for i, depth in enumerate(depths):
        t = start + timedelta(minutes=i * interval)
        ts_lines.append(f"{series_id:<24} {t.strftime('%m/%d/%Y')} {t.strftime('%H:%M')} {depth:.6f}")
    sections["TIMESERIES"] = ts_lines

    # Point all model rain gages to the generated series while retaining their IDs.
    rg_lines: list[str] = []
    for line in sections.get("RAINGAGES", []):
        parsed = _data_tokens(line)
        if parsed:
            tokens, comment = parsed
            if len(tokens) >= 1:
                gage_id = tokens[0]
                tokens = [gage_id, "VOLUME", f"0:{interval:02d}", "1.0", "TIMESERIES", series_id]
                line = _replace_tokens(line, tokens, comment)
        rg_lines.append(line)
    sections["RAINGAGES"] = rg_lines



def extract_rainfall_event_catalog(text: str) -> list[dict[str, str]]:
    """Return rainfall time-series available inside an INP model.

    SWMM models often retain several design-event series (for example 1:5 and
    1:100) while only one series is referenced by the active rain gage.
    """
    _, sections = _split_sections(text)
    active = set()
    gages = {}
    for line in sections.get("RAINGAGES", []):
        parsed = _data_tokens(line)
        if not parsed:
            continue
        tokens, _ = parsed
        if len(tokens) >= 6 and tokens[4].upper() == "TIMESERIES":
            gages[tokens[0]] = tokens[5]
            active.add(tokens[5].casefold())
    ids=[]
    seen=set()
    for line in sections.get("TIMESERIES", []):
        parsed=_data_tokens(line)
        if not parsed:
            continue
        tokens,_=parsed
        if not tokens:
            continue
        sid=tokens[0]
        if sid.casefold() in seen:
            continue
        seen.add(sid.casefold())
        ids.append({"event_id":sid,"active":"Yes" if sid.casefold() in active else "No","used_by":", ".join(k for k,v in gages.items() if v.casefold()==sid.casefold())})
    return ids


def _select_existing_timeseries(sections: dict[str, list[str]], series_id: str) -> None:
    """Point every TIMESERIES-based rain gage to an existing model series."""
    available={x["event_id"].casefold():x["event_id"] for x in extract_rainfall_event_catalog(_join_sections([], sections))}
    if series_id.casefold() not in available:
        raise ValueError(f"Rainfall time series {series_id!r} was not found in the selected model.")
    canonical=available[series_id.casefold()]
    new=[]
    changed=0
    for line in sections.get("RAINGAGES", []):
        parsed=_data_tokens(line)
        if parsed:
            tokens,comment=parsed
            if len(tokens)>=6 and tokens[4].upper()=="TIMESERIES":
                tokens[5]=canonical
                line=_replace_tokens(line,tokens,comment)
                changed+=1
        new.append(line)
    if changed==0:
        raise ValueError("The selected model has no TIMESERIES-based rain gage to assign.")
    sections["RAINGAGES"]=new

def build_scenario_inp(base_inp: str | Path, scenario: ScenarioDefinition, output_path: str | Path) -> dict[str, Any]:
    base = Path(base_inp)
    text = base.read_text(encoding="utf-8", errors="ignore")
    preamble, sections = _split_sections(text)
    change_log: list[ScenarioChange] = []

    if scenario.storm.mode == "generated_preliminary":
        _inject_preliminary_storm(sections, scenario.storm, scenario.scenario_id)
        change_log.append(ScenarioChange("storm", scenario.storm.name, "rainfall_series", None, scenario.storm.total_depth_mm, "applied", scenario.storm.source_status))
    elif scenario.storm.mode == "existing_timeseries" and scenario.storm.selected_timeseries:
        _select_existing_timeseries(sections, scenario.storm.selected_timeseries)
        change_log.append(ScenarioChange("storm", scenario.storm.selected_timeseries, "active_timeseries", None, scenario.storm.selected_timeseries, "applied", "Existing series selected from model"))

    if scenario.simulation_hours and scenario.simulation_hours > 0:
        start = datetime(2000, 1, 1, 0, 0)
        end = start + timedelta(hours=float(scenario.simulation_hours))
        opts = sections.setdefault("OPTIONS", [])
        for key, val in [
            ("START_DATE", start.strftime("%m/%d/%Y")),
            ("START_TIME", start.strftime("%H:%M:%S")),
            ("REPORT_START_DATE", start.strftime("%m/%d/%Y")),
            ("REPORT_START_TIME", start.strftime("%H:%M:%S")),
            ("END_DATE", end.strftime("%m/%d/%Y")),
            ("END_TIME", end.strftime("%H:%M:%S")),
        ]:
            opts = _set_option(opts, key, val)
        sections["OPTIONS"] = opts

    # SWMM [SUBCATCHMENTS]: Name RainGage Outlet Area %Imperv Width %Slope ...
    for oid, value in scenario.imperviousness_overrides.items():
        lines, old, ok = _update_named_row(sections.get("SUBCATCHMENTS", []), oid, 4, float(value))
        sections["SUBCATCHMENTS"] = lines
        change_log.append(ScenarioChange("subcatchment", oid, "imperviousness_percent", old, value, "applied" if ok else "not_found"))

    # SWMM [XSECTIONS]: Link Shape Geom1 ... ; circular Geom1 is diameter.
    for oid, value in scenario.conduit_diameter_overrides.items():
        lines, old, ok = _update_named_row(sections.get("XSECTIONS", []), oid, 2, float(value))
        sections["XSECTIONS"] = lines
        change_log.append(ScenarioChange("link", oid, "diameter_or_geom1", old, value, "applied" if ok else "not_found"))

    # SWMM [CONDUITS]: Name From To Length Roughness ...
    for oid, value in scenario.conduit_roughness_overrides.items():
        lines, old, ok = _update_named_row(sections.get("CONDUITS", []), oid, 4, float(value))
        sections["CONDUITS"] = lines
        change_log.append(ScenarioChange("conduit", oid, "manning_n", old, value, "applied" if ok else "not_found"))

    # SWMM [STORAGE]: Name Elev MaxDepth InitDepth Shape ...
    for oid, value in scenario.storage_depth_overrides.items():
        lines, old, ok = _update_named_row(sections.get("STORAGE", []), oid, 2, float(value))
        sections["STORAGE"] = lines
        change_log.append(ScenarioChange("storage", oid, "maximum_depth", old, value, "applied" if ok else "not_found"))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_join_sections(preamble, sections), encoding="utf-8")
    return {
        "scenario": asdict(scenario),
        "changes": [asdict(x) for x in change_log],
        "input_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "output_path": str(output),
    }


def summarize_scenario_results(results: dict[str, Any], scenario: ScenarioDefinition) -> dict[str, Any]:
    node_ts = results.get("node_ts", {}) or {}
    link_ts = results.get("link_ts", {}) or {}
    sub_ts = results.get("sub_ts", {}) or {}
    meta = results.get("metadata", {}) or {}

    max_flood = max((max(v.get("flooding", []) or [0.0]) for v in node_ts.values()), default=0.0)
    total_peak_inflow = max((max(v.get("inflow", []) or [0.0]) for v in node_ts.values()), default=0.0)
    max_velocity = 0.0
    max_velocity_link = ""
    max_depth_ratio = 0.0
    max_depth_ratio_link = ""
    peak_link_flow = 0.0
    for lid, values in link_ts.items():
        vel = max((abs(float(x)) for x in values.get("velocity", []) or [0.0]), default=0.0)
        if vel > max_velocity:
            max_velocity, max_velocity_link = vel, lid
        depth = max((float(x) for x in values.get("depth", []) or [0.0]), default=0.0)
        diameter = float(values.get("diameter", 0.0) or 0.0)
        ratio = depth / diameter if diameter > 0 else 0.0
        if ratio > max_depth_ratio:
            max_depth_ratio, max_depth_ratio_link = ratio, lid
        peak_link_flow = max(peak_link_flow, max((abs(float(x)) for x in values.get("flow", []) or [0.0]), default=0.0))
    peak_runoff = max((max(v.get("runoff", []) or [0.0]) for v in sub_ts.values()), default=0.0)
    return {
        "Scenario ID": scenario.scenario_id,
        "Scenario Name": scenario.scenario_name,
        "Storm": scenario.storm.name,
        "Storm Status": scenario.storm.source_status,
        "Simulation Status": "Completed",
        "Runoff Error (%)": float(meta.get("runoff_error", 0.0) or 0.0),
        "Flow Error (%)": float(meta.get("flow_error", 0.0) or 0.0),
        "Peak Subcatchment Runoff": peak_runoff,
        "Peak Link Flow": peak_link_flow,
        "Maximum Link Velocity": max_velocity,
        "Velocity Link": max_velocity_link,
        "Maximum Modelled Depth Ratio": max_depth_ratio,
        "Depth-Ratio Link": max_depth_ratio_link,
        "Maximum Node Flooding": max_flood,
        "Maximum Node Inflow": total_peak_inflow,
        "Review Status": scenario.review_status,
        "Model Role": "Scenario",
    }


def run_scenario(base_inp: str | Path, scenario: ScenarioDefinition, work_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="swmm_scenario_"))
    root.mkdir(parents=True, exist_ok=True)
    sid = safe_scenario_id(scenario.scenario_id)
    inp = root / f"{sid}.inp"
    manifest = build_scenario_inp(base_inp, scenario, inp)
    rpt = root / f"{sid}.rpt"
    out = root / f"{sid}.out"
    results = run_swmm(inp, rpt, out)
    # Attach final-input geometry to result records so scenario depth-ratio
    # summaries are computed from the scenario model rather than shown as zero.
    final_sections = {}
    try:
        _, final_sections = _split_sections(inp.read_text(encoding="utf-8", errors="ignore"))
        diameters = {}
        for line in final_sections.get("XSECTIONS", []):
            parsed = _data_tokens(line)
            if parsed:
                tokens, _ = parsed
                if len(tokens) >= 3:
                    try:
                        diameters[tokens[0]] = float(tokens[2])
                    except ValueError:
                        pass
        for lid, values in (results.get("link_ts", {}) or {}).items():
            if lid in diameters:
                values["diameter"] = diameters[lid]
    except Exception:
        pass
    summary = summarize_scenario_results(results, scenario)
    summary["Conduit Count"] = len(final_sections.get("CONDUITS", []) or [])
    storage_ids = [(_data_tokens(line)[0][0] if _data_tokens(line) else "") for line in (final_sections.get("STORAGE", []) or [])]
    storage_ids = [x for x in storage_ids if x]
    storage_depth = 0.0
    storage_volume = 0.0
    storage_node = ""
    for node_id in storage_ids:
        values = (results.get("node_ts", {}) or {}).get(node_id, {})
        depth = max((float(x) for x in values.get("depth", []) or [0.0]), default=0.0)
        volume = max((float(x) for x in values.get("volume", []) or [0.0]), default=0.0)
        if depth > storage_depth:
            storage_depth, storage_node = depth, node_id
        storage_volume = max(storage_volume, volume)
    summary["Maximum Storage Depth"] = storage_depth if storage_ids else None
    summary["Maximum Storage Volume"] = storage_volume if storage_ids else None
    summary["Controlling Storage Node"] = storage_node if storage_ids else ""
    manifest.update({
        "report_path": str(rpt),
        "output_path": str(out),
        "report_sha256": hashlib.sha256(rpt.read_bytes()).hexdigest() if rpt.exists() else None,
        "summary": summary,
    })
    return {"definition": asdict(scenario), "manifest": manifest, "results": results, "summary": summary, "files": {"inp": inp.read_bytes(), "rpt": rpt.read_bytes() if rpt.exists() else b"", "out": out.read_bytes() if out.exists() else b""}}



def base_model_record(results: dict[str, Any], *, scenario_name: str = "Base Model", review_status: str = "Reference model", source_name: str = "Base Model") -> dict[str, Any]:
    """Create a comparison record for the currently simulated base model."""
    definition = ScenarioDefinition(
        scenario_id="BASE_MODEL",
        scenario_name=scenario_name,
        description="Current uploaded and simulated reference model.",
        storm=StormDefinition(
            mode="existing_model",
            name="Existing model rainfall",
            return_period="Model-defined",
            source_status="Base model input",
        ),
        review_status=review_status,
    )
    summary = summarize_scenario_results(results or {}, definition)
    summary["Model Role"] = "Base"
    summary["Source Model"] = source_name
    summary["Input Changed"] = "Reference"
    summary["Input SHA256 (short)"] = ""
    summary["Conduit Count"] = sum(1 for values in ((results or {}).get("link_ts", {}) or {}).values() if float(values.get("diameter", 0) or 0) > 0)
    return {
        "definition": asdict(definition),
        "manifest": {"summary": summary, "model_role": "Base", "source": "Current uploaded model"},
        "results": results or {},
        "summary": summary,
        "files": {},
    }


def comparison_with_base(base_results: dict[str, Any] | None, records: Iterable[dict[str, Any]], *, base_name: str = "Base Model") -> pd.DataFrame:
    """Return one comparison table containing the base model and scenario records."""
    combined: list[dict[str, Any]] = []
    if base_results:
        combined.append(base_model_record(base_results, scenario_name=base_name, source_name=base_name))
    combined.extend(list(records))
    df = comparison_dataframe(combined)
    if not df.empty and "Model Role" not in df.columns:
        df.insert(0, "Model Role", ["Base" if str(v) == "BASE_MODEL" else "Scenario" for v in df.get("Scenario ID", [])])
    elif not df.empty:
        df["Model Role"] = df["Model Role"].fillna("Scenario")
    if not df.empty:
        base_rows = df[df["Scenario ID"].astype(str) == "BASE_MODEL"]
        if not base_rows.empty:
            b = base_rows.iloc[0]
            metric_cols = ["Peak Subcatchment Runoff", "Peak Link Flow", "Maximum Link Velocity", "Maximum Modelled Depth Ratio", "Maximum Node Flooding", "Maximum Node Inflow"]
            flags = []
            for _, row in df.iterrows():
                if str(row.get("Scenario ID")) == "BASE_MODEL":
                    flags.append("Reference")
                    continue
                changed = False
                for col in metric_cols:
                    try:
                        if abs(float(row.get(col, 0) or 0) - float(b.get(col, 0) or 0)) > 1e-8:
                            changed = True
                            break
                    except Exception:
                        pass
                flags.append("Different" if changed else "No summary-level difference")
            df["Hydraulic Difference"] = flags
    return df


def deterministic_comparison_analysis(comparison: pd.DataFrame) -> str:
    """Create a conservative, deterministic scenario-comparison narrative."""
    if comparison is None or comparison.empty:
        return "No scenario comparison data are available."
    df = comparison.copy()
    base = df[df["Scenario ID"].astype(str) == "BASE_MODEL"]
    if base.empty:
        base = df.iloc[[0]]
    b = base.iloc[0]
    metrics = [
        ("Peak Subcatchment Runoff", "peak subcatchment runoff"),
        ("Peak Link Flow", "peak link flow"),
        ("Maximum Link Velocity", "maximum link velocity"),
        ("Maximum Modelled Depth Ratio", "maximum modelled depth ratio"),
        ("Maximum Node Flooding", "maximum node flooding"),
        ("Maximum Node Inflow", "maximum node inflow"),
        ("Maximum Storage Depth", "maximum storage depth"),
        ("Maximum Storage Volume", "maximum storage volume"),
    ]
    lines = [
        "The comparison uses the current uploaded model as the reference case. Differences are calculated from deterministic simulation summaries and are intended for preliminary engineering review.",
        "",
    ]
    # Guard: if every base metric is zero while at least one scenario is
    # non-zero, the base record almost certainly did not carry usable
    # results (e.g. it was built from an empty or malformed results dict).
    # Deltas quoted against a zeroed base are misleading, so say so
    # explicitly instead of presenting "+X relative to base" as fact.
    def _metric_value(record, col):
        try:
            return abs(float(record.get(col, 0) or 0))
        except Exception:
            return 0.0
    base_all_zero = all(_metric_value(b, col) <= 1e-12 for col, _ in metrics)
    any_scenario_nonzero = any(
        _metric_value(row, col) > 1e-12
        for _, row in df[df["Scenario ID"].astype(str) != str(b.get("Scenario ID", "BASE_MODEL"))].iterrows()
        for col, _ in metrics
    )
    if base_all_zero and any_scenario_nonzero:
        lines.insert(0, (
            "CAUTION: All reference-case metrics are zero while scenario results are non-zero. "
            "The base record does not appear to contain usable simulation results; differences below "
            "are NOT valid deltas against the uploaded model. Re-simulate or rebuild the base record "
            "before relying on this comparison."
        ))
        lines.insert(1, "")
    scenarios = df[df["Scenario ID"].astype(str) != str(b.get("Scenario ID", "BASE_MODEL"))]
    if scenarios.empty:
        lines.append("No alternative scenario has been completed.")
        return "\n".join(lines)
    for _, row in scenarios.iterrows():
        sid = row.get("Scenario ID", "Scenario")
        name = row.get("Scenario Name", sid)
        lines.append(f"{name} ({sid}):")
        changes=[]
        no_conduits = int(row.get("Conduit Count", 0) or 0) == 0
        for col,label in metrics:
            if no_conduits and col in {"Maximum Link Velocity", "Maximum Modelled Depth Ratio"}:
                changes.append(f"- {label}: Not applicable — no conduits in model")
                continue
            try:
                bv=float(b.get(col,0) or 0); sv=float(row.get(col,0) or 0)
            except Exception:
                continue
            delta=sv-bv
            if abs(bv)>1e-12:
                pct=100*delta/abs(bv)
                changes.append(f"- {label}: {sv:.4g} ({delta:+.4g}; {pct:+.1f}% relative to base)")
            else:
                changes.append(f"- {label}: {sv:.4g} ({delta:+.4g} relative to base)")
        lines.extend(changes)
        if str(row.get("Hydraulic Difference", "")) == "No summary-level difference":
            lines.append("- No difference was detected in the reported summary metrics. Check the input-change status and detailed time series before treating this as a distinct hydraulic alternative.")
        if str(row.get("Input Changed", "")) == "No":
            lines.append("- The final scenario input is identical to the base-model input; identical results are expected.")
        if float(row.get("Maximum Node Flooding",0) or 0)>0:
            lines.append("- Modelled node flooding is present and requires review.")
        if abs(float(row.get("Runoff Error (%)",0) or 0))>1 or abs(float(row.get("Flow Error (%)",0) or 0))>1:
            lines.append("- Numerical continuity exceeds 1% for at least one reported balance and requires review.")
        lines.append("")
    lines.append("The comparison does not establish design adequacy or compliance. The responsible engineer must review model changes, storm sources, controlling elements, physical feasibility, and applicable project criteria.")
    return "\n".join(lines).strip()

def comparison_dataframe(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows = [r.get("summary", {}) for r in records]
    return pd.DataFrame(rows)


def build_scenario_package(records: Iterable[dict[str, Any]]) -> bytes:
    records = list(records)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        comparison = comparison_dataframe(records)
        zf.writestr("scenario_comparison.csv", comparison.to_csv(index=False))
        manifest = []
        for rec in records:
            sid = safe_scenario_id(rec.get("definition", {}).get("scenario_id", "scenario"))
            base = f"scenarios/{sid}"
            editable_clone = rec.get("files", {}).get("editable_clone", b"")
            if editable_clone:
                zf.writestr(f"{base}/{sid}_editable_clone_source.inp", editable_clone)
            zf.writestr(f"{base}/{sid}.inp", rec.get("files", {}).get("inp", b""))
            zf.writestr(f"{base}/{sid}.rpt", rec.get("files", {}).get("rpt", b""))
            out_bytes = rec.get("files", {}).get("out", b"")
            if out_bytes:
                zf.writestr(f"{base}/{sid}.out", out_bytes)
            zf.writestr(f"{base}/scenario_definition.json", json.dumps(rec.get("definition", {}), indent=2, default=str))
            zf.writestr(f"{base}/scenario_manifest.json", json.dumps(rec.get("manifest", {}), indent=2, default=str))
            manifest.append(rec.get("manifest", {}))
        zf.writestr("scenario_register.json", json.dumps(manifest, indent=2, default=str))
        zf.writestr("README.txt", "Rev22.1 preliminary scenario package. Editable clone source files are preserved separately from final scenario input files. Generated storms and parameter changes require professional verification before design use or municipal submission.\n")
    return buffer.getvalue()
