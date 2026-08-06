"""Deterministic screening logic shared by the report engine and tests.

Implements the evidence-precedence, continuity-disclosure, and
missing-information rules that must never be delegated to an LLM:

1. Effective-velocity precedence — for links flagged by the worker-vs-.rpt
   reconciliation, the engine .rpt value governs screening; both values,
   their differences, and whether the discrepancy changes the screening
   classification are recorded. Unflagged links use worker values.
2. Continuity disclosure — runoff and routing errors are reported separately,
   sign preserved, each checked against ABSOLUTE review/warning thresholds;
   water quality is "Not applicable" when no pollutants are modelled.
3. Missing-information register — deterministic list of evidence the report
   cannot supply, assembled from metadata, the criteria register, and the
   checklist. Anything listed here can never be a Pass elsewhere.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd


# ---------------------------------------------------------------------------
# Solver-option and execution-integrity gates
# ---------------------------------------------------------------------------

def resolve_legacy_solver_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve auditable SWMM legacy-zero sentinels for an execution copy.

    Older/converted INP files can explicitly serialize zero for dynamic-wave
    options that EPA SWMM displays and executes using unit-aware defaults.
    This function returns substitutions for an immutable derivative; it never
    edits the uploaded source model. Negative and non-numeric values remain
    blocking errors. Omitted values remain omitted for the engine to default.
    """
    opts = {str(k).upper(): str(v).strip() for k, v in options.items()}
    if opts.get("FLOW_ROUTING", "").upper() != "DYNWAVE":
        return {"effective_options": dict(opts), "substitutions": [], "errors": []}
    flow_units = opts.get("FLOW_UNITS", "").upper()
    si_units = flow_units in {"CMS", "LPS", "MLD"}
    defaults = {
        "MAX_TRIALS": (8.0, "count"),
        "HEAD_TOLERANCE": (0.0015 if si_units else 0.005, "m" if si_units else "ft"),
        "MIN_SURFAREA": (1.167 if si_units else 12.566, "m2" if si_units else "ft2"),
    }
    effective = dict(opts)
    substitutions: list[dict[str, Any]] = []
    errors: list[str] = []
    for name, (default, units) in defaults.items():
        if name not in opts:
            continue  # omitted means use the engine default
        try:
            value = float(opts[name])
        except (TypeError, ValueError):
            errors.append(f"{name} must be numeric for dynamic-wave routing.")
            continue
        if value < 0:
            errors.append(
                f"{name} cannot be negative for dynamic-wave routing; "
                f"the uploaded value is {opts[name]!r}."
            )
        elif value == 0:
            effective[name] = format(default, "g")
            substitutions.append({
                "option": name, "original_value": opts[name],
                "effective_value": default, "units": units,
                "reason": "Recognized legacy zero/default sentinel",
            })
    return {"effective_options": effective,
            "substitutions": substitutions, "errors": errors}


def validate_solver_options(options: Mapping[str, Any]) -> list[str]:
    """Return only blocking errors after legacy-default resolution."""
    return list(resolve_legacy_solver_options(options)["errors"])


def execution_integrity_assessment(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Classify whether hydraulic results can support screening conclusions."""
    def number(key: str, default: float = 0.0) -> float:
        try:
            return float(metadata.get(key, default))
        except (TypeError, ValueError):
            return default

    steps = int(number("routing_steps"))
    failed = int(number("not_converged_steps"))
    pct_failed = number("pct_not_converged")
    flow_error = abs(number("flow_error"))
    runoff_error = abs(number("runoff_error"))

    invalid_reasons: list[str] = []
    if steps > 0 and failed >= steps:
        invalid_reasons.append("every routing step failed to converge")
    elif pct_failed >= 5.0:
        invalid_reasons.append(f"{pct_failed:.3f}% of routing steps failed to converge")
    if flow_error >= 10.0:
        invalid_reasons.append(f"flow-routing continuity error is {flow_error:.3f}%")

    if invalid_reasons:
        return {
            "status": "invalid",
            "results_usable": False,
            "hydraulic_conclusions_allowed": False,
            "reason": "; ".join(invalid_reasons) + ".",
        }

    limitations: list[str] = []
    if failed > 0:
        limitations.append(f"{failed} routing step(s) did not converge")
    if flow_error > 1.0:
        limitations.append(f"flow-routing continuity error is {flow_error:.3f}%")
    if runoff_error > 1.0:
        limitations.append(f"runoff continuity error is {runoff_error:.3f}%")
    return {
        "status": "limited" if limitations else "valid",
        "results_usable": True,
        "hydraulic_conclusions_allowed": True,
        "reason": "; ".join(limitations) + ("." if limitations else "Execution-integrity checks passed."),
    }


# ---------------------------------------------------------------------------
# Velocity classification and evidence precedence
# ---------------------------------------------------------------------------

def classify_velocity(velocity: float | None, advisory: float = 3.0,
                      critical: float = 4.0) -> str:
    """Deterministic dual-threshold screening classification (not a
    regulatory determination)."""
    if velocity is None:
        return "Not assessed"
    try:
        v = float(velocity)
    except (TypeError, ValueError):
        return "Not assessed"
    if math.isnan(v):
        return "Not assessed"
    if v > critical:
        return f"Critical screening exceedance (> {critical:g} m/s)"
    if v > advisory:
        return f"Advisory screening exceedance (> {advisory:g} m/s)"
    return f"Below advisory threshold ({advisory:g} m/s)"


def effective_velocity_table(link_df: pd.DataFrame,
                             recon_links: pd.DataFrame | None,
                             advisory: float = 3.0,
                             critical: float = 4.0) -> pd.DataFrame:
    """Per-conduit screening table applying the reconciliation precedence.

    Columns: Link ID, Worker Peak Velocity, RPT Peak Velocity,
    Screening Velocity, Evidence Source, Delta (abs), Delta (%),
    Screening Classification, Classification Changed by Reconciliation.
    """
    if link_df is None or link_df.empty:
        return pd.DataFrame()
    vel_col = next((c for c in link_df.columns if c.startswith("Peak Velocity")), None)
    if vel_col is None:
        return pd.DataFrame()
    recon: dict[str, dict[str, Any]] = {}
    if recon_links is not None and not recon_links.empty:
        for _, r in recon_links.iterrows():
            recon[str(r.get("Link ID"))] = r.to_dict()

    rows: list[dict[str, Any]] = []
    for _, r in link_df.iterrows():
        link_id = str(r.get("Link ID"))
        worker_v = pd.to_numeric(pd.Series([r.get(vel_col)]), errors="coerce").iloc[0]
        rec = recon.get(link_id, {})
        rpt_v = rec.get("RPT Peak Velocity")
        rpt_v = float(rpt_v) if rpt_v is not None and not (isinstance(rpt_v, float) and math.isnan(rpt_v)) else None
        flagged = str(rec.get("Overall Status", "OK")) not in ("OK", "Unavailable", "nan", "None")
        if flagged and rpt_v is not None:
            eff, source = rpt_v, "engine .rpt (reconciliation-flagged)"
        else:
            eff, source = (float(worker_v) if pd.notna(worker_v) else None), "worker time series"
        worker_class = classify_velocity(float(worker_v) if pd.notna(worker_v) else None, advisory, critical)
        eff_class = classify_velocity(eff, advisory, critical)
        delta_abs = (float(worker_v) - rpt_v) if (pd.notna(worker_v) and rpt_v is not None) else None
        delta_pct = (100.0 * delta_abs / abs(rpt_v)) if (delta_abs is not None and rpt_v not in (None, 0)) else None
        rows.append({
            "Link ID": link_id,
            "Worker Peak Velocity (m/s)": round(float(worker_v), 3) if pd.notna(worker_v) else None,
            "RPT Peak Velocity (m/s)": round(rpt_v, 3) if rpt_v is not None else None,
            "Screening Velocity (m/s)": round(eff, 3) if eff is not None else None,
            "Evidence Source": source,
            "Delta (m/s)": round(delta_abs, 3) if delta_abs is not None else None,
            "Delta (%)": round(delta_pct, 1) if delta_pct is not None else None,
            "Screening Classification": eff_class,
            "Classification Changed by Reconciliation": (
                "Yes" if (flagged and rpt_v is not None and worker_class != eff_class)
                else ("No" if flagged else "n/a - not flagged")),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Continuity disclosure
# ---------------------------------------------------------------------------

def continuity_disclosure(metadata: Mapping[str, Any], review_pct: float = 0.5,
                          warning_pct: float = 1.0,
                          has_pollutants: bool = False) -> list[str]:
    """Sign-preserving continuity lines with symmetric absolute thresholds."""
    lines: list[str] = []
    for label, key in (("Surface-runoff continuity error", "runoff_error"),
                       ("Flow-routing continuity error", "flow_error")):
        val = metadata.get(key)
        try:
            v = float(val)
        except (TypeError, ValueError):
            lines.append(f"{label}: not reported by the engine.")
            continue
        lines.append(f"{label}: {v:+.3f}% (engine-reported sign preserved).")
        if abs(v) > warning_pct:
            lines.append(f"⚠️ {label} magnitude |{v:.3f}%| exceeds the {warning_pct:g}% absolute warning threshold and must be reviewed before the results are relied upon.")
        elif abs(v) > review_pct:
            lines.append(f"{label} magnitude |{v:.3f}%| exceeds the {review_pct:g}% absolute review threshold.")
    if has_pollutants:
        qv = metadata.get("quality_error")
        try:
            lines.append(f"Water-quality continuity error: {float(qv):+.3f}%.")
        except (TypeError, ValueError):
            lines.append("Water-quality continuity error: pollutants modelled but continuity not reported — review engine output.")
    else:
        lines.append("Water-quality continuity: Not applicable — no pollutants modelled.")
    return lines


# ---------------------------------------------------------------------------
# Missing-information register
# ---------------------------------------------------------------------------

_METADATA_LABELS = {
    "legal_description": "Legal land description",
    "outline_plan_no": "Outline plan number",
    "subdivision_no": "Subdivision number",
    "development_permit_no": "Development permit number",
    "consultant_file_no": "Consultant file number",
    "prepared_by": "Prepared by (responsible person)",
    "checked_by": "Checked by (reviewer)",
    "client": "Client",
    "consultant": "Consultant",
    "construction_drawing_no": "Construction drawing number",
    "development_agreement_no": "Development agreement number",
}


def missing_information_register(metadata: Mapping[str, Any],
                                 criteria_register: pd.DataFrame | None,
                                 checklist: pd.DataFrame | None) -> pd.DataFrame:
    """Deterministic register of evidence the report cannot supply.

    Items listed here block any related Pass classification elsewhere.
    """
    rows: list[dict[str, str]] = []
    for key, label in _METADATA_LABELS.items():
        value = str(metadata.get(key, "") or "").strip()
        if not value or value.lower() in ("not provided", "none", "-", "—"):
            rows.append({"Item": label, "Category": "Project information",
                         "Status": "Not provided",
                         "Consequence": "Related administrative checklist items remain incomplete."})
    if criteria_register is not None and not criteria_register.empty:
        status_col = next((c for c in criteria_register.columns if "status" in c.lower()), None)
        name_col = next((c for c in criteria_register.columns
                         if c.lower() in ("criterion", "requirement", "item", "name")),
                        criteria_register.columns[0])
        if status_col:
            for _, r in criteria_register.iterrows():
                if "not established" in str(r.get(status_col, "")).lower():
                    rows.append({"Item": str(r.get(name_col)), "Category": "Governing criteria",
                                 "Status": "Not established",
                                 "Consequence": "Related screening cannot be reported as Pass; results remain screening-only."})
    if checklist is not None and not checklist.empty and "Status" in checklist.columns:
        for _, r in checklist.iterrows():
            if str(r.get("Status", "")).strip().lower() == "missing":
                rows.append({"Item": f"{r.get('Item')}: {str(r.get('Requirement'))[:80]}",
                             "Category": "SWMR checklist",
                             "Status": "Missing",
                             "Consequence": "Required for a submission-ready report."})
    if not rows:
        rows.append({"Item": "None identified", "Category": "—", "Status": "—",
                     "Consequence": "All tracked evidence items were supplied."})
    return pd.DataFrame(rows)
