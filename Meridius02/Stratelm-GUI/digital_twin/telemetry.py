"""
Art. 54e scoring: km per m^3 of hydrogen consumed -- the on-track efficiency
score for the Hydrogen Fuel Cell energy class. H2 volume is a pure objective
to minimize (no cylinder capacity constraint exists anywhere in the rules,
confirmed absent from Chapter I/II).

Art. 54e's official worked example: total consumed = (H2 measured by the flow
meter) + (accessory/starter battery energy measured by the joulemeter,
converted to an equivalent H2 volume via the example's stated 0.5 assumed
fuel-cell efficiency). Per Art. 56(c)(iii), the horn circuit is explicitly
exempt from joulemeter measurement and must NOT be included in the accessory
energy total passed in here.
"""

import numpy as np
import pandas as pd

from . import config


def accessory_h2_equivalent_m3(accessory_energy_j: float,
                                assumed_fc_efficiency: float = config.ART54E_ASSUMED_FC_EFFICIENCY_FOR_JOULEMETER) -> float:
    """Joulemeter-measured accessory/starter battery energy -> equivalent H2 volume,
    per Art. 54e's own worked example formula (verified to reproduce its 1.855 L result
    for 10,000 J at 0.5 efficiency)."""
    if accessory_energy_j <= 0:
        return 0.0
    mass_kg = (accessory_energy_j / assumed_fc_efficiency) / (config.H2_NCV_KJ_PER_KG * 1000.0)
    return mass_kg / config.H2_DENSITY_G_PER_L_STP


def h2_score_km_per_m3(total_distance_km: float, total_h2_volume_m3: float,
                        accessory_energy_j: float = 0.0) -> float:
    """Art. 54e net score: flow-meter H2 + joulemeter-equivalent H2 from accessory battery."""
    total_h2_with_accessory_m3 = total_h2_volume_m3 + accessory_h2_equivalent_m3(accessory_energy_j)
    if total_h2_with_accessory_m3 <= 0:
        return float("inf")
    return total_distance_km / total_h2_with_accessory_m3


def motor_usage_breakdown(telemetry: pd.DataFrame) -> dict:
    """For a two-motor run, attribute electrical energy, H2 volume and engaged-time to each
    motor, and count accel<->cruise handoffs. STRATEGY reporting only -- shows WHERE each
    motor does its work so the driving-strategy split is visible in the dashboard."""
    df = telemetry
    if "active_motor" not in df or df["active_motor"].isna().all():
        return {}
    t = df["t_s"].to_numpy()
    dt = np.diff(t, append=t[-1])                       # forward step duration; last step 0
    elec_w = df["p_motor_elec_w"].to_numpy()
    h2_flow = df["h2_flow_m3_s"].to_numpy()
    active = df["active_motor"].to_numpy()

    per_motor = {}
    for name in pd.unique(active[pd.notna(active)]):
        sel = active == name
        per_motor[name] = {
            "energy_wh": float(np.sum(elec_w[sel] * dt[sel]) / 3600.0),
            "h2_m3": float(np.sum(h2_flow[sel] * dt[sel])),
            "engaged_time_s": float(np.sum(dt[sel])),
            "engaged_dist_m": float(np.sum(df["v_kmh"].to_numpy()[sel] / 3.6 * dt[sel])),
        }
    # handoffs: transitions between two distinct, non-null motor names
    valid = active[pd.notna(active)]
    switches = int(np.sum(valid[1:] != valid[:-1])) if len(valid) > 1 else 0
    return {"per_motor": per_motor, "handoffs": switches}


def estimated_handoff_loss_wh(telemetry: pd.DataFrame, transition_s: float = 0.5) -> float:
    """Rough upper bound on energy 'lost' to the clutch/rpm-sync handoffs, if each switch
    opened the driveline for transition_s (car coasts against resistance, no drive). Reported
    separately so the instantaneous-switch model can be sanity-checked -- it is NOT added to
    the H2 score. Approximated as drag+roll power at the switch speed x transition_s x #handoffs."""
    bd = motor_usage_breakdown(telemetry)
    handoffs = bd.get("handoffs", 0)
    if handoffs == 0:
        return 0.0
    df = telemetry
    active = df["active_motor"].to_numpy()
    valid_idx = np.where(pd.notna(active))[0]
    switch_rows = valid_idx[1:][active[valid_idx][1:] != active[valid_idx][:-1]]
    res_w = (df["f_drag_n"].to_numpy() + df["f_roll_n"].to_numpy()) * (df["v_kmh"].to_numpy() / 3.6)
    return float(np.sum(np.abs(res_w[switch_rows])) * transition_s / 3600.0)
