"""SWMM analysis tool registry.

Every capability is a plain typed function registered in TOOL_REGISTRY.
The MCP surface, the REST surface, and the internal agent all dispatch to
these same functions, so behaviour is identical regardless of platform.

Epistemics: all screening results are deterministic and distinguish
"screening" from "criterion"; nothing here is a professional engineering
determination. Outputs are bounded (row/point limits) so they remain usable
as LLM tool results.
"""
from __future__ import annotations

import base64
import binascii
import json
import math
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import model_pipeline as mp
import rpt_reconciliation as rr
from calgary_rules import (
    CalgaryCriteria,
    apply_storage_classification,
    criteria_register,
    infer_design_event,
)
from preliminary_design_assistant import build_deterministic_findings, findings_dataframe
from results_db import ResultDatabase
from sessions import STORE
from sql_agent import SafeSQLAgent
from swmm_core import run_swmm
from screening_logic import execution_integrity_assessment, resolve_legacy_solver_options

MAX_ROWS = 60
MAX_TS_POINTS = 200


def _df_records(df: pd.DataFrame | None, limit: int = MAX_ROWS) -> dict[str, Any]:
    if df is None or df.empty:
        return {"rows": [], "row_count": 0, "truncated": False}
    clean = df.replace({float("nan"): None})
    return {
        "rows": json.loads(clean.head(limit).to_json(orient="records")),
        "row_count": int(len(df)),
        "truncated": bool(len(df) > limit),
    }


def _require_results(session) -> None:
    if not session.data.get("results"):
        raise ValueError(f"Session '{session.id}' has no simulation results yet. Call run_simulation first.")


def _options_map(sections: dict[str, list[list[str]]]) -> dict[str, str]:
    return {str(r[0]).upper(): str(r[1]) for r in sections.get("OPTIONS", []) if len(r) >= 2}


def _write_normalized_execution_copy(source: Path, substitutions: list[dict[str, Any]]) -> Path:
    """Write a derivative INP containing only audited legacy substitutions."""
    replacements = {str(s["option"]).upper(): format(float(s["effective_value"]), "g")
                    for s in substitutions}
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    in_options = False
    changed: set[str] = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_options = stripped.upper() == "[OPTIONS]"
            continue
        if not in_options or not stripped or stripped.startswith(";"):
            continue
        parts = stripped.split()
        key = parts[0].upper() if parts else ""
        if key in replacements:
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            lines[i] = f"{parts[0]:<20} {replacements[key]}{newline}"
            changed.add(key)
    missing = sorted(set(replacements) - changed)
    if missing:
        raise ValueError("Could not normalize legacy [OPTIONS] values: " + ", ".join(missing))
    target = source.with_name(f"{source.stem}_legacy_defaults_normalized{source.suffix}")
    target.write_text("".join(lines), encoding="utf-8", newline="")
    return target


# ---------------------------------------------------------------------------
# Model lifecycle
# ---------------------------------------------------------------------------

def upload_model(inp_content: str, filename: str = "model.inp") -> dict:
    """Upload an EPA SWMM .inp model (raw text or base64) and create a session.

    Returns a session_id used by every other tool, plus element counts.
    """
    text = inp_content
    if "[" not in inp_content[:2000]:  # likely base64
        try:
            text = base64.b64decode(inp_content, validate=True).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            pass
    if "[OPTIONS]" not in text.upper() and "[JUNCTIONS]" not in text.upper():
        raise ValueError("Content does not look like a SWMM .inp file (no [OPTIONS]/[JUNCTIONS] section).")
    session = STORE.create()
    safe_name = Path(filename).name or "model.inp"
    if not safe_name.lower().endswith(".inp"):
        safe_name += ".inp"
    inp_path = session.workdir / safe_name
    inp_path.write_text(text, encoding="utf-8")
    sections = mp.parse_inp_sections(str(inp_path))
    session.data.update({"filename": safe_name, "inp_path": str(inp_path), "sections": sections})
    counts = {name: len(rows) for name, rows in sections.items()
              if name in ("JUNCTIONS", "OUTFALLS", "STORAGE", "CONDUITS", "PUMPS", "WEIRS",
                          "ORIFICES", "OUTLETS", "SUBCATCHMENTS", "RAINGAGES", "TIMESERIES")}
    gages = [row[0] for row in sections.get("RAINGAGES", []) if row]
    return {
        "session_id": session.id,
        "filename": safe_name,
        "element_counts": counts,
        "rain_gages": gages,
        "design_event_inference": infer_design_event(gages) if gages else None,
        "next_step": "Call run_simulation with this session_id.",
    }


def run_simulation(session_id: str) -> dict:
    """Run the model in the crash-isolated OpenSWMM worker and build summaries.

    Also runs the deterministic worker-vs-.rpt reconciliation cross-check.
    """
    session = STORE.get(session_id)
    inp_path = session.data.get("inp_path")
    if not inp_path:
        raise ValueError("Session has no uploaded model.")
    sections = session.data["sections"]
    resolution = resolve_legacy_solver_options(_options_map(sections))
    option_errors = resolution["errors"]
    if option_errors:
        session.data["input_validation_errors"] = option_errors
        raise ValueError(
            "Input validation failed; simulation was not run. " + " ".join(option_errors)
        )
    original_path = Path(inp_path)
    substitutions = list(resolution["substitutions"])
    execution_path = (_write_normalized_execution_copy(original_path, substitutions)
                      if substitutions else original_path)
    results = run_swmm(str(execution_path))
    md = results["metadata"]
    import hashlib, datetime
    original_sha256 = hashlib.sha256(original_path.read_bytes()).hexdigest()
    execution_sha256 = hashlib.sha256(execution_path.read_bytes()).hexdigest()
    run_id = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    md["model_sha256"] = original_sha256
    md["original_model_sha256"] = original_sha256
    md["execution_model_sha256"] = execution_sha256
    md["original_model_filename"] = original_path.name
    md["execution_model_filename"] = execution_path.name
    md["legacy_defaults_normalized"] = bool(substitutions)
    md["solver_option_substitutions"] = substitutions
    md["run_id"] = run_id
    integrity = execution_integrity_assessment(md)
    md.update({
        "execution_integrity_status": integrity["status"],
        "results_usable": integrity["results_usable"],
        "hydraulic_conclusions_allowed": integrity["hydraulic_conclusions_allowed"],
        "execution_integrity_reason": integrity["reason"],
    })
    node_df = mp.build_node_summary(results["node_ts"], mp.parse_node_types(sections), 0.001, 0.9)
    link_df = mp.build_link_summary(results["link_ts"], mp.parse_link_topology(sections),
                                    mp.parse_conduit_geometry(sections), 0.9, 3.0)
    sub_df = mp.build_sub_summary(results["sub_ts"], mp.parse_subcatchment_attrs(sections),
                                  results.get("times"), md.get("flow_units", "CMS"))
    if not integrity["results_usable"]:
        invalid_label = "Not assessed - hydraulic routing solution invalid"
        if "Status" in node_df:
            node_df["Status"] = invalid_label
        if "Status" in link_df:
            link_df["Status"] = invalid_label
    db = ResultDatabase(str(session.workdir / "results.sqlite"))
    db.load(node_df, link_df, sub_df, inp_path=original_path, results=results)

    recon = {"verdict": "Not performed"}
    recon_links = recon_nodes = recon_cont = None
    rpt_path = md.get("report_path")
    if rpt_path and Path(str(rpt_path)).exists():
        recon_links = rr.reconcile_links(link_df, rpt_path)
        recon_nodes = rr.reconcile_nodes(node_df, rpt_path)
        recon_cont = rr.reconcile_continuity(md, rpt_path)
        recon = rr.reconciliation_summary(recon_links)

    session.data.update({
        "results": results, "node_df": node_df, "link_df": link_df, "sub_df": sub_df,
        "execution_inp_path": str(execution_path),
        "db": db, "recon_links": recon_links, "recon_nodes": recon_nodes,
        "recon_continuity": recon_cont, "recon_summary": recon,
    })
    flooded_col = next((c for c in node_df.columns if c.startswith("Peak Flooding (")), None)
    flooded = int((pd.to_numeric(node_df[flooded_col], errors="coerce").fillna(0) > 0.001).sum()) if flooded_col else 0
    return {
        "session_id": session.id,
        "simulation": "completed" if integrity["results_usable"] else "completed_invalid",
        "execution_integrity": integrity,
        "results_usable": integrity["results_usable"],
        "model_sha256": original_sha256,
        "execution_model_sha256": execution_sha256,
        "legacy_defaults_normalized": bool(substitutions),
        "solver_option_substitutions": substitutions,
        "run_id": run_id,
        "flow_units": md.get("flow_units"),
        "runoff_continuity_error_pct": round(float(md.get("runoff_error", 0.0)), 3),
        "flow_continuity_error_pct": round(float(md.get("flow_error", 0.0)), 3),
        "warnings": (results.get("warnings") or md.get("warnings") or [])[:10],
        "flooded_nodes": flooded,
        "rpt_reconciliation": recon,
        "note": ("Values are model results, not engineering determinations."
                 if integrity["results_usable"] else
                 "Hydraulic arrays are retained for audit only and must not be used for screening conclusions."),
    }


def list_sessions() -> dict:
    """List active sessions (id, model filename, simulated flag, age)."""
    return {"sessions": STORE.list()}


def close_session(session_id: str) -> dict:
    """Delete a session and its working files."""
    return {"session_id": session_id, "deleted": STORE.drop(session_id)}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def get_node_results(session_id: str, node_type: str = "", sort_by: str = "Depth Ratio",
                     limit: int = 20) -> dict:
    """Node result summary. Optional node_type filter (junction/storage/outfall);
    sorted descending by sort_by column (default Depth Ratio)."""
    session = STORE.get(session_id)
    _require_results(session)
    df = session.data["node_df"]
    if node_type:
        df = df[df["Type"].astype(str).str.lower() == node_type.lower()]
    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False)
    return _df_records(df, min(int(limit), MAX_ROWS))


def get_link_results(session_id: str, sort_by: str = "Peak Velocity (m/s)", limit: int = 20) -> dict:
    """Link result summary sorted descending by sort_by (default peak velocity)."""
    session = STORE.get(session_id)
    _require_results(session)
    df = session.data["link_df"]
    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False)
    return _df_records(df, min(int(limit), MAX_ROWS))


def get_subcatchment_results(session_id: str, limit: int = 30) -> dict:
    """Subcatchment runoff summary."""
    session = STORE.get(session_id)
    _require_results(session)
    return _df_records(session.data["sub_df"], min(int(limit), MAX_ROWS))


def get_timeseries(session_id: str, object_type: str, object_id: str, variable: str) -> dict:
    """Bounded time series for one object.

    object_type: node|link|subcatchment. Variables — node: depth, flooding,
    inflow, head, outflow, volume; link: flow, depth, velocity, volume,
    capacity; subcatchment: runoff, rainfall, infil. Series longer than 200
    points are decimated evenly (peaks preserved via max-in-bucket).
    """
    session = STORE.get(session_id)
    _require_results(session)
    results = session.data["results"]
    key = {"node": "node_ts", "link": "link_ts", "subcatchment": "sub_ts"}.get(object_type.lower())
    if key is None:
        raise ValueError("object_type must be node, link, or subcatchment")
    store = results[key]
    if object_id not in store:
        raise ValueError(f"Unknown {object_type} '{object_id}'. Known: {sorted(store)[:25]}")
    series = store[object_id].get(variable)
    if not isinstance(series, list):
        available = [k for k, v in store[object_id].items() if isinstance(v, list)]
        raise ValueError(f"Unknown variable '{variable}'. Available: {available}")
    times = results.get("times", [])
    n = len(series)
    if n > MAX_TS_POINTS:
        bucket = math.ceil(n / MAX_TS_POINTS)
        points = []
        for i in range(0, n, bucket):
            chunk = series[i:i + bucket]
            j = i + max(range(len(chunk)), key=lambda k: abs(chunk[k]))
            points.append({"t": str(times[j]) if j < len(times) else j, "v": round(float(series[j]), 6)})
    else:
        points = [{"t": str(times[i]) if i < len(times) else i, "v": round(float(v), 6)}
                  for i, v in enumerate(series)]
    peak_val = max(series, key=abs, default=0.0)
    peak_idx = series.index(peak_val) if series else 0
    time_of_peak = str(times[peak_idx]) if peak_idx < len(times) else None
    return {"object_id": object_id, "variable": variable, "n_source_points": n,
            "decimated": n > MAX_TS_POINTS, "peak": round(float(peak_val), 6),
            "time_of_peak": time_of_peak,
            "note": "time_of_peak is from the full-resolution series; do not infer it from decimated point labels.",
            "points": points}


def query_results(session_id: str, plan: dict | str) -> dict:
    """Execute a validated JSON retrieval plan against the bounded result DB.

    Plan format: {"actions":[{"type":"select"|"aggregate","table":...,
    "columns":[...], "filters":[{"column","op","value"}], "order_by":[...],
    "limit":N, "aggregations":[{"agg","column"}]}]}. Use get_table_catalog
    for table/column names. Read-only; invalid plans degrade gracefully.
    """
    session = STORE.get(session_id)
    _require_results(session)
    if isinstance(plan, str):
        plan = json.loads(plan)
    agent = SafeSQLAgent(session.data["db"])
    result = agent.execute_plan(plan)
    return {"context": result.context[:12000]}


def get_table_catalog(session_id: str) -> dict:
    """List queryable tables (results + complete tokenized INP) for query_results."""
    session = STORE.get(session_id)
    _require_results(session)
    return _df_records(session.data["db"].table_catalog(), 60)


# ---------------------------------------------------------------------------
# Screening and review
# ---------------------------------------------------------------------------

def calgary_screening(session_id: str) -> dict:
    """Screen results against City-of-Calgary-style criteria.

    Velocity screen (3.0 m/s advisory / 4.0 m/s critical), storage
    classification (trap-low vs pond heuristics), and the criteria register.
    SCREENING ONLY — thresholds must be confirmed by the responsible engineer.
    """
    session = STORE.get(session_id)
    _require_results(session)
    cfg = dict(session.data.get("report_configuration", {}))
    crit = CalgaryCriteria(
        minor_release_rate_lps_ha=cfg.get("minor_release_rate_lps_ha"),
        trap_low_max_depth_m=cfg.get("trap_low_max_depth_m", 0.50),
        entrance_grade_margin_m=cfg.get("entrance_grade_margin_m", 0.30),
        pipe_advisory_velocity_mps=cfg.get("velocity_advisory", 3.0),
        pipe_critical_velocity_mps=cfg.get("velocity_threshold", 4.0),
        conduit_capacity_review_ratio=cfg.get("conduit_depth_ratio", 0.80),
        conduit_capacity_warning_ratio=cfg.get("conduit_capacity_warning_ratio", 0.95),
        continuity_review_pct=cfg.get("continuity_review", 0.50),
        continuity_warning_pct=cfg.get("continuity_warning", 1.00),
        special_link_limits=cfg.get("special_link_limits", {}),
        storage_classification=cfg.get("storage_classification", {}),
        outfall_classification=cfg.get("outfall_classification", {}),
    )
    integrity = execution_integrity_assessment(session.data["results"].get("metadata", {}))
    if not integrity["results_usable"]:
        return {
            "velocity_screen_flagged": _df_records(pd.DataFrame(), 30),
            "storage_classification": _df_records(pd.DataFrame(), 30),
            "criteria_register": _df_records(criteria_register(crit), 40),
            "status": "Not assessed - hydraulic routing solution invalid",
            "execution_integrity": integrity,
        }
    link_df = session.data["link_df"]
    node_df = session.data["node_df"]
    vel_col = next((c for c in link_df.columns if c.startswith("Peak Velocity")), None)
    lv = link_df[["Link ID", vel_col, "Depth Ratio"]].copy()
    lv["Screen"] = lv[vel_col].apply(
        lambda v: (f"CRITICAL > {crit.pipe_critical_velocity_mps:g}"
                   if v > crit.pipe_critical_velocity_mps else
                   (f"Advisory > {crit.pipe_advisory_velocity_mps:g}"
                    if v > crit.pipe_advisory_velocity_mps else "OK")))
    flagged = lv[lv["Screen"] != "OK"].sort_values(vel_col, ascending=False)
    storage = node_df[node_df["Type"].astype(str).str.lower() == "storage"].copy()
    storage_class = apply_storage_classification(storage, crit, "m") if not storage.empty else pd.DataFrame()
    return {
        "velocity_screen_flagged": _df_records(flagged, 30),
        "storage_classification": _df_records(storage_class, 30),
        "criteria_register": _df_records(criteria_register(crit), 40),
        "status": "Screening only — criteria applicability requires engineer confirmation.",
    }


def preliminary_design_review(session_id: str) -> dict:
    """Deterministic QA/QC findings register (topology, hydrology, screening)
    merged with the worker-vs-.rpt reconciliation findings (RPT-###)."""
    session = STORE.get(session_id)
    _require_results(session)
    inp_text = Path(session.data["inp_path"]).read_text(encoding="utf-8", errors="replace")
    findings = build_deterministic_findings(
        inp_text=inp_text, node_summary=session.data["node_df"],
        link_summary=session.data["link_df"], sub_summary=session.data["sub_df"],
        metadata=session.data["results"]["metadata"],
        simulation_completed=True,
        output_results_available=bool(session.data["results"]["metadata"].get("results_usable", True)))
    recon_findings = rr.reconciliation_findings(
        session.data.get("recon_links"), session.data.get("recon_nodes"),
        session.data.get("recon_continuity"))
    all_findings = list(findings) + list(recon_findings)
    session.data["findings"] = all_findings
    return {"findings": _df_records(findings_dataframe(all_findings), 60),
            "rpt_reconciliation": session.data.get("recon_summary", {})}


def get_reconciliation(session_id: str) -> dict:
    """Worker-vs-.rpt reconciliation detail: flagged links and continuity check.
    For flagged links, .rpt values are authoritative for screening."""
    session = STORE.get(session_id)
    _require_results(session)
    lr = session.data.get("recon_links")
    flagged = lr[lr["Overall Status"] != "OK"] if lr is not None and not lr.empty else pd.DataFrame()
    return {"summary": session.data.get("recon_summary", {}),
            "flagged_links": _df_records(flagged, 40),
            "continuity": _df_records(session.data.get("recon_continuity"), 5)}


# ---------------------------------------------------------------------------
# Scenarios and reporting
# ---------------------------------------------------------------------------

def run_scenario(session_id: str, scenario_name: str,
                 conduit_diameter_overrides: dict | str | None = None,
                 rainfall_multiplier: float | None = None) -> dict:
    """Clone the base model, apply controlled changes, re-simulate, compare.

    conduit_diameter_overrides: {"link_id": new_diameter_m}. The base model is
    never mutated; comparisons quote deterministic summary deltas.
    """
    import scenario_manager as sm
    session = STORE.get(session_id)
    _require_results(session)
    if isinstance(conduit_diameter_overrides, str) and conduit_diameter_overrides:
        conduit_diameter_overrides = json.loads(conduit_diameter_overrides)
    kwargs: dict[str, Any] = {}
    if conduit_diameter_overrides:
        kwargs["conduit_diameter_overrides"] = {str(k): float(v) for k, v in conduit_diameter_overrides.items()}
    if rainfall_multiplier is not None:
        kwargs["rainfall_multiplier"] = float(rainfall_multiplier)
    scen_id = f"scn_{len(session.data.setdefault('scenarios', [])) + 1}"
    definition = sm.ScenarioDefinition(scenario_id=scen_id, scenario_name=scenario_name, **kwargs)
    record = sm.run_scenario(session.data["inp_path"], definition,
                             work_dir=str(session.workdir / "scenarios"))
    base_record = sm.base_model_record(session.data["results"])
    session.data["scenarios"].append(record)
    comparison = sm.comparison_with_base(base_record, session.data["scenarios"])
    narrative = sm.deterministic_comparison_analysis(comparison)
    session.data["scenario_comparison"] = comparison
    keep = [c for c in comparison.columns if comparison[c].dtype != object or c in
            ("Scenario ID", "Scenario Name", "Simulation Status", "Velocity Link")]
    return {"scenario_id": scen_id, "comparison": _df_records(comparison[keep], 20),
            "deterministic_analysis": narrative[:6000]}


def attach_figure(session_id: str, image_base64: str, caption: str,
                  section: str = "results", figure_name: str = "") -> dict:
    """Attach a client-generated figure (PNG/JPEG, base64) to the session so
    generate_report embeds it in the AUDITED report instead of the client
    rebuilding the document itself.

    section: keyword matched against report Heading-1 titles (e.g. "results",
    "methodology", "site"); the figure is placed at the end of that section.
    Figures are labelled as client-attached illustrative material — they are
    not server-verified outputs. Limits: PNG or JPEG, 5 MB decoded.
    """
    session = STORE.get(session_id)
    try:
        blob = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"image_base64 is not valid base64: {exc}")
    if len(blob) > 5 * 1024 * 1024:
        raise ValueError("Figure exceeds the 5 MB limit.")
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    elif blob[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    else:
        raise ValueError("Only PNG or JPEG figures are accepted (magic-byte check failed).")
    figures = session.data.setdefault("figures", [])
    figure_id = f"FIG-{len(figures) + 1:02d}"
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (figure_name or figure_id))
    fig_dir = session.workdir / "figures"
    fig_dir.mkdir(exist_ok=True)
    path = fig_dir / f"{safe}.{ext}"
    path.write_bytes(blob)
    figures.append({"figure_id": figure_id, "path": str(path), "caption": caption.strip(),
                    "section": section.strip().lower() or "results", "source": "client-attached"})
    return {"figure_id": figure_id, "stored": path.name, "size_bytes": len(blob),
            "section": section, "attached_figures": [
                {"figure_id": f["figure_id"], "caption": f["caption"], "section": f["section"]}
                for f in figures],
            "next_step": "Call generate_report; the figure will be embedded with a labelled caption."}


_METADATA_FIELDS = {
    "client", "consultant", "consultant_file_no", "subdivision_no", "outline_plan_no",
    "development_permit_no", "design_storm", "prepared_by", "checked_by", "municipality",
    "contact_name", "contact_email", "legal_description", "construction_drawing_no",
    "development_agreement_no",
}
_NARRATIVE_FIELDS = {
    "introduction", "site_description", "design_objectives", "methodology",
    "applicable_criteria",
}


def set_report_details(session_id: str, details: dict | str) -> dict:
    """Store site-specific narrative and project metadata for generate_report.

    details keys — NARRATIVE (multi-line text; design_objectives lines become
    bullets): introduction, site_description, design_objectives, methodology,
    applicable_criteria. METADATA (single values): client, consultant,
    consultant_file_no, subdivision_no, outline_plan_no,
    development_permit_no, design_storm, prepared_by, checked_by,
    municipality, contact_name, contact_email, legal_description,
    construction_drawing_no, development_agreement_no.

    Repeated calls merge (later values win); pass an empty string to clear a
    key. Attribute provenance inside the text itself (model-derived vs
    user-supplied vs inferred) — the server stores it verbatim. For a site
    aerial/location image use attach_figure with section="site".
    """
    session = STORE.get(session_id)
    if isinstance(details, str):
        details = json.loads(details)
    if not isinstance(details, dict):
        raise ValueError("details must be a JSON object of field -> text.")
    unknown = sorted(set(details) - _METADATA_FIELDS - _NARRATIVE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown field(s) {unknown}. Narrative: {sorted(_NARRATIVE_FIELDS)}; "
                         f"metadata: {sorted(_METADATA_FIELDS)}.")
    store = session.data.setdefault("report_details", {})
    for key, value in details.items():
        text = str(value).strip()
        if text:
            store[key] = text
        else:
            store.pop(key, None)
    return {"session_id": session.id,
            "stored_narrative": sorted(k for k in store if k in _NARRATIVE_FIELDS),
            "stored_metadata": sorted(k for k in store if k in _METADATA_FIELDS),
            "next_step": "generate_report will include these details; readiness scoring reflects them."}


_REPORT_CONFIG_FIELDS = {
    "node_depth_ratio", "minimum_freeboard", "conduit_depth_ratio",
    "velocity_threshold", "velocity_advisory", "continuity_review",
    "continuity_warning", "suppress_empty_sections", "major_link_ids",
    "area_classification", "calgary_enabled", "minor_release_rate_lps_ha",
    "trap_low_max_depth_m", "entrance_grade_margin_m",
    "conduit_capacity_warning_ratio", "special_link_limits",
    "storage_classification", "outfall_classification", "checklist_overrides",
    "drawing_inventory", "applicable_reports",
}
_REPORT_CONFIG_LISTS = {"major_link_ids", "drawing_inventory", "applicable_reports"}
_REPORT_CONFIG_MAPS = {
    "area_classification", "special_link_limits", "storage_classification",
    "outfall_classification", "checklist_overrides",
}
_REPORT_CONFIG_BOOLS = {"suppress_empty_sections", "calgary_enabled"}


def set_report_configuration(session_id: str, configuration: dict | str) -> dict:
    """Set project-specific City of Calgary SWMR criteria and evidence inputs.

    Use this after upload and before generate_report. Supported configuration
    includes major_link_ids, project-specific flow limits, storage/outfall/area
    classifications, numerical screening thresholds, drawing_inventory,
    applicable_reports, and checklist_overrides. Repeated calls merge; JSON
    null removes a field. This configures deterministic screening and report
    completeness—it does not establish municipal acceptance or professional
    authentication.
    """
    session = STORE.get(session_id)
    if isinstance(configuration, str):
        configuration = json.loads(configuration)
    if not isinstance(configuration, dict):
        raise ValueError("configuration must be a JSON object.")
    unknown = sorted(set(configuration) - _REPORT_CONFIG_FIELDS)
    if unknown:
        raise ValueError(f"Unknown report configuration field(s): {unknown}. "
                         f"Supported: {sorted(_REPORT_CONFIG_FIELDS)}")
    normalized: dict[str, Any] = {}
    for key, value in configuration.items():
        if value is None:
            normalized[key] = None
        elif key in _REPORT_CONFIG_LISTS:
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"{key} must be a JSON array.")
            normalized[key] = tuple(str(x).strip() for x in value if str(x).strip())
        elif key in _REPORT_CONFIG_MAPS:
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be a JSON object.")
            if key == "special_link_limits":
                try:
                    normalized[key] = {str(k): float(v) for k, v in value.items()}
                except (TypeError, ValueError):
                    raise ValueError("special_link_limits values must be numeric.")
            else:
                normalized[key] = {str(k): str(v) for k, v in value.items()}
        elif key in _REPORT_CONFIG_BOOLS:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false.")
            normalized[key] = value
        else:
            if isinstance(value, bool):
                raise ValueError(f"{key} must be numeric or null.")
            try:
                normalized[key] = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be numeric or null.")
    stored = session.data.setdefault("report_configuration", {})
    for key, value in normalized.items():
        if value is None:
            stored.pop(key, None)
        else:
            stored[key] = value
    return {
        "session_id": session.id,
        "report_configuration": stored,
        "next_step": "Run Calgary screening/review as needed, then call generate_report.",
        "disclaimer": "Project criteria and classifications require responsible-engineer verification.",
    }


def generate_report(session_id: str, project_name: str, client: str = "",
                    consultant: str = "", prepared_by: str = "",
                    outline_plan_no: str = "",
                    include_model_appendix: bool = True) -> dict:
    """Generate the Calgary-style SWMR draft package (docx + audit zip).

    include_model_appendix (default True) reproduces the model input (.inp)
    and engine output (.rpt) as fixed-width listings in APPENDIX D, per the
    Calgary SWMR checklist; very long files are middle-truncated in the docx
    with the untruncated copies archived in the audit zip under model/.
    Returns download paths served by this Space at /files/{session_id}/{name}.
    The draft-readiness score honestly reflects missing project information.
    """
    from report_engine import ReportCriteria, ReportMetadata, generate_report_package
    session = STORE.get(session_id)
    _require_results(session)
    stored = dict(session.data.get("report_details", {}))
    meta_kwargs = {k: v for k, v in stored.items() if k in _METADATA_FIELDS}
    # Explicit arguments override stored details when provided.
    for key, value in (("client", client), ("consultant", consultant),
                       ("prepared_by", prepared_by), ("outline_plan_no", outline_plan_no)):
        if value:
            meta_kwargs[key] = value
    narrative = {k: v for k, v in stored.items() if k in _NARRATIVE_FIELDS}
    meta = ReportMetadata(project_name=project_name, **meta_kwargs)
    report_criteria = ReportCriteria(**dict(session.data.get("report_configuration", {})))
    model_listings = None
    if include_model_appendix:
        inp_p = Path(session.data["inp_path"])
        model_listings = {"inp_name": inp_p.name,
                          "inp_text": inp_p.read_text(encoding="utf-8", errors="replace")}
        execution_p = Path(session.data.get("execution_inp_path", inp_p))
        if execution_p != inp_p:
            model_listings.update({
                "execution_inp_name": execution_p.name,
                "execution_inp_text": execution_p.read_text(encoding="utf-8", errors="replace"),
            })
        rpt_p = (session.data["results"].get("metadata", {}) or {}).get("report_path")
        if rpt_p and Path(str(rpt_p)).exists():
            model_listings["rpt_name"] = Path(str(rpt_p)).name
            model_listings["rpt_text"] = Path(str(rpt_p)).read_text(encoding="utf-8", errors="replace")
    findings = session.data.get("findings") or []
    pkg = generate_report_package(
        metadata=meta, inp_sections=session.data["sections"],
        node_summary=session.data["node_df"], link_summary=session.data["link_df"],
        sub_summary=session.data["sub_df"],
        simulation_metadata=session.data["results"]["metadata"],
        criteria=report_criteria,
        result_db_bytes=session.data["db"].export_bytes(),
        preliminary_review_artifacts={
            "findings": findings, "status": "Preliminary",
            "manifest": {"rpt_reconciliation": session.data.get("recon_summary", {})},
        } if findings else None,
        attached_figures=session.data.get("figures") or None,
        narrative_sections=narrative or None,
        model_listings=model_listings,
        reconciliation={"links": session.data.get("recon_links"),
                        "summary": session.data.get("recon_summary", {})},
        model_identity={"inp_name": Path(session.data["inp_path"]).name,
                        "sha256": session.data["results"]["metadata"].get("model_sha256", "—"),
                        "execution_inp_name": session.data["results"]["metadata"].get("execution_model_filename"),
                        "execution_sha256": session.data["results"]["metadata"].get("execution_model_sha256"),
                        "legacy_defaults_normalized": session.data["results"]["metadata"].get("legacy_defaults_normalized", False),
                        "solver_option_substitutions": session.data["results"]["metadata"].get("solver_option_substitutions", []),
                        "session_id": session.id,
                        "run_id": session.data["results"]["metadata"].get("run_id", "—"),
                        "engine": "EPA SWMM / OpenSWMM 6 (crash-isolated worker, engine Rev 23.2)",
                        "status": ("Completed - results usable" if
                                   session.data["results"]["metadata"].get("results_usable", True)
                                   else "Completed - hydraulic results invalid")})
    outputs = session.workdir / "outputs"
    outputs.mkdir(exist_ok=True)
    files = {}
    for key, blob in pkg.items():
        if isinstance(blob, (bytes, bytearray)):
            name = pkg.get(f"{key}_name") if isinstance(pkg.get(f"{key}_name"), str) else f"{key}.bin"
            if key == "docx":
                name = f"{project_name.replace(' ', '_')}_SWMR_Draft.docx"
            elif key == "zip":
                name = f"{project_name.replace(' ', '_')}_SWMR_Package.zip"
            (outputs / name).write_bytes(blob)
            files[key] = f"/files/{session.id}/{name}"
    return {"files": files, "size_bytes": {k: len(v) for k, v in pkg.items() if isinstance(v, (bytes, bytearray))},
            "note": "Draft for engineering review — not an issued document."}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Callable[..., dict]] = {
    fn.__name__: fn for fn in [
        upload_model, run_simulation, list_sessions, close_session,
        get_node_results, get_link_results, get_subcatchment_results,
        get_timeseries, query_results, get_table_catalog,
        calgary_screening, preliminary_design_review, get_reconciliation,
        run_scenario, attach_figure, set_report_details, set_report_configuration,
        generate_report,
    ]
}
