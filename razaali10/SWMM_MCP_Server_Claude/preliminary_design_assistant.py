"""Rev23 preliminary design review and controlled-correction workflow.

Deterministic code identifies traceable model findings and applies only
engineer-approved edits. The LLM explains and prioritises findings; it does not
silently alter the model or determine municipal compliance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence
import hashlib
import json
import re

import pandas as pd

from ai_report_assistant import PROVIDERS, _call_provider, load_prompt
from scenario_manager import _split_sections, _join_sections, _data_tokens, _replace_tokens, _set_option

REVIEW_SYSTEM_PROMPT = load_prompt("preliminary_design_review_system.txt")


@dataclass
class DesignFinding:
    finding_id: str
    category: str
    severity: str
    finding_type: str
    object_type: str = "MODEL"
    object_id: str = "MODEL"
    rule_id: str = ""
    criterion_status: str = "Screening"
    deterministic_basis: str = ""
    recommended_action: str = ""
    proposed_parameter: str = ""
    proposed_value: Any = None
    units: str = ""
    engineer_decision: str = "Defer"
    resolution_status: str = "Open"
    reviewer_comment: str = ""
    ai_explanation: str = ""


def _rows(sections: Mapping[str, Sequence[str]], name: str) -> list[list[str]]:
    out: list[list[str]] = []
    for line in sections.get(name, []):
        parsed = _data_tokens(line)
        if parsed:
            out.append(parsed[0])
    return out


def _ids(sections: Mapping[str, Sequence[str]], names: Sequence[str]) -> set[str]:
    values: set[str] = set()
    for name in names:
        values.update(row[0] for row in _rows(sections, name) if row)
    return values


def _first_numeric(row: Mapping[str, Any], aliases: Sequence[str]) -> float | None:
    """Return the first explicitly available numeric value without converting missing data to zero."""
    for key in aliases:
        if key not in row:
            continue
        value = row.get(key)
        if value is None or value == "":
            continue
        parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.notna(parsed):
            return float(parsed)
    return None


def _records(df: pd.DataFrame | None, limit: int = 500) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    clean = df.head(limit).copy()
    clean = clean.where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


def build_deterministic_findings(
    *,
    inp_text: str,
    node_summary: pd.DataFrame | None = None,
    link_summary: pd.DataFrame | None = None,
    sub_summary: pd.DataFrame | None = None,
    metadata: Mapping[str, Any] | None = None,
    simulation_completed: bool = False,
    output_results_available: bool = False,
    flood_threshold: float = 0.0,
    depth_ratio_threshold: float = 0.85,
    velocity_threshold: float = 3.0,
) -> list[dict[str, Any]]:
    """Create a conservative, traceable preliminary-review register."""
    _, sections = _split_sections(inp_text)
    findings: list[DesignFinding] = []
    counter = 1

    def add(category: str, severity: str, finding_type: str, basis: str, action: str,
            object_type: str = "MODEL", object_id: str = "MODEL", rule_id: str = "",
            proposed_parameter: str = "", proposed_value: Any = None, units: str = "",
            criterion_status: str = "Screening") -> None:
        nonlocal counter
        findings.append(DesignFinding(
            finding_id=f"PDA-{counter:03d}", category=category, severity=severity,
            finding_type=finding_type, object_type=object_type, object_id=str(object_id),
            rule_id=rule_id, criterion_status=criterion_status,
            deterministic_basis=basis, recommended_action=action,
            proposed_parameter=proposed_parameter, proposed_value=proposed_value, units=units,
        ))
        counter += 1

    # Completeness and topology.
    node_ids = _ids(sections, ["JUNCTIONS", "STORAGE", "OUTFALLS", "DIVIDERS"])
    link_rows = []
    for sec in ["CONDUITS", "PUMPS", "ORIFICES", "WEIRS", "OUTLETS"]:
        for row in _rows(sections, sec):
            if len(row) >= 3:
                link_rows.append((sec, row[0], row[1], row[2]))
    referenced_nodes = {x for _, _, a, b in link_rows for x in (a, b)}
    # SWMM matches object IDs case-insensitively, so an endpoint that
    # differs from a defined node only by letter case still routes in the
    # engine. Treat exact-case misses with a case-insensitive fallback:
    # genuine misses stay Critical; case-only mismatches are a Medium
    # naming-consistency finding (they break exact-match post-processing
    # and GIS joins even though the simulation runs).
    node_ids_casefold = {str(n).casefold(): n for n in node_ids}
    for nid in sorted(referenced_nodes - node_ids):
        matched = node_ids_casefold.get(str(nid).casefold())
        if matched is not None:
            add("Topology", "Medium", "ID case inconsistency",
                f"Link endpoint '{nid}' matches defined node '{matched}' only when letter case is ignored. "
                "SWMM resolves the connection, but exact-match tools (GIS joins, scripts, result queries) will not.",
                f"Rename the link endpoint or the node so both use '{matched}' consistently.", "NODE", nid)
        else:
            add("Topology", "Critical", "Invalid reference", f"Node '{nid}' is referenced by a link but is not defined.",
                "Define the node or correct the link endpoint before design use.", "NODE", nid)

    connected = referenced_nodes
    for nid in sorted(node_ids - connected):
        # Outfalls/storage-only models can legitimately have simple topology, so advisory.
        add("Topology", "Advisory", "Connectivity review", f"Node '{nid}' is not referenced by a hydraulic link.",
            "Confirm whether the node is intentionally isolated or the model connection is incomplete.", "NODE", nid)

    sub_rows = _rows(sections, "SUBCATCHMENTS")
    sub_names = {r[0] for r in sub_rows}
    sub_names_casefold = {str(s).casefold(): s for s in sub_names}
    for row in sub_rows:
        if len(row) >= 3 and row[2] not in node_ids and row[2] not in sub_names:
            outlet = str(row[2])
            matched = node_ids_casefold.get(outlet.casefold()) or sub_names_casefold.get(outlet.casefold())
            if matched is not None:
                add("Hydrology", "Medium", "ID case inconsistency",
                    f"Subcatchment '{row[0]}' outlet '{outlet}' matches defined object '{matched}' only when letter case is ignored. "
                    "SWMM resolves the routing, but exact-match tools will not.",
                    f"Rename the outlet reference or the object so both use '{matched}' consistently.", "SUBCATCHMENT", row[0])
            else:
                add("Hydrology", "Critical", "Invalid outlet", f"Subcatchment '{row[0]}' routes to undefined outlet '{outlet}'.",
                    "Correct the outlet reference.", "SUBCATCHMENT", row[0])
        if len(row) >= 7:
            try:
                area, imperv, width, slope = float(row[3]), float(row[4]), float(row[5]), float(row[6])
                if area <= 0:
                    add("Hydrology", "High", "Input review", f"Area is {area}.", "Enter a positive drainage area.", "SUBCATCHMENT", row[0], proposed_parameter="area")
                if imperv < 0 or imperv > 100:
                    add("Hydrology", "Critical", "Input range", f"Imperviousness is {imperv}%.", "Set imperviousness within 0–100%.", "SUBCATCHMENT", row[0], proposed_parameter="imperviousness", units="%")
                elif imperv >= 95:
                    add("Hydrology", "Moderate", "Sensitivity review", f"Imperviousness is {imperv}%.", "Confirm land-use basis and test sensitivity.", "SUBCATCHMENT", row[0])
                if width <= 0:
                    add("Hydrology", "High", "Input review", f"Width is {width}.", "Enter and document a representative subcatchment width.", "SUBCATCHMENT", row[0], proposed_parameter="width")
                if slope <= 0:
                    add("Hydrology", "High", "Input review", f"Slope is {slope}%.", "Confirm grading and enter a positive slope.", "SUBCATCHMENT", row[0], proposed_parameter="slope", units="%")
            except Exception:
                pass

    # Options and rainfall.
    options = {r[0].upper(): r[1] for r in _rows(sections, "OPTIONS") if len(r) >= 2}
    if "FLOW_UNITS" not in options:
        add("Simulation setup", "High", "Missing option", "FLOW_UNITS is not explicitly defined.", "Define and verify the model unit system.")
    report_step = options.get("REPORT_STEP", "")
    wet_step = options.get("WET_STEP", "")
    if not report_step:
        add("Simulation setup", "Moderate", "Missing option", "REPORT_STEP is not explicitly defined.", "Set a reporting timestep appropriate for the event and control response.", proposed_parameter="REPORT_STEP")
    if not wet_step:
        add("Simulation setup", "Moderate", "Missing option", "WET_STEP is not explicitly defined.", "Set and document the wet-weather timestep.", proposed_parameter="WET_STEP")
    rain_gages = _rows(sections, "RAINGAGES")
    time_series = _rows(sections, "TIMESERIES")
    if not rain_gages:
        add("Rainfall", "Critical", "Missing rainfall", "No [RAINGAGES] records were identified.", "Add and verify the applicable design rainfall.")
    if rain_gages and not time_series:
        add("Rainfall", "High", "Rainfall source review", "Rain gages exist but no internal [TIMESERIES] records were identified.", "Confirm external rainfall files and package them with the model.")

    # Deterministic result screening. Result-based findings are permitted only
    # when a successful simulation and parsed output tables are explicitly available.
    results_ready = bool(simulation_completed and output_results_available)
    if results_ready and node_summary is not None and not node_summary.empty:
        for _, r in node_summary.iterrows():
            row = r.to_dict()
            nid = str(row.get("Node ID", row.get("ID", "")))
            flooding = _first_numeric(row, ["Peak Flooding (m³/s)", "Peak Flooding", "Max Flooding", "Maximum Flooding"] )
            if flooding is not None and flooding > flood_threshold:
                add("Hydraulics", "Critical", "Flooding", f"Peak model flooding is {flooding:.6g}.", "Review HGL, rim elevation, downstream boundary, and design alternatives.", "NODE", nid, "CAL-HYD-FLOOD", units=str(metadata.get("flow_units", "") if metadata else ""))

    if results_ready and link_summary is not None and not link_summary.empty:
        for _, r in link_summary.iterrows():
            row = r.to_dict()
            lid = str(row.get("Link ID", row.get("ID", "")))
            vel = _first_numeric(row, ["Peak Velocity (m/s)", "Max Velocity", "Maximum Velocity", "Velocity"] )
            ratio = _first_numeric(row, ["Depth Ratio", "Max/Full Depth", "Maximum Depth Ratio"] )
            if vel is not None and vel > velocity_threshold:
                add("Hydraulics", "High", "Velocity screening", f"Maximum modelled velocity is {vel:.4g}, above the configured {velocity_threshold:g} screening value.", "Confirm pipe/channel material, erosion protection, energy dissipation, and applicable criterion.", "LINK", lid, "CAL-HYD-VEL", units="model units")
            if ratio is not None and ratio >= depth_ratio_threshold:
                add("Hydraulics", "High", "Depth-ratio screening", f"Maximum modelled depth ratio is {ratio:.4g}, at or above the configured {depth_ratio_threshold:g} screening value.", "Review capacity, HGL, surcharge duration, and downstream boundary conditions.", "LINK", lid, "CAL-HYD-DEPTH")

    if results_ready and sub_summary is not None and not sub_summary.empty:
        zero_runoff_tolerance = 1e-9
        for _, r in sub_summary.iterrows():
            row = r.to_dict()
            sid = str(row.get("Sub ID", row.get("Subcatchment", row.get("ID", ""))))
            runoff = _first_numeric(row, ["Peak Runoff (m³/s)", "Peak Runoff", "Peak Runoff (cfs)", "Peak Runoff (L/s)"] )
            if runoff is not None and abs(runoff) <= zero_runoff_tolerance:
                add("Hydrology", "Moderate", "Zero runoff", "Peak runoff is explicitly reported as zero for the completed simulation.", "Confirm rainfall assignment, infiltration, routing, and subcatchment activation.", "SUBCATCHMENT", sid)

    # Missing design criteria are never silently replaced by generic standards.
    add("Criteria", "High", "Missing project criterion", "Project-specific allowable release rate is not established by the model alone.", "Enter the approved release criterion and source before evaluating outlet compliance.", rule_id="CAL-MIN-001", criterion_status="Not established")
    if _rows(sections, "STORAGE"):
        add("Storage", "High", "Missing project criterion", "Approved pond/storage HWL, freeboard, emergency spill elevation, and classification are not established by the model alone.", "Enter the approved storage criteria and source before concluding performance.", rule_id="CAL-POND-001", criterion_status="Not established")

    return [asdict(x) for x in findings]


def findings_dataframe(findings: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    columns = [f.name for f in DesignFinding.__dataclass_fields__.values()]
    df = pd.DataFrame(list(findings))
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def build_review_context(
    *,
    inp_name: str,
    inp_text: str,
    findings: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    criteria: Mapping[str, Any] | None = None,
    node_summary: pd.DataFrame | None = None,
    link_summary: pd.DataFrame | None = None,
    sub_summary: pd.DataFrame | None = None,
    simulation_completed: bool = False,
    output_results_available: bool = False,
    review_mode: str = "Input and simulation-output review",
) -> dict[str, Any]:
    _, sections = _split_sections(inp_text)
    output_ready = bool(simulation_completed and output_results_available)
    return {
        "review_mode": review_mode,
        "availability": {
            "model_input_available": bool(inp_text),
            "simulation_completed": bool(simulation_completed),
            "output_results_available": bool(output_results_available),
            "result_based_review_authorized": output_ready,
        },
        "model": {
            "name": inp_name,
            "sha256": hashlib.sha256(inp_text.encode("utf-8")).hexdigest(),
            "section_counts": {k: len(_rows(sections, k)) for k in sections},
        },
        "metadata": dict(metadata or {}),
        "criteria": dict(criteria or {}),
        "simulation_results": {
            "node_summary": _records(node_summary) if output_ready else [],
            "link_summary": _records(link_summary) if output_ready else [],
            "subcatchment_summary": _records(sub_summary) if output_ready else [],
        },
        "result_table_counts": {
            "nodes": 0 if node_summary is None else int(len(node_summary)),
            "links": 0 if link_summary is None else int(len(link_summary)),
            "subcatchments": 0 if sub_summary is None else int(len(sub_summary)),
        },
        "deterministic_findings": list(findings),
        "allowed_ai_actions": ["explain", "prioritise", "identify missing information", "propose review steps", "propose structured edits for engineer approval"],
        "prohibited_ai_actions": ["claim compliance", "silently modify the model", "invent criteria", "certify design", "approve a preferred design", "convert missing values to zero"],
    }


def ai_review_findings(*, provider_name: str, api_key: str, model: str, review_context: Mapping[str, Any], user_request: str = "") -> str:
    request = f"""Review the preliminary SWMM model using only the deterministic context below.
Prioritise issues, explain likely engineering implications, identify missing criteria,
and propose conservative next actions. Do not recalculate results or claim compliance.

USER_REQUEST:
{user_request or 'Provide a complete preliminary design review.'}

DETERMINISTIC_CONTEXT:
{json.dumps(review_context, ensure_ascii=False, default=str)}

Return concise professional Markdown with these headings:
1. Review summary
2. Priority findings
3. Modelling corrections for engineer consideration
4. Design-criteria confirmations required
5. Recommended path to scenario analysis
"""
    return _call_provider(provider_name, api_key, model, [{"role": "user", "content": request}], REVIEW_SYSTEM_PROMPT, max_tokens=3600)


def apply_approved_changes(inp_text: str, findings: Sequence[Mapping[str, Any]], edited_values: Mapping[str, Any] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Apply a deliberately limited set of approved, structured edits."""
    preamble, sections = _split_sections(inp_text)
    log: list[dict[str, Any]] = []
    edited_values = dict(edited_values or {})

    def update_named(section: str, object_id: str, token_index: int, value: Any, finding_id: str, parameter: str):
        lines = sections.get(section, [])
        changed = False
        old = None
        new_lines = []
        for line in lines:
            parsed = _data_tokens(line)
            if parsed and parsed[0][0].casefold() == object_id.casefold() and len(parsed[0]) > token_index:
                tokens, comment = parsed
                old = tokens[token_index]
                tokens[token_index] = str(value)
                line = _replace_tokens(line, tokens, comment)
                changed = True
            new_lines.append(line)
        sections[section] = new_lines
        log.append({"finding_id": finding_id, "object_id": object_id, "parameter": parameter, "old_value": old, "new_value": value, "applied": changed})

    for f in findings:
        if str(f.get("engineer_decision", "")).lower() != "accept":
            continue
        fid = str(f.get("finding_id", ""))
        parameter = str(f.get("proposed_parameter", ""))
        value = edited_values.get(fid, f.get("proposed_value"))
        oid = str(f.get("object_id", ""))
        otype = str(f.get("object_type", "")).upper()
        if value in (None, "") or not parameter:
            log.append({"finding_id": fid, "object_id": oid, "parameter": parameter, "applied": False, "note": "No structured value supplied; retained as an accepted review action only."})
            continue
        if otype == "SUBCATCHMENT":
            idx = {"area": 3, "imperviousness": 4, "width": 5, "slope": 6}.get(parameter)
            if idx is not None:
                update_named("SUBCATCHMENTS", oid, idx, value, fid, parameter)
                continue
        if otype == "MODEL" and parameter.upper() in {"REPORT_STEP", "WET_STEP", "ROUTING_STEP", "END_DATE", "END_TIME"}:
            sections["OPTIONS"] = _set_option(sections.get("OPTIONS", []), parameter.upper(), str(value))
            log.append({"finding_id": fid, "object_id": "MODEL", "parameter": parameter.upper(), "new_value": value, "applied": True})
            continue
        log.append({"finding_id": fid, "object_id": oid, "parameter": parameter, "new_value": value, "applied": False, "note": "Parameter is not yet supported by the controlled correction engine."})
    return _join_sections(preamble, sections), log


def review_manifest(*, original_name: str, reviewed_name: str, original_text: str, reviewed_text: str, findings: Sequence[Mapping[str, Any]], change_log: Sequence[Mapping[str, Any]], status: str) -> dict[str, Any]:
    return {
        "workflow": "Rev23 Preliminary Design Assistant",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "original_model": original_name,
        "reviewed_model": reviewed_name,
        "original_sha256": hashlib.sha256(original_text.encode("utf-8")).hexdigest(),
        "reviewed_sha256": hashlib.sha256(reviewed_text.encode("utf-8")).hexdigest(),
        "review_status": status,
        "finding_counts": pd.Series([f.get("severity", "") for f in findings]).value_counts().to_dict() if findings else {},
        "decision_counts": pd.Series([f.get("engineer_decision", "") for f in findings]).value_counts().to_dict() if findings else {},
        "change_log": list(change_log),
    }
