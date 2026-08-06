"""
Centralized constants for the digital twin, every value tagged by confidence/source:

  MEASURED       -- taken directly from a datasheet/parameter PDF or a clean physical measurement
  RULE-DERIVED   -- computed from a 2026 rulebook article (Chapter I/II), not measured
  PLACEHOLDER    -- estimated/assumed because no real data exists yet; safe to overwrite once
                    the responsible sub-team (VD/Motor/FC/EP/BnF) supplies a real number

Scan this file to see at a glance what's solid vs. guessed. See the project plan
(hey-u-can-read-fizzy-pizza.md) section "Concrete gap-handling methodology" for the
reasoning behind each PLACEHOLDER and each resolved data conflict.
"""

# --- Mass (Chapter I, Article 20 driver-weight floor; Article 45h vehicle-weight cap) ---
MASS_VEHICLE_KG = 88.0     # MEASURED, EP.pdf 85.0 + 3.0 kg team-confirmed addition (2026-07-17) -- must stay <=225 kg per Art. 45h
MASS_DRIVER_KG = 70.0      # RULE-DERIVED, Art. 20 minimum driver weight floor (matches EP.pdf exactly)
MASS_TOTAL_KG = MASS_VEHICLE_KG + MASS_DRIVER_KG  # 158.0

# --- Aerodynamics ---
# MEASURED-CFD (2026-07-23): Ansys Fluent runs (SST k-omega, steady, Student edition)
# for "Geom-3", the fixed/finalized body -- supersedes the geom1/geom2 candidates below.
# 4-point speed sweep, reference area 0.5649898 m^2, Cd falls with speed (correct
# Reynolds-number behavior): 0.177872@10 / 0.165844@20 / 0.157805@30 / 0.153671@40 km/h.
# CdA (drag area) is stored directly, per geometry, as (speed_kmh, CdA_m2) points --
# that's the quantity CFD actually measures; vehicle.py interpolates over speed
# (constant beyond the endpoints).
AERO_CDA_CFD = {
    "geom3": [(10.0, 0.100496), (20.0, 0.093700), (30.0, 0.089158), (40.0, 0.086823)],
}
AERO_BODY_GEOMETRY = "geom3"  # MEASURED-CFD -- "Alle The First" fixed geometry
AERO_FRONTAL_AREA_CFD_M2 = 0.5649898  # MEASURED-CFD, Fluent reference area for Geom-3

# Superseded by the CFD numbers above -- kept only as provenance for the old estimate
# (EP.pdf's k=0.6 shape factor overestimated frontal area: real k = 0.509/(1.22*1.05) = 0.40):
AERO_CD_LEGACY_ESTIMATE = 0.1       # SUPERSEDED, EP.pdf estimate
FRONTAL_AREA_LEGACY_M2 = 0.77       # SUPERSEDED, EP.pdf W*H*k estimate
VEHICLE_WIDTH_M = 1.22              # MEASURED, EP.pdf
VEHICLE_HEIGHT_M = 1.05             # MEASURED, EP.pdf
AIR_DENSITY_STD_KG_M3 = 1.225       # standard atmosphere reference only -- actual sims should use weather.py's air_density()

# --- Rolling resistance & wheel ---
CRR = 0.004               # MEASURED (2026-07-24 team confirmation): tyre selected by another sub-team,
                           # value comes from that tyre's own datasheet -- the datasheet itself isn't
                           # in this repo (no direct access), so the specific document can't be cited
                           # here, but the number is a real spec pick, not the earlier no-citation
                           # EP.pdf "Assumption" guess it replaces.
WHEEL_DIAMETER_IN = 16.0  # MEASURED, EP.pdf
WHEEL_RADIUS_M = 0.203    # MEASURED, EP.pdf (16in wheel)

# --- Drivetrain ---
DRIVETRAIN_EFFICIENCY_ASSUMED = 0.80  # CONSERVATIVE PLACEHOLDER (was 0.92): Accounts for chain, bearings, brake drag
# Gear ratio is NOT documented anywhere in any parameter PDF for any candidate motor.
# Computed per-motor in powertrain.py::compute_gear_ratio() from RPM-matching at
# V_TARGET_AVG_KMH_CRUISE -- see that module, not a fixed constant here.

# --- Chassis geometry (VD.pdf -- only these specific rows are usable, rest of that
#     PDF and all of BnF.pdf are corrupted/mislabeled exports, discarded entirely) ---
FRONT_TRACK_WIDTH_MM = 1100.0   # MEASURED, VD.pdf
REAR_TRACK_WIDTH_MM = 850.0     # MEASURED, VD.pdf
WHEELBASE_MM = 1600.0           # MEASURED, VD.pdf
VEHICLE_TURNING_RADIUS_M = 6.0  # RULE-DERIVED ceiling, Art. 47 (VD.pdf's "6 m" matches exactly -- it's the regulatory
                                 # max, not an independently measured value; also the hard floor for racing_line.py's
                                 # apex radius constraint)

# --- Track / attempt rules (Chapter II, Article 226-228) ---
LAP_DISTANCE_KM = 3.7
TOTAL_LAPS = 4
TOTAL_DISTANCE_KM = 14.8            # RULE-DERIVED, Art. 226 (this is the TOTAL for all 4 laps, not per-lap x4 again --
                                     # VD.pdf's Vavg formula double-counted this, see V_TARGET_AVG_KMH_MIN below)
MAX_ATTEMPT_TIME_MIN = 35.0         # RULE-DERIVED, Art. 226
STOPS_PER_LAP = 2                   # RULE-DERIVED, Art. 227 (full stop, not rolling)

# VD.pdf's "Vavg = 28 m/s" is a diagnosed formula bug (double-counted the x4 lap multiplier
# on a distance that's already the 4-lap total). Correct value, matching Art. 226 exactly:
V_TARGET_AVG_KMH_MIN = (TOTAL_DISTANCE_KM * 1000) / (MAX_ATTEMPT_TIME_MIN * 60) * 3.6  # RULE-DERIVED, ~25.4 km/h
V_TARGET_AVG_KMH_CRUISE = 30.0       # MEASURED (EP.pdf cruise-speed design point), consistent with the rule-derived minimum above

# Compulsory stop locations (Art. 227): the rule text itself says these are only
# "confirmed at the event" -- this is NOT a data gap we can close from documents,
# it's genuinely unknown until competition day. Placeholder at straight-section
# midpoints (physically reasonable, not mid-corner) -- OVERRIDE ONCE CONFIRMED ONSITE.
STOP_LOCATIONS_KM = [0.0, 0.95]  # Derived from user coordinates: 0.0km (Start/Finish) and 0.95km

# --- Scoring (Chapter I, Article 54e) ---
H2_NCV_KJ_PER_KG = 119930.0        # RULE-DERIVED, Art. 54e, net calorific value of hydrogen
H2_DENSITY_G_PER_L_STP = 0.08988   # RULE-DERIVED, Art. 54e, hydrogen density at STP
# No H2 cylinder capacity is specified anywhere in Chapter I or II -- confirmed absent.
# H2 volume is a pure objective to MINIMIZE, not a constraint to stay under.

# --- Cornering safety ---
CORNERING_FRICTION_MU = 0.85  # PLACEHOLDER (assumed dry-track friction coefficient), used for v_safe = sqrt(mu*g*R)
GRAVITY_M_S2 = 9.81

# --- Longitudinal limits (crude-twin phase only -- real values come from powertrain.py
#     once motor/FC/buffer are wired in; braking is not documented anywhere so this
#     stays a placeholder even after that) ---
ACCEL_MAX_MS2 = 0.833   # MEASURED-derived, EP.pdf's own 0-30km/h-in-10s design target (30/3.6/10)
BRAKE_MAX_MS2 = 3.0     # PLACEHOLDER (~0.3g, comfortable braking) -- not documented anywhere
STOP_DWELL_TIME_S = 1.0  # Art. 227 requires a full stop but specifies no dwell duration (set to 1.0s)
# PLACEHOLDER (generous, not tuned per-speed) -- the GA/PSO/CMA-ES gas/glide gene
# is chosen per 15 track segments, NOT aligned to the 2 mandatory-stop locations,
# so a segment straddling a stop has no way to know one is coming: confirmed in
# telemetry (2026-07-20), all 3 optimizers gas right up to ~4m before a stop, then
# have to slam BRAKE_MAX_MS2 to still make it. Forcing glide inside this lookahead
# (see simulate.py) makes every strategy physically stop-aware regardless of what
# the segment gene says, instead of relying on the optimizer to happen to discover
# it -- a safety floor, not a replacement for smarter (stop-aligned) segmentation.
STOP_GLIDE_LOOKAHEAD_M = 150.0
# Trial 2 (2026-07-24): corner-anticipation glide distance for the brake-minimising driver
# (Fuzzy). If a slower zone is within this many metres ahead, start coasting early so the car
# reaches the corner speed on drag instead of a late brake. 0 disables it (other strategies).
BRAKE_AVOID_LOOKAHEAD_M = 0.0   # Trial 2 REMOVED (2026-07-25): let Fuzzy brake naturally (0 disables the
                                # corner-anticipation glide). Physics/SEM rules unchanged.

# --- Powertrain candidate selection (default for the Days 3-4 milestone; hardware_search.py
#     later enumerates ALL motor x FC combos instead of hardcoding one) ---
DEFAULT_MOTOR_NAME = "Innotec Power 145-DZS48-010"   # highest measured efficiency of the 4 candidates (~93.7% peak)
DEFAULT_FC_NAME = "SZFC-1000"                        # real unit the team is using (2026-07-21, SZFC-1000.pdf) --
                                                      # replaces the earlier "G-HFCS 600W 24V" placeholder pick

# --- Two-motor (Urban Concept) powertrain: a high-torque acceleration motor + a
#     high-efficiency cruise motor, switched mid-run so each stays in its efficient
#     band. The switch is a driving-strategy lever, not fixed wiring -- see simulate.py. ---
ACCEL_MOTOR_NAME = "BLDC 650W"          # high-torque motor for launches/climbs (48V, ~953W peak)
CRUISE_MOTOR_NAME = "BG 42x30 dCore"    # high-efficiency low-power motor for cruising (24V, 64W continuous /
                                         # 156W peak -- corrected 2026-07-21, was mislabeled "42x45" with a
                                         # 226W peak that didn't match the real datasheet)
# "efficiency" = each step pick the most-efficient motor that can supply the demand
#   (Design B, maximises efficiency). "rule" = launch-from-stop / climb heuristic that
#   mirrors how a simple physical controller would actually switch (Design A). See simulate.py.
MOTOR_SELECT_MODE_DEFAULT = "efficiency"
# "rule" mode: accel motor is engaged while RELAUNCHING from a stop-and-go (v~0 -> cruise
# speed, i.e. off the two STOP_LOCATIONS_KM points and the standing start) OR while grade
# exceeds this climb threshold. Keyed to the stops, not a bare speed cut, because stop-and-go 2
# sits on a -1.75% descent -- you still launch there. PLACEHOLDER threshold, tune per track.
INCLINE_GRADE_THRESHOLD_PCT = 1.0
# Max time the accel motor stays engaged per launch (0 -> 30 km/h target). Design choice:
# 15 s (gentle, 0.56 m/s^2) is expected to sip less peak power than the original 10 s design
# target (0.83 m/s^2, ACCEL_MAX_MS2); the 10-vs-15 s tradeoff is compared in two_motor_compare.py.
MOTOR_ACCEL_WINDOW_S = 15.0
MOTOR_MIN_DWELL_S = 5.0                 # hysteresis: min time on a motor before switching again, so demand hovering near a
                                        #  crossover doesn't chatter the motors. A clip-forced switch (current motor can't
                                        #  supply the demand) overrides this. Updated to 5.0s per team request.

# Physical time the servo needs to actually swap the drive between the two motors. During this
# window the powertrain cannot deliver full traction: power ramps back from MOTOR_SWITCH_MIN_POWER_FRAC
# up to 1.0 as the servo completes, so every accel<->cruise handoff costs a little speed, time and H2.
# Real measured value from the two-motor servo rig. Configurable (tested at 0.5 / 1 / 2 / 3 s).
MOTOR_SWITCH_TIME_S = 0.5
MOTOR_SWITCH_MIN_POWER_FRAC = 0.35      # traction available at the instant a switch starts (0.35 -> 1.0 over the window)

# The accel motor (48V) sits directly on the main bus -- no conversion needed. The
# cruise motor (24V) needs a buck converter down from 48V, and that conversion has its
# own loss on top of the cruise motor's own electrical_power_w() (see
# powertrain.ConverterModel, applied only when the cruise motor is active in two-motor
# "rule"/"efficiency" mode). Real candidate datasheets (2026-07-22), but both converters
# are far oversized for our actual ~64-156W cruise load relative to their rated
# capacity (300-984W) -- their quoted efficiency is an extrapolation past the
# datasheet's own validated load floor, not a measured light-load point. See
# data/dcdc_candidates.csv's source notes for the specifics.
CRUISE_CONVERTER_NAME = "Querom DDL3050-48 (24V aux)"  # better size match (300W rated) than
                                                         # the ELECDAN alternative (984W rated)

# DP's (distance, speed) grid can't see MOTOR_ACCEL_WINDOW_S directly: two trajectories
# reaching the same distance+speed cell can have taken different elapsed times to get
# there, so a TIME-based relaunch window isn't a function of DP's state. Distance-since-
# last-stop IS a pure function of position alone (stops are at fixed locations), so
# optimize_dp.py approximates the accel-motor window this way instead -- see
# optimize_dp.compute_accel_availability(). PLACEHOLDER estimate: a launch reaching
# cruise speed (30 km/h) under ACCEL_MAX_MS2 covers ~42m in ~10s; continuing toward the
# real 15s cap (grade-limited launches, gentler accel_cap) covers more -- 100m is a
# round, generous approximation of that, not a measured value. This makes DP test a
# DISTANCE-based version of the rule, not an exact match to the TIME-based one
# simulate.py/mpc.py actually implement.
DP_RELAUNCH_DISTANCE_M = 100.0

# --- Buffer: real hardware now confirmed (2026-07-23, team chat) -- 3x Maxwell
#     BMOD0058 E016 C02 ultracapacitor modules IN SERIES (datasheet: 3003212.2), feeding
#     the ACCEL motor only (cruise motor draws straight from the FC, no buffer stage --
#     see simulate.py's FC-draw note below, NOT YET reflected in the physics). Per-module
#     datasheet values: 16V rated / 17V absolute max, 58-70F (61F typ), ESR 22-25 mOhm
#     (22 typ), 0.63 kg, 2.1 Wh, Pd (usable specific power) 2200 W/kg. 3-series stacking:
#     voltage triples (3x16=48V rated, matches the accel motor's direct 48V bus -- no
#     DC-DC needed, and comfortably under the 60V MAX_ELECTRICAL_VOLTAGE_V ceiling),
#     capacitance divides by 3 (61/3 = 20.3F typ), ESR triples (66 mOhm typ), mass triples
#     (1.89 kg), energy triples (E=0.5*C*V^2 scales as n for n-series at fixed per-module
#     energy: 3*2.1 = 6.3 Wh). Specific power (W/kg) is unchanged by series stacking, so
#     usable continuous power = 2200 W/kg * 1.89 kg = ~4158 W -- but that's an efficiency
#     figure, not a thermal limit; MAX_CHARGE/DISCHARGE_W below instead use the
#     datasheet's own "Maximum Continuous Current" spec (IDCMAX), which IS a thermal
#     rating: 23 ARMS at the DeltaT=40C design point (JUDGMENT CALL -- the sheet also
#     offers a cooler-running 14A/DeltaT=15C point; 23A chosen because it's close to what
#     the accel motor actually draws at peak, ~1.1kW/48V=~23A, so the cooler point would
#     already clip a normal launch) -- 23A * 48V = ~1104 W, symmetric for charge/discharge.
BUFFER_CAPACITY_WH_PLACEHOLDER = 6.3
BUFFER_MAX_CHARGE_W_PLACEHOLDER = 1104.0
BUFFER_MAX_DISCHARGE_W_PLACEHOLDER = 1104.0    # must cover peak motor electrical draw
# Round-trip eff. has no direct datasheet spec (supercaps aren't rated this way like
# batteries) -- derived from ESR loss at the 23A/48V continuous point: one-way eta = 1 -
# I*R/V = 1 - 23*0.066/48 = 0.968; round trip (charge then discharge) = 0.968^2 = 0.937.
BUFFER_ROUND_TRIP_EFF_PLACEHOLDER = 0.94
BUFFER_SOC_MIN_FRAC = 0.2
BUFFER_SOC_MAX_FRAC = 0.9
# These 6 constants no longer back a live physics class (powertrain.BufferModel was
# removed 2026-07-25 -- unused, superseded by hybrid_energy.py's real ESR-based supercap
# model). Still read by Stratelm-GUI/backend/registry.py to show the vehicle spec sheet
# an explicit, tagged PLACEHOLDER for this generic-buffer figure -- kept for that reason.
POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED = 0.90  # CONSERVATIVE PLACEHOLDER: 10% thermal loss through buffer
CORNERING_SCRUB_COEFF = 0.05                 # CONSERVATIVE PLACEHOLDER: 5% of lateral force becomes induced drag

# --- FC parasitic / balance-of-plant load (Art. 65: the fuel cell must power its own
#     auxiliary loads) -- PLACEHOLDER ballpark: FC controller board only. The hydrogen
#     sensor and shutoff solenoid valve moved OUT of this constant (see team's global
#     rule mastersheet, 2026-07): those are safety-shutoff components and must be
#     powered by the SEPARATE accessory/safety battery, not by the FC itself -- a
#     shutoff valve that depended on the FC it's meant to isolate would defeat its own
#     purpose. Not documented in any parameter PDF.
FC_PARASITIC_LOAD_W = 10.0

# --- HYBRID FUEL-CELL + SUPERCAPACITOR ENERGY SYSTEM -------------------------------
#     Real electrical architecture (2026-07 team update): the SZFC-1000 fuel cell runs
#     in PARALLEL with a supercapacitor bank, both feeding a DC-DC converter. The FC is
#     held at a STABLE, efficient operating point (its 500-570 W band) and the
#     supercapacitor absorbs the instantaneous load transients (launch peaks) and returns
#     energy during low-demand cruise -- so the FC never has to chase the spiky motor
#     demand. Hydrogen is then billed off the FC electrical energy at its fixed operating
#     efficiency, via Art. 54e's joulemeter formula. Set USE_HYBRID_SUPERCAP=False to fall
#     back to the previous per-step FC-efficiency-curve model.
USE_HYBRID_SUPERCAP = True
FC_HYBRID_OP_POWER_W = 558.0        # FC electrical output when ON (measured op point: 45 V, 12.4 A)
FC_HYBRID_BAND_W = (500.0, 570.0)   # FC stable operating band (the supercap covers anything outside)
FC_HYBRID_EFF = 0.62                # fixed FC efficiency at that operating point (measured, last table row)
# Trial 4 (2026-07-24): the FC cannot ramp fast (e.g. 800->1000 W over ~5 m is physically
# impossible), so its usable load is HARD-CAPPED at 600 W. The FC never sources more than this;
# the supercapacitor covers every transient above it. (Op point 558 W is already under the cap.)
FC_HYBRID_MAX_W = 600.0
# Trial 3 (2026-07-24): the supercap MAY charge above its start SOC during the lap while gliding
# (motor off / low bus demand) -- the FC banks the spare energy into the cap instead of idling.
# The charge ceiling during glide is this fraction of E_max (kept < 1.0 so it never hits V_max /
# overcharges). Outside glide the FC still tops out at the start SOC.
SUPERCAP_GLIDE_CHARGE_FRAC = 0.98
SUPERCAP_GLIDE_BUS_FRAC = 0.5       # "gliding" for charging = bus demand < this * FC op power

# Supercapacitor bank: Maxwell BMOD0058 E016 C02 (16 V, 58 F module), 3 modules in SERIES.
SUPERCAP_MODULE_C_F = 58.0          # module rated capacitance (min CR, datasheet)
SUPERCAP_MODULE_V = 16.0           # module rated voltage
SUPERCAP_MODULE_ESR_OHM = 0.022    # module ESR (typ 22 mOhm, datasheet)
SUPERCAP_N_SERIES = 3              # 3 modules in series -> 48 V bank
SUPERCAP_N_PARALLEL = 1
SUPERCAP_SOC_MIN_FRAC = 0.5        # do not discharge below 50% voltage (keeps 75% of energy usable)
# SEM Art. 56c(iii): the supercap voltage AFTER the run must be >= the voltage BEFORE it; if lower,
# the FC must recharge it back to the start voltage and that time is ADDED to the run time. So we do
# NOT start fully charged (a full cap can only drain and would always need recharging); we start a
# little below max -- leaving headroom so charging can never overcharge past V_max -- and the FC tops
# the cap back up to exactly the start SOC at the end (energy-conservative; the FC supplies all
# traction energy either way, so hydrogen is unchanged -- only a small recharge time is added).
SUPERCAP_SOC_START_FRAC = 0.90     # pre-run charge level (< 1.0 so recharge-to-start never overcharges)
SUPERCAP_OP_SWING_FRAC = 0.35      # FC load-levels the cap within [start-swing, start]; sized to buffer peaks

# --- Accessory battery load -- per the team's electrical diagram this is a SEPARATE
#     battery, not the FC/H2 path at all. Per the team's global rule mastersheet
#     (2026-07, Art. 56/57 joulemeter exemptions): horn, driver comms, driver instrument
#     display, and driver ventilation fan are all EXEMPT from joulemeter measurement --
#     do NOT add their wattage here (it would cost the H2 score for no reason). Only sum:
#     Lighting (Art. 50 mandatory running lights/turn indicators) + Wiper + Hydrogen
#     Sensor + H2 shutoff solenoid valve holding current (safety-critical, must run off
#     this separate battery per the mastersheet). PLACEHOLDER ballpark, continuous for
#     the whole attempt.
ACCESSORY_LOAD_W_CONTINUOUS = 15.0

# --- Regulatory ceilings from the team's global rule mastersheet (2026-07) --
#     RULE-DERIVED, not measured; used to flag/exclude non-compliant hardware candidates.
MAX_ELECTRICAL_VOLTAGE_V = 60.0   # whole-vehicle electrical system voltage limit
MAX_BUFFER_CAPACITY_WH = 1000.0   # battery/buffer capacity limit (current 200 Wh placeholder is well under)

# Art. 54e's own worked example states "0.5 = efficiency of the fuel cell" as the
# conversion factor for turning joulemeter-measured accessory-battery joules into an
# equivalent volume of hydrogen -- RULE-DERIVED (verified: reproduces the official
# example's 1.855 L result exactly), not a guess. Formula: h2_equiv_kg = (J / this) /
# (H2_NCV_KJ_PER_KG * 1000); h2_equiv_m3 = h2_equiv_kg / H2_DENSITY_G_PER_L_STP.
ART54E_ASSUMED_FC_EFFICIENCY_FOR_JOULEMETER = 0.5

# --- MPC (receding-horizon strategy controller; see MPC_SPEC.md) --------------
#     theta = the hyperparameters the GA/PSO OUTER loop tunes. Defaults below are a
#     hand-tuned starting point that produces a feasible (<35 min, 0 violations) run;
#     mpc_analyze.ipynb sweeps them for the best Art. 54e score. All PLACEHOLDER --
#     no measured optimum exists yet, they are pure design knobs.
#
#     Cost-function unit note: the H2 term is accumulated in GRAMS/step (~1e-4 g) while
#     the time term is in SECONDS/step (~0.1 s), so w_h2 must be several thousand x w_time
#     for hydrogen to actually dominate the decision -- that is why w_h2 defaults high.
MPC_THETA_DEFAULT = {
    "horizon_n": 25,      # steps of lookahead (~1 m/step) -- how far ahead the MPC plans
    "w_h2":      6000.0,  # weight on H2 grams over the horizon (primary objective, Art. 54e)
    "w_time":    1.0,     # weight on elapsed time (keeps the run under the 35-min cap)
    "w_track":   60.0,    # penalty for exceeding the safety speed ceiling
    "w_du":      2.0,     # command-smoothness penalty (anti-chatter)
    "w_drv":     0.0,     # weight on tracking the (predicted) driver setpoint -- 0 = ideal driver
    "alpha_drv": 0.3,     # driver-deviation correction gain (MPC_SPEC 6.3)
    "v_min_kmh": 18.0,    # floor speed the MPC will command on open track
    "v_max_kmh": 33.0,    # ceiling speed the MPC will command (within the safety ceiling)
}
MPC_N_CANDIDATES = 11                    # grid-enumeration candidate speeds per step (MPC_SPEC 3.5)
MPC_DRIVER_DEVIATION_THRESHOLD_MS = 1.0  # PLACEHOLDER -- |v_actual - v_cmd| above this triggers CORRECTION mode
MPC_DRIVER_BIAS_THRESHOLD_MS = 12.0      # PLACEHOLDER -- |cumulative deviation| above this flags a systematic driver bias
