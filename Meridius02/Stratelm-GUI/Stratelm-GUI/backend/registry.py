"""
Vehicle + track registries -- the "Garage". Stratelm-GUI started as a
single-car, single-track dashboard for the SEM Urban Concept H2 project, but
a team runs more than one vehicle and races at more than one venue over
time, so every physics parameter that used to live only in
digital_twin/config.py (mass, aero, powertrain limits, ...) is persisted here
as a named, editable vehicle profile, and every track-specific number
(GPS/turns source files, lap distance, attempt rules) as a named track
profile. digital_twin/config.py's module-level constants remain the
mechanism physics code actually reads at call time (see vehicle.py's
live-lookup fix) -- apply_vehicle()/apply_track() just set them from
whichever profile the GUI selected for a given run.

Each vehicle/track is a plain JSON document. No database: a team's whole
fleet is a handful of files, and JSON is easy to hand-edit or diff in git.
"""

import json
import os
import threading

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
VEHICLES_PATH = os.path.join(DATA_DIR, "vehicles.json")
TRACKS_PATH = os.path.join(DATA_DIR, "tracks.json")

_lock = threading.Lock()

VALID_TAGS = ["MEASURED", "MEASURED-CFD", "RULE-DERIVED", "PLACEHOLDER", "PLACEHOLDER-CHOICE", "ASSUMPTION", "DERIVED"]


def _f(value, unit=None, tag="PLACEHOLDER", note=None):
    entry = {"value": value, "tag": tag}
    if unit is not None:
        entry["unit"] = unit
    if note is not None:
        entry["note"] = note
    return entry


def _seed_vehicles(config):
    """First-run seed: the SEM Urban Concept H2 car, values copied verbatim
    from digital_twin/config.py so behavior doesn't change for existing users."""
    return {
        "urban-h2-2027": {
            "id": "urban-h2-2027",
            "name": "Urban Concept H2 2027",
            "energy_class": "hydrogen_fuel_cell",
            "notes": "SEM 2027 Lusail entry -- migrated from digital_twin/config.py",
            "default_motor": config.DEFAULT_MOTOR_NAME,
            "default_motor_accel": config.ACCEL_MOTOR_NAME,
            "default_motor_cruise": config.CRUISE_MOTOR_NAME,
            "default_cruise_converter": config.CRUISE_CONVERTER_NAME,
            "default_fc": config.DEFAULT_FC_NAME,
            "motor_catalog_csv": "data/motor_candidates.csv",
            "fc_catalog_csv": "data/fc_candidates.csv",
            "aero_cda_by_geometry": config.AERO_CDA_CFD,
            "fields": {
                "vehicle_mass_kg": _f(config.MASS_VEHICLE_KG, "kg", "MEASURED"),
                "driver_mass_kg": _f(config.MASS_DRIVER_KG, "kg", "RULE-DERIVED"),
                "cruise_target_kmh": _f(config.V_TARGET_AVG_KMH_CRUISE, "km/h", "MEASURED",
                                         "EP.pdf cruise design point; can be disabled per-run to go uncapped"),
                "crr": _f(config.CRR, tag="PLACEHOLDER"),
                "body_geometry": _f(config.AERO_BODY_GEOMETRY, tag="PLACEHOLDER-CHOICE"),
                "drivetrain_efficiency": _f(0.83, tag="MEASURED", note="Dikalibrasi dari telemetri cruise nyata (digital_twin/calibrate.py) = 0.83"),
                "wheel_radius_m": _f(config.WHEEL_RADIUS_M, "m", "MEASURED",
                                      "only feeds gear-ratio calc, not exercised by the current simulator phase"),
                "frontal_area_m2": _f(config.AERO_FRONTAL_AREA_CFD_M2, "m^2", "MEASURED-CFD"),
                "accel_max_ms2": _f(config.ACCEL_MAX_MS2, "m/s^2", "MEASURED"),
                "brake_max_ms2": _f(config.BRAKE_MAX_MS2, "m/s^2", "PLACEHOLDER"),
                "stop_dwell_time_s": _f(config.STOP_DWELL_TIME_S, "s", "PLACEHOLDER",
                                         "Art. 227 requires a full stop but specifies no dwell duration"),
                "cornering_scrub_coeff": _f(config.CORNERING_SCRUB_COEFF, tag="PLACEHOLDER"),
                "cornering_friction_mu": _f(config.CORNERING_FRICTION_MU, tag="PLACEHOLDER",
                                             note="bakes into a track's precomputed v_safe_kmh -- not read live by /api/simulate"),
                "fc_parasitic_load_w": _f(config.FC_PARASITIC_LOAD_W, "W", "PLACEHOLDER"),
                "accessory_load_w": _f(config.ACCESSORY_LOAD_W_CONTINUOUS, "W", "PLACEHOLDER"),
                "buffer_path_efficiency": _f(config.POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED, tag="PLACEHOLDER",
                                              note="flat thermal-loss derate through the buffer path"),
                "buffer_capacity_wh": _f(config.BUFFER_CAPACITY_WH_PLACEHOLDER, "Wh", "PLACEHOLDER",
                                          note="buffer SOC/capacity scheduling not yet exercised by simulate()"),
                "buffer_max_charge_w": _f(config.BUFFER_MAX_CHARGE_W_PLACEHOLDER, "W", "PLACEHOLDER"),
                "buffer_max_discharge_w": _f(config.BUFFER_MAX_DISCHARGE_W_PLACEHOLDER, "W", "PLACEHOLDER"),
                "buffer_round_trip_eff": _f(config.BUFFER_ROUND_TRIP_EFF_PLACEHOLDER, tag="PLACEHOLDER"),
                "buffer_soc_min_frac": _f(config.BUFFER_SOC_MIN_FRAC, tag="PLACEHOLDER",
                                           note="floor state-of-charge fraction powertrain.py won't discharge below"),
                "buffer_soc_max_frac": _f(config.BUFFER_SOC_MAX_FRAC, tag="PLACEHOLDER",
                                           note="ceiling state-of-charge fraction powertrain.py won't charge above"),
                "max_electrical_voltage_v": _f(config.MAX_ELECTRICAL_VOLTAGE_V, "V", "RULE-DERIVED"),
                "max_buffer_capacity_wh": _f(config.MAX_BUFFER_CAPACITY_WH, "Wh", "RULE-DERIVED"),
            },
        }
    }


def _seed_tracks(config):
    return {
        "lusail-urban-2027": {
            "id": "lusail-urban-2027",
            "name": "Lusail Urban Circuit",
            "location": "Lusail, Qatar",
            "notes": "SEM 2027 attempt track -- migrated from digital_twin/track.py + config.py",
            "coordinates_csv": "data/sem_apme_2025-track_coordinates.csv",
            "turns_csv": "data/turns.csv",
            "edges_csv": "data/track_edges_imagery.csv",
            "racing_line_csv": "data/racing_line.csv",
            "lap_distance_km": config.LAP_DISTANCE_KM,
            "total_laps": config.TOTAL_LAPS,
            "total_distance_km": config.TOTAL_DISTANCE_KM,
            "max_attempt_time_min": config.MAX_ATTEMPT_TIME_MIN,
            "stops_per_lap": config.STOPS_PER_LAP,
            "stop_locations_km": config.STOP_LOCATIONS_KM,
        }
    }


def _load(path: str, seed_fn, config) -> dict:
    with _lock:
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        seeded = seed_fn(config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(seeded, f, indent=2)
        return seeded


def _save(path: str, data: dict):
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def load_vehicles(config) -> dict:
    return _load(VEHICLES_PATH, _seed_vehicles, config)


def load_tracks(config) -> dict:
    return _load(TRACKS_PATH, _seed_tracks, config)


def save_vehicles(data: dict):
    _save(VEHICLES_PATH, data)


def save_tracks(data: dict):
    _save(TRACKS_PATH, data)


def slugify(name: str, existing: dict) -> str:
    base = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    while "--" in base:
        base = base.replace("--", "-")
    base = base or "item"
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


FIELD_TO_CONFIG = {
    "vehicle_mass_kg": "MASS_VEHICLE_KG",
    "driver_mass_kg": "MASS_DRIVER_KG",
    "cruise_target_kmh": "V_TARGET_AVG_KMH_CRUISE",
    "crr": "CRR",
    "body_geometry": "AERO_BODY_GEOMETRY",
    "drivetrain_efficiency": "DRIVETRAIN_EFFICIENCY_ASSUMED",
    "wheel_radius_m": "WHEEL_RADIUS_M",
    "frontal_area_m2": "AERO_FRONTAL_AREA_CFD_M2",
    "accel_max_ms2": "ACCEL_MAX_MS2",
    "brake_max_ms2": "BRAKE_MAX_MS2",
    "stop_dwell_time_s": "STOP_DWELL_TIME_S",
    "cornering_scrub_coeff": "CORNERING_SCRUB_COEFF",
    "cornering_friction_mu": "CORNERING_FRICTION_MU",
    "fc_parasitic_load_w": "FC_PARASITIC_LOAD_W",
    "accessory_load_w": "ACCESSORY_LOAD_W_CONTINUOUS",
    "buffer_path_efficiency": "POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED",
    "buffer_capacity_wh": "BUFFER_CAPACITY_WH_PLACEHOLDER",
    "buffer_max_charge_w": "BUFFER_MAX_CHARGE_W_PLACEHOLDER",
    "buffer_max_discharge_w": "BUFFER_MAX_DISCHARGE_W_PLACEHOLDER",
    "buffer_round_trip_eff": "BUFFER_ROUND_TRIP_EFF_PLACEHOLDER",
    "buffer_soc_min_frac": "BUFFER_SOC_MIN_FRAC",
    "buffer_soc_max_frac": "BUFFER_SOC_MAX_FRAC",
    "max_electrical_voltage_v": "MAX_ELECTRICAL_VOLTAGE_V",
    "max_buffer_capacity_wh": "MAX_BUFFER_CAPACITY_WH",
}


def apply_vehicle(config, vehicle: dict) -> dict:
    """Set every config.* attribute the physics code reads live from this
    vehicle's saved profile. Returns the prior values so the caller can
    restore them after the request (config is process-global state)."""
    orig = {}
    fields = vehicle.get("fields", {})
    for field, config_attr in FIELD_TO_CONFIG.items():
        if field not in fields:
            continue
        orig[config_attr] = getattr(config, config_attr)
        setattr(config, config_attr, fields[field]["value"])
    orig["MASS_TOTAL_KG"] = config.MASS_TOTAL_KG
    config.MASS_TOTAL_KG = fields["vehicle_mass_kg"]["value"] + fields["driver_mass_kg"]["value"]
    # NOTE: use truthiness, not "in" / dict.get(key, default) -- a Pydantic
    # model_dump() includes unset Optional fields as real keys with value
    # None, so "key in vehicle" is True even when nothing was provided and
    # dict.get(key, default) never falls back to `default` for an explicit
    # None value either.
    if vehicle.get("aero_cda_by_geometry"):
        orig["AERO_CDA_CFD"] = config.AERO_CDA_CFD
        config.AERO_CDA_CFD = vehicle["aero_cda_by_geometry"]
    orig["DEFAULT_MOTOR_NAME"] = config.DEFAULT_MOTOR_NAME
    orig["DEFAULT_FC_NAME"] = config.DEFAULT_FC_NAME
    config.DEFAULT_MOTOR_NAME = vehicle.get("default_motor") or config.DEFAULT_MOTOR_NAME
    config.DEFAULT_FC_NAME = vehicle.get("default_fc") or config.DEFAULT_FC_NAME
    return orig


def restore_config(config, orig: dict):
    for attr, value in orig.items():
        setattr(config, attr, value)


def apply_track(config, track: dict) -> dict:
    """Set the config.* attributes that describe the attempt format (lap
    length, laps, time limit, stops) for this track. The GPS/turns/edges CSV
    paths are NOT set on config -- they're passed straight into
    track.build_track_profile()."""
    orig = dict(
        LAP_DISTANCE_KM=config.LAP_DISTANCE_KM,
        TOTAL_LAPS=config.TOTAL_LAPS,
        TOTAL_DISTANCE_KM=config.TOTAL_DISTANCE_KM,
        MAX_ATTEMPT_TIME_MIN=config.MAX_ATTEMPT_TIME_MIN,
        STOPS_PER_LAP=config.STOPS_PER_LAP,
        STOP_LOCATIONS_KM=config.STOP_LOCATIONS_KM,
    )
    config.LAP_DISTANCE_KM = track.get("lap_distance_km", config.LAP_DISTANCE_KM)
    config.TOTAL_LAPS = track.get("total_laps", config.TOTAL_LAPS)
    config.TOTAL_DISTANCE_KM = track.get("total_distance_km", config.TOTAL_DISTANCE_KM)
    config.MAX_ATTEMPT_TIME_MIN = track.get("max_attempt_time_min", config.MAX_ATTEMPT_TIME_MIN)
    config.STOPS_PER_LAP = track.get("stops_per_lap", config.STOPS_PER_LAP)
    config.STOP_LOCATIONS_KM = track.get("stop_locations_km", config.STOP_LOCATIONS_KM)
    return orig
