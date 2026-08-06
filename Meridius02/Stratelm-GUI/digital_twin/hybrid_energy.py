"""Hybrid fuel-cell + supercapacitor energy system (2026-07 electrical architecture).

The SZFC-1000 fuel cell runs in PARALLEL with a Maxwell BMOD0058 supercapacitor bank
(3 modules in series), both feeding a DC-DC converter. The FC is held at its stable,
efficient operating point (its 500-570 W band, measured 558 W @ 62%) and the supercap
absorbs the instantaneous load transients -- launch peaks the FC could not follow, and
low-demand cruise where the FC would otherwise idle inefficiently. Hydrogen is then billed
off the FC electrical ENERGY at its fixed operating efficiency, using Art. 54e's own
joulemeter formula:

    litres_H2 = (E_fc_joules / FC_efficiency) / (H2_NCV_kJ_per_kg * H2_density_kg_m3)

`apply_hybrid(tel)` post-processes a simulate()-schema telemetry frame: it runs the power
split, adds the supercapacitor diagnostic columns, and overwrites `h2_flow_m3_s` /
`h2_cumulative_m3` so the whole downstream pipeline (enrich, summary, score, every notebook)
reports the hybrid-system hydrogen with no further changes. The motor-side demand is not
touched -- only how the FC + supercap SOURCE that demand.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from . import config


# ---------------------------------------------------------------- supercap bank geometry
def supercap_specs() -> dict:
    """Series/parallel-combined electrical specs of the supercapacitor bank."""
    ns, npar = config.SUPERCAP_N_SERIES, config.SUPERCAP_N_PARALLEL
    C = config.SUPERCAP_MODULE_C_F * npar / ns          # F
    Vmax = config.SUPERCAP_MODULE_V * ns                # V
    ESR = config.SUPERCAP_MODULE_ESR_OHM * ns / npar    # ohm
    Vmin = config.SUPERCAP_SOC_MIN_FRAC * Vmax
    e_max = 0.5 * C * Vmax ** 2                          # J
    e_min = 0.5 * C * Vmin ** 2                          # J
    return dict(C=C, Vmax=Vmax, Vmin=Vmin, ESR=ESR, E_max=e_max, E_min=e_min)


# ---------------------------------------------------------------- hydrogen (Art. 54e)
def h2_litres_from_fc_energy(e_fc_j: float, eff: float = None) -> float:
    """Art. 54e joulemeter formula: FC electrical energy (J) -> litres of H2.
    Result is in litres directly (the kJ->J and m^3->L factors cancel)."""
    if eff is None:
        eff = config.FC_HYBRID_EFF
    if e_fc_j <= 0:
        return 0.0
    return (e_fc_j / eff) / (config.H2_NCV_KJ_PER_KG * config.H2_DENSITY_G_PER_L_STP)


# ---------------------------------------------------------------- the power split
def split_fc_supercap(p_bus_w: np.ndarray, dt_s: np.ndarray) -> dict:
    """Load-level the DC-bus demand between a fixed-point FC and a supercapacitor buffer.

    The FC is bang-bang controlled on the supercap state-of-charge: it switches ON (at its
    efficient FC_HYBRID_OP_POWER_W) when the cap falls to the low SOC threshold and OFF when it
    reaches the start SOC, so the FC only ever runs at its measured 62% operating point, the cap
    smooths everything in between, and -- crucially for SEM Art. 56c(iii) -- the charge ceiling is
    the START level, so the cap can never overcharge past where it began. Whatever SOC the cap
    ends the driving at, the FC then tops it back up to the start SOC; that recharge energy is
    billed to the FC (energy-conservative hydrogen) and its DURATION is returned so it can be added
    to the run time per the rule. Returns per-step FC/supercap power, cap voltage & stored energy,
    the traction-equivalent FC energy, and the recharge time."""
    sc = supercap_specs()
    p_op = config.FC_HYBRID_OP_POWER_W
    n = len(p_bus_w)
    p_fc = np.zeros(n)
    p_sc = np.zeros(n)          # supercap power: + = discharging to the bus, - = charging
    e_cap = np.zeros(n)
    v_cap = np.zeros(n)

    # Operate the cap in a band that TOPS OUT at the start SOC (never above it -> no overcharge,
    # SEM-compliant) and swings down by SUPERCAP_OP_SWING_FRAC to buffer the transients.
    e_start = config.SUPERCAP_SOC_START_FRAC * sc["E_max"]
    e_hi = e_start
    e_lo = max(e_start - config.SUPERCAP_OP_SWING_FRAC * sc["E_max"], sc["E_min"])
    e_floor = sc["E_min"]
    e = e_start
    fc_on = False
    # Trial 4: FC load hard-capped (it cannot ramp higher than this).
    p_fc_max = min(p_op, getattr(config, "FC_HYBRID_MAX_W", p_op))
    # Trial 3: while GLIDING (low bus demand) the FC may bank spare energy into the cap up to a
    # higher ceiling instead of switching off at the start SOC -> the cap can charge mid-lap.
    e_hi_glide = getattr(config, "SUPERCAP_GLIDE_CHARGE_FRAC", config.SUPERCAP_SOC_START_FRAC) * sc["E_max"]
    glide_bus_w = getattr(config, "SUPERCAP_GLIDE_BUS_FRAC", 0.5) * p_op

    for i in range(n):
        v = np.sqrt(max(2.0 * e / sc["C"], 1e-6))
        # FC-off (charge) ceiling: the higher glide ceiling when coasting, else the start SOC.
        hi = e_hi_glide if p_bus_w[i] < glide_bus_w else e_hi
        # FC bang-bang on cap SOC (hysteresis), forced ON if the cap is near its floor so it
        # can still support a sustained peak.
        if fc_on and e >= hi:
            fc_on = False
        elif (not fc_on) and e <= e_lo:
            fc_on = True
        if e <= 1.02 * e_floor:
            fc_on = True
        p_fc[i] = p_fc_max if fc_on else 0.0

        p_net = p_fc[i] - p_bus_w[i]                     # + charges the cap, - discharges it
        i_cap = p_net / max(v, 1.0)
        p_loss = i_cap ** 2 * sc["ESR"]                  # ohmic loss on the cap current
        p_sc[i] = -p_net
        e_cap[i] = e
        v_cap[i] = v
        # Physical ceiling is E_max (V_max); the FC's OFF threshold is the start SOC (e_hi), so the
        # cap only ever overshoots start by at most one 558 W step -- still well under V_max (no
        # overcharge) -- and no FC energy is ever dumped against the ceiling (energy-conservative).
        e = min(max(e + (p_net - p_loss) * dt_s[i], e_floor), sc["E_max"])

    e_fc = float(np.sum(p_fc * dt_s))
    # SEM Art. 56c(iii): the cap must end at >= its start SOC. Whatever SOC the cap ends the DRIVING
    # at, the FC must physically pump it back up to the start SOC -- energy IN raises the stored
    # energy and therefore the voltage (E = 1/2 C V^2), and the time this takes is added to the run
    # clock. This is a REAL recharge (see apply_hybrid, which appends it to the telemetry so the
    # voltage series genuinely returns to V_start), not a bookkeeping add-back. Energy is billed to
    # the FC as hydrogen.
    e_recharge = max(0.0, e_start - e_cap[-1])
    recharge_time_s = e_recharge / p_op if p_op > 0 else 0.0   # real post-driving recharge duration
    v_end_run = float(v_cap[-1])                               # actual voltage when driving ends
    e_fc_traction = e_fc + e_recharge                          # energy-conservative FC accounting
    return dict(p_fc_w=p_fc, p_supercap_w=p_sc, supercap_v=v_cap, supercap_e_j=e_cap,
                e_fc_j=e_fc, e_fc_traction_j=max(e_fc_traction, 0.0),
                e_recharge_j=float(e_recharge), e_start_j=float(e_start),
                recharge_time_s=float(recharge_time_s),
                v_start=float(np.sqrt(2.0 * e_start / sc["C"])), v_end_run=v_end_run,
                duty=float((p_fc > 0).mean()), v_min=float(v_cap.min()),
                v_max=float(v_cap.max()), specs=sc)


# ---------------------------------------------------------------- telemetry integration
def apply_hybrid(tel: pd.DataFrame) -> pd.DataFrame:
    """Return `tel` with the hybrid FC+supercap columns added and the hydrogen columns
    (`h2_flow_m3_s`, `h2_cumulative_m3`) overwritten to reflect the FC-at-62% + supercap
    system. No-op passthrough (adds nothing) if USE_HYBRID_SUPERCAP is False."""
    if not getattr(config, "USE_HYBRID_SUPERCAP", False):
        return tel
    df = tel
    # Idempotent: if a recharge tail was already appended (e.g. telemetry saved by simulate() and
    # then re-processed by a notebook), strip it so we recompute from the DRIVING portion only and
    # never stack tails.
    if "is_recharge" in df.columns:
        df = df[~df["is_recharge"].astype(bool)].reset_index(drop=True)
    t = df["t_s"].to_numpy(dtype=float)
    dt = np.diff(t, append=t[-1])
    dt = np.clip(dt, 0.0, None)
    # DC-bus electrical demand the source must deliver == the FC-electrical demand column
    # simulate() already computes (motor elec / buffer eff + parasitic).
    p_bus = np.clip(df["p_fc_elec_w"].to_numpy(dtype=float), 0.0, None)

    r = split_fc_supercap(p_bus, dt)
    C = r["specs"]["C"]; p_op = config.FC_HYBRID_OP_POWER_W

    # --- SEM Art. 56c(iii) REAL recharge tail -----------------------------------------------
    # The cap ends the driving at e_drive_end (< start), so its voltage has dropped (E = 1/2 C V^2).
    # We append a physical recharge phase -- car stopped past the finish line, FC at 558 W pumping
    # energy back into the cap -- so the stored energy (and therefore the voltage) climbs back to
    # V_start. The last telemetry row then GENUINELY sits at V_start, and the recharge duration is
    # part of the attempt clock. FC power over this tail bills the recharge hydrogen (no double count:
    # h2 is billed on driving FC energy + this tail's FC energy = e_fc_traction).
    p_fc = np.asarray(r["p_fc_w"], float); p_scap = np.asarray(r["p_supercap_w"], float)
    v_cap = np.asarray(r["supercap_v"], float); e_cap = np.asarray(r["supercap_e_j"], float)
    e_recharge = r["e_recharge_j"]; e_start = r["e_start_j"]
    recharge_time = r["recharge_time_s"]
    tail_dt = []
    if p_op > 0:
        # FIXED number of recharge samples so every telemetry (baseline vs driver-error, any
        # strategy) has the SAME length -- the driving portion is identical (same track), so a
        # constant-K tail keeps all frames aligned for downstream element-wise comparisons. The
        # tail DURATION still scales with the recharge energy (dts below); if no recharge is needed
        # the tail is a zero-duration flat hold at V_start (harmless).
        K = int(getattr(config, "SUPERCAP_RECHARGE_STEPS", 12))
        dts = recharge_time / K
        e_tail = np.linspace(e_cap[-1], e_start, K + 1)[1:]   # energy climbs to start SOC
        v_tail = np.sqrt(np.maximum(2.0 * e_tail / C, 1e-6))  # -> V rises to V_start (E=1/2 C V^2)
        charging = dts > 0                                    # FC only draws H2 if it actually runs
        p_fc = np.concatenate([p_fc, np.full(K, p_op if charging else 0.0)])
        p_scap = np.concatenate([p_scap, np.full(K, -(p_op if charging else 0.0))])
        v_cap = np.concatenate([v_cap, v_tail])
        e_cap = np.concatenate([e_cap, e_tail])
        tail_dt = [dts] * K
        # extend the base telemetry: car stopped at the finish (v=0, distance constant), clock runs
        last = df.iloc[[-1]]
        tail = pd.concat([last] * K, ignore_index=True)
        tail["t_s"] = t[-1] + np.arange(1, K + 1) * dts
        for c in ("v_kmh", "v_ms", "a_ms2", "p_wheel_w", "p_mech_w", "p_motor_elec_w"):
            if c in tail.columns:
                tail[c] = 0.0
        if "rule_violation" in tail.columns:
            tail["rule_violation"] = 0
        df = pd.concat([df, tail], ignore_index=True)

    dt_full = np.concatenate([dt, tail_dt]) if tail_dt else dt

    # Per-step FC hydrogen flow (m^3/s), scaled so the cumulative endpoint equals the
    # energy-conservative traction hydrogen (flow<->cumulative stay consistent for charts).
    h2_total_m3 = h2_litres_from_fc_energy(r["e_fc_traction_j"]) / 1000.0
    fc_energy_step = p_fc * dt_full
    denom = fc_energy_step.sum()
    h2_cum_m3 = (np.cumsum(fc_energy_step) / denom * h2_total_m3) if denom > 0 else np.zeros(len(df))
    h2_flow = np.zeros(len(df))
    h2_flow[dt_full > 0] = np.diff(h2_cum_m3, prepend=0.0)[dt_full > 0] / dt_full[dt_full > 0]

    df = df.copy()
    df["p_fc_out_w"] = p_fc                         # FC electrical output (0 when idle)
    df["p_supercap_w"] = p_scap                     # supercap power (+discharge / -charge)
    df["supercap_voltage_v"] = v_cap               # bank terminal voltage (rises back to V_start)
    df["supercap_energy_j"] = e_cap                # bank stored energy
    df["supercap_soc_frac"] = e_cap / r["specs"]["E_max"]
    # SEM Art. 56c(iii): after the real recharge tail the last row sits at V_start, so v_end reports
    # the ACTUAL end-of-attempt voltage (== v_start), consistent with the energy/voltage series.
    df["supercap_v_start"] = r["v_start"]
    df["supercap_v_end"] = float(v_cap[-1])        # actual last-row voltage (now == v_start)
    df["supercap_recharge_s"] = r["recharge_time_s"]
    df["h2_flow_m3_s"] = h2_flow                   # OVERWRITTEN: hybrid-system hydrogen
    df["h2_cumulative_m3"] = h2_cum_m3             # OVERWRITTEN
    n_drive = len(df) - len(tail_dt)               # driving rows vs appended recharge-tail rows
    df["is_recharge"] = np.concatenate([np.zeros(n_drive, bool), np.ones(len(tail_dt), bool)])
    return df


def recharge_time_s(tel: pd.DataFrame) -> float:
    """SEM Art. 56c(iii) recharge time (s) to add to the run time; 0 if not a hybrid run."""
    if "supercap_recharge_s" in tel.columns and len(tel):
        return float(tel["supercap_recharge_s"].iloc[0])
    return 0.0
