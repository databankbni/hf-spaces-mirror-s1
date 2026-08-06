import os
import sys
import json
import time
import asyncio
import threading
from dataclasses import replace
from typing import Optional

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add mqtt module path to sys.path so clean_telemetry & assign_laps are always importable
_mqtt_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'mqtt'))
if os.path.isdir(_mqtt_dir) and _mqtt_dir not in sys.path:
    sys.path.append(_mqtt_dir)
if '/app/mqtt' not in sys.path:
    sys.path.append('/app/mqtt')

# digital_twin now lives in a separate repo, installed editable (`pip install
# -e` there) so `import digital_twin` resolves regardless of cwd. Its modules
# still use paths like "data/motor_candidates.csv" relative to ITS OWN repo
# root (not this file, and not this repo) -- once imported, PROJECT_ROOT is
# derived from where the package actually lives on disk, and we chdir there
# so those relative reads keep resolving no matter where uvicorn is launched
# from. This repo's own GUI-state paths (attempts.json/tracks.json/vehicles.json)
# are resolved separately in registry.py/attempts.py relative to THIS file,
# unaffected by the chdir since they use absolute paths.
try:
    import digital_twin.config as config
    import digital_twin.powertrain as pt
    import digital_twin.simulate as sim
    import digital_twin.track as track_mod
    import digital_twin.vehicle as vehicle
    import digital_twin.weather as weather
    import digital_twin.telemetry as telemetry
    import digital_twin as _digital_twin_pkg
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(_digital_twin_pkg.__file__)))
    os.chdir(PROJECT_ROOT)
    DIGITAL_TWIN_AVAILABLE = True
except ImportError as e:
    print(f"Warning: digital_twin not fully loaded: {e}")
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    DIGITAL_TWIN_AVAILABLE = False

# dp_policy/driver_advisory are newer digital_twin modules (live driver
# recommendation tables) -- guarded separately so an older digital_twin
# checkout without them yet doesn't take down the whole backend.
try:
    import driver_advisory_bridge
    ADVISORY_AVAILABLE = DIGITAL_TWIN_AVAILABLE
except ImportError:
    ADVISORY_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt  # noqa: F401 -- availability probe only, telemetry_capture owns the real client
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False

import registry
import attempts as attempts_mod
import telemetry_capture
import optimizer_jobs

app = FastAPI(title="Stratelm Telemetry Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Physics/benchmark data (motor & FC candidates, track CSVs, GA/PSO/CMA/DP
# seed telemetry, racing_line.csv, ...) lives in the digital_twin repo, not
# this one -- DATA_DIR must follow the same PROJECT_ROOT the digital_twin
# import resolved above, not this file's own location.
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# ---------------------------------------------------------------------------
# Garage: every vehicle spec and every track lives in data/vehicles.json and
# data/tracks.json (see registry.py) instead of being hardcoded to the one
# SEM Urban Concept H2 car + Lusail circuit this dashboard started with. A
# /api/simulate call selects a vehicle_id + track_id; the full 4-lap track
# profile is expensive to rebuild (~9s), so it's cached per track.
# ---------------------------------------------------------------------------
_TRACK_CACHE: dict = {}
_SIM_LOCK = threading.Lock()


def get_full_track(track: dict):
    key = track["id"]
    if key not in _TRACK_CACHE:
        profile_1lap = track_mod.build_track_profile(
            save=False,
            coordinates_csv=track.get("coordinates_csv"),
            turns_csv=track.get("turns_csv"),
            edges_csv=track.get("edges_csv"),
            stop_locations_km=track.get("stop_locations_km"),
        )
        _TRACK_CACHE[key] = sim.build_full_attempt_track(
            profile_1lap, laps=track.get("total_laps", config.TOTAL_LAPS))
    return _TRACK_CACHE[key]


def _resolve_data_path(path: str) -> str:
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))


def _validate_data_csv(path: str) -> Optional[str]:
    full = _resolve_data_path(path)
    if not full.startswith(DATA_DIR):
        return f"'{path}' must be under the data/ directory"
    if not os.path.isfile(full):
        return f"'{path}' does not exist"
    return None


# ---------------------------------------------------------------------------
# Live Telemetry: MQTT bridge (telemetry_capture.py). Mirrors the same
# broker/topics the download/MQTT logger (log.py) uses for the real car --
# this dashboard is a second subscriber, it never publishes. Nothing here
# fabricates data: if no publisher is on the broker, state stays "offline"
# with empty payloads, exactly like a real race-day dashboard before the car
# powers on. Broker/topics/QoS are runtime-configurable from the GUI.
# ---------------------------------------------------------------------------
bridge = telemetry_capture.TelemetryBridge()
simulator = telemetry_capture.SimulatorManager()


def _snapshot_with_advisory() -> dict:
    """bridge.snapshot() plus a live "what should the driver do right now"
    recommendation (digital_twin.dp_policy + digital_twin.driver_advisory),
    computed off the same snapshot's distance/speed. Every consumer of
    bridge.snapshot() (the /ws/telemetry stream and the REST status/connect/
    disconnect/record endpoints) goes through this instead, so the advisory
    is available everywhere for free."""
    snap = bridge.snapshot()
    snap["advisory"] = driver_advisory_bridge.compute_advisory(snap["latest"]) if ADVISORY_AVAILABLE else {"available": False}
    return snap


@app.on_event("startup")
def _startup():
    bridge.connect()
    # NOT auto-started: the field simulator is a deliberate, visible action
    # from the GUI (Start Simulator button), never something that's just
    # running because the backend happened to boot.


@app.on_event("shutdown")
def _shutdown():
    simulator.stop()


@app.get("/api/health")
def health_check():
    return {"status": "ok", "digital_twin_loaded": DIGITAL_TWIN_AVAILABLE, "mqtt_available": PAHO_AVAILABLE}


class AdvisoryModeRequest(BaseModel):
    mode: str  # "dynamic" or "ga_strict"


@app.get("/api/telemetry/advisory-mode")
def get_advisory_mode():
    """Current driver-advisory mode: "dynamic" (current-strategy prefers a live MPC
    re-solve every call) or "ga_strict" (current-strategy is a pure static lookup
    against GA's recorded plan, never calls MPC). next_turn/next_stop are GA-sourced
    in both modes already -- this switch only affects the current-strategy field."""
    if not ADVISORY_AVAILABLE:
        return {"mode": None, "available": False}
    return {"mode": driver_advisory_bridge.get_advisory_mode(), "available": True}


@app.post("/api/telemetry/advisory-mode")
def set_advisory_mode(body: AdvisoryModeRequest):
    if not ADVISORY_AVAILABLE:
        return {"success": False, "error": "advisory module not available"}
    try:
        mode = driver_advisory_bridge.set_advisory_mode(body.mode)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "mode": mode}


class SimulatorStartRequest(BaseModel):
    gps: bool = True
    track_id: Optional[str] = None


@app.post("/api/telemetry/simulator/start")
def start_simulator(body: SimulatorStartRequest):
    ok, error = simulator.start(gps=body.gps, track_id=body.track_id)
    return {"success": ok, "error": error, **simulator.status()}


@app.post("/api/telemetry/simulator/stop")
def stop_simulator():
    ok, error = simulator.stop()
    return {"success": ok, "error": error, **simulator.status()}


@app.get("/api/telemetry/simulator/status")
def simulator_status():
    return simulator.status()


class MqttConfig(BaseModel):
    broker_host: Optional[str] = None
    broker_port: Optional[int] = None
    car_topic: Optional[str] = None
    gps_topic: Optional[str] = None
    qos: Optional[int] = None


@app.post("/api/telemetry/configure")
def configure_telemetry(cfg: MqttConfig):
    """Update broker/topics/QoS. Does NOT reconnect by itself -- call
    /api/telemetry/connect afterwards to apply (matches an explicit
    "Apply & Reconnect" button rather than silently dropping the session)."""
    bridge.configure(broker_host=cfg.broker_host, broker_port=cfg.broker_port,
                      car_topic=cfg.car_topic, gps_topic=cfg.gps_topic, qos=cfg.qos)
    return _snapshot_with_advisory()


@app.post("/api/telemetry/connect")
def connect_telemetry():
    bridge.connect()
    return _snapshot_with_advisory()


@app.post("/api/telemetry/disconnect")
def disconnect_telemetry():
    bridge.disconnect()
    return _snapshot_with_advisory()


@app.post("/api/telemetry/record/start")
def start_recording():
    bridge.start_recording()
    return _snapshot_with_advisory()


class SaveRecordingRequest(BaseModel):
    name: str
    vehicle_id: Optional[str] = None
    track_id: Optional[str] = None
    notes: str = ""


@app.post("/api/telemetry/record/stop")
def stop_recording(body: SaveRecordingRequest):
    """Stops buffering and immediately runs mqtt/clean_telemetry.py's cleaner
    over whatever was captured (car+GPS nearest-timestamp merged if both
    topics produced data), then registers it as a real Attempt."""
    rows, car_topic, gps_topic, duration_s = bridge.stop_recording()
    doc, error = telemetry_capture.save_recording_as_attempt(
        rows, car_topic, gps_topic, name=body.name, vehicle_id=body.vehicle_id,
        track_id=body.track_id, notes=body.notes)
    if error:
        return {"success": False, "error": error}
    if doc.get("summary"):
        doc["summary"]["duration_s"] = round(duration_s, 1)
        attempts = attempts_mod.load_attempts()
        attempts[doc["id"]] = doc
        attempts_mod.save_attempts(attempts)
    return {"success": True, "attempt": doc}


@app.post("/api/telemetry/record/discard")
def discard_recording():
    bridge.discard_recording()
    return _snapshot_with_advisory()


# ---------------------------------------------------------------------------
# Garage -- vehicles
# ---------------------------------------------------------------------------
class VehicleFieldValue(BaseModel):
    value: float | str
    unit: Optional[str] = None
    tag: str = "PLACEHOLDER"
    note: Optional[str] = None


class VehicleIn(BaseModel):
    name: str
    energy_class: str = "hydrogen_fuel_cell"
    notes: str = ""
    default_motor: Optional[str] = None
    default_motor_accel: Optional[str] = None
    default_motor_cruise: Optional[str] = None
    default_cruise_converter: Optional[str] = None
    default_fc: Optional[str] = None
    motor_catalog_csv: Optional[str] = None
    fc_catalog_csv: Optional[str] = None
    aero_cda_by_geometry: Optional[dict] = None
    fields: dict


class TagOnly(BaseModel):
    tag: str


@app.get("/api/vehicles")
def list_vehicles():
    if not DIGITAL_TWIN_AVAILABLE:
        return {"vehicles": [], "valid_tags": registry.VALID_TAGS}
    vehicles = registry.load_vehicles(config)
    out = []
    for v in vehicles.values():
        f = v.get("fields", {})
        out.append({
            "id": v["id"],
            "name": v["name"],
            "energy_class": v.get("energy_class"),
            "notes": v.get("notes", ""),
            "vehicle_mass_kg": f.get("vehicle_mass_kg", {}).get("value"),
            "driver_mass_kg": f.get("driver_mass_kg", {}).get("value"),
            "default_motor": v.get("default_motor"),
            "default_motor_accel": v.get("default_motor_accel"),
            "default_motor_cruise": v.get("default_motor_cruise"),
            "default_cruise_converter": v.get("default_cruise_converter"),
            "default_fc": v.get("default_fc"),
        })
    return {"vehicles": out, "valid_tags": registry.VALID_TAGS}


def compute_powertrain_efficiency(v: dict, speed_kmh: float = 30.0) -> Optional[dict]:
    if not DIGITAL_TWIN_AVAILABLE:
        return None
    try:
        import digital_twin.powertrain as pt
        import digital_twin.vehicle as vehicle_mod
        import digital_twin.weather as weather_mod

        physics_root = os.path.dirname(os.path.dirname(os.path.abspath(pt.__file__)))
        data_dir = os.path.join(physics_root, 'data')

        motor_csv = os.path.join(data_dir, 'motor_candidates.csv')
        fc_csv = os.path.join(data_dir, 'fc_candidates.csv')

        motors = pt.load_motors(motor_csv)
        fuel_cells = pt.load_fuel_cells(fc_csv)

        motor_name = v.get('default_motor_cruise') or v.get('default_motor') or config.CRUISE_MOTOR_NAME
        fc_name = v.get('default_fc') or config.DEFAULT_FC_NAME
        converter_name = v.get('default_cruise_converter') or config.CRUISE_CONVERTER_NAME

        motor = motors.get(motor_name)
        fc = fuel_cells.get(fc_name)
        if not motor or not fc:
            return None
        converter = pt.load_converters().get(converter_name)

        fields = v.get('fields', {})
        drivetrain_eff = float(fields.get('drivetrain_efficiency', {}).get('value', 0.80))
        buffer_eff = float(fields.get('buffer_path_efficiency', {}).get('value', 0.90))
        fc_parasitic_w = float(fields.get('fc_parasitic_load_w', {}).get('value', 10.0))

        scenario = weather_mod.WEATHER_CALM if hasattr(weather_mod, "WEATHER_CALM") else weather_mod.WeatherScenario("calm", 17.5, 0.65, 1013.25, 0.0, 0.0, "", "")
        f_res = vehicle_mod.resistance_force_n(v_kmh=speed_kmh, grade_pct=0.0, scenario=scenario, track_heading_deg=0.0)
        v_ms = speed_kmh / 3.6
        p_wheel_w = max(0.1, f_res * v_ms)

        p_motor_mech_w = p_wheel_w / drivetrain_eff if drivetrain_eff > 0 else p_wheel_w
        p_motor_elec_w, _ = motor.electrical_power_w(p_motor_mech_w)
        # This motor (default_motor_cruise) is assumed to be the 24V cruise motor of a
        # two-motor split -- it draws through a buck converter off the 48V bus, on top
        # of its own electrical draw (see digital_twin.config.CRUISE_CONVERTER_NAME).
        converter_eff = converter.efficiency_at_power(p_motor_elec_w) if converter else 1.0
        p_bus_elec_w = converter.input_power_w(p_motor_elec_w) if converter else p_motor_elec_w
        p_fc_elec_w = (p_bus_elec_w / buffer_eff if buffer_eff > 0 else p_bus_elec_w) + fc_parasitic_w
        fc_eff = fc.efficiency_at_power(p_fc_elec_w)
        if fc_eff <= 0:
            return None
        chemical_power_w = p_fc_elec_w / fc_eff
        overall_eff = p_wheel_w / chemical_power_w

        motor_eff = (p_motor_mech_w / p_motor_elec_w) if p_motor_elec_w > 0 else 0.0

        return {
            "speed_kmh": speed_kmh,
            "p_wheel_w": round(p_wheel_w, 2),
            "p_motor_mech_w": round(p_motor_mech_w, 2),
            "p_motor_elec_w": round(p_motor_elec_w, 2),
            "p_bus_elec_w": round(p_bus_elec_w, 2),
            "p_fc_elec_w": round(p_fc_elec_w, 2),
            "chemical_power_w": round(chemical_power_w, 2),
            "drivetrain_eff_pct": round(drivetrain_eff * 100, 1),
            "motor_eff_pct": round(motor_eff * 100, 1),
            "converter_eff_pct": round(converter_eff * 100, 1) if converter else None,
            "buffer_eff_pct": round(buffer_eff * 100, 1),
            "fc_eff_pct": round(fc_eff * 100, 1),
            "overall_eff_pct": round(overall_eff * 100, 1),
            "motor_name": motor.name,
            "fc_name": fc.name,
            "converter_name": converter.name if converter else None,
        }
    except Exception as err:
        print(f"Error computing powertrain efficiency: {err}")
        return None


@app.get("/api/vehicles/{vehicle_id}")
def get_vehicle(vehicle_id: str):
    vehicles = registry.load_vehicles(config)
    v = vehicles.get(vehicle_id)
    if not v:
        return {"error": f"vehicle '{vehicle_id}' not found"}
    out = dict(v)
    out["derived_powertrain_efficiency"] = compute_powertrain_efficiency(v)
    return out


@app.post("/api/vehicles/powertrain-efficiency")
def calc_powertrain_efficiency(v: dict):
    res = compute_powertrain_efficiency(v)
    return {"efficiency": res}


@app.post("/api/vehicles")
def create_vehicle(body: VehicleIn):
    vehicles = registry.load_vehicles(config)
    vid = registry.slugify(body.name, vehicles)
    vehicle_doc = body.model_dump()
    vehicle_doc["id"] = vid
    vehicles[vid] = vehicle_doc
    registry.save_vehicles(vehicles)
    return vehicle_doc


@app.put("/api/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: str, body: VehicleIn):
    vehicles = registry.load_vehicles(config)
    if vehicle_id not in vehicles:
        return {"error": f"vehicle '{vehicle_id}' not found"}
    vehicle_doc = body.model_dump()
    vehicle_doc["id"] = vehicle_id
    vehicles[vehicle_id] = vehicle_doc
    registry.save_vehicles(vehicles)
    return vehicle_doc


@app.delete("/api/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: str):
    vehicles = registry.load_vehicles(config)
    if vehicle_id not in vehicles:
        return {"success": False, "error": f"vehicle '{vehicle_id}' not found"}
    if len(vehicles) <= 1:
        return {"success": False, "error": "cannot delete the last remaining vehicle"}
    del vehicles[vehicle_id]
    registry.save_vehicles(vehicles)
    return {"success": True}


@app.post("/api/vehicles/{vehicle_id}/fields/{field}/tag")
def set_vehicle_field_tag(vehicle_id: str, field: str, body: TagOnly):
    if body.tag not in registry.VALID_TAGS:
        return {"success": False, "error": f"invalid tag '{body.tag}', expected one of {registry.VALID_TAGS}"}
    vehicles = registry.load_vehicles(config)
    v = vehicles.get(vehicle_id)
    if not v or field not in v.get("fields", {}):
        return {"success": False, "error": "vehicle or field not found"}
    v["fields"][field]["tag"] = body.tag
    registry.save_vehicles(vehicles)
    return {"success": True}


# ---------------------------------------------------------------------------
# Garage -- tracks
# ---------------------------------------------------------------------------
class TrackIn(BaseModel):
    name: str
    location: str = ""
    notes: str = ""
    coordinates_csv: str
    turns_csv: str
    edges_csv: str
    racing_line_csv: Optional[str] = None
    lap_distance_km: float
    total_laps: int
    total_distance_km: float
    max_attempt_time_min: float
    stops_per_lap: int
    stop_locations_km: list = []


@app.get("/api/tracks")
def list_tracks():
    tracks = registry.load_tracks(config) if DIGITAL_TWIN_AVAILABLE else {}
    return {"tracks": list(tracks.values())}


@app.get("/api/tracks/{track_id}")
def get_track(track_id: str):
    tracks = registry.load_tracks(config)
    t = tracks.get(track_id)
    if not t:
        return {"error": f"track '{track_id}' not found"}
    return t


@app.post("/api/tracks")
def create_track(body: TrackIn):
    for p in (body.coordinates_csv, body.turns_csv, body.edges_csv):
        err = _validate_data_csv(p)
        if err:
            return {"success": False, "error": err}
    tracks = registry.load_tracks(config)
    tid = registry.slugify(body.name, tracks)
    track_doc = body.model_dump()
    track_doc["id"] = tid
    tracks[tid] = track_doc
    registry.save_tracks(tracks)
    return track_doc


@app.put("/api/tracks/{track_id}")
def update_track(track_id: str, body: TrackIn):
    tracks = registry.load_tracks(config)
    if track_id not in tracks:
        return {"error": f"track '{track_id}' not found"}
    for p in (body.coordinates_csv, body.turns_csv, body.edges_csv):
        err = _validate_data_csv(p)
        if err:
            return {"success": False, "error": err}
    track_doc = body.model_dump()
    track_doc["id"] = track_id
    tracks[track_id] = track_doc
    registry.save_tracks(tracks)
    _TRACK_CACHE.pop(track_id, None)
    _TRACK_ANALYSIS_CACHE.pop(track_id, None)
    _STOP_POINTS_CACHE.pop(track_id, None)
    return track_doc


@app.delete("/api/tracks/{track_id}")
def delete_track(track_id: str):
    tracks = registry.load_tracks(config)
    if track_id not in tracks:
        return {"success": False, "error": f"track '{track_id}' not found"}
    if len(tracks) <= 1:
        return {"success": False, "error": "cannot delete the last remaining track"}
    del tracks[track_id]
    registry.save_tracks(tracks)
    _TRACK_CACHE.pop(track_id, None)
    _TRACK_ANALYSIS_CACHE.pop(track_id, None)
    _STOP_POINTS_CACHE.pop(track_id, None)
    return {"success": True}


@app.get("/api/data-files")
def list_data_files():
    """CSV files under data/ -- lets the track-creation form offer a picker
    instead of free-typed paths (GPS/turns/width digitization is a data-eng
    task done outside the GUI; this just points a new track at the results)."""
    files = []
    for root, _, names in os.walk(DATA_DIR):
        for n in names:
            if n.lower().endswith(".csv"):
                rel = os.path.relpath(os.path.join(root, n), PROJECT_ROOT).replace("\\", "/")
                files.append(rel)
    return {"files": sorted(files)}


# ---------------------------------------------------------------------------
# Motors / fuel cells / weather (motor & FC catalogs are shared CSVs across
# vehicles by default, but a vehicle can point at its own catalog file)
# ---------------------------------------------------------------------------
@app.get("/api/motors")
def get_motors(vehicle_id: Optional[str] = None):
    if not DIGITAL_TWIN_AVAILABLE:
        return {"motors": []}
    path = pt.MOTOR_CSV
    default_name = config.DEFAULT_MOTOR_NAME
    if vehicle_id:
        v = registry.load_vehicles(config).get(vehicle_id)
        if v:
            path = v.get("motor_catalog_csv") or path
            default_name = v.get("default_motor") or default_name
    motors = pt.load_motors(path)
    return {
        "motors": [
            {
                "name": name,
                "voltage_v": float(m.voltage_v),
                "max_mech_power_w": m.max_mech_power_w(),
                "rpm_range": m.rpm_range(),
            }
            for name, m in motors.items()
        ],
        "default": default_name,
    }


@app.get("/api/fuel-cells")
def get_fuel_cells(vehicle_id: Optional[str] = None):
    if not DIGITAL_TWIN_AVAILABLE:
        return {"fuel_cells": []}
    path = pt.FC_CSV
    default_name = config.DEFAULT_FC_NAME
    if vehicle_id:
        v = registry.load_vehicles(config).get(vehicle_id)
        if v:
            path = v.get("fc_catalog_csv") or path
            default_name = v.get("default_fc") or default_name
    fcs = pt.load_fuel_cells(path)
    return {
        "fuel_cells": [
            {"name": name, "rated_power_w": float(fc.rated_power_w), "has_efficiency_curve": fc.has_efficiency_curve()}
            for name, fc in fcs.items()
        ],
        "default": default_name,
    }


@app.get("/api/converters")
def get_converters():
    """DC/DC buck converters for the two-motor cruise-motor rail (48V bus -> 24V) --
    see digital_twin/config.py's CRUISE_CONVERTER_NAME. The accel motor sits on the
    48V bus directly and never needs one."""
    if not DIGITAL_TWIN_AVAILABLE:
        return {"converters": []}
    converters = pt.load_converters()
    return {
        "converters": [
            {
                "name": name,
                "output_v": c.output_v,
                "rated_power_w": c.rated_power_w,
                "efficiency_pct": round(c.efficiency_at_power(c.rated_power_w) * 100, 1),
            }
            for name, c in converters.items()
        ],
        "default": config.CRUISE_CONVERTER_NAME,
    }


@app.get("/api/weather-scenarios")
def get_weather_scenarios():
    if not DIGITAL_TWIN_AVAILABLE:
        return {"scenarios": []}
    out = []
    for name, s in weather.SCENARIOS.items():
        out.append({
            "name": s.name,
            "temperature_c": s.temperature_c,
            "relative_humidity": s.relative_humidity,
            "pressure_hpa": s.pressure_hpa,
            "wind_speed_kmh": s.wind_speed_kmh,
            "wind_from_bearing_deg": s.wind_from_bearing_deg,
            "air_density_kg_m3": round(weather.air_density(s), 4),
            "confidence": s.confidence,
            "source": s.source,
        })
    return {"scenarios": out, "default": "typical_january"}


# ---------------------------------------------------------------------------
# Simulation: pick a vehicle_id + track_id (Garage entries), an environment,
# and run the constant-cruise strategy digital twin.
# ---------------------------------------------------------------------------
class SimulationParams(BaseModel):
    vehicle_id: Optional[str] = None
    track_id: Optional[str] = None
    motor_mode: str = "single"  # "single" (one motor for the whole run) or "dual"
    # (Urban Concept accel/cruise split -- see digital_twin.simulate.simulate()'s
    # two_motor path). "single" is the default so every existing caller/attempt
    # keeps behaving exactly as before this field was added.
    motor_name: Optional[str] = None
    accel_motor_name: Optional[str] = None
    cruise_motor_name: Optional[str] = None
    fc_name: Optional[str] = None
    cruise_cap_enabled: bool = True
    cruise_kmh: Optional[float] = None
    weather_scenario: str = "typical_january"
    temperature_c: Optional[float] = None
    relative_humidity: Optional[float] = None
    pressure_hpa: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    wind_from_bearing_deg: Optional[float] = None


def _resolve_scenario(params: SimulationParams) -> "weather.WeatherScenario":
    base = weather.SCENARIOS.get(params.weather_scenario, weather.SCENARIOS["typical_january"])
    overrides = {}
    if params.temperature_c is not None:
        overrides["temperature_c"] = params.temperature_c
    if params.relative_humidity is not None:
        overrides["relative_humidity"] = params.relative_humidity
    if params.pressure_hpa is not None:
        overrides["pressure_hpa"] = params.pressure_hpa
    if params.wind_speed_kmh is not None:
        overrides["wind_speed_kmh"] = params.wind_speed_kmh
    if params.wind_from_bearing_deg is not None:
        overrides["wind_from_bearing_deg"] = params.wind_from_bearing_deg
    if overrides:
        return replace(base, name="custom", **overrides)
    return base


def _downsample_chart(result_df, step: int = 10):
    df = result_df.iloc[::step].copy()
    chart_data = []
    for _, row in df.iterrows():
        chart_data.append({
            "distance_km": row["s_m"] / 1000.0,
            "speed_kmh": row["v_kmh"],
            "altitude_m": row.get("altitude_m"),
            "grade_pct": row.get("grade_pct"),
            "a_ms2": row["a_ms2"],
            "h2_flow_lpm": row["h2_flow_m3_s"] * 1000.0 * 60.0,
            "p_motor_elec_w": row["p_motor_elec_w"],
            "p_fc_elec_w": row["p_fc_elec_w"],
            "f_drag_n": row["f_drag_n"],
            "f_roll_n": row["f_roll_n"],
            "f_grade_n": row["f_grade_n"],
            "f_cornering_n": row["f_cornering_n"],
        })
    return chart_data


def _simulate_core(params: SimulationParams):
    """Shared by /api/simulate (throwaway what-if runs) and
    /api/attempts/from-simulation (the same run, persisted). Returns
    (response_dict, result_df, veh, trk) on success, or (error_dict, None,
    None, None) on failure -- error_dict already has success=False set."""
    with _SIM_LOCK:
        vehicles = registry.load_vehicles(config)
        tracks = registry.load_tracks(config)
        veh = vehicles.get(params.vehicle_id) if params.vehicle_id else next(iter(vehicles.values()), None)
        trk = tracks.get(params.track_id) if params.track_id else next(iter(tracks.values()), None)
        if veh is None:
            return {"success": False, "error": "no vehicle found -- create one in the Garage first"}, None, None, None
        if trk is None:
            return {"success": False, "error": "no track found -- create one in the Garage first"}, None, None, None

        orig_vehicle_cfg = registry.apply_vehicle(config, veh)
        orig_track_cfg = registry.apply_track(config, trk)
        try:
            motor_catalog = veh.get("motor_catalog_csv") or pt.MOTOR_CSV
            fc_catalog = veh.get("fc_catalog_csv") or pt.FC_CSV
            motors = pt.load_motors(motor_catalog)
            fcs = pt.load_fuel_cells(fc_catalog)
            fc_name = params.fc_name or veh.get("default_fc")
            if not motors or not fcs:
                return {"success": False, "error": "vehicle's motor/FC catalog has no usable entries"}, None, None, None
            # Fall back to an FC that actually HAS an efficiency curve when no
            # default is set (e.g. a freshly created vehicle) -- e.g.
            # "G-HFCS 1000W" has no digitized curve and would otherwise crash
            # h2_volume_flow_m3_s()'s np.interp on an empty table.
            fc = fcs.get(fc_name) or next((f for f in fcs.values() if f.has_efficiency_curve()), next(iter(fcs.values())))
            scenario = _resolve_scenario(params)

            dual_motor = params.motor_mode == "dual"
            accel_motor = cruise_motor = cruise_converter = None
            motor = None
            if dual_motor:
                accel_name = params.accel_motor_name or veh.get("default_motor_accel")
                cruise_name = params.cruise_motor_name or veh.get("default_motor_cruise")
                accel_motor = motors.get(accel_name)
                cruise_motor = motors.get(cruise_name)
                if accel_motor is None or cruise_motor is None:
                    return {
                        "success": False,
                        "error": "Dual-motor mode needs both an accel and a cruise motor -- "
                                 "set them for this run, or configure the vehicle's defaults in the Garage.",
                    }, None, None, None
                converter_name = veh.get("default_cruise_converter") or config.CRUISE_CONVERTER_NAME
                cruise_converter = pt.load_converters().get(converter_name)
            else:
                motor_name = params.motor_name or veh.get("default_motor")
                motor = motors.get(motor_name) or next(iter(motors.values()))

            cruise_target_kmh = veh["fields"]["cruise_target_kmh"]["value"]
            cruise_kmh_value = params.cruise_kmh if params.cruise_kmh is not None else cruise_target_kmh
            # Cruise cap OFF -> 999 km/h ceiling, same "unbound cruise, ceiling only
            # from track safety/stops" convention simulate.py already uses for the
            # gas/glide (v_target_kmh) path -- lets the car run as fast as the track
            # and motor allow instead of holding a chosen cruise speed.
            effective_cruise_kmh = cruise_kmh_value if params.cruise_cap_enabled else 999.0

            full_track = get_full_track(trk)
            if dual_motor:
                result = sim.simulate(full_track, scenario, fc=fc,
                                       accel_motor=accel_motor, cruise_motor=cruise_motor,
                                       cruise_converter=cruise_converter,
                                       cruise_kmh=effective_cruise_kmh)
            else:
                result = sim.simulate(full_track, scenario, motor=motor, fc=fc,
                                       cruise_kmh=effective_cruise_kmh)

            total_dist_km = result["s_m"].iloc[-1] / 1000.0
            total_h2_m3 = result["h2_cumulative_m3"].iloc[-1]
            accessory_j = result["accessory_energy_cumulative_j"].iloc[-1]
            score = telemetry.h2_score_km_per_m3(total_dist_km, total_h2_m3, accessory_energy_j=accessory_j)
            total_time_s = result["t_s"].iloc[-1]

            response = {
                "success": True,
                "vehicle_id": veh["id"],
                "vehicle_name": veh["name"],
                "track_id": trk["id"],
                "track_name": trk["name"],
                "motor_mode": params.motor_mode,
                "motor_name": f"{accel_motor.name} + {cruise_motor.name}" if dual_motor else motor.name,
                "fc_name": fc.name,
                "cruise_kmh_used": cruise_kmh_value,
                "score_km_per_m3": score,
                "h2_total_l": total_h2_m3 * 1000.0,
                "accessory_h2_equiv_l": telemetry.accessory_h2_equivalent_m3(accessory_j) * 1000.0,
                "total_time_min": total_time_s / 60.0,
                "avg_speed_kmh": total_dist_km / (total_time_s / 3600.0) if total_time_s > 0 else 0.0,
                "max_speed_kmh": float(result["v_kmh"].max()),
                "air_density_kg_m3": round(weather.air_density(scenario), 4),
                "rule_violations": int(result["rule_violation"].sum()),
                "stop_events": int(result["stop_event"].sum()),
                "motor_power_clipped_points": int(result["motor_clipped"].sum()),
                "chart_data": _downsample_chart(result, step=10),
            }
            return response, result, veh, trk
        except Exception as e:
            return {"success": False, "error": str(e)}, None, None, None
        finally:
            registry.restore_config(config, orig_vehicle_cfg)
            registry.restore_config(config, orig_track_cfg)


@app.post("/api/simulate")
def run_simulation(params: SimulationParams):
    """Run the digital twin (constant-cruise strategy) for a selected
    vehicle + track + environment. Throwaway -- see /api/attempts/from-simulation
    to persist the run."""
    if not DIGITAL_TWIN_AVAILABLE:
        return {"error": "Digital twin module not found."}
    response, _result, _veh, _trk = _simulate_core(params)
    return response


class SaveSimulationRequest(SimulationParams):
    name: str
    notes: str = ""


@app.post("/api/attempts/from-simulation")
def save_simulation_as_attempt(body: SaveSimulationRequest):
    """Runs the same constant-cruise simulate() as /api/simulate, but keeps
    the full telemetry and registers it as a "cruise" Attempt -- the plain
    physics baseline is often exactly what a team wants to save and compare
    against GA/PSO/CMA-ES runs, not just the optimizer outputs."""
    if not DIGITAL_TWIN_AVAILABLE:
        return {"success": False, "error": "Digital twin module not found."}
    response, result, veh, trk = _simulate_core(body)
    if not response.get("success"):
        return response

    aid = attempts_mod.new_attempt_id()
    d = attempts_mod.attempt_dir(aid)
    tel_path = os.path.join(d, "telemetry.csv")
    result.to_csv(tel_path, index=False)

    doc = attempts_mod.register_attempt(
        attempt_id=aid,
        name=body.name,
        source_type="simulated",
        algorithm="cruise",
        vehicle_id=veh["id"],
        track_id=trk["id"],
        has_gps="latitude" in result.columns,
        telemetry_csv_abs=tel_path,
        summary={
            "score_km_per_m3": response["score_km_per_m3"],
            "h2_total_l": response["h2_total_l"],
            "accessory_h2_equiv_l": response["accessory_h2_equiv_l"],
            "total_time_min": response["total_time_min"],
            "avg_speed_kmh": response["avg_speed_kmh"],
            "max_speed_kmh": response["max_speed_kmh"],
        },
        notes=body.notes,
    )
    return {"success": True, "attempt": doc}


STRATEGY_ALGOS = {
    "ga": {"label": "Genetic Algorithm", "segments": "ga_segment_targets.csv", "telemetry": "simulated_telemetry_ga.csv"},
    "pso": {"label": "Particle Swarm Optimization", "segments": "pso_segment_targets.csv", "telemetry": "simulated_telemetry_pso.csv"},
    "cma": {"label": "CMA-ES", "segments": "cma_segment_targets.csv", "telemetry": "simulated_telemetry_cma.csv"},
}
# The precomputed GA/PSO/CMA-ES runs (each takes 10s of minutes -- see
# digital_twin/optimize_*.py) were generated for this vehicle/track pair.
# If the Garage grows a second vehicle or track, these comparisons still
# refer to the original SEM entry until someone reruns the optimizers.
STRATEGY_VEHICLE_ID = "urban-h2-2027"
STRATEGY_TRACK_ID = "lusail-urban-2027"


def _load_strategy_result(algo: str):
    import pandas as pd
    meta = STRATEGY_ALGOS[algo]
    seg_path = os.path.join(DATA_DIR, meta["segments"])
    tel_path = os.path.join(DATA_DIR, meta["telemetry"])
    if not (os.path.isfile(seg_path) and os.path.isfile(tel_path)):
        return {"algo": algo, "label": meta["label"], "available": False}

    segments_df = pd.read_csv(seg_path)
    if segments_df.empty:
        return {"algo": algo, "label": meta["label"], "available": False}

    tel = pd.read_csv(tel_path)
    total_dist_km = tel["s_m"].iloc[-1] / 1000.0
    total_h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
    accessory_j = tel["accessory_energy_cumulative_j"].iloc[-1]
    accessory_h2_equiv_l = telemetry.accessory_h2_equivalent_m3(accessory_j) * 1000.0 if DIGITAL_TWIN_AVAILABLE else 0.0
    score = telemetry.h2_score_km_per_m3(total_dist_km, total_h2_m3, accessory_energy_j=accessory_j) if DIGITAL_TWIN_AVAILABLE else None
    total_time_s = tel["t_s"].iloc[-1]

    chart = tel.iloc[::20].copy()
    chart_data = [
        {
            "distance_km": row["s_m"] / 1000.0,
            "speed_kmh": row["v_kmh"],
            "h2_flow_lpm": row["h2_flow_m3_s"] * 1000.0 * 60.0,
        }
        for _, row in chart.iterrows()
    ]

    return {
        "algo": algo,
        "label": meta["label"],
        "available": True,
        "score_km_per_m3": score,
        "h2_total_l": total_h2_m3 * 1000.0,
        "accessory_h2_equiv_l": accessory_h2_equiv_l,
        "total_time_min": total_time_s / 60.0,
        "avg_speed_kmh": total_dist_km / (total_time_s / 3600.0) if total_time_s > 0 else 0.0,
        "max_speed_kmh": float(tel["v_kmh"].max()),
        "weather_scenario": tel["weather_scenario"].iloc[0] if "weather_scenario" in tel.columns else None,
        "motor_name": tel["motor_name"].iloc[0] if "motor_name" in tel.columns else None,
        "fc_name": tel["fc_name"].iloc[0] if "fc_name" in tel.columns else None,
        "segment_targets": segments_df.to_dict(orient="records"),
        "chart_data": chart_data,
    }


@app.get("/api/strategy/compare")
def strategy_compare():
    """Lusail Urban Hydrogen Strategy: GA vs PSO vs CMA-ES precomputed results
    (each optimizer run takes 10s of minutes -- these are the last batch runs,
    not regenerated on request)."""
    results = {algo: _load_strategy_result(algo) for algo in STRATEGY_ALGOS}
    vehicles = registry.load_vehicles(config) if DIGITAL_TWIN_AVAILABLE else {}
    tracks = registry.load_tracks(config) if DIGITAL_TWIN_AVAILABLE else {}
    veh = vehicles.get(STRATEGY_VEHICLE_ID)
    trk = tracks.get(STRATEGY_TRACK_ID)
    return {
        "results": results,
        "vehicle": {"id": veh["id"], "name": veh["name"]} if veh else None,
        "track": {
            "id": trk["id"], "name": trk["name"],
            "lap_distance_km": trk["lap_distance_km"], "total_laps": trk["total_laps"],
            "total_distance_km": trk["total_distance_km"], "max_attempt_time_min": trk["max_attempt_time_min"],
        } if trk else None,
    }


@app.get("/api/strategy/{algo}")
def strategy_detail(algo: str):
    if algo not in STRATEGY_ALGOS:
        return {"error": f"unknown algorithm '{algo}', expected one of {list(STRATEGY_ALGOS)}"}
    return _load_strategy_result(algo)


# ---------------------------------------------------------------------------
# Attempts -- saved runs (simulated: cruise/ga/pso/cma, or real: captured off
# the MQTT bridge and cleaned). This is what the Strategy tab now lists.
# ---------------------------------------------------------------------------
@app.get("/api/attempts")
def list_attempts():
    attempts = attempts_mod.load_attempts(config, telemetry) if DIGITAL_TWIN_AVAILABLE else {}
    items = sorted(attempts.values(), key=lambda a: a.get("created_at", ""), reverse=True)
    return {"attempts": items}


@app.get("/api/attempts/{attempt_id}")
def get_attempt(attempt_id: str):
    attempts = attempts_mod.load_attempts(config, telemetry)
    doc = attempts.get(attempt_id)
    if not doc:
        return {"error": f"attempt '{attempt_id}' not found"}
    return doc


@app.get("/api/attempts/{attempt_id}/chart")
def get_attempt_chart(attempt_id: str, lap: Optional[int] = None, use_raw: Optional[bool] = False):
    attempts = attempts_mod.load_attempts(config, telemetry) if DIGITAL_TWIN_AVAILABLE else attempts_mod.load_attempts()
    doc = attempts.get(attempt_id)
    if not doc:
        return {"error": f"attempt '{attempt_id}' not found"}
    return attempts_mod.load_chart_data(doc, lap=lap, use_raw=bool(use_raw))


@app.get("/api/attempts/{attempt_id}/qc-report")
def get_attempt_qc_report(attempt_id: str):
    attempts = attempts_mod.load_attempts(config, telemetry) if DIGITAL_TWIN_AVAILABLE else attempts_mod.load_attempts()
    doc = attempts.get(attempt_id)
    if not doc:
        return {"available": False, "error": f"attempt '{attempt_id}' not found"}
    return attempts_mod.get_qc_report(doc)


@app.get("/api/attempts/{attempt_id}/segments")
def get_attempt_segments(attempt_id: str):
    """Per-segment gas/glide targets (v_target_kmh/v_coast_kmh) -- only
    present for GA/PSO/CMA-ES attempts, not a plain cruise run or a real
    recording."""
    import pandas as pd
    attempts = attempts_mod.load_attempts(config, telemetry)
    doc = attempts.get(attempt_id)
    if not doc:
        return {"available": False, "error": f"attempt '{attempt_id}' not found"}
    rel = doc.get("segment_targets_csv")
    if not rel:
        return {"available": False}
    full_path = attempts_mod.resolve_attempt_path(attempt_id, rel)
    if not os.path.isfile(full_path):
        return {"available": False}
    return {"available": True, "segments": pd.read_csv(full_path).to_dict(orient="records")}


@app.delete("/api/attempts/{attempt_id}")
def delete_attempt_route(attempt_id: str):
    ok = attempts_mod.delete_attempt(attempt_id)
    return {"success": ok, "error": None if ok else f"attempt '{attempt_id}' not found"}


class CleanAndAssignParams(BaseModel):
    durations: Optional[str] = None
    lap_dist: Optional[float] = None
    use_gps: Optional[bool] = True
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    start_time: Optional[str] = None


@app.post("/api/attempts/{attempt_id}/clean-and-assign-laps")
def clean_and_assign_laps_route(attempt_id: str, body: CleanAndAssignParams):
    """Cleans raw telemetry CSV using clean_telemetry.py and assigns lap_number
    and elapsed_s using assign_laps.py (via GPS start-line return, durations, or start_time)."""
    try:
        attempts = attempts_mod.load_attempts(config, telemetry) if DIGITAL_TWIN_AVAILABLE else attempts_mod.load_attempts()
        doc = attempts.get(attempt_id)
        if not doc:
            return {"success": False, "error": f"attempt '{attempt_id}' not found"}
        
        csv_rel = doc.get("telemetry_csv")
        if not csv_rel:
            return {"success": False, "error": "attempt has no telemetry CSV file"}
        
        full_path = attempts_mod.resolve_attempt_path(attempt_id, csv_rel)
        if not os.path.isfile(full_path):
            return {"success": False, "error": f"file not found: {csv_rel}"}

        mqtt_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'mqtt'))
        if mqtt_dir not in sys.path:
            sys.path.append(mqtt_dir)
        import clean_telemetry
        import assign_laps

        df_raw = pd.read_csv(full_path)
        # Global lat/lon bounds, not clean()'s Indonesia-calibrated default box --
        # this route's attempts aren't all recorded at Antasena's home track (e.g.
        # Lusail, Qatar is ~25N/51E, entirely outside the default box), and the
        # default would silently wipe every GPS point for any other venue. Mirrors
        # telemetry_capture.save_recording_as_attempt()'s own call.
        df_clean, qc_report = clean_telemetry.clean(df_raw, lat_bounds=(-90.0, 90.0), lon_bounds=(-180.0, 180.0))

        # If start_lat/start_lon not explicitly passed in body, try fetching from track registry
        start_lat = body.start_lat
        start_lon = body.start_lon
        lap_dist = body.lap_dist

        if doc.get("track_id"):
            tracks = registry.load_tracks(config)
            tr_doc = tracks.get(doc["track_id"])
            if tr_doc:
                if start_lat is None and "start_lat" in tr_doc:
                    start_lat = float(tr_doc["start_lat"])
                if start_lon is None and "start_lon" in tr_doc:
                    start_lon = float(tr_doc["start_lon"])
                if lap_dist is None and "lap_distance_m" in tr_doc:
                    lap_dist = float(tr_doc["lap_distance_m"])

        durations_list = [float(x.strip()) for x in body.durations.split(",")] if body.durations else None

        df_laps = assign_laps.assign_laps_to_df(
            df_clean,
            durations=durations_list,
            lap_dist=lap_dist,
            use_gps=body.use_gps,
            start_lat=start_lat,
            start_lon=start_lon,
            start_time=body.start_time
        )

        df_laps.to_csv(full_path, index=False)

        # Summary of laps assigned
        laps_found = sorted(int(x) for x in df_laps["lap_number"].dropna().unique()) if "lap_number" in df_laps.columns else []

        return {
            "success": True,
            "laps_assigned": laps_found,
            "total_rows": len(df_laps),
            "qc_report": qc_report,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


class TrackStartLineParams(BaseModel):
    start_lat: float
    start_lon: float


@app.post("/api/tracks/{track_id}/start-line")
def update_track_start_line(track_id: str, body: TrackStartLineParams):
    tracks = registry.load_tracks(config)
    tr_doc = tracks.get(track_id)
    if not tr_doc:
        return {"success": False, "error": f"track '{track_id}' not found"}
    tr_doc["start_lat"] = body.start_lat
    tr_doc["start_lon"] = body.start_lon
    registry.save_tracks(tracks)
    return {"success": True, "start_lat": body.start_lat, "start_lon": body.start_lon}


# Two DIFFERENT, both-real reference lines per track (neither is invented
# here -- both come straight out of the existing track-analysis pipeline):
#   centerline  -- data/track_edges_imagery.csv's own (lat, lon): the rebuilt
#                  corridor midline from the satellite-imagery width
#                  digitization (edge midpoint), NOT the raw Shell GPS trace
#                  the simulator drives on -- see sem-digital-twin-state memory,
#                  "Shell GPS line is NOT the corridor midline".
#   racing_line -- data/racing_line.csv: digital_twin/racing_line.py's
#                  shortest-path QP solve over that same corridor.
# Both are 735-row, same-station tables (5 m spacing) so they line up.
# Only computed for lusail-urban-2027 so far.
REFERENCE_LINES_BY_TRACK = {
    "lusail-urban-2027": {"centerline": "data/track_edges_imagery.csv", "racing_line": "data/racing_line.csv"},
}


def _load_reference_line(rel_path: str, max_points: int = 800):
    import pandas as pd
    full_path = os.path.join(PROJECT_ROOT, rel_path)
    if not os.path.isfile(full_path):
        return {"available": False, "points": []}
    df = pd.read_csv(full_path)
    step = max(1, len(df) // max_points)
    df = df.iloc[::step]
    return {
        "available": True,
        "points": [{"latitude": float(r["lat"]), "longitude": float(r["lon"])} for _, r in df.iterrows()],
    }


_STOP_POINTS_CACHE: dict = {}


def _get_stop_points(track: dict):
    """The 2 mandatory-stop lat/lon per lap (Art. 226/227), read off the
    track's own 1-lap profile so they line up with whichever coordinates/
    stop_locations_km this specific track was registered with -- not
    hardcoded to Lusail."""
    key = track["id"]
    if key not in _STOP_POINTS_CACHE:
        profile_1lap = track_mod.build_track_profile(
            save=False,
            coordinates_csv=track.get("coordinates_csv"),
            turns_csv=track.get("turns_csv"),
            edges_csv=track.get("edges_csv"),
            stop_locations_km=track.get("stop_locations_km"),
        )
        stops = profile_1lap[profile_1lap["stop_event"]]
        _STOP_POINTS_CACHE[key] = [
            {"latitude": float(r["latitude"]), "longitude": float(r["longitude"]), "distance_km": float(r["distance_km"])}
            for _, r in stops.iterrows()
        ]
    return _STOP_POINTS_CACHE[key]


@app.get("/api/tracks/{track_id}/reference-lines")
def get_reference_lines(track_id: str, max_points: int = 800):
    """Both the corridor centerline and the QP-optimum racing line together,
    so the Strategy tab can show a fixed 'what's the ideal line' comparison
    alongside whatever this specific attempt actually drove. Also carries the
    mandatory-stop lat/lon so maps can mark them."""
    paths = REFERENCE_LINES_BY_TRACK.get(track_id)
    stops = []
    if DIGITAL_TWIN_AVAILABLE:
        track = registry.load_tracks(config).get(track_id)
        if track:
            try:
                stops = _get_stop_points(track)
            except Exception:
                stops = []
    if not paths:
        return {"centerline": {"available": False, "points": []}, "racing_line": {"available": False, "points": []}, "stops": stops}
    return {
        "centerline": _load_reference_line(paths["centerline"], max_points),
        "racing_line": _load_reference_line(paths["racing_line"], max_points),
        "stops": stops,
    }


# Backward-compatible alias (racing line only).
@app.get("/api/tracks/{track_id}/racing-line")
def get_racing_line(track_id: str, max_points: int = 800):
    paths = REFERENCE_LINES_BY_TRACK.get(track_id)
    if not paths:
        return {"points": [], "available": False}
    return _load_reference_line(paths["racing_line"], max_points)


# ---------------------------------------------------------------------------
# Track analysis -- the same underlying per-point profile that
# notebooks/Track_Analysis.ipynb explores by hand (turns, elevation, width,
# stops), computed live off whichever track a user has registered in the
# Garage instead of being frozen to one notebook run against Lusail. Keeps
# this dashboard usable for future tracks, not just the one it started with.
# ---------------------------------------------------------------------------
_TRACK_ANALYSIS_CACHE: dict = {}


def _compute_track_analysis(track: dict) -> dict:
    key = track["id"]
    if key in _TRACK_ANALYSIS_CACHE:
        return _TRACK_ANALYSIS_CACHE[key]

    profile = track_mod.build_track_profile(
        save=False,
        coordinates_csv=track.get("coordinates_csv"),
        turns_csv=track.get("turns_csv"),
        edges_csv=track.get("edges_csv"),
        stop_locations_km=track.get("stop_locations_km"),
    )

    turns = []
    turn_zones = profile[profile["zone_type"] == "turn"]
    for zid, g in turn_zones.groupby("zone_id"):
        r_min = g["r_min_m"].min() if g["r_min_m"].notna().any() else None
        v_safe = g["v_safe_kmh"].min() if g["v_safe_kmh"].notna().any() else None
        turns.append({
            "zone_id": int(zid),
            "start_km": float(g["distance_km"].min()),
            "end_km": float(g["distance_km"].max()),
            "r_min_m": float(r_min) if r_min is not None else None,
            "v_safe_kmh_min": float(v_safe) if v_safe is not None else None,
        })
    turns.sort(key=lambda t: t["start_km"])

    grade = profile["grade_pct"].dropna()
    max_up_idx = grade.idxmax() if len(grade) else None
    max_down_idx = grade.idxmin() if len(grade) else None

    stops = profile[profile["stop_event"]]
    has_width = "width_m" in profile.columns and profile["width_m"].notna().any()

    analysis = {
        "track_id": key,
        "n_points": int(len(profile)),
        "lap_distance_km": float(profile["distance_km"].iloc[-1]),
        "elevation": {
            "min_altitude_m": float(profile["altitude_m"].min()),
            "max_altitude_m": float(profile["altitude_m"].max()),
            "max_uphill_grade_pct": float(grade.loc[max_up_idx]) if max_up_idx is not None else None,
            "max_uphill_km": float(profile.loc[max_up_idx, "distance_km"]) if max_up_idx is not None else None,
            "max_downhill_grade_pct": float(grade.loc[max_down_idx]) if max_down_idx is not None else None,
            "max_downhill_km": float(profile.loc[max_down_idx, "distance_km"]) if max_down_idx is not None else None,
            "profile": [
                {"distance_km": float(r["distance_km"]), "altitude_m": float(r["altitude_m"]), "grade_pct": (float(r["grade_pct"]) if pd.notna(r["grade_pct"]) else None)}
                for _, r in profile.iloc[::max(1, len(profile) // 400)].iterrows()
            ],
        },
        "turns": {
            "count": len(turns),
            "tightest_r_min_m": min((t["r_min_m"] for t in turns if t["r_min_m"] is not None), default=None),
            "list": turns,
        },
        "width": {
            "min_m": float(profile["width_m"].min()) if has_width else None,
            "median_m": float(profile["width_m"].median()) if has_width else None,
            "max_m": float(profile["width_m"].max()) if has_width else None,
        },
        "stops": [
            {"distance_km": float(r["distance_km"]), "latitude": float(r["latitude"]), "longitude": float(r["longitude"])}
            for _, r in stops.iterrows()
        ],
    }
    _TRACK_ANALYSIS_CACHE[key] = analysis
    return analysis


@app.get("/api/tracks/{track_id}/analysis")
def get_track_analysis(track_id: str):
    if not DIGITAL_TWIN_AVAILABLE:
        return {"available": False, "error": "digital_twin not loaded"}
    track = registry.load_tracks(config).get(track_id)
    if not track:
        return {"available": False, "error": f"track '{track_id}' not found"}
    try:
        analysis = _compute_track_analysis(track)
        return {"available": True, **analysis}
    except Exception as e:
        return {"available": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Optimizer jobs -- run the REAL GA/PSO/CMA-ES strategy search from the
# Sandbox (not just the flat constant-cruise physics) instead of only ever
# showing the seeded benchmark comparison. Multiple algorithms in one request
# are queued together and run one after another (see optimizer_jobs.py for
# why true concurrency isn't safe here).
# ---------------------------------------------------------------------------
class OptimizeRunRequest(BaseModel):
    algorithms: list[str]
    vehicle_id: Optional[str] = None
    track_id: Optional[str] = None
    motor_name: Optional[str] = None
    fc_name: Optional[str] = None
    weather_scenario: str = "typical_january"
    pop_size: Optional[int] = None  # None -> use Final_Project's own tuned/best config per algorithm
    n_gen: Optional[int] = None


@app.post("/api/optimize/run")
def optimize_run(body: OptimizeRunRequest):
    if not DIGITAL_TWIN_AVAILABLE:
        return {"error": "Digital twin module not found."}
    vehicles = registry.load_vehicles(config)
    tracks = registry.load_tracks(config)
    veh = vehicles.get(body.vehicle_id) if body.vehicle_id else next(iter(vehicles.values()), None)
    trk = tracks.get(body.track_id) if body.track_id else next(iter(tracks.values()), None)
    if veh is None or trk is None:
        return {"success": False, "error": "no vehicle/track available -- create one in the Garage first"}
    motor_name = body.motor_name or veh.get("default_motor") or config.DEFAULT_MOTOR_NAME
    fc_name = body.fc_name or veh.get("default_fc") or config.DEFAULT_FC_NAME

    valid_algos = [a for a in body.algorithms if a in ("ga", "pso", "cma", "dp")]
    if not valid_algos:
        return {"success": False, "error": "algorithms must be a non-empty list of 'ga'/'pso'/'cma'/'dp'"}

    import uuid
    group_id = uuid.uuid4().hex[:10]
    job_ids = [
        optimizer_jobs.submit(algo=algo, vehicle=veh, track=trk, scenario_name=body.weather_scenario,
                               motor_name=motor_name, fc_name=fc_name, pop_size=body.pop_size,
                               n_gen=body.n_gen, group_id=group_id)
        for algo in valid_algos
    ]
    # sum, not per-job: the queue runs them one after another (see
    # optimizer_jobs.py), so total wall-clock is the sum across the group.
    total_eta = sum(optimizer_jobs.estimate_seconds(a, body.pop_size, body.n_gen) for a in valid_algos)
    return {"success": True, "group_id": group_id, "job_ids": job_ids, "eta_seconds_total": total_eta}


@app.get("/api/optimize/jobs/{job_id}")
def get_optimize_job(job_id: str):
    job = optimizer_jobs.get_job(job_id)
    if not job:
        return {"error": f"job '{job_id}' not found"}
    return job


@app.get("/api/optimize/groups/{group_id}")
def get_optimize_group(group_id: str):
    jobs = [j for j in optimizer_jobs.JOBS.values() if j.get("group_id") == group_id]
    return {"jobs": jobs}


class SaveJobRequest(BaseModel):
    name: str
    notes: str = ""


@app.post("/api/optimize/jobs/{job_id}/save")
def save_optimize_job(job_id: str, body: SaveJobRequest):
    doc, error = optimizer_jobs.save_job_as_attempt(job_id, body.name, body.notes)
    if error:
        return {"success": False, "error": error}
    return {"success": True, "attempt": doc}


@app.delete("/api/optimize/jobs/{job_id}")
def discard_optimize_job(job_id: str):
    ok = optimizer_jobs.discard_job(job_id)
    return {"success": ok}


@app.get("/api/telemetry/status")
def telemetry_status():
    """REST snapshot of the live-telemetry MQTT bridge state, for initial page
    load before the websocket connects."""
    return _snapshot_with_advisory()


@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_snapshot_with_advisory())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass


# --- Frontend SPA Integration ---
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist'))

if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    
    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback(request, exc):
        if exc.status_code == 404:
            if request.url.path.startswith("/api/") or request.url.path.startswith("/ws/"):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            index_file = os.path.join(frontend_dist, "index.html")
            if os.path.isfile(index_file):
                return FileResponse(index_file)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
else:
    print(f"Warning: frontend dist not found at {frontend_dist}. API-only mode.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
