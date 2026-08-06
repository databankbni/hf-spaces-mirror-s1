"""Deterministic Calgary SWMR criteria helpers.

The rules in this module are deliberately transparent and configurable. They are
screening/default values, not a substitute for current City direction, an
approved SMDP/MDP, or professional engineering judgement.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass
class CalgaryCriteria:
    profile_name: str = "City of Calgary SWMR"
    source_manual: str = "City of Calgary Stormwater Management & Design Manual (2011)"
    manual_status: str = "Historical baseline - verify current amendments"
    minor_release_rate_lps_ha: float | None = None
    trap_low_max_depth_m: float = 0.50
    entrance_grade_margin_m: float = 0.30
    pipe_advisory_velocity_mps: float = 3.0
    pipe_critical_velocity_mps: float = 4.0
    conduit_capacity_review_ratio: float = 0.80
    conduit_capacity_warning_ratio: float = 0.95
    continuity_review_pct: float = 0.50
    continuity_warning_pct: float = 1.00
    depth_velocity_curve: tuple[tuple[float, float], ...] = (
        (0.5, 0.80), (1.0, 0.32), (2.0, 0.21), (3.0, 0.09)
    )
    special_link_limits: dict[str, float] = field(default_factory=dict)
    storage_classification: dict[str, str] = field(default_factory=dict)
    outfall_classification: dict[str, str] = field(default_factory=dict)


def infer_design_event(rain_gages: list[str], fallback: str = "Model design event") -> tuple[str, str]:
    names = [str(x) for x in rain_gages if str(x).strip()]
    for name in names:
        normalized = name.replace("_", " ").replace("-", " ")
        duration = re.search(r"(\d+(?:\.\d+)?)\s*h", normalized, re.I)
        return_period = re.search(r"(?:1\s*[:/]\s*)?(\d+)\s*y", normalized, re.I)
        if duration and return_period:
            return (
                f"Calgary {duration.group(1)}-hour, 1:{return_period.group(1)}-year design storm",
                f"Inferred from rain-gage name '{name}'; confirm before issue.",
            )
    return fallback, "Entered by user or retained from model metadata; confirm before issue."


def permissible_overland_depth(velocity_mps: float, curve: tuple[tuple[float, float], ...]) -> float | None:
    """Linearly interpolate the Alberta/Calgary street depth-velocity envelope."""
    try:
        v = float(velocity_mps)
    except (TypeError, ValueError):
        return None
    pts = sorted((float(x), float(y)) for x, y in curve)
    if not pts:
        return None
    if v <= pts[0][0]:
        return pts[0][1]
    if v > pts[-1][0]:
        return pts[-1][1]
    for (v1, d1), (v2, d2) in zip(pts[:-1], pts[1:]):
        if v1 <= v <= v2:
            f = (v - v1) / (v2 - v1)
            return d1 + f * (d2 - d1)
    return None


def classify_overland(depth_m: float, velocity_mps: float, curve: tuple[tuple[float, float], ...]) -> tuple[str, float | None]:
    allowed = permissible_overland_depth(velocity_mps, curve)
    if allowed is None:
        return "Review - criterion unavailable", None
    d = float(depth_m or 0.0)
    ratio = d / allowed if allowed > 0 else math.inf
    if ratio <= 0.90:
        return "Screens within depth-velocity criterion", allowed
    if ratio <= 1.00:
        return "Screens within criterion - near limit", allowed
    return "Exceeds depth-velocity criterion", allowed


def manning_full_capacity_circular(diameter: float, slope: float, n: float, unit_system: str) -> float | None:
    """Full-flow Manning capacity for a circular conduit in model-native flow units.

    SI result: m3/s. US customary result: cfs.
    """
    try:
        d, s, rough = float(diameter), float(slope), float(n)
    except (TypeError, ValueError):
        return None
    if d <= 0 or s <= 0 or rough <= 0:
        return None
    area = math.pi * d * d / 4.0
    radius = d / 4.0
    coefficient = 1.0 if unit_system.upper().startswith("SI") else 1.486
    return coefficient / rough * area * radius ** (2.0 / 3.0) * math.sqrt(s)


def build_minor_system_capacity_table(link_table: pd.DataFrame, unit_system: str, flow_unit: str, length_unit: str, criteria: CalgaryCriteria) -> pd.DataFrame:
    if link_table is None or link_table.empty:
        return pd.DataFrame()
    df = link_table.copy()
    if "Model Type" in df:
        df = df[df["Model Type"].astype(str).str.lower().eq("conduit")]
    if "Shape" in df:
        df = df[df["Shape"].astype(str).str.upper().eq("CIRCULAR")]
    diam_col = next((c for c in df.columns if c.startswith("Diameter / Geom1") or c.startswith("Diameter (")), None)
    flow_col = next((c for c in df.columns if c.startswith("Peak Flow (")), None)
    length_col = next((c for c in df.columns if c.startswith("Length (")), None)
    if not all([diam_col, flow_col]):
        return pd.DataFrame()
    rows = []
    for _, r in df.iterrows():
        slope = pd.to_numeric(r.get("Slope (ft/ft)", r.get("Slope", math.nan)), errors="coerce")
        # The model table may not include slope. Calculate from offsets/inverts only when explicitly available.
        cap = manning_full_capacity_circular(r.get(diam_col), slope, r.get("Manning n"), unit_system) if pd.notna(slope) else None
        peak = pd.to_numeric(r.get(flow_col), errors="coerce")
        modelled_depth_ratio = pd.to_numeric(r.get("Depth Ratio"), errors="coerce")
        capacity_ratio = float(peak / cap) if cap and pd.notna(peak) else math.nan
        if pd.notna(capacity_ratio):
            if capacity_ratio >= criteria.conduit_capacity_warning_ratio:
                status = "Warning - limited calculated capacity"
            elif capacity_ratio >= criteria.conduit_capacity_review_ratio:
                status = "Review calculated capacity"
            else:
                status = "Pass calculated capacity screening"
            capacity_basis = "Manning full-flow capacity"
        elif pd.notna(modelled_depth_ratio):
            if modelled_depth_ratio >= criteria.conduit_capacity_warning_ratio:
                status = "Warning - high modelled depth ratio"
            elif modelled_depth_ratio >= criteria.conduit_capacity_review_ratio:
                status = "Review modelled depth ratio"
            else:
                status = "Below depth-ratio screening threshold"
            capacity_basis = "Full-flow capacity not calculated"
        else:
            status = "Not assessed - missing capacity and depth ratio"
            capacity_basis = "Insufficient data"
        rows.append({
            "Segment": r.get("Link ID"), "From": r.get("From Node"), "To": r.get("To Node"),
            f"Diameter ({length_unit})": r.get(diam_col), f"Length ({length_unit})": r.get(length_col) if length_col else None,
            "Manning n": r.get("Manning n"), f"Routed Flow ({flow_unit})": peak,
            f"Full-Flow Capacity ({flow_unit})": cap,
            "Calculated Capacity Ratio": capacity_ratio if pd.notna(capacity_ratio) else None,
            "Modelled Depth Ratio": modelled_depth_ratio if pd.notna(modelled_depth_ratio) else None,
            f"Spare Capacity ({flow_unit})": (cap - peak) if cap and pd.notna(peak) else None,
            "Assessment Basis": capacity_basis,
            "Status": status,
        })
    return pd.DataFrame(rows)


def build_overland_compliance_table(overland: pd.DataFrame, criteria: CalgaryCriteria, flow_unit: str, length_unit: str, velocity_unit: str) -> pd.DataFrame:
    if overland is None or overland.empty:
        return pd.DataFrame()
    flow_col = next((c for c in overland.columns if c.startswith("Peak Flow (")), None)
    depth_col = next((c for c in overland.columns if c.startswith("Peak Depth (")), None)
    vel_col = next((c for c in overland.columns if c.startswith("Peak Velocity (")), None)
    rows = []
    for _, r in overland.iterrows():
        d = pd.to_numeric(r.get(depth_col), errors="coerce") if depth_col else math.nan
        v = pd.to_numeric(r.get(vel_col), errors="coerce") if vel_col else math.nan
        status, permitted = classify_overland(d, v, criteria.depth_velocity_curve) if pd.notna(d) and pd.notna(v) else ("Review - missing depth/velocity", None)
        link_id = str(r.get("Link ID", ""))
        special_limit = criteria.special_link_limits.get(link_id)
        special_status = ""
        if special_limit is not None and flow_col:
            q = pd.to_numeric(r.get(flow_col), errors="coerce")
            special_status = "Pass" if pd.notna(q) and q <= special_limit else "Exceeds project-specific flow limit"
        rows.append({
            "Segment": link_id, "From": r.get("From Node"), "To": r.get("To Node"),
            f"Peak Flow ({flow_unit})": r.get(flow_col) if flow_col else None,
            f"Peak Depth ({length_unit})": d, f"Peak Velocity ({velocity_unit})": v,
            f"Permissible Depth ({length_unit})": permitted, "Depth-Velocity Status": status,
            f"Special Flow Limit ({flow_unit})": special_limit, "Special Limit Status": special_status,
            "Spill Active": "Yes" if ("spill" in link_id.lower() and pd.to_numeric(r.get(flow_col), errors="coerce") > 0) else "No",
        })
    return pd.DataFrame(rows)


def apply_storage_classification(storage_table: pd.DataFrame, criteria: CalgaryCriteria, length_unit: str) -> pd.DataFrame:
    if storage_table is None or storage_table.empty:
        return pd.DataFrame()
    df = storage_table.copy()
    depth_col = next((c for c in df.columns if c.startswith("Time-Series Peak Depth") or c.startswith("Reported Peak Depth")), None)
    max_col = next((c for c in df.columns if c.startswith("Maximum Depth")), None)
    classes, statuses, margins = [], [], []
    for _, r in df.iterrows():
        sid = str(r.get("Storage ID", ""))
        cls = criteria.storage_classification.get(sid)
        if not cls:
            s = sid.lower()
            if "storage" in s:
                cls = "Street trap low / surface storage"
            elif s.startswith("cb"):
                cls = "Catchbasin ponding storage"
            elif s.startswith("sub"):
                cls = "Private-site / routing storage"
            else:
                cls = "Unclassified storage"
        peak = pd.to_numeric(r.get(depth_col), errors="coerce") if depth_col else math.nan
        maxd = pd.to_numeric(r.get(max_col), errors="coerce") if max_col else math.nan
        margin = maxd - peak if pd.notna(maxd) and pd.notna(peak) else math.nan
        ratio = peak / maxd if pd.notna(maxd) and maxd > 0 and pd.notna(peak) else math.nan
        if cls.startswith("Street trap"):
            # Trap-low criterion (0.5 m ponding, Alberta Environment 1999) is an
            # established register entry, so a screening verdict is supportable.
            if pd.isna(peak): status = "Not assessed - missing peak depth"
            elif peak > criteria.trap_low_max_depth_m: status = "Exceeds trap-low depth criterion"
            elif peak >= 0.95 * criteria.trap_low_max_depth_m: status = "Screens below trap-low criterion - limited margin"
            else: status = "Screens below trap-low depth criterion"
        else:
            # No facility classification, design HWL, required freeboard, or
            # release/spill criterion is available from the model alone, so a
            # Pass verdict is unsupportable here (deterministic rule): report
            # the modelled utilisation and return Not assessed for compliance.
            if pd.isna(ratio): status = "Not assessed - unclassified or incomplete"
            elif ratio >= 1.0: status = "Exceeds modelled depth - flag for review"
            elif ratio >= 0.90: status = "Near modelled capacity - review"
            else: status = "Within modelled depth - compliance Not assessed (criteria not established)"
        classes.append(cls); statuses.append(status); margins.append(margin)
    df.insert(1, "Calgary Storage Classification", classes)
    df[f"Modelled Depth Margin ({length_unit})"] = margins  # model quantity, NOT regulatory freeboard
    df["Calgary Status"] = statuses
    return df


def criteria_register(criteria: CalgaryCriteria) -> pd.DataFrame:
    rows = [
        ("CAL-GEN-001", "Source manual", criteria.source_manual, criteria.manual_status, "Verify current City amendments"),
        ("CAL-MIN-001", "Minor-system release rate", criteria.minor_release_rate_lps_ha, "Project-specific", "L/s/ha"),
        ("CAL-MAJ-001", "Street depth-velocity envelope", json.dumps(criteria.depth_velocity_curve), "Calgary/Alberta reference curve", "m/s vs m"),
        ("CAL-TRL-001", "Trap-low maximum ponding depth", criteria.trap_low_max_depth_m, "Configurable default", "m"),
        ("CAL-TRL-002", "Entrance grade margin", criteria.entrance_grade_margin_m, "Configurable default", "m"),
        ("CAL-MIN-002", "Conduit capacity review ratio", criteria.conduit_capacity_review_ratio, "Screening", "fraction"),
        ("CAL-MIN-003", "Conduit capacity warning ratio", criteria.conduit_capacity_warning_ratio, "Screening", "fraction"),
        ("CAL-QA-001", "Continuity review threshold", criteria.continuity_review_pct, "Screening", "%"),
        ("CAL-QA-002", "Continuity warning threshold", criteria.continuity_warning_pct, "Screening", "%"),
    ]
    return pd.DataFrame(rows, columns=["Rule ID", "Criterion", "Value", "Rule Status", "Units / Note"])


def build_llm_report_context(*, metadata: dict[str, Any], criteria: CalgaryCriteria, findings: list[str], tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    compact_tables = {}
    for name, df in tables.items():
        if df is not None and not df.empty:
            compact_tables[name] = df.head(30).where(pd.notna(df), None).to_dict(orient="records")
    return {
        "task": "Draft a City of Calgary stormwater management report narrative for professional review.",
        "metadata": metadata,
        "approved_criteria": asdict(criteria),
        "deterministic_findings": findings,
        "verified_tables": compact_tables,
        "interpretation_controls": {
            "minor_system_primary_metric": "modelled depth ratio unless a calculated full-flow capacity is present",
            "full_flow_capacity_available": bool("minor_system" in compact_tables and any(r.get("Full-Flow Capacity (m³/s)") is not None or r.get("Full-Flow Capacity (cfs)") is not None for r in compact_tables.get("minor_system", []))),
            "generic_storage_freeboard_screening_allowed": False,
            "storm_name_verified": False,
            "model_input_output_overall_status": next((r.get("Status") for r in compact_tables.get("swmr_checklist", []) if r.get("Item") == "SWMR-17"), "Not assessed"),
            "allowed_conclusions": {"adequate": False, "compliant": False, "safe": False, "effective": False, "approved": False},
        },
        "preferred_wording": {
            "minor_system": "Use 'modelled depth ratio' when full-flow capacity is unavailable.",
            "storage": "Use 'remaining depth margin' for maximum ponding-depth criteria.",
            "event": "State that the design-event name is inferred when not independently verified.",
            "outfalls": "Report modelled flows and state that downstream capacity requires confirmation.",
            "model_documentation": "Distinguish digital package completeness from report appendix, schematic, drawing reconciliation, and authenticated-file completeness.",
        },
        "constraints": [
            "Do not change or recalculate numerical results.",
            "Do not claim City approval or professional certification.",
            "Identify inferred, project-specific, historical, and unverified criteria.",
            "Use 'not provided' where project facts are missing.",
            "Distinguish pass, warning, information gap, and professional judgement.",
            "Do not use adequate, compliant, safe, effective, acceptable, or approved unless deterministic verified criteria authorize that wording.",
            "Use the Calgary SWMR completeness register and state all missing or partial mandatory items.",
            "Never call modelled depth ratio capacity used unless calculated full-flow capacity is present.",
            "Do not apply generic junction freeboard screening to storage nodes.",
        ],
    }


CALGARY_LLM_SYSTEM_PROMPT = """You are a Calgary stormwater report drafting assistant.
Use only the verified structured data, deterministic findings, approved Project Criteria Register, and Calgary SWMR Completeness Register supplied by the application.
Never calculate or modify hydraulic values. Never invent project facts. Never describe a screening threshold as a current City requirement unless its rule status is verified.

ENGINEERING INTERPRETATION RULES
1. Do not describe the model, system, infrastructure, design, or results as adequate, compliant, safe, effective, acceptable, or approved unless the deterministic compliance engine explicitly returns that conclusion for the applicable verified criterion.
2. Do not apply generic junction freeboard or depth-ratio criteria to storage nodes. Use the Calgary storage classification, adopted maximum ponding depth, remaining depth margin, utilization, spill elevation, and Calgary status fields.
3. For active spill links, report the modeled peak flow, depth, velocity, and deterministic depth-velocity screening result. Also require confirmation of grading continuity, route containment, public safety, erosion, downstream impacts, and receiving-system capacity.
4. Do not state that outfalls manage flow effectively or have adequate receiving capacity. Report only modeled flow, depth, flooding, boundary type, and verified downstream criteria.
5. When full-flow pipe capacity is unavailable, do not describe conduit depth ratio as full capacity utilization, spare capacity, or hydraulic capacity. Call it modeled depth ratio.
6. Prioritize approved project-specific criteria, applicable MDP/SMDP/pond-report/prior-SWMR criteria, verified current City requirements, historical manual criteria, then user-defined screening thresholds.
7. Clearly distinguish deterministic results, screening results, project-specific requirements, historical reference criteria, inferred information, missing information, and professional judgement.
8. Do not invent project facts, capacities, material properties, downstream conditions, grading information, or compliance conclusions.
9. Where criteria are missing or unverified, use wording such as 'requires confirmation', 'screening only', 'not established from the available data', or 'cannot be concluded from the model results alone'.
10. The generated text is an engineering draft for professional review and must not be presented as final certification or municipal approval.

CALGARY SWMR CHECKLIST RULES
Use the completeness register when drafting. Do not omit a checklist subject merely because data are unavailable; state what is missing and what must be provided. For each material conclusion, identify supporting report tables, figures, model results, approved criteria, or source documents. Do not state that the SWMR is complete when mandatory items are Missing, Partially complete, or Require professional confirmation. Highlight unresolved issues, departures, missing project data, drawing gaps, and unverified downstream conditions in the executive summary and Outstanding Information and Actions section. Distinguish model-derived information from drawing-, survey-, project-, and professionally-confirmed information.

Draft clear consultant-quality narrative for professional review. Do not certify compliance or approval.
"""
