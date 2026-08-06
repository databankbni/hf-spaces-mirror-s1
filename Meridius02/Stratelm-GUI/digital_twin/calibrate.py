"""Post-hoc calibration of digital-twin PLACEHOLDER constants from a REAL logged
telemetry segment, as a free byproduct of an ordinary test drive instead of a
dedicated bench/dyno test nobody has time to run.

First (only, so far) user: DRIVETRAIN_EFFICIENCY_ASSUMED (config.py) -- see
estimate_drivetrain_efficiency()'s docstring for the method.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from . import vehicle
from . import weather as weather_mod


def estimate_drivetrain_efficiency(telemetry: pd.DataFrame, motor, scenario: weather_mod.WeatherScenario,
                                    v_col: str = "v_kmh", elec_col: str = "p_motor_elec_w",
                                    v_tolerance_kmh: float = 1.0) -> dict:
    """Back out drivetrain efficiency from a REAL steady-cruise telemetry segment,
    instead of a dedicated bench/dyno test.

    Method: at near-steady speed (|dv/dt| small -- no meaningful inertial term), the
    wheel power required is fully determined by vehicle.py's own resistance model
    (drag from the CFD CdA table + weather, rolling resistance from the now-measured
    CRR, grade, cornering scrub) -- there is no unknown left in that side of the
    equation. The motor's own (measured, digitized-datasheet) mechanical->electrical
    efficiency curve is also known. That leaves exactly one free variable standing
    between "predicted electrical draw" and "what the telemetry logger actually
    measured" at that speed: drivetrain_eff. So it's solved for directly:

        p_wheel               = f_resistance(v, grade, heading, r_min) * v      [vehicle.py, no unknowns]
        p_motor_mech           = p_wheel / drivetrain_eff                       [drivetrain_eff = unknown]
        p_motor_elec_predicted = motor.electrical_power_w(p_motor_mech)         [motor's own curve, known]

        minimize over drivetrain_eff:  (p_motor_elec_predicted - p_motor_elec_measured)^2

    summed over every near-steady row. This turns "measure the drivetrain" from a
    dedicated lab/dyno task into something that falls out of any ordinary steady-
    cruise segment of a real drive -- no new test rig, no extra time booked.

    Expected telemetry columns: `v_col` (km/h), `grade_pct`, `heading_deg`, `r_min_m`
    (all optional except v_col/elec_col -- missing ones default to flat/straight, so
    this also works on a real MQTT-cleaned log that only has speed + electrical
    power, at the cost of ignoring grade/cornering corrections), and `elec_col` (the
    REAL measured electrical power, e.g. Battery Voltage * Battery Current from a
    real log, or p_motor_elec_w from a simulated one).

    Only rows near-steady-speed are used -- accelerating/braking segments have an
    inertial term (m*dv/dt) this method does not solve for, and would bias the fit.
    Returns {"available": False, "reason": ...} if no steady-speed rows survive the
    filter, otherwise {"available": True, "drivetrain_eff": ..., "rmse_w": ...,
    "n_points": ...}.
    """
    df = telemetry
    v_kmh = df[v_col].to_numpy(dtype=float)
    if len(v_kmh) < 3:
        return {"available": False, "reason": "fewer than 3 telemetry rows"}

    dv = np.gradient(v_kmh)
    steady = np.abs(dv) < v_tolerance_kmh
    df = df[steady]
    if len(df) == 0:
        return {"available": False, "reason": "no near-steady-speed rows found (all accelerating/braking)"}

    v_kmh = df[v_col].to_numpy(dtype=float)
    grade = df["grade_pct"].to_numpy(dtype=float) if "grade_pct" in df else np.zeros(len(df))
    heading = df["heading_deg"].to_numpy(dtype=float) if "heading_deg" in df else np.zeros(len(df))
    r_min = df["r_min_m"].to_numpy(dtype=float) if "r_min_m" in df else np.full(len(df), np.inf)
    p_elec_measured = df[elec_col].to_numpy(dtype=float)

    # Only rows that actually needed positive traction (coasting/braking rows carry
    # no drivetrain-efficiency information -- the motor isn't delivering power).
    keep = v_kmh > 1.0
    v_kmh, grade, heading, r_min, p_elec_measured = (
        v_kmh[keep], grade[keep], heading[keep], r_min[keep], p_elec_measured[keep])
    if len(v_kmh) == 0:
        return {"available": False, "reason": "no steady-speed rows above 1 km/h"}

    f_res = np.array([vehicle.resistance_force_n(v, g, scenario, h, r_min_m=r)
                       for v, g, h, r in zip(v_kmh, grade, heading, r_min)])
    p_wheel = np.clip(f_res, 0.0, None) * (v_kmh / 3.6)

    def cost(eta):
        p_mech = p_wheel / eta
        p_elec_pred = np.array([motor.electrical_power_w(p)[0] for p in p_mech])
        return float(np.mean((p_elec_pred - p_elec_measured) ** 2))

    res = minimize_scalar(cost, bounds=(0.4, 1.0), method="bounded",
                           options={"xatol": 1e-4})
    return {
        "available": True,
        "drivetrain_eff": float(res.x),
        "rmse_w": float(np.sqrt(res.fun)),
        "n_points": len(v_kmh),
    }
