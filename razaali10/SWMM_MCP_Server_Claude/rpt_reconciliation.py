"""Deterministic reconciliation of app-extracted results against the SWMM .rpt file.

Rationale
---------
The application builds its result tables (and therefore the Calgary velocity
screening and the Table 9A depth-velocity assessment) from time series read
through the OpenSWMM Python API inside the isolated worker. The engine's own
``.rpt`` file independently reports per-timestep maxima in its Link Flow
Summary and Node Depth Summary. On the Kincora Phase 2 reference model these
two sources were found to disagree: pipe peak velocities differed by 5-12%,
and peak velocities in irregular-transect (street) channels were understated
by up to a factor of six in the API-derived tables, while the ``.rpt`` values
matched the original consultant's SWMM 5.0.022 run almost exactly.

This module parses the ``.rpt`` summaries and produces an auditable
reconciliation table plus findings-register entries compatible with the
Preliminary Design Assistant. It performs no simulation and calls no LLM.

Notes and limitations
---------------------
* RPT object names are truncated to 20 characters by the engine. Where a
  worker ID is longer than 20 characters, matching falls back to the
  truncated prefix; ambiguous prefixes are reported as ``Unmatched`` rather
  than guessed.
* Only CONDUIT and CHANNEL rows carry velocity; OUTLET/DUMMY/PUMP/ORIFICE/
  WEIR rows are reconciled on peak flow only.
* The ``.rpt`` is treated as the authoritative cross-check because it is the
  engine's own per-timestep statistic. A discrepancy does not by itself say
  which value is "true"; it says the two extraction paths disagree and the
  responsible engineer must not rely on the affected screening rows until
  the cause is resolved.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

_RPT_NAME_WIDTH = 20
_VELOCITY_TYPES = {"CONDUIT", "CHANNEL"}
_FLOW_ONLY_TYPES = {"OUTLET", "DUMMY", "PUMP", "ORIFICE", "WEIR"}


@dataclass
class ReconciliationTolerances:
    """Screening tolerances for worker-vs-RPT deltas.

    Values are relative unless stated. Absolute floors avoid flagging noise
    on near-zero quantities (e.g. a 0.002 vs 0.004 m/s trickle).
    """

    velocity_review_pct: float = 5.0
    velocity_discrepancy_pct: float = 15.0
    velocity_abs_floor: float = 0.05          # m/s or ft/s
    flow_review_pct: float = 2.0
    flow_discrepancy_pct: float = 10.0
    flow_abs_floor: float = 0.005             # model flow units
    depth_review_pct: float = 5.0
    depth_discrepancy_pct: float = 15.0
    depth_abs_floor: float = 0.01             # m or ft
    continuity_abs_review: float = 0.05       # absolute percentage points


# ---------------------------------------------------------------------------
# RPT parsing
# ---------------------------------------------------------------------------

def _section_lines(text: str, header: str) -> list[str]:
    """Return the body lines of a starred RPT section, or an empty list."""
    pattern = re.compile(
        r"^\s*" + re.escape(header) + r"\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return []
    lines = text[match.end():].splitlines()
    # The data table starts after the LAST dashed rule that precedes the
    # first data row: title banner (****), blank, dashed rule, column
    # headers, dashed rule, data rows, blank line.
    last_rule = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and set(stripped) <= {"-"}:
            last_rule = i
            continue
        if last_rule >= 0 and stripped and not stripped.startswith("*"):
            # Column-header lines sit between the two rules; a line after a
            # rule that is followed by another rule is a header, so only
            # accept this as the data start if no further rule intervenes
            # before the next blank line.
            remainder = lines[i:]
            if any(set(l.strip()) <= {"-"} and l.strip() for l in remainder[:4]):
                continue  # still inside the header block
            body: list[str] = []
            for data_line in remainder:
                if not data_line.strip():
                    break
                if data_line.strip().startswith("*"):
                    break
                body.append(data_line.rstrip("\n"))
            return body
    return []


def _row_tokens(line: str) -> tuple[str, list[str]]:
    """Split an RPT summary row into (object name, remaining tokens).

    The name field is fixed-width (20 chars) and may itself contain no
    spaces in SWMM inputs, but is sliced positionally to be safe.
    """
    name = line[:2 + _RPT_NAME_WIDTH].strip()
    rest = line[2 + _RPT_NAME_WIDTH:].split()
    return name, rest


def _to_float(token: str) -> float | None:
    try:
        value = float(token)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_link_flow_summary(rpt_path: str | Path) -> pd.DataFrame:
    """Parse the Link Flow Summary into a DataFrame.

    Columns: ``Link ID``, ``RPT Type``, ``RPT Peak |Flow|``,
    ``RPT Time of Max``, ``RPT Peak |Velocity|``, ``RPT Max/Full Flow``,
    ``RPT Max/Full Depth``. Velocity columns are NaN for flow-only types.
    """
    text = Path(rpt_path).read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for line in _section_lines(text, "Link Flow Summary"):
        name, tokens = _row_tokens(line)
        if not name or len(tokens) < 2:
            continue
        rtype = tokens[0].upper()
        record: dict[str, Any] = {
            "Link ID": name, "RPT Type": rtype,
            "RPT Peak |Flow|": _to_float(tokens[1]),
            "RPT Time of Max": None, "RPT Peak |Velocity|": None,
            "RPT Max/Full Flow": None, "RPT Max/Full Depth": None,
        }
        if len(tokens) >= 4:
            record["RPT Time of Max"] = f"{tokens[2]} {tokens[3]}"
        if rtype in _VELOCITY_TYPES and len(tokens) >= 7:
            record["RPT Peak |Velocity|"] = _to_float(tokens[4])
            record["RPT Max/Full Flow"] = _to_float(tokens[5])
            record["RPT Max/Full Depth"] = _to_float(tokens[6])
        rows.append(record)
    return pd.DataFrame(rows)


def parse_node_depth_summary(rpt_path: str | Path) -> pd.DataFrame:
    """Parse the Node Depth Summary into a DataFrame."""
    text = Path(rpt_path).read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for line in _section_lines(text, "Node Depth Summary"):
        name, tokens = _row_tokens(line)
        if not name or len(tokens) < 4:
            continue
        rows.append({
            "Node ID": name, "RPT Type": tokens[0].upper(),
            "RPT Avg Depth": _to_float(tokens[1]),
            "RPT Max Depth": _to_float(tokens[2]),
            "RPT Max HGL": _to_float(tokens[3]),
        })
    return pd.DataFrame(rows)


def parse_continuity_errors(rpt_path: str | Path) -> dict[str, float | None]:
    """Return runoff and flow-routing continuity errors in PERCENT.

    The first ``Continuity Error (%)`` line in the RPT belongs to the runoff
    quantity block and the second to flow routing, matching the engine's
    output order.
    """
    text = Path(rpt_path).read_text(encoding="utf-8", errors="replace")
    values = [
        _to_float(m.group(1))
        for m in re.finditer(r"Continuity Error \(%\) \.+\s+(-?[\d.]+)", text)
    ]
    return {
        "runoff_error_pct": values[0] if len(values) > 0 else None,
        "flow_error_pct": values[1] if len(values) > 1 else None,
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def _match_rpt_row(object_id: str, rpt: pd.DataFrame, id_col: str) -> pd.Series | None:
    exact = rpt[rpt[id_col].astype(str) == str(object_id)]
    if len(exact) == 1:
        return exact.iloc[0]
    prefix = str(object_id)[:_RPT_NAME_WIDTH]
    by_prefix = rpt[rpt[id_col].astype(str) == prefix]
    if len(by_prefix) == 1:
        return by_prefix.iloc[0]
    return None


def _classify(worker: float | None, reference: float | None,
              review_pct: float, discrepancy_pct: float,
              abs_floor: float) -> tuple[str, float | None]:
    """Return (status, delta_pct). Deltas below the absolute floor pass."""
    if worker is None or reference is None:
        return "Unavailable", None
    if abs(worker - reference) <= abs_floor:
        return "OK", 0.0 if reference == 0 else round(
            100.0 * (worker - reference) / abs(reference), 2)
    if reference == 0:
        return "Discrepancy", None
    delta = 100.0 * (worker - reference) / abs(reference)
    if abs(delta) <= review_pct:
        return "OK", round(delta, 2)
    if abs(delta) <= discrepancy_pct:
        return "Review", round(delta, 2)
    return "Discrepancy", round(delta, 2)


def reconcile_links(
    link_summary: pd.DataFrame,
    rpt_path: str | Path,
    tolerances: ReconciliationTolerances | None = None,
) -> pd.DataFrame:
    """Reconcile the app's link table against the RPT Link Flow Summary.

    ``link_summary`` must contain ``Link ID`` plus any of the recognised
    worker columns (``Peak Flow (...)``, ``Peak Velocity (...)``,
    ``Depth Ratio``). Unrecognised columns are ignored so unit-suffix
    variations (m³/s vs cfs, m/s vs ft/s) are handled transparently.
    """
    tol = tolerances or ReconciliationTolerances()
    if link_summary is None or link_summary.empty:
        return pd.DataFrame()
    rpt = parse_link_flow_summary(rpt_path)
    if rpt.empty:
        return pd.DataFrame()

    flow_col = next((c for c in link_summary.columns if c.startswith("Peak Flow (")), None)
    vel_col = next((c for c in link_summary.columns if c.startswith("Peak Velocity (")), None)
    depth_ratio_col = "Depth Ratio" if "Depth Ratio" in link_summary.columns else None

    rows: list[dict[str, Any]] = []
    for _, record in link_summary.iterrows():
        link_id = str(record["Link ID"])
        matched = _match_rpt_row(link_id, rpt, "Link ID")
        if matched is None:
            rows.append({"Link ID": link_id, "RPT Type": None,
                         "Overall Status": "Unmatched"})
            continue
        entry: dict[str, Any] = {"Link ID": link_id, "RPT Type": matched["RPT Type"]}
        statuses: list[str] = []

        worker_flow = _to_float(record.get(flow_col)) if flow_col else None
        entry["Worker Peak Flow"] = worker_flow
        entry["RPT Peak Flow"] = matched["RPT Peak |Flow|"]
        status, delta = _classify(worker_flow, matched["RPT Peak |Flow|"],
                                  tol.flow_review_pct, tol.flow_discrepancy_pct,
                                  tol.flow_abs_floor)
        entry["Flow Delta (%)"], entry["Flow Status"] = delta, status
        statuses.append(status)

        if matched["RPT Type"] in _VELOCITY_TYPES:
            worker_vel = _to_float(record.get(vel_col)) if vel_col else None
            entry["Worker Peak Velocity"] = worker_vel
            entry["RPT Peak Velocity"] = matched["RPT Peak |Velocity|"]
            status, delta = _classify(worker_vel, matched["RPT Peak |Velocity|"],
                                      tol.velocity_review_pct,
                                      tol.velocity_discrepancy_pct,
                                      tol.velocity_abs_floor)
            entry["Velocity Delta (%)"], entry["Velocity Status"] = delta, status
            statuses.append(status)

            if depth_ratio_col is not None:
                worker_ratio = _to_float(record.get(depth_ratio_col))
                entry["Worker Depth Ratio"] = worker_ratio
                entry["RPT Max/Full Depth"] = matched["RPT Max/Full Depth"]
                status, delta = _classify(worker_ratio, matched["RPT Max/Full Depth"],
                                          tol.depth_review_pct,
                                          tol.depth_discrepancy_pct,
                                          tol.depth_abs_floor)
                entry["Depth Ratio Delta (%)"], entry["Depth Ratio Status"] = delta, status
                statuses.append(status)

        order = {"Discrepancy": 3, "Unmatched": 3, "Review": 2, "Unavailable": 1, "OK": 0}
        entry["Overall Status"] = max(statuses, key=lambda s: order.get(s, 0)) if statuses else "Unavailable"
        rows.append(entry)
    return pd.DataFrame(rows)


def reconcile_nodes(
    node_summary: pd.DataFrame,
    rpt_path: str | Path,
    tolerances: ReconciliationTolerances | None = None,
) -> pd.DataFrame:
    """Reconcile app node peak depths against the RPT Node Depth Summary."""
    tol = tolerances or ReconciliationTolerances()
    if node_summary is None or node_summary.empty:
        return pd.DataFrame()
    rpt = parse_node_depth_summary(rpt_path)
    if rpt.empty:
        return pd.DataFrame()
    depth_col = next((c for c in node_summary.columns if c.startswith("Peak Depth (")), None)
    if depth_col is None:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, record in node_summary.iterrows():
        node_id = str(record["Node ID"])
        matched = _match_rpt_row(node_id, rpt, "Node ID")
        if matched is None:
            rows.append({"Node ID": node_id, "Overall Status": "Unmatched"})
            continue
        worker_depth = _to_float(record.get(depth_col))
        status, delta = _classify(worker_depth, matched["RPT Max Depth"],
                                  tol.depth_review_pct, tol.depth_discrepancy_pct,
                                  tol.depth_abs_floor)
        rows.append({
            "Node ID": node_id, "RPT Type": matched["RPT Type"],
            "Worker Peak Depth": worker_depth,
            "RPT Max Depth": matched["RPT Max Depth"],
            "Depth Delta (%)": delta, "Overall Status": status,
        })
    return pd.DataFrame(rows)


def reconcile_continuity(
    simulation_metadata: Mapping[str, Any],
    rpt_path: str | Path,
    tolerances: ReconciliationTolerances | None = None,
) -> pd.DataFrame:
    """Reconcile worker continuity errors against the RPT, in percent.

    Detects the fraction-vs-percent inconsistency: if the worker value is
    approximately the RPT value divided by 100, the row is marked
    ``Unit inconsistency (fraction vs percent)`` rather than a numeric
    discrepancy, since the underlying simulation agrees.
    """
    tol = tolerances or ReconciliationTolerances()
    rpt_values = parse_continuity_errors(rpt_path)
    pairs = [
        ("Runoff continuity", simulation_metadata.get("runoff_error"),
         rpt_values["runoff_error_pct"]),
        ("Flow routing continuity", simulation_metadata.get("flow_error"),
         rpt_values["flow_error_pct"]),
    ]
    rows: list[dict[str, Any]] = []
    for label, worker, reference in pairs:
        worker_f, ref_f = _to_float(worker), _to_float(reference)
        if worker_f is None or ref_f is None:
            status = "Unavailable"
        elif abs(worker_f - ref_f) <= tol.continuity_abs_review:
            status = "OK"
        elif abs(worker_f * 100.0 - ref_f) <= tol.continuity_abs_review:
            status = "Unit inconsistency (fraction vs percent)"
        else:
            status = "Discrepancy"
        rows.append({"Quantity": label, "Worker Value": worker_f,
                     "RPT Value (%)": ref_f, "Status": status})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Findings-register integration
# ---------------------------------------------------------------------------

def reconciliation_findings(
    link_recon: pd.DataFrame,
    node_recon: pd.DataFrame | None = None,
    continuity_recon: pd.DataFrame | None = None,
    start_index: int = 1,
) -> list[dict[str, Any]]:
    """Convert reconciliation discrepancies into PDA-style finding dicts.

    Only ``Review``, ``Discrepancy``, ``Unmatched`` and unit-inconsistency
    rows generate findings. Severity: Discrepancy/Unmatched -> High,
    Review -> Medium. These findings carry no proposed model edit; the
    recommended action is to resolve the extraction path before relying on
    the affected screening tables.
    """
    findings: list[dict[str, Any]] = []
    counter = start_index

    def add(severity: str, object_type: str, object_id: str, basis: str) -> None:
        nonlocal counter
        findings.append({
            "finding_id": f"RPT-{counter:03d}",
            "category": "Result reconciliation",
            "severity": severity,
            "finding_type": "Worker/RPT disagreement",
            "object_type": object_type,
            "object_id": object_id,
            "rule_id": "QA-RECON-001",
            "criterion_status": "Deterministic cross-check",
            "deterministic_basis": basis,
            "recommended_action": (
                "Do not rely on the affected screening rows until the API "
                "extraction and the engine report file agree. Verify units, "
                "extraction property, and sampling of the worker time series."
            ),
            "engineer_decision": "Defer",
            "resolution_status": "Open",
        })
        counter += 1

    if link_recon is not None and not link_recon.empty:
        for _, row in link_recon.iterrows():
            status = row.get("Overall Status")
            if status in {"OK", "Unavailable", None}:
                continue
            severity = "High" if status in {"Discrepancy", "Unmatched"} else "Medium"
            parts = []
            for label, w, r, d in [
                ("velocity", row.get("Worker Peak Velocity"), row.get("RPT Peak Velocity"), row.get("Velocity Delta (%)")),
                ("flow", row.get("Worker Peak Flow"), row.get("RPT Peak Flow"), row.get("Flow Delta (%)")),
                ("depth ratio", row.get("Worker Depth Ratio"), row.get("RPT Max/Full Depth"), row.get("Depth Ratio Delta (%)")),
            ]:
                if d is not None and not (isinstance(d, float) and math.isnan(d)) and abs(d) > 5.0:
                    parts.append(f"peak {label} worker={w} vs rpt={r} ({d:+.1f}%)")
            basis = (f"Link '{row['Link ID']}': " + "; ".join(parts)) if parts else (
                f"Link '{row['Link ID']}': status {status}.")
            add(severity, "LINK", str(row["Link ID"]), basis)

    if node_recon is not None and not node_recon.empty:
        for _, row in node_recon.iterrows():
            if row.get("Overall Status") in {"Review", "Discrepancy", "Unmatched"}:
                severity = "Medium" if row["Overall Status"] == "Review" else "High"
                add(severity, "NODE", str(row["Node ID"]),
                    f"Node '{row['Node ID']}': peak depth worker="
                    f"{row.get('Worker Peak Depth')} vs rpt={row.get('RPT Max Depth')}"
                    f" ({row.get('Depth Delta (%)')}%).")

    if continuity_recon is not None and not continuity_recon.empty:
        for _, row in continuity_recon.iterrows():
            if row["Status"] not in {"OK", "Unavailable"}:
                add("Medium", "MODEL", "MODEL",
                    f"{row['Quantity']}: worker={row['Worker Value']} vs "
                    f"rpt={row['RPT Value (%)']}%. {row['Status']}.")
    return findings


def reconciliation_summary(link_recon: pd.DataFrame) -> dict[str, Any]:
    """Compact machine-readable summary for the report package metadata."""
    if link_recon is None or link_recon.empty:
        return {"links_checked": 0, "ok": 0, "review": 0,
                "discrepancy": 0, "unmatched": 0, "verdict": "Not performed"}
    counts = link_recon["Overall Status"].value_counts().to_dict()
    discrepancies = counts.get("Discrepancy", 0) + counts.get("Unmatched", 0)
    verdict = ("Pass - worker tables agree with engine report" if discrepancies == 0
               and counts.get("Review", 0) == 0 else
               "Review required - worker tables disagree with engine report")
    return {
        "links_checked": int(len(link_recon)),
        "ok": int(counts.get("OK", 0)),
        "review": int(counts.get("Review", 0)),
        "discrepancy": int(counts.get("Discrepancy", 0)),
        "unmatched": int(counts.get("Unmatched", 0)),
        "verdict": verdict,
    }
