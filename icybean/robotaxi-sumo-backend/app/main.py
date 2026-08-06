import asyncio
import gzip
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


APP_DIR = Path(__file__).resolve().parent
SUMO_DISTRICT_SCENARIO_DIR = APP_DIR / "sumo" / "reinickendorf-district"
SUMO_CORRIDOR_SCENARIO_DIR = APP_DIR / "sumo" / "charlottenburg-moabit-tiergarten"
SUMO_DEPOT_ADDITIONAL_FILE = SUMO_DISTRICT_SCENARIO_DIR / "txl-adac-cybercab-depot.add.xml"
MATSIM_DEMAND_DIR = APP_DIR / "data" / "matsim"
PUBLIC_REPLAY_DIR = APP_DIR / "data" / "replays"
MATSIM_REINICKENDORF_DEMAND_FILE = MATSIM_DEMAND_DIR / "reinickendorf_person_trips_1pct_180000_210000_all_modes.json"
MATSIM_CORRIDOR_DEMAND_FILE = (
    MATSIM_DEMAND_DIR
    / "charlottenburg-moabit-tiergarten_person_trips_1pct_180000_190000_car_ride.json"
)
MATSIM_DEFAULT_DEMAND_FILE = MATSIM_CORRIDOR_DEMAND_FILE
SUMO_BERLIN_SCENARIO_DIR = APP_DIR / "sumo" / "berlin"
# seed15 = 0.15 adoption scale over the 7,502-trip evening pool (133 requests)
# — the demand level the fleet-60 sizing matrix was run at.
MATSIM_BERLIN_DEMAND_FILE = MATSIM_DEMAND_DIR / "berlin_person_trips_1pct_180000_190000_seed15.json"
SUMO_START_SEC = 64_800
SUMO_END_SEC = 75_600
SUMO_CORRIDOR_END_SEC = 68_400  # 19:00 — v1 one-hour watchable window
# Berlin city scenario starts 17:40: the fleet leaves the TXL depot and drives
# into position while the evening background traffic fills the city.
# 17:40: the fleet leaves the TXL depot in a staggered convoy, fans out to
# the city stands, serves 18:00-19:00, and comes home. Playback compresses
# the drive-in (3x pacing); the recording carries the whole story.
SUMO_BERLIN_START_SEC = 63_600
ROBOTAXI_REQUEST_EXPIRY_SEC = 600
SUMO_WINDOW_LABEL = "18:00-21:00"
DEFAULT_SUMO_DELAY_MS = 0
MAX_SUMO_DELAY_MS = 1000
FAST_SIM_BURST_STEPS = 500
PLAYBACK_SCOPE = "charlottenburg-moabit-tiergarten"
PLAYBACK_SCOPES = {"charlottenburg-moabit-tiergarten", "berlin"}
# Small sizes are corridor-scale fleets; the tens are the berlin sizing matrix.
FLEET_SIZE_OPTIONS = {3, 4, 5, 6, 7, 8, 10, 20, 30, 40, 50, 60}
PLAYBACK_DATA_FPS = 50
PLAYBACK_DEFAULT_RATE = 10
PLAYBACK_SPEEDS = {5, 10, 25, 50, 100, 250, 500, 1000}
PLAYBACK_CHUNK_VISUAL_FRAMES = 10
DEFAULT_REPLACEMENT_PERCENT = 5
REPLACEMENT_PERCENT_OPTIONS = {5, 10, 15, 25}
DEFAULT_DEMAND_SOURCE = "matsim"
DEMAND_SOURCE_OPTIONS = {"matsim", "sumo"}
DEFAULT_DISPATCH_ENGINE = "taxi"
DISPATCH_ENGINE_OPTIONS = {"taxi", "custom"}
DEFAULT_PLAYBACK_DETAIL = "full"
PLAYBACK_DETAIL_OPTIONS = {"full", "public"}
DEFAULT_PLAYBACK_CACHE = "auto"
PLAYBACK_CACHE_OPTIONS = {"auto", "live", "cache"}

# libsumo runs one simulation per process: live runs are strictly serialized,
# and a new live connection preempts whatever run came before it (single-viewer
# product — the newest page load wins; abandoned tabs must not hold the sim).
LIVE_RUN_LOCK = threading.Lock()
_latest_live_stop_event: threading.Event | None = None
PUBLIC_BACKGROUND_VEHICLE_LIMIT = 180
PUBLIC_REPLAY_STREAM_FRAMES_PER_CHUNK = 25
# Pace the cached replay to ~2.5 chunks/s. The client consumes ~1.6 chunks/s
# at 40x playback; dumping the whole file in seconds forces it to JSON-parse
# ~85MB in one burst, which locks the page for the entire intro.
PUBLIC_REPLAY_CHUNK_DELAY_SEC = 0.15
# All primary modes are loadable; which trips become robotaxi requests is
# decided upstream by the demand-seed sampler (mode-weighted adoption).
MATSIM_ROBOTAXI_MODES = {"car", "ride", "pt", "bike", "walk"}
MATSIM_MAX_STOP_DISTANCE_M = 1_000.0
MATSIM_SAMPLE_EXPANSION_FACTOR = 100
MATSIM_REFERENCE_MAX_WAIT_SEC = 300
MATSIM_REFERENCE_MAX_TRAVEL_TIME_ALPHA = 1.7
MATSIM_REFERENCE_MAX_TRAVEL_TIME_BETA_SEC = 120.0
ROBOTAXI_FLEET_SIZE = 10
ROBOTAXI_ID_PREFIX = "cybercab_"
ROBOTAXI_TYPE_ID = "CybercabRobotaxi"
ROBOTAXI_ROUTE_ID = "cybercab_depot_loop"
ROBOTAXI_DEPOT_PARKING_ID = "txl_adac_cybercab_depot"
ROBOTAXI_DEPOT_CHARGING_STATION_ID = "txl_adac_wireless_charging"
ROBOTAXI_DEPOT_CHARGER_COUNT = 20
ROBOTAXI_DEPOT_CHARGING_POWER_W = 150_000
# Cybercab EPA filing (June 2026): 47.6 kWh pack, 165 Wh/mile (~102.5 Wh/km).
ROBOTAXI_BATTERY_CAPACITY_WH = 47_600
ROBOTAXI_INITIAL_CHARGE_WH = 43_000
ROBOTAXI_DEPOT_ROUTE_EDGES = ["8036812#2", "-8036812#2"]
ROBOTAXI_CYBERCAB_SEATS = 2
ROBOTAXI_FALLBACK_SEATS = 5
ROBOTAXI_MIN_RESERVE_WH = 8_000
ROBOTAXI_RETURN_RESERVE_WH = 12_000
ROBOTAXI_SERVICE_HOLD_SEC = 30
ROBOTAXI_LOCAL_PARK_SEC = 180
ROBOTAXI_CONSUMPTION_WH_PER_M = 0.1025
ROBOTAXI_DEMAND_LOOKAHEAD_SEC = 600
ROBOTAXI_STAGING_LOOKAHEAD_SEC = 900
ROBOTAXI_STAGING_RECHECK_SEC = 60
ROBOTAXI_STAGING_CANDIDATE_LIMIT = 12
# Idle cabs without a staging target drift to a nearby service edge instead of
# sitting still forever; parked-then-roam reads as a live fleet, not a recording.
ROBOTAXI_ROAM_IDLE_MIN_SEC = 120
ROBOTAXI_ROAM_RECHECK_SEC = 150
ROBOTAXI_ROAM_MIN_EDGE_LENGTH_M = 60.0
# City-scale sanity caps. 30 cabs over 800 km2 means ~5 km spacing, i.e. a
# typical pickup drive of 10-15 min — a tight cap starves the fleet (measured:
# 9/78 served at 540 s). 12 min keeps hauls bounded without starving.
ROBOTAXI_MAX_PICKUP_ROUTE_SEC = 900.0
# Staging cap (python staging layer — inactive when a stands file is wired,
# as in berlin; see stands_mode): at 480 s a periphery drop-off could reach
# no hotspot and stranded. 960 s lets every drop-off walk back toward demand.
# The berlin equivalent of this fix is the demand-weighted stands file
# (scripts/build_berlin_taxi_stands.py) — measured nearest-stand P50 for real
# demand: 3.5 km (uniform grid) -> 1.6 km (demand-weighted).
ROBOTAXI_MAX_STAGING_ROUTE_SEC = 960.0
ROBOTAXI_CHARGE_READY_FRACTION = 0.88
ROBOTAXI_FINAL_DEPOT_MARGIN_SEC = 180
ROBOTAXI_TAXI_DRT_WINDDOWN_SEC = 600
# Hidden depot-recovery tail after service close. The run ends as soon as the
# fleet is parked at the depot; this is only the hard cap. Real depot returns
# from the corridor take up to ~12 min in traffic.
ROBOTAXI_POST_SERVICE_RECOVERY_SEC = 600
ROBOTAXI_DEADLINE_ROUTE_TIME_FACTOR = 1.5
ROBOTAXI_DEADLINE_RECHECK_SEC = 30
ROBOTAXI_ACTIVE_STATES = {
    "en_route_pickup",
    "with_passenger",
    "returning_to_depot",
}
ROBOTAXI_ASSIGNABLE_STATES = {"idle", "staged", "charging"}

SUMO_SCENARIOS: dict[str, dict[str, Any]] = {
    "reinickendorf-district": {
        "key": "reinickendorf-district",
        "label": "BeST Reinickendorf cutout with TXL depot corridor",
        "dir": SUMO_DISTRICT_SCENARIO_DIR,
        "config": SUMO_DISTRICT_SCENARIO_DIR / "reinickendorf-district.sumocfg",
        "net": SUMO_DISTRICT_SCENARIO_DIR / "reinickendorf-district.net.xml",
        "route": SUMO_DISTRICT_SCENARIO_DIR / "reinickendorf-district-contained.rou.xml",
        "additional": SUMO_DEPOT_ADDITIONAL_FILE,
        "boundary": SUMO_DISTRICT_SCENARIO_DIR / "reinickendorf-district.geojson",
        "depotEdge": None,
        "startSec": SUMO_START_SEC,
        "endSec": SUMO_END_SEC,
        "networkMaxLanes": None,
        "includeInternalLanes": True,
        "includeSignalLinks": True,
    },
    "charlottenburg-moabit-tiergarten": {
        "key": "charlottenburg-moabit-tiergarten",
        "label": "Charlottenburg + Moabit + Tiergarten corridor",
        "dir": SUMO_CORRIDOR_SCENARIO_DIR,
        "config": SUMO_CORRIDOR_SCENARIO_DIR / "charlottenburg-moabit-tiergarten.sumocfg",
        "net": SUMO_CORRIDOR_SCENARIO_DIR / "charlottenburg-moabit-tiergarten.net.xml",
        "route": SUMO_CORRIDOR_SCENARIO_DIR / "charlottenburg-moabit-tiergarten-contained.rou.xml",
        # Demand-weighted stands (8): idle cabs park at real bays where riders
        # appear instead of stopping in-lane — the berlin stands lesson at
        # corridor scale. Wiring this also hands idle placement to SUMO's
        # taxistand algorithm (stands_mode) like berlin.
        "additional": SUMO_CORRIDOR_SCENARIO_DIR
        / "charlottenburg-moabit-tiergarten-taxi-stands.add.xml",
        "boundary": SUMO_CORRIDOR_SCENARIO_DIR / "charlottenburg-moabit-tiergarten.geojson",
        "depotEdge": "8036812#2",
        # 17:45: the depot-to-zone drive is 12-16 min at rush speeds, so the
        # convoy needs a real head start to be staged when the first rider
        # appears (17:54 was measured short — cabs arrived ~18:08 and the
        # first six requests each ate a 4-8 km pickup drive from the convoy).
        "startSec": 63_900,
        "endSec": SUMO_CORRIDOR_END_SEC,
        "networkMaxLanes": None,
        "includeInternalLanes": True,
        "includeSignalLinks": True,
        # Small-fleet corridor: the story is 5 cabs serving a village-sized
        # area live — calibrated against the corridor seeds so the shift ends
        # a success, not a triage log.
        "fleetSize": 5,
        # seed11 = 0.5 adoption scale over the 451-trip corridor evening pool
        # (21 requests): measured at fleet 5 — every rider served, P50 wait
        # ~6 min. The shift ends a success and the cabs still visibly rest
        # at their stands between rides.
        "demandFileDefault": MATSIM_DEMAND_DIR
        / "charlottenburg-moabit-tiergarten_person_trips_1pct_180000_190000_seed11.json",
        # The fleet leaves the depot at 18:00 sharp and rolls into the zone
        # while the evening traffic builds — the depot story at street zoom.
        "spawnAtDepot": True,
        # Accept requests until the window ends (no 18:50 cutoff): an accepted
        # 18:58 rider still gets driven home inside the recovery cushion —
        # the last ten minutes of the shift must not read as "rider gave up".
        "assignmentWinddownSec": 0,
        "postServiceRecoverySec": 900,
    },
    "berlin": {
        "key": "berlin",
        "label": "Berlin city (full BeST network, 1pct traffic)",
        "dir": SUMO_BERLIN_SCENARIO_DIR,
        "config": SUMO_BERLIN_SCENARIO_DIR / "berlin.sumocfg",
        "net": SUMO_BERLIN_SCENARIO_DIR / "berlin.net.xml",
        "route": SUMO_BERLIN_SCENARIO_DIR / "berlin-background-1pct.rou.xml",
        # Taxi stands across the city: the taxistand idle algorithm makes the
        # depot story physically real (convoy out at 17:40, stands during the
        # hour, home at close). It costs sim speed (~2 sim-s/s worst) — fine
        # for the recorded default; live viewers pay it knowingly.
        "additional": SUMO_BERLIN_SCENARIO_DIR / "berlin-taxi-stands.add.xml",
        "boundary": SUMO_BERLIN_SCENARIO_DIR / "berlin.area.geojson",
        "depotEdge": "8036812#2",
        "startSec": SUMO_BERLIN_START_SEC,
        "endSec": SUMO_CORRIDOR_END_SEC,
        "networkMaxLanes": None,
        "includeInternalLanes": True,
        "includeSignalLinks": True,
        # Sized by the 2026-07-08 matrix at 133 requests: 40 cabs serve 70%,
        # 60 serve 89%; waits are pickup-drive-bound (~15 min) at every size.
        "fleetSize": 60,
        "demandFileDefault": MATSIM_BERLIN_DEMAND_FILE,
        # Depot bookends: the fleet leaves the TXL depot as a staggered convoy
        # and returns at close; the stands file gives idle cabs city homes.
        "spawnAtDepot": True,
        "includeTrafficLights": False,
        # City-scale: with ~5 km between idle cabs a rider realistically waits
        # longer than the corridor's 10 min before "no cab nearby", and an
        # accepted 18:45 rider with a cross-town trip still gets driven home —
        # the shift closes when the last accepted ride ends (up to ~19:30).
        "requestExpirySec": 900,
        # Hard cap only: the run ends the moment the whole fleet is parked at
        # the depot. City-scale returns from Köpenick to Tegel take ~30-40 min.
        "postServiceRecoverySec": 3_600,
        # City scale: accept requests until the window ends (no 18:50 cutoff);
        # accepted rides finish inside the recovery cushion.
        "assignmentWinddownSec": 0,
    },
}

app = FastAPI(title="Robotaxi SUMO Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("ALLOW_ORIGINS", "*").split(",") if origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_sumo_scenario(key: str | None) -> dict[str, Any]:
    scenario_key = (key or PLAYBACK_SCOPE).lower()
    if scenario_key not in SUMO_SCENARIOS:
        known_scopes = ", ".join(sorted(SUMO_SCENARIOS))
        raise HTTPException(
            status_code=404,
            detail=f"Unknown SUMO scope '{scenario_key}'. Known scopes: {known_scopes}",
        )
    return SUMO_SCENARIOS[scenario_key]


def scenario_window_label(selected: dict[str, Any]) -> str:
    return f"{format_time_label(selected['startSec'])}-{format_time_label(selected['endSec'])}"


def parse_playback_rate(websocket: WebSocket) -> int:
    raw_speed = websocket.query_params.get("speed")
    try:
        speed = int(raw_speed) if raw_speed is not None else PLAYBACK_DEFAULT_RATE
    except (TypeError, ValueError):
        return PLAYBACK_DEFAULT_RATE
    return speed if speed in PLAYBACK_SPEEDS else PLAYBACK_DEFAULT_RATE


def parse_replacement_percent(websocket: WebSocket) -> int:
    raw_percent = websocket.query_params.get("replacement")
    try:
        percent = int(raw_percent) if raw_percent is not None else DEFAULT_REPLACEMENT_PERCENT
    except (TypeError, ValueError):
        return DEFAULT_REPLACEMENT_PERCENT
    return percent if percent in REPLACEMENT_PERCENT_OPTIONS else DEFAULT_REPLACEMENT_PERCENT


def parse_demand_source(websocket: WebSocket) -> str:
    raw_source = str(websocket.query_params.get("demand") or DEFAULT_DEMAND_SOURCE).lower()
    return raw_source if raw_source in DEMAND_SOURCE_OPTIONS else DEFAULT_DEMAND_SOURCE


def parse_dispatch_engine(websocket: WebSocket) -> str:
    raw_engine = str(websocket.query_params.get("engine") or DEFAULT_DISPATCH_ENGINE).lower()
    return raw_engine if raw_engine in DISPATCH_ENGINE_OPTIONS else DEFAULT_DISPATCH_ENGINE


def parse_playback_detail(websocket: WebSocket) -> str:
    raw_detail = str(websocket.query_params.get("detail") or DEFAULT_PLAYBACK_DETAIL).lower()
    return raw_detail if raw_detail in PLAYBACK_DETAIL_OPTIONS else DEFAULT_PLAYBACK_DETAIL


def parse_playback_cache(websocket: WebSocket) -> str:
    raw_cache = str(websocket.query_params.get("cache") or DEFAULT_PLAYBACK_CACHE).lower()
    return raw_cache if raw_cache in PLAYBACK_CACHE_OPTIONS else DEFAULT_PLAYBACK_CACHE


def parse_sumo_seed(websocket: WebSocket) -> int | None:
    """Pin the SUMO RNG for reproducible recordings; live visits stay random."""
    raw = str(websocket.query_params.get("sumoseed") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_fleet_size(websocket: WebSocket) -> int | None:
    """Optional fleet-size override (recording matrix / fleet-sizing runs)."""
    raw = str(websocket.query_params.get("fleet") or "").strip()
    if not raw:
        return None
    try:
        fleet = int(raw)
    except ValueError:
        return None
    return fleet if fleet in FLEET_SIZE_OPTIONS else None


def scenario_fleet_size(selected: dict[str, Any]) -> int:
    try:
        fleet = int(selected.get("fleetSize") or 0)
    except (TypeError, ValueError):
        fleet = 0
    return fleet if fleet > 0 else ROBOTAXI_FLEET_SIZE


def parse_demand_file(websocket: WebSocket) -> Path | None:
    """Optional demand-file override for live recordings (seed variants).

    Only bare filenames inside MATSIM_DEMAND_DIR are accepted.
    """
    raw = str(websocket.query_params.get("demandfile") or "").strip()
    if not raw:
        return None
    candidate = MATSIM_DEMAND_DIR / Path(raw).name
    if not candidate.exists():
        return None
    return candidate


def playback_step_and_stride(playback_rate: int) -> tuple[float, int]:
    if playback_rate <= PLAYBACK_DATA_FPS:
        return playback_rate / PLAYBACK_DATA_FPS, 1
    return 1.0, max(1, int(round(playback_rate / PLAYBACK_DATA_FPS)))


def stable_sample_key(value: str) -> int:
    return int(hashlib.sha1(value.encode("utf-8")).hexdigest()[:8], 16)


def public_replay_cache_path(
    selected: dict[str, Any],
    playback_rate: int,
    demand_source: str,
    dispatch_engine: str,
    playback_detail: str,
) -> Path | None:
    if (
        selected["key"] not in PLAYBACK_SCOPES
        or demand_source != "matsim"
        or dispatch_engine != "taxi"
        or playback_detail != "public"
    ):
        return None
    # Seeded recordings are different sampled evenings; pick one at random per
    # connection so repeat visits do not replay the identical run. The berlin
    # scenario additionally keys the cache on fleet size (recording matrix).
    if selected["key"] == "berlin":
        fleet = scenario_fleet_size(selected)
        seeded = sorted(
            PUBLIC_REPLAY_DIR.glob(f"berlin_taxi_matsim_public.fleet{fleet}.seed*.jsonl.gz")
        )
        if seeded:
            return random.choice(seeded)
        return PUBLIC_REPLAY_DIR / f"berlin_taxi_matsim_public.fleet{fleet}.jsonl.gz"
    seeded = sorted(
        PUBLIC_REPLAY_DIR.glob("charlottenburg-moabit-tiergarten_taxi_matsim_public.seed*.jsonl.gz")
    )
    if seeded:
        return random.choice(seeded)
    return PUBLIC_REPLAY_DIR / "charlottenburg-moabit-tiergarten_taxi_matsim_public.jsonl.gz"


async def stream_cached_public_replay(
    websocket: WebSocket,
    cache_path: Path,
) -> None:
    opener = gzip.open if cache_path.suffix == ".gz" else open
    streamed_chunk_index = 0
    with opener(cache_path, "rt", encoding="utf-8") as replay_file:
        for line in replay_file:
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("type") == "chunk":
                frames = payload.get("frames") or []
                if not frames:
                    continue
                for frame_start in range(0, len(frames), PUBLIC_REPLAY_STREAM_FRAMES_PER_CHUNK):
                    frame_slice = frames[frame_start : frame_start + PUBLIC_REPLAY_STREAM_FRAMES_PER_CHUNK]
                    chunk_payload = {
                        **payload,
                        "chunkIndex": streamed_chunk_index,
                        "chunkVisualFrames": len(frame_slice),
                        "startSimSec": frame_slice[0].get("simSec"),
                        "endSimSec": frame_slice[-1].get("simSec"),
                        "frames": frame_slice,
                    }
                    profile = dict(payload.get("profile") or {})
                    profile["frames"] = len(frame_slice)
                    chunk_payload["profile"] = profile
                    try:
                        await websocket.send_json(chunk_payload)
                    except (RuntimeError, WebSocketDisconnect):
                        return
                    streamed_chunk_index += 1
                    await asyncio.sleep(PUBLIC_REPLAY_CHUNK_DELAY_SEC)
                continue

            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                return


def find_sumo_home() -> Path | None:
    configured_home = os.getenv("SUMO_HOME")
    if configured_home and Path(configured_home).exists():
        return Path(configured_home)

    windows_home = Path(r"C:\Program Files (x86)\Eclipse\Sumo")
    if windows_home.exists():
        return windows_home

    linux_home = Path("/usr/share/sumo")
    if linux_home.exists():
        return linux_home

    return None


def find_sumo_binary() -> str | None:
    configured_binary = os.getenv("SUMO_BINARY")
    if configured_binary and Path(configured_binary).exists():
        return configured_binary

    path_binary = shutil.which("sumo")
    if path_binary:
        return path_binary

    sumo_home = find_sumo_home()
    if not sumo_home:
        return None

    candidate = sumo_home / "bin" / ("sumo.exe" if os.name == "nt" else "sumo")
    return str(candidate) if candidate.exists() else None


def ensure_traci_import() -> Any:
    """Return the SUMO control module: libsumo (in-process) when available.

    libsumo mirrors the traci API but replaces the per-command TCP round-trip
    with direct C++ calls (~15 ms/step saved on Windows loopback; measured
    45x -> 62x real-time on the Berlin scenario). Set
    ROBOTAXI_SUMO_TRANSPORT=traci to force the socket transport.
    """
    ensure_sumo_tools()

    transport = os.getenv("ROBOTAXI_SUMO_TRANSPORT", "libsumo").strip().lower()
    if transport != "traci":
        try:
            import libsumo  # type: ignore[import-not-found]

            if not hasattr(libsumo, "constants"):
                libsumo.constants = libsumo  # constants live on the module
            if not hasattr(libsumo, "getConnection"):
                libsumo.getConnection = lambda label=None: libsumo
            if not getattr(libsumo, "_robotaxi_start_shim", False):
                original_start = libsumo.start

                def start_without_label(cmd: Any, *args: Any, **kwargs: Any) -> Any:
                    kwargs.pop("label", None)
                    return original_start(cmd, *args, **kwargs)

                libsumo.start = start_without_label
                libsumo._robotaxi_start_shim = True
            return libsumo
        except ImportError:
            pass

    import traci  # type: ignore[import-not-found]

    return traci


def ensure_sumo_tools() -> None:
    sumo_home = find_sumo_home()
    if sumo_home:
        tools_path = sumo_home / "tools"
        if tools_path.exists() and str(tools_path) not in sys.path:
            sys.path.append(str(tools_path))


def sumo_version() -> dict[str, Any]:
    sumo_binary = find_sumo_binary()
    if not sumo_binary:
        return {"available": False, "error": "sumo binary not found"}

    try:
        result = subprocess.run(
            [sumo_binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "available": result.returncode == 0,
            "binary": sumo_binary,
            "returnCode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except FileNotFoundError:
        return {"available": False, "error": "sumo binary not found"}
    except subprocess.TimeoutExpired:
        return {"available": False, "error": "sumo --version timed out"}


@app.get("/health")
def health() -> dict[str, Any]:
    sumo = sumo_version()
    selected = get_sumo_scenario(None)
    files = packaged_sumo_files(selected)
    return {
        "ok": bool(sumo["available"] and all(files.values())),
        "service": "robotaxi-sumo-backend",
        "scope": selected["key"],
        "sumoAvailable": sumo["available"],
        "packagedFiles": files,
    }


@app.get("/sumo/version")
def get_sumo_version() -> dict[str, Any]:
    return sumo_version()


def packaged_sumo_files(sumo_scenario: dict[str, Any] | None = None) -> dict[str, bool]:
    selected = sumo_scenario or get_sumo_scenario(None)
    return {
        "net": selected["net"].exists(),
        "routes": selected["route"].exists(),
        "config": selected["config"].exists(),
        "additional": selected.get("additional") is None or selected["additional"].exists(),
    }


@lru_cache(maxsize=8)
def load_geojson(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=8)
def load_sumo_projection(net_path_value: str | None) -> tuple[tuple[float, float], int]:
    net_path = Path(net_path_value) if net_path_value else get_sumo_scenario(None)["net"]
    root = ET.parse(net_path).getroot()
    location = root.find("location")
    if location is None:
        raise ValueError("SUMO network location metadata is missing.")

    net_offset = parse_pair(location.attrib["netOffset"])
    zone_match = re.search(r"\+zone=(\d+)", location.attrib.get("projParameter", ""))
    utm_zone = int(zone_match.group(1)) if zone_match else 33
    return net_offset, utm_zone


@lru_cache(maxsize=4)
def load_sumo_network(
    net_path_value: str | None = None,
    max_lane_features: int | None = None,
    include_internal_lanes: bool = True,
    include_signal_links: bool = True,
) -> dict[str, Any]:
    net_path = Path(net_path_value) if net_path_value else get_sumo_scenario(None)["net"]
    tree = ET.parse(net_path)
    root = tree.getroot()
    location = root.find("location")
    if location is None:
        raise ValueError("SUMO network location metadata is missing.")

    net_offset, utm_zone = load_sumo_projection(str(net_path))

    lane_features = []
    internal_lane_features = []
    lane_shapes_by_id = {}
    lane_xy_shapes_by_id = {}
    total_lane_count = 0
    total_internal_lane_count = 0
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        is_internal = edge.attrib.get("function") == "internal" or edge_id.startswith(":")

        for lane in edge.findall("lane"):
            total_lane_count += 1
            if is_internal:
                total_internal_lane_count += 1
                if not include_internal_lanes:
                    continue
            if max_lane_features is not None and (
                len(lane_features) + len(internal_lane_features) >= max_lane_features
            ):
                continue
            lane_id = lane.attrib.get("id", "")
            xy_shape = parse_sumo_xy_shape(lane.attrib.get("shape", ""))
            shape = sumo_xy_shape_to_lonlat(xy_shape, net_offset, utm_zone)
            if len(shape) < 2:
                continue

            lane_shapes_by_id[lane_id] = shape
            lane_xy_shapes_by_id[lane_id] = xy_shape
            feature = {
                "type": "Feature",
                "properties": {
                    "id": lane_id,
                    "edgeId": edge_id,
                    "internal": is_internal,
                    "speed": round(float(lane.attrib.get("speed", 0)), 3),
                    "length": round(float(lane.attrib.get("length", 0)), 3),
                },
                "geometry": {"type": "LineString", "coordinates": shape},
            }
            if is_internal:
                internal_lane_features.append(feature)
            else:
                lane_features.append(feature)

    traffic_light_ids_by_junction = map_traffic_light_ids_by_junction(root)
    traffic_light_features = []
    for junction in root.findall("junction"):
        if junction.attrib.get("type") != "traffic_light":
            continue

        lon, lat = sumo_xy_to_lonlat(
            float(junction.attrib["x"]),
            float(junction.attrib["y"]),
            net_offset,
            utm_zone,
        )
        traffic_light_features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": junction.attrib.get("id"),
                    "trafficLightId": traffic_light_ids_by_junction.get(
                        junction.attrib.get("id", ""),
                        junction.attrib.get("id"),
                    ),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
            }
        )

    signal_records = []
    if include_signal_links:
        connection_elements = root.findall("connection")
    else:
        connection_elements = []
    for connection in connection_elements:
        traffic_light_id = connection.attrib.get("tl")
        link_index = connection.attrib.get("linkIndex")
        via_lane_id = connection.attrib.get("via")
        from_edge_id = connection.attrib.get("from")
        from_lane_index = connection.attrib.get("fromLane")
        if (
            not traffic_light_id
            or link_index is None
            or not via_lane_id
            or not from_edge_id
            or from_lane_index is None
        ):
            continue

        incoming_lane_id = f"{from_edge_id}_{from_lane_index}"
        is_incoming_lane_geometry = incoming_lane_id in lane_xy_shapes_by_id
        xy_shape = lane_xy_shapes_by_id.get(incoming_lane_id)
        if not xy_shape:
            is_incoming_lane_geometry = False
            xy_shape = lane_xy_shapes_by_id.get(via_lane_id)
        if not xy_shape:
            continue

        signal_records.append(
            {
                "traffic_light_id": traffic_light_id,
                "link_index": int(link_index),
                "incoming_lane_id": incoming_lane_id,
                "via_lane_id": via_lane_id,
                "from_edge_id": from_edge_id,
                "to_edge_id": connection.attrib.get("to"),
                "direction": connection.attrib.get("dir"),
                "xy_shape": xy_shape,
                "at_end": is_incoming_lane_geometry,
            }
        )

    signal_records_by_incoming_lane: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in signal_records:
        key = (record["traffic_light_id"], record["incoming_lane_id"])
        signal_records_by_incoming_lane.setdefault(key, []).append(record)

    signal_link_features = []
    for records in signal_records_by_incoming_lane.values():
        records.sort(key=lambda record: record["link_index"])
        for slot_index, record in enumerate(records):
            slot_count = len(records)
            signal_link_features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": (
                            f"{record['traffic_light_id']}:"
                            f"{record['link_index']}:"
                            f"{record['incoming_lane_id']}"
                        ),
                        "trafficLightId": record["traffic_light_id"],
                        "linkIndex": record["link_index"],
                        "incomingLaneId": record["incoming_lane_id"],
                        "viaLaneId": record["via_lane_id"],
                        "fromEdge": record["from_edge_id"],
                        "toEdge": record["to_edge_id"],
                        "direction": record["direction"],
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": signal_stop_line_coordinates(
                            record["xy_shape"],
                            net_offset,
                            utm_zone,
                            at_end=record["at_end"],
                            slot_index=slot_index,
                            slot_count=slot_count,
                        ),
                    },
                }
            )

    return {
        "lanes": {"type": "FeatureCollection", "features": lane_features},
        "internalLanes": {
            "type": "FeatureCollection",
            "features": internal_lane_features,
        },
        "trafficLights": {
            "type": "FeatureCollection",
            "features": traffic_light_features,
        },
        "signalLinks": {
            "type": "FeatureCollection",
            "features": signal_link_features,
        },
        "counts": {
            "lanes": len(lane_features),
            "internalLanes": len(internal_lane_features),
            "trafficLights": len(traffic_light_features),
            "signalLinks": len(signal_link_features),
            "totalLanes": total_lane_count - total_internal_lane_count,
            "totalInternalLanes": total_internal_lane_count,
        },
        "limited": max_lane_features is not None
        and len(lane_features) + len(internal_lane_features) >= max_lane_features,
    }


@lru_cache(maxsize=4)
def load_sumo_edge_line_shapes(net_path_value: str) -> dict[str, list[list[float]]]:
    net_path = Path(net_path_value)
    net_offset, utm_zone = load_sumo_projection(str(net_path))
    root = ET.parse(net_path).getroot()
    edge_shapes: dict[str, list[list[float]]] = {}

    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if not edge_id or edge_id.startswith(":") or edge.attrib.get("function") == "internal":
            continue
        lane = edge.find("lane")
        if lane is None:
            continue
        shape = parse_sumo_shape(lane.attrib.get("shape", ""), net_offset, utm_zone)
        if len(shape) >= 2:
            edge_shapes[edge_id] = shape

    return edge_shapes


def map_traffic_light_ids_by_junction(root: ET.Element) -> dict[str, str]:
    traffic_junction_ids = [
        junction.attrib["id"]
        for junction in root.findall("junction")
        if junction.attrib.get("type") == "traffic_light" and junction.attrib.get("id")
    ]
    traffic_junction_ids.sort(key=len, reverse=True)

    traffic_light_ids_by_junction: dict[str, str] = {}
    for connection in root.findall("connection"):
        traffic_light_id = connection.attrib.get("tl")
        via_lane_id = connection.attrib.get("via", "")
        if not traffic_light_id or not via_lane_id.startswith(":"):
            continue

        internal_lane_id = via_lane_id[1:]
        for junction_id in traffic_junction_ids:
            if internal_lane_id.startswith(f"{junction_id}_"):
                traffic_light_ids_by_junction.setdefault(junction_id, traffic_light_id)
                break

    return traffic_light_ids_by_junction


def parse_pair(value: str) -> tuple[float, float]:
    first, second = value.split(",", maxsplit=1)
    return float(first), float(second)


def parse_sumo_shape(
    shape: str,
    net_offset: tuple[float, float],
    utm_zone: int,
) -> list[list[float]]:
    return sumo_xy_shape_to_lonlat(parse_sumo_xy_shape(shape), net_offset, utm_zone)


@lru_cache(maxsize=8)
def load_sumo_additional_geometry(
    additional_path_value: str | None,
    net_path_value: str | None,
) -> dict[str, Any]:
    if not additional_path_value:
        return {"type": "FeatureCollection", "features": []}

    additional_path = Path(additional_path_value)
    if not additional_path.exists():
        return {"type": "FeatureCollection", "features": []}

    net_offset, utm_zone = load_sumo_projection(net_path_value)
    root = ET.parse(additional_path).getroot()
    features = []
    for poly in root.findall("poly"):
        shape = poly.attrib.get("shape", "")
        coordinates = parse_sumo_shape(shape, net_offset, utm_zone)
        if len(coordinates) < 3:
            continue
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": poly.attrib.get("id"),
                    "color": poly.attrib.get("color"),
                    "layer": poly.attrib.get("layer"),
                },
                "geometry": {"type": "Polygon", "coordinates": [coordinates]},
            }
        )

    return {"type": "FeatureCollection", "features": features}


def sumo_command_with_additional(command: list[str], selected: dict[str, Any]) -> list[str]:
    additional_path = selected.get("additional")
    if additional_path and Path(additional_path).exists():
        return [*command, "--additional-files", str(additional_path)]
    return command


def sumo_command_with_route_file(command: list[str], route_path: Path | None) -> list[str]:
    if route_path and route_path.exists():
        return [*command, "--route-files", str(route_path)]
    return command


def unlink_with_retries(path: Path, attempts: int = 10, delay_sec: float = 0.1) -> None:
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == attempts - 1:
                return
            time.sleep(delay_sec)
        except FileNotFoundError:
            return


def parse_sumo_xy_shape(shape: str) -> list[tuple[float, float]]:
    coordinates = []
    for point in shape.split():
        coordinates.append(parse_pair(point))
    return coordinates


def sumo_xy_shape_to_lonlat(
    xy_shape: list[tuple[float, float]],
    net_offset: tuple[float, float],
    utm_zone: int,
) -> list[list[float]]:
    coordinates = []
    for x, y in xy_shape:
        lon, lat = sumo_xy_to_lonlat(x, y, net_offset, utm_zone)
        coordinates.append([lon, lat])
    return coordinates


def signal_stop_line_coordinates(
    xy_shape: list[tuple[float, float]],
    net_offset: tuple[float, float],
    utm_zone: int,
    at_end: bool = False,
    slot_index: int = 0,
    slot_count: int = 1,
) -> list[list[float]]:
    if len(xy_shape) < 2:
        return sumo_xy_shape_to_lonlat(xy_shape, net_offset, utm_zone)

    if at_end:
        anchor_x, anchor_y = xy_shape[-1]
        previous_x, previous_y = xy_shape[-2]
        dx = anchor_x - previous_x
        dy = anchor_y - previous_y
    else:
        anchor_x, anchor_y = xy_shape[0]
        next_x, next_y = xy_shape[1]
        dx = next_x - anchor_x
        dy = next_y - anchor_y

    length = math.hypot(dx, dy)
    if length == 0:
        return sumo_xy_shape_to_lonlat(xy_shape[:2], net_offset, utm_zone)

    half_width_m = 3.0
    perp_x = -dy / length
    perp_y = dx / length
    safe_slot_count = max(1, slot_count)
    gap_m = 0.75 if safe_slot_count > 1 else 0
    total_width_m = half_width_m * 2
    segment_width_m = max(
        0.35,
        (total_width_m - gap_m * (safe_slot_count - 1)) / safe_slot_count,
    )
    slot_start_m = -half_width_m + slot_index * (segment_width_m + gap_m)
    slot_end_m = slot_start_m + segment_width_m
    endpoints = [
        (anchor_x + perp_x * slot_start_m, anchor_y + perp_y * slot_start_m),
        (anchor_x + perp_x * slot_end_m, anchor_y + perp_y * slot_end_m),
    ]
    return sumo_xy_shape_to_lonlat(endpoints, net_offset, utm_zone)


def sumo_xy_to_lonlat(
    x: float,
    y: float,
    net_offset: tuple[float, float],
    utm_zone: int,
) -> tuple[float, float]:
    easting = x - net_offset[0]
    northing = y - net_offset[1]
    return utm_to_lonlat(easting, northing, utm_zone)


def interpolate_xy_along_shape(
    xy_shape: list[tuple[float, float]],
    pos: float,
) -> tuple[float, float]:
    if not xy_shape:
        return 0.0, 0.0
    if len(xy_shape) == 1:
        return xy_shape[0]

    remaining = max(0.0, pos)
    for start, end in zip(xy_shape, xy_shape[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        segment_length = math.hypot(dx, dy)
        if segment_length <= 0:
            continue
        if remaining <= segment_length:
            ratio = remaining / segment_length
            return start[0] + dx * ratio, start[1] + dy * ratio
        remaining -= segment_length
    return xy_shape[-1]


@lru_cache(maxsize=4)
def load_sumo_edge_reference_points(
    net_path_value: str,
) -> dict[str, dict[str, Any]]:
    net_offset, utm_zone = load_sumo_projection(net_path_value)
    root = ET.parse(net_path_value).getroot()
    edge_points: dict[str, dict[str, Any]] = {}

    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if not edge_id or edge_id.startswith(":"):
            continue
        lane = edge.find("lane")
        if lane is None:
            continue
        # Riders board taxis: a pickup/dropoff on a lane without taxi access
        # crashes SUMO's reservation add mid-run ("origin edge does not permit
        # taxi access"), killing the whole recording.
        lane_allow = lane.attrib.get("allow")
        if lane_allow is not None:
            allow_classes = lane_allow.split()
            taxi_allowed = "taxi" in allow_classes or "all" in allow_classes
        else:
            taxi_allowed = "taxi" not in (lane.attrib.get("disallow") or "").split()
        if not taxi_allowed:
            continue

        xy_shape = parse_sumo_xy_shape(lane.attrib.get("shape", ""))
        if len(xy_shape) < 2:
            continue

        lane_length = float(lane.attrib.get("length", 0))
        if lane_length <= 2:
            continue

        pickup_pos = min(10.0, max(1.0, lane_length * 0.33))
        dropoff_pos = max(1.0, min(lane_length - 2.0, lane_length - 10.0))
        pickup_x, pickup_y = interpolate_xy_along_shape(xy_shape, pickup_pos)
        dropoff_x, dropoff_y = interpolate_xy_along_shape(xy_shape, dropoff_pos)
        pickup_lon, pickup_lat = sumo_xy_to_lonlat(pickup_x, pickup_y, net_offset, utm_zone)
        dropoff_lon, dropoff_lat = sumo_xy_to_lonlat(dropoff_x, dropoff_y, net_offset, utm_zone)
        edge_points[edge_id] = {
            "length": lane_length,
            "pickupPos": round(pickup_pos, 3),
            "dropoffPos": round(dropoff_pos, 3),
            "pickup": {"lon": round(pickup_lon, 7), "lat": round(pickup_lat, 7)},
            "dropoff": {"lon": round(dropoff_lon, 7), "lat": round(dropoff_lat, 7)},
        }

    return edge_points


def stable_percent_bucket(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def cybercab_can_serve_party(party_size: int | None) -> bool:
    return int(party_size or 1) <= ROBOTAXI_CYBERCAB_SEATS


def lonlat_distance_m(a_lon: float, a_lat: float, b_lon: float, b_lat: float) -> float:
    mean_lat_rad = math.radians((a_lat + b_lat) / 2.0)
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = 111_320.0 * math.cos(mean_lat_rad)
    dx = (a_lon - b_lon) * meters_per_degree_lon
    dy = (a_lat - b_lat) * meters_per_degree_lat
    return math.hypot(dx, dy)


def nearest_edge_stop(
    edge_points: dict[str, dict[str, Any]],
    lon: float,
    lat: float,
    stop_kind: str,
    max_distance_m: float,
) -> dict[str, Any] | None:
    best_match: dict[str, Any] | None = None
    best_distance = float("inf")
    pos_key = "pickupPos" if stop_kind == "pickup" else "dropoffPos"

    for edge_id, point in edge_points.items():
        coordinate = point[stop_kind]
        distance_m = lonlat_distance_m(
            lon,
            lat,
            float(coordinate["lon"]),
            float(coordinate["lat"]),
        )
        if distance_m < best_distance:
            best_distance = distance_m
            best_match = {
                "edge": edge_id,
                "pos": point[pos_key],
                "coordinate": coordinate,
                "distanceM": distance_m,
            }

    if best_match is None or best_distance > max_distance_m:
        return None
    return best_match


def rejected_matsim_request(
    trip: dict[str, Any],
    reason: str,
    *,
    pickup: dict[str, float] | None = None,
    dropoff: dict[str, float] | None = None,
    pickup_match: dict[str, Any] | None = None,
    dropoff_match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    party_size = 1
    return {
        "id": f"matsim_{trip.get('requestId') or trip.get('personId')}",
        "source": "matsim",
        "sourcePersonId": trip.get("personId"),
        "sourceTripId": trip.get("requestId"),
        "sourceMode": trip.get("primaryMode"),
        "sourceExpansionFactor": MATSIM_SAMPLE_EXPANSION_FACTOR,
        "requestedAtSec": float(trip.get("departureSec", SUMO_START_SEC)),
        "partySize": party_size,
        "passengers": party_size,
        "cybercabSeats": ROBOTAXI_CYBERCAB_SEATS,
        "fallbackSeats": ROBOTAXI_FALLBACK_SEATS,
        "cybercabCapable": cybercab_can_serve_party(party_size),
        "pickupEdge": pickup_match["edge"] if pickup_match else None,
        "pickupPos": pickup_match["pos"] if pickup_match else None,
        "pickup": pickup or {
            "lon": trip.get("originLon"),
            "lat": trip.get("originLat"),
        },
        "dropoffEdge": dropoff_match["edge"] if dropoff_match else None,
        "dropoffPos": dropoff_match["pos"] if dropoff_match else None,
        "dropoff": dropoff or {
            "lon": trip.get("destinationLon"),
            "lat": trip.get("destinationLat"),
        },
        "pickupMapDistanceM": round(float(pickup_match["distanceM"]), 1)
        if pickup_match
        else None,
        "dropoffMapDistanceM": round(float(dropoff_match["distanceM"]), 1)
        if dropoff_match
        else None,
        "status": "rejected",
        "assignedVehicleId": None,
        "pickupAtSec": None,
        "completedAtSec": None,
        "error": reason,
        "rejectionReason": reason,
    }


@lru_cache(maxsize=8)
def load_matsim_person_demand_requests(
    demand_path_value: str,
    net_path_value: str,
    start_sec: int,
    end_sec: int,
    max_stop_distance_m: float,
) -> dict[str, Any]:
    demand_path = Path(demand_path_value)
    if not demand_path.exists():
        return {
            "requests": [],
            "sourceTripCount": 0,
            "eligibleTripCount": 0,
            "targetRequestCount": 0,
            "rejectedRequestCount": 0,
            "rejectionCounts": {"missing_demand_file": 1},
            "error": f"MATSim demand file missing: {demand_path}",
        }

    with demand_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    trips = payload.get("trips", [])
    metadata = payload.get("metadata", {})
    edge_points = load_sumo_edge_reference_points(net_path_value)
    requests: list[dict[str, Any]] = []
    source_trip_count = 0
    eligible_trip_count = 0
    mapped_request_count = 0
    reachable_request_count = 0
    rejection_counts: dict[str, int] = {}

    def reject(reason: str, trip: dict[str, Any], **kwargs: Any) -> None:
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        requests.append(rejected_matsim_request(trip, reason, **kwargs))

    for trip in trips:
        try:
            depart_sec = float(trip.get("departureSec", -1))
        except (TypeError, ValueError):
            reject("invalid_departure_time", trip)
            continue

        if not (start_sec <= depart_sec < end_sec):
            continue

        primary_mode = str(trip.get("primaryMode") or trip.get("mode") or "").strip().lower()
        if primary_mode not in MATSIM_ROBOTAXI_MODES:
            rejection_counts["unsupported_mode"] = rejection_counts.get("unsupported_mode", 0) + 1
            continue

        source_trip_count += 1
        try:
            origin_lon = float(trip["originLon"])
            origin_lat = float(trip["originLat"])
            destination_lon = float(trip["destinationLon"])
            destination_lat = float(trip["destinationLat"])
        except (KeyError, TypeError, ValueError):
            reject("missing_coordinates", trip)
            continue

        eligible_trip_count += 1
        pickup_match = nearest_edge_stop(
            edge_points,
            origin_lon,
            origin_lat,
            "pickup",
            max_stop_distance_m,
        )
        dropoff_match = nearest_edge_stop(
            edge_points,
            destination_lon,
            destination_lat,
            "dropoff",
            max_stop_distance_m,
        )
        pickup = {"lon": round(origin_lon, 7), "lat": round(origin_lat, 7)}
        dropoff = {"lon": round(destination_lon, 7), "lat": round(destination_lat, 7)}

        if not pickup_match:
            reject("pickup_unmapped", trip, pickup=pickup, dropoff=dropoff)
            continue
        if not dropoff_match:
            reject(
                "dropoff_unmapped",
                trip,
                pickup=pickup,
                dropoff=dropoff,
                pickup_match=pickup_match,
            )
            continue

        mapped_request_count += 1
        party_size = 1
        request = {
            "id": f"matsim_{trip.get('requestId') or trip.get('personId')}",
            "source": "matsim",
            "sourcePersonId": trip.get("personId"),
            "sourceTripId": trip.get("requestId"),
            "sourceMode": primary_mode,
            "sourceExpansionFactor": MATSIM_SAMPLE_EXPANSION_FACTOR,
            "requestedAtSec": depart_sec,
            "partySize": party_size,
            "passengers": party_size,
            "cybercabSeats": ROBOTAXI_CYBERCAB_SEATS,
            "fallbackSeats": ROBOTAXI_FALLBACK_SEATS,
            "cybercabCapable": cybercab_can_serve_party(party_size),
            "pickupEdge": pickup_match["edge"],
            "pickupPos": pickup_match["pos"],
            "pickup": pickup_match["coordinate"],
            "dropoffEdge": dropoff_match["edge"],
            "dropoffPos": dropoff_match["pos"],
            "dropoff": dropoff_match["coordinate"],
            "origin": pickup,
            "destination": dropoff,
            "pickupMapDistanceM": round(float(pickup_match["distanceM"]), 1),
            "dropoffMapDistanceM": round(float(dropoff_match["distanceM"]), 1),
            "sourceDistanceM": trip.get("distanceM"),
            "sourceTravelTimeSec": trip.get("travelTimeSec"),
        }

        if not is_robotaxi_request_reachable(request, net_path_value):
            reject(
                "unreachable_in_sumo",
                trip,
                pickup=pickup_match["coordinate"],
                dropoff=dropoff_match["coordinate"],
                pickup_match=pickup_match,
                dropoff_match=dropoff_match,
            )
            continue

        reachable_request_count += 1
        requests.append(request)

    requests.sort(key=lambda request: (float(request.get("requestedAtSec", 0.0)), str(request["id"])))
    return {
        "requests": requests,
        "sourceTripCount": source_trip_count,
        "eligibleTripCount": eligible_trip_count,
        "mappedRequestCount": mapped_request_count,
        "reachableRequestCount": reachable_request_count,
        "targetRequestCount": reachable_request_count,
        "rejectedRequestCount": sum(rejection_counts.values()),
        "rejectionCounts": rejection_counts,
        "metadata": metadata,
        "sourceFile": str(demand_path),
        "source": "matsim",
        "error": None,
    }


@lru_cache(maxsize=12)
def load_trip_replacement_requests(
    route_path_value: str,
    net_path_value: str,
    start_sec: int,
    end_sec: int,
    replacement_percent: int,
) -> dict[str, Any]:
    route_path = Path(route_path_value)
    if not route_path.exists():
        return {
            "requests": [],
            "sourceTripCount": 0,
            "eligibleTripCount": 0,
            "targetRequestCount": 0,
            "error": f"route file missing: {route_path}",
        }

    edge_points = load_sumo_edge_reference_points(net_path_value)
    requests = []
    source_trip_count = 0
    eligible_trip_count = 0

    for _, vehicle in ET.iterparse(route_path, events=("end",)):
        if vehicle.tag != "vehicle":
            continue

        vehicle_id = vehicle.attrib.get("id", "")
        try:
            depart_sec = float(vehicle.attrib.get("depart", "-1"))
        except ValueError:
            vehicle.clear()
            continue

        if start_sec <= depart_sec < end_sec:
            route = vehicle.find("route")
            edges = route.attrib.get("edges", "").split() if route is not None else []
            if len(edges) >= 2:
                source_trip_count += 1
                pickup_edge = edges[0]
                dropoff_edge = edges[-1]
                pickup_point = edge_points.get(pickup_edge)
                dropoff_point = edge_points.get(dropoff_edge)
                if pickup_point and dropoff_point:
                    eligible_trip_count += 1
                if (
                    pickup_point
                    and dropoff_point
                    and stable_percent_bucket(vehicle_id) < replacement_percent
                ):
                    party_size = 1
                    requests.append(
                        {
                            "id": f"trip_{vehicle_id}",
                            "sourceVehicleId": vehicle_id,
                            "requestedAtSec": depart_sec,
                            "partySize": party_size,
                            "passengers": party_size,
                            "cybercabSeats": ROBOTAXI_CYBERCAB_SEATS,
                            "fallbackSeats": ROBOTAXI_FALLBACK_SEATS,
                            "cybercabCapable": cybercab_can_serve_party(party_size),
                            "pickupEdge": pickup_edge,
                            "pickupPos": pickup_point["pickupPos"],
                            "pickup": pickup_point["pickup"],
                            "dropoffEdge": dropoff_edge,
                            "dropoffPos": dropoff_point["dropoffPos"],
                            "dropoff": dropoff_point["dropoff"],
                            "originalEdgeCount": len(edges),
                        }
                    )

        vehicle.clear()

    requests.sort(key=lambda request: (request["requestedAtSec"], request["id"]))
    return {
        "requests": requests,
        "sourceTripCount": source_trip_count,
        "eligibleTripCount": eligible_trip_count,
        "targetRequestCount": len(requests),
        "error": None,
    }


@lru_cache(maxsize=4)
def load_sumolib_net(net_path_value: str) -> Any:
    ensure_sumo_tools()
    import sumolib  # type: ignore[import-not-found]

    return sumolib.net.readNet(net_path_value, withInternal=False)


@lru_cache(maxsize=20_000)
def has_sumolib_route(net_path_value: str, from_edge_id: str, to_edge_id: str) -> bool:
    try:
        net = load_sumolib_net(net_path_value)
        from_edge = net.getEdge(from_edge_id)
        to_edge = net.getEdge(to_edge_id)
        route, _cost = net.getShortestPath(from_edge, to_edge)
        return bool(route)
    except Exception:
        return False


def is_robotaxi_request_reachable(request: dict[str, Any], net_path_value: str) -> bool:
    pickup_edge = str(request["pickupEdge"])
    dropoff_edge = str(request["dropoffEdge"])
    depot_edge = ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    return (
        has_sumolib_route(net_path_value, depot_edge, pickup_edge)
        and has_sumolib_route(net_path_value, pickup_edge, dropoff_edge)
        and has_sumolib_route(net_path_value, dropoff_edge, depot_edge)
    )


@lru_cache(maxsize=12)
def load_reachable_trip_replacement_requests(
    route_path_value: str,
    net_path_value: str,
    start_sec: int,
    end_sec: int,
    replacement_percent: int,
) -> dict[str, Any]:
    demand = load_trip_replacement_requests(
        route_path_value,
        net_path_value,
        start_sec,
        end_sec,
        replacement_percent,
    )
    reachable_requests = []
    unreachable_count = 0
    for request in demand["requests"]:
        if is_robotaxi_request_reachable(request, net_path_value):
            reachable_requests.append(request)
        else:
            unreachable_count += 1

    return {
        **demand,
        "requests": reachable_requests,
        "sampledRequestCount": len(demand["requests"]),
        "unreachableRequestCount": unreachable_count,
        "targetRequestCount": len(reachable_requests),
        "reachabilityFiltered": True,
    }


def filtered_route_file_for_replacement(
    selected: dict[str, Any],
    replacement_percent: int,
    demand_source: str = "sumo",
) -> Path | None:
    if demand_source != "sumo":
        return None

    demand = load_reachable_trip_replacement_requests(
        str(selected["route"]),
        str(selected["net"]),
        int(selected["startSec"]),
        int(selected["endSec"]),
        replacement_percent,
    )
    source_vehicle_ids = {
        str(request["sourceVehicleId"])
        for request in demand["requests"]
        if request.get("sourceVehicleId") is not None
        and cybercab_can_serve_party(request.get("partySize"))
    }
    if not source_vehicle_ids:
        return None

    output_dir = Path(selected["dir"]) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    filtered_route_path = output_dir / f"replacement-v2-{replacement_percent:02d}-contained.rou.xml"
    source_route_path = Path(selected["route"])

    tree = ET.parse(source_route_path)
    root = tree.getroot()
    for vehicle in list(root.findall("vehicle")):
        if vehicle.attrib.get("id") in source_vehicle_ids:
            root.remove(vehicle)

    temp_path = filtered_route_path.with_suffix(".tmp")
    tree.write(temp_path, encoding="utf-8", xml_declaration=True)
    temp_path.replace(filtered_route_path)
    return filtered_route_path


def robotaxi_source_demand(
    selected: dict[str, Any],
    replacement_percent: int,
    demand_source: str,
) -> dict[str, Any]:
    if demand_source == "matsim":
        demand_file = selected.get("demandFile") or MATSIM_DEFAULT_DEMAND_FILE
        return load_matsim_person_demand_requests(
            str(demand_file),
            str(selected["net"]),
            int(selected["startSec"]),
            int(selected["endSec"]),
            MATSIM_MAX_STOP_DISTANCE_M,
        )

    return load_reachable_trip_replacement_requests(
        str(selected["route"]),
        str(selected["net"]),
        int(selected["startSec"]),
        int(selected["endSec"]),
        replacement_percent,
    )


def dispatchable_robotaxi_requests(demand: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        request
        for request in demand.get("requests", [])
        if request.get("status", "scheduled") == "scheduled"
        and request.get("pickupEdge")
        and request.get("dropoffEdge")
        and cybercab_can_serve_party(request.get("partySize"))
    ]


@lru_cache(maxsize=8)
def load_scenario_metadata(metadata_path_value: str) -> dict[str, Any]:
    metadata_path = Path(metadata_path_value)
    if not metadata_path.exists():
        return {}
    with metadata_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def scenario_staging_edges(selected: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = load_scenario_metadata(str(Path(selected["dir"]) / "metadata.json"))
    staging = metadata.get("staging")
    if not isinstance(staging, dict):
        return []
    edges = staging.get("edges")
    return [edge for edge in edges if isinstance(edge, dict) and edge.get("edgeId")] if isinstance(edges, list) else []


def scenario_staging_edge_id(selected: dict[str, Any], index: int) -> str:
    staging_edges = scenario_staging_edges(selected)
    if staging_edges:
        # Fleets larger than the staging grid wrap around it — nobody falls
        # back to the depot (the depot-sleeper trap).
        return str(staging_edges[index % len(staging_edges)]["edgeId"])
    return ROBOTAXI_DEPOT_ROUTE_EDGES[0]


def scenario_staging_depart_pos(selected: dict[str, Any], index: int) -> str:
    staging_edges = scenario_staging_edges(selected)
    if not staging_edges:
        return str(82 + (index % 6) * 6)
    slot = index % len(staging_edges)
    try:
        length_m = float(staging_edges[slot].get("lengthM") or 20.0)
    except (TypeError, ValueError):
        length_m = 20.0
    # Wrapped fleet mates share an edge: offset them a car-length apart so
    # simultaneous inserts don't collide.
    base_pos = max(1.0, min(length_m * 0.5, max(1.0, length_m - 2.0)))
    offset = (index // len(staging_edges)) * 9.0
    return str(round(max(1.0, min(base_pos + offset, max(1.0, length_m - 2.0))), 1))


def build_taxi_drt_route_file(
    selected: dict[str, Any],
    replacement_percent: int,
    demand_source: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    demand = robotaxi_source_demand(selected, replacement_percent, demand_source)
    requests = dispatchable_robotaxi_requests(demand)
    output_dir = Path(selected["dir"]) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    route_run_id = run_id or uuid.uuid4().hex
    route_path = output_dir / f"taxi-drt-{demand_source}-{replacement_percent:02d}-{route_run_id}.rou.xml"

    root = ET.Element("routes")
    vehicle_type = ET.SubElement(
        root,
        "vType",
        id=ROBOTAXI_TYPE_ID,
        vClass="taxi",
        personCapacity=str(ROBOTAXI_CYBERCAB_SEATS),
        length="4.2",
        width="1.85",
        color="255,193,7",
    )
    ET.SubElement(vehicle_type, "param", key="has.taxi.device", value="true")
    ET.SubElement(
        vehicle_type,
        "param",
        key="device.taxi.end",
        value=str(selected.get("runtimeEndSec", selected["endSec"])),
    )
    ET.SubElement(vehicle_type, "param", key="device.taxi.pickUpDuration", value=str(ROBOTAXI_SERVICE_HOLD_SEC))
    ET.SubElement(vehicle_type, "param", key="device.taxi.dropOffDuration", value=str(ROBOTAXI_SERVICE_HOLD_SEC))
    ET.SubElement(vehicle_type, "param", key="device.taxi.parking", value="true")
    if selected.get("additional") is not None:
        ET.SubElement(
            vehicle_type,
            "param",
            key="device.taxi.stands-rerouter",
            value="txl_adac_cybercab_taxi_stands",
        )
    ET.SubElement(vehicle_type, "param", key="parking.ignoreDest", value="1")

    spawn_at_depot = bool(selected.get("spawnAtDepot")) and selected.get("depotEdge")
    for index in range(scenario_fleet_size(selected)):
        vehicle_id = f"{ROBOTAXI_ID_PREFIX}{index + 1:02d}"
        route_id = f"{ROBOTAXI_ROUTE_ID}_{index + 1:02d}"
        if spawn_at_depot:
            # Depot drive-in: the fleet leaves the depot in a staggered convoy
            # at shift start; the staging dispatcher routes them into the city.
            start_edge = str(selected["depotEdge"])
            depart = str(int(selected["startSec"]) + index * 8)
            depart_pos = "base"
        else:
            start_edge = scenario_staging_edge_id(selected, index)
            depart = str(selected["startSec"])
            depart_pos = scenario_staging_depart_pos(selected, index)
        ET.SubElement(root, "route", id=route_id, edges=start_edge)
        vehicle = ET.SubElement(
            root,
            "vehicle",
            id=vehicle_id,
            type=ROBOTAXI_TYPE_ID,
            route=route_id,
            depart=depart,
            departLane="best",
            departPos=depart_pos,
            departSpeed="0",
        )
        ET.SubElement(vehicle, "param", key="device.battery.capacity", value=str(ROBOTAXI_BATTERY_CAPACITY_WH))
        ET.SubElement(
            vehicle,
            "param",
            key="device.battery.maximumBatteryCapacity",
            value=str(ROBOTAXI_BATTERY_CAPACITY_WH),
        )
        ET.SubElement(
            vehicle,
            "param",
            key="device.battery.actualBatteryCapacity",
            value=str(ROBOTAXI_INITIAL_CHARGE_WH),
        )

    generated_requests = []
    for index, request in enumerate(requests):
        person_id = f"taxi_person_{index + 1:04d}"
        reservation_request = {
            **request,
            "personId": person_id,
            "status": "scheduled",
            "assignedVehicleId": None,
            "pickupAtSec": None,
            "completedAtSec": None,
            "reservationId": None,
        }
        generated_requests.append(reservation_request)
        person = ET.SubElement(
            root,
            "person",
            id=person_id,
            depart=str(float(request["requestedAtSec"])),
        )
        ride = ET.SubElement(
            person,
            "ride",
            {
                "from": str(request["pickupEdge"]),
                "to": str(request["dropoffEdge"]),
                "lines": "taxi",
            },
        )
        ET.SubElement(ride, "param", key="requestId", value=str(request["id"]))

    temp_path = route_path.with_suffix(".tmp")
    ET.ElementTree(root).write(temp_path, encoding="utf-8", xml_declaration=True)
    temp_path.replace(route_path)

    return {
        "routePath": route_path,
        "demand": demand,
        "requests": generated_requests,
    }


def utm_to_lonlat(easting: float, northing: float, zone: int) -> tuple[float, float]:
    # WGS84 UTM inverse projection. This avoids a heavyweight pyproj dependency
    # for one fixed SUMO network while matching sumolib's conversion closely.
    semi_major = 6_378_137.0
    flattening = 1 / 298.257223563
    scale_factor = 0.9996
    eccentricity = math.sqrt(flattening * (2 - flattening))
    eccentricity_prime_sq = eccentricity**2 / (1 - eccentricity**2)

    x = easting - 500_000.0
    central_meridian = math.radians((zone - 1) * 6 - 180 + 3)
    meridional_arc = northing / scale_factor
    mu = meridional_arc / (
        semi_major
        * (
            1
            - eccentricity**2 / 4
            - 3 * eccentricity**4 / 64
            - 5 * eccentricity**6 / 256
        )
    )

    e1 = (1 - math.sqrt(1 - eccentricity**2)) / (
        1 + math.sqrt(1 - eccentricity**2)
    )
    footpoint_lat = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )

    sin_lat = math.sin(footpoint_lat)
    cos_lat = math.cos(footpoint_lat)
    tan_lat = math.tan(footpoint_lat)
    c1 = eccentricity_prime_sq * cos_lat**2
    t1 = tan_lat**2
    radius_curvature = semi_major * (1 - eccentricity**2) / (
        (1 - eccentricity**2 * sin_lat**2) ** 1.5
    )
    prime_vertical = semi_major / math.sqrt(1 - eccentricity**2 * sin_lat**2)
    d = x / (prime_vertical * scale_factor)

    latitude = footpoint_lat - (prime_vertical * tan_lat / radius_curvature) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * eccentricity_prime_sq)
        * d**4
        / 24
        + (
            61
            + 90 * t1
            + 298 * c1
            + 45 * t1**2
            - 252 * eccentricity_prime_sq
            - 3 * c1**2
        )
        * d**6
        / 720
    )
    longitude = central_meridian + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * eccentricity_prime_sq + 24 * t1**2)
        * d**5
        / 120
    ) / cos_lat

    return math.degrees(longitude), math.degrees(latitude)


@app.get("/sumo/{scope}/summary")
def sumo_summary(scope: str) -> dict[str, Any]:
    selected = get_sumo_scenario(scope)
    return {
        "available": selected["config"].exists() and find_sumo_binary() is not None,
        "sumo": sumo_version(),
        "scope": selected["key"],
        "label": selected["label"],
        "config": str(selected["config"]),
        "window": {
            "startSec": selected["startSec"],
            "endSec": selected["endSec"],
            "label": scenario_window_label(selected),
        },
        "requestExpirySec": ROBOTAXI_REQUEST_EXPIRY_SEC,
        "fleetSize": scenario_fleet_size(selected),
        "files": packaged_sumo_files(selected),
    }


@app.get("/sumo/{scope}/network")
def sumo_network(scope: str) -> dict[str, Any]:
    selected = get_sumo_scenario(scope)
    if not selected["net"].exists():
        return {"available": False, "error": f"{selected['label']} SUMO net file is missing."}

    try:
        network = load_sumo_network(
            str(selected["net"]),
            selected["networkMaxLanes"],
            selected["includeInternalLanes"],
            selected["includeSignalLinks"],
        )
    except Exception as error:
        return {"available": False, "error": str(error)}

    boundary = load_geojson(str(selected["boundary"])) if selected.get("boundary") else None
    depot = load_sumo_additional_geometry(
        str(selected["additional"]) if selected.get("additional") else None,
        str(selected["net"]),
    )

    return {
        "available": True,
        "scope": selected["key"],
        "boundary": boundary,
        "depot": depot,
        **network,
    }


@app.get("/sumo/{scope}/validate")
def validate_sumo_scope(scope: str) -> dict[str, Any]:
    selected = get_sumo_scenario(scope)
    sumo_binary = find_sumo_binary()
    if not sumo_binary:
        return {"ok": False, "error": "sumo binary not found"}

    selected["dir"].mkdir(exist_ok=True)
    (selected["dir"] / "output").mkdir(exist_ok=True)
    sumo_home = find_sumo_home()
    env = os.environ.copy()
    if sumo_home:
        env["SUMO_HOME"] = str(sumo_home)

    command = [
        sumo_binary,
        "-c",
        str(selected["config"]),
        "--begin",
        str(selected["startSec"]),
        "--end",
        str(selected["startSec"] + 10),
        "--step-length",
        "1",
        "--no-step-log",
        "true",
        "--no-warnings",
        "true",
        "--duration-log.disable",
        "true",
        "--quit-on-end",
        "true",
    ]
    command = sumo_command_with_additional(command, selected)
    result = subprocess.run(
        command,
        cwd=str(selected["dir"]),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "ok": result.returncode == 0,
        "returnCode": result.returncode,
        "command": command,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


@app.get("/sumo/{scope}/playback")
def sumo_playback(scope: str) -> dict[str, Any]:
    selected = get_sumo_scenario(scope)
    default_step_sec, default_visual_stride = playback_step_and_stride(PLAYBACK_DEFAULT_RATE)
    return {
        "available": selected["key"] == PLAYBACK_SCOPE
        and selected["config"].exists()
        and find_sumo_binary() is not None,
        "backend": "sumo-traci-playback",
        "scope": selected["key"],
        "window": {
            "startSec": selected["startSec"],
            "endSec": selected["endSec"],
            "label": scenario_window_label(selected),
        },
        "playbackRate": PLAYBACK_DEFAULT_RATE,
        "dataFps": PLAYBACK_DATA_FPS,
        "availablePlaybackRates": sorted(PLAYBACK_SPEEDS),
        "replacementPercents": sorted(REPLACEMENT_PERCENT_OPTIONS),
        "defaultReplacementPercent": DEFAULT_REPLACEMENT_PERCENT,
        "demandSources": sorted(DEMAND_SOURCE_OPTIONS),
        "defaultDemandSource": DEFAULT_DEMAND_SOURCE,
        "chunkVisualFrames": PLAYBACK_CHUNK_VISUAL_FRAMES,
        "chunkSimSeconds": default_step_sec * default_visual_stride * PLAYBACK_CHUNK_VISUAL_FRAMES,
        "frameStepSec": default_step_sec,
        "visualStride": default_visual_stride,
        "websocket": f"/ws/sumo/{selected['key']}/playback",
        "frameShape": {
            "simSec": "number",
            "vehicles": [{"id": "string", "lon": "number", "lat": "number", "angle": "number"}],
            "trafficLights": {"trafficLightId": "state"},
            "dispatch": {
                "requests": [
                    {
                        "id": "string",
                        "status": "scheduled|waiting|assigned|onboard|completed|capacity_miss",
                    }
                ],
                "metrics": {
                    "waiting": "number",
                    "completed": "number",
                    "unservedCapacityPassengers": "number",
                    "passengerKm": "number",
                    "vehicleKm": "number",
                    "emptyKm": "number",
                    "energyKwh": "number",
                    "avgWaitSec": "number|null",
                },
            },
        },
    }


@app.websocket("/ws/sumo/{scope}/playback")
async def sumo_scope_playback(websocket: WebSocket, scope: str) -> None:
    await websocket.accept()

    try:
        selected = dict(get_sumo_scenario(scope))
    except HTTPException as error:
        await websocket.send_json({"type": "error", "message": error.detail})
        await websocket.close()
        return

    if selected["key"] not in PLAYBACK_SCOPES:
        await websocket.send_json(
            {
                "type": "error",
                "message": f"Playback recording is only available for {sorted(PLAYBACK_SCOPES)}.",
            }
        )
        await websocket.close()
        return

    playback_rate = parse_playback_rate(websocket)
    replacement_percent = parse_replacement_percent(websocket)
    demand_source = parse_demand_source(websocket)
    dispatch_engine = parse_dispatch_engine(websocket)
    playback_detail = parse_playback_detail(websocket)
    playback_cache = parse_playback_cache(websocket)
    selected["demandFile"] = parse_demand_file(websocket) or selected.get("demandFileDefault")
    fleet_override = parse_fleet_size(websocket)
    if fleet_override:
        selected["fleetSize"] = fleet_override
    sumo_seed_override = parse_sumo_seed(websocket)
    if sumo_seed_override is not None:
        selected["sumoSeed"] = sumo_seed_override
    frame_step_sec, visual_stride = playback_step_and_stride(playback_rate)
    runtime_end_sec = float(selected["endSec"])
    if dispatch_engine == "taxi":
        runtime_end_sec += float(
            selected.get("postServiceRecoverySec") or ROBOTAXI_POST_SERVICE_RECOVERY_SEC
        )
    selected["runtimeEndSec"] = runtime_end_sec
    cache_path = public_replay_cache_path(
        selected,
        playback_rate,
        demand_source,
        dispatch_engine,
        playback_detail,
    )
    cache_available = cache_path is not None and cache_path.exists()
    use_cache = playback_cache != "live" and cache_available

    if playback_cache == "cache" and not cache_available:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Public replay cache is unavailable. Regenerate it or use cache=live.",
            }
        )
        await websocket.close()
        return

    sumo_binary = find_sumo_binary()
    if not use_cache and (not sumo_binary or not selected["config"].exists()):
        await websocket.send_json(
            {
                "type": "error",
                "message": f"SUMO binary or {selected['label']} config is unavailable.",
                "sumoAvailable": bool(sumo_binary),
                "configExists": selected["config"].exists(),
            }
        )
        await websocket.close()
        return

    traci = None
    if not use_cache:
        try:
            traci = ensure_traci_import()
        except Exception as error:  # pragma: no cover - runtime environment dependent
            await websocket.send_json({"type": "error", "message": f"TraCI import failed: {error}"})
            await websocket.close()
            return

    command = [
        sumo_binary,
        "-c",
        str(selected["config"]),
        "--begin",
        str(selected["startSec"]),
        "--end",
        str(selected["runtimeEndSec"]),
        "--step-length",
        str(frame_step_sec),
        "--no-step-log",
        "true",
        "--quit-on-end",
        "true",
    ]

    sumo_home = find_sumo_home()
    if sumo_home:
        os.environ["SUMO_HOME"] = str(sumo_home)

    if dispatch_engine == "custom":
        replacement_route_path = filtered_route_file_for_replacement(selected, replacement_percent, demand_source)
        command = sumo_command_with_route_file(command, replacement_route_path)
        command = sumo_command_with_additional(command, selected)

    stop_event = threading.Event()
    global _latest_live_stop_event
    if not use_cache:
        # Newest live connection wins the single simulator — but a cached
        # stream must never displace someone's live run (the frontend's
        # preemption fallback reconnects via cache, which used to boomerang
        # and kill the very run that displaced it).
        if _latest_live_stop_event is not None:
            _latest_live_stop_event.set()
        _latest_live_stop_event = stop_event
    message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    event_loop = asyncio.get_running_loop()
    connection_label = f"{selected['key']}-playback-{id(websocket)}"

    command_task: asyncio.Task[None] | None = None
    worker_task: asyncio.Task[None] | None = None

    async def send_playback_json(payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except (RuntimeError, WebSocketDisconnect):
            stop_event.set()
            return False

    if not await send_playback_json(
        {
            "type": "hello",
            "backend": "cached-sumo-public-replay" if use_cache else "sumo-traci-playback",
            "dispatchEngine": dispatch_engine,
            "scope": selected["key"],
            "window": {"startSec": selected["startSec"], "endSec": selected["endSec"]},
            "playbackRate": playback_rate,
            "demandSource": demand_source,
            "replacementPercent": replacement_percent,
            "detail": playback_detail,
            "cache": {
                "mode": playback_cache,
                "available": cache_available,
                "used": use_cache,
            },
            "dataFps": PLAYBACK_DATA_FPS,
            "chunkVisualFrames": PLAYBACK_CHUNK_VISUAL_FRAMES,
            "chunkSimSeconds": frame_step_sec * visual_stride * PLAYBACK_CHUNK_VISUAL_FRAMES,
            "frameStepSec": frame_step_sec,
            "visualStride": visual_stride,
            "commands": ["stop"],
        }
    ):
        return

    if use_cache and cache_path is not None:
        await stream_cached_public_replay(websocket, cache_path)
        return

    async def receive_commands() -> None:
        try:
            while True:
                payload = await websocket.receive_json()
                command_name = str(payload.get("command") or payload.get("type") or "").lower()
                if command_name in {"stop", "close"}:
                    stop_event.set()
                    return
        except WebSocketDisconnect:
            stop_event.set()

    try:
        command_task = asyncio.create_task(receive_commands())
        producer = (
            produce_sumo_taxi_drt_playback_chunks
            if dispatch_engine == "taxi"
            else produce_sumo_playback_chunks
        )
        def run_live_producer() -> None:
            # Serialize on the single libsumo instance; if this connection was
            # preempted while waiting its turn, don't start the sim at all.
            with LIVE_RUN_LOCK:
                # Grace beat: connections abandoned within moments of opening
                # (dev StrictMode remounts, bounced tabs) die here instead of
                # paying a full, uninterruptible net load.
                stop_event.wait(0.4)
                if stop_event.is_set():
                    event_loop.call_soon_threadsafe(
                        message_queue.put_nowait, {"type": "stopped", "reason": "preempted"}
                    )
                    return
                producer(
                    traci,
                    command,
                    connection_label,
                    selected,
                    playback_rate,
                    replacement_percent,
                    demand_source,
                    playback_detail,
                    frame_step_sec,
                    visual_stride,
                    message_queue,
                    event_loop,
                    stop_event,
                )

        worker_task = asyncio.create_task(asyncio.to_thread(run_live_producer))

        while True:
            if command_task.done():
                command_error = command_task.exception()
                if command_error and not isinstance(command_error, WebSocketDisconnect):
                    raise command_error

            try:
                payload = await asyncio.wait_for(message_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # A crashed producer never posts done/error — surface it
                # instead of waiting on the queue forever.
                if worker_task.done() and message_queue.empty():
                    worker_error = worker_task.exception()
                    if worker_error:
                        raise worker_error
                    break
                continue
            send_started_at = time.perf_counter()
            if not await send_playback_json(payload):
                break
            if payload.get("type") == "chunk":
                if not await send_playback_json(
                    {
                        "type": "transportProfile",
                        "chunkIndex": payload.get("chunkIndex"),
                        "sendMs": round((time.perf_counter() - send_started_at) * 1000, 2),
                    }
                ):
                    break
            if payload.get("type") in {"done", "error", "stopped"}:
                break
    except WebSocketDisconnect:
        stop_event.set()
    except Exception as error:
        stop_event.set()
        await send_playback_json({"type": "error", "message": str(error)})
    finally:
        stop_event.set()
        if command_task and not command_task.done():
            command_task.cancel()
            try:
                await command_task
            except asyncio.CancelledError:
                pass
        if worker_task:
            try:
                await worker_task
            except Exception:
                pass


@app.websocket("/ws/sumo/{scope}")
async def sumo_scope(websocket: WebSocket, scope: str) -> None:
    await websocket.accept()

    try:
        selected = get_sumo_scenario(scope)
    except HTTPException as error:
        await websocket.send_json({"type": "error", "message": error.detail})
        await websocket.close()
        return

    sumo_binary = find_sumo_binary()
    if not sumo_binary or not selected["config"].exists():
        await websocket.send_json(
            {
                "type": "error",
                "message": f"SUMO binary or {selected['label']} config is unavailable.",
                "sumoAvailable": bool(sumo_binary),
                "configExists": selected["config"].exists(),
            }
        )
        await websocket.close()
        return

    command = [
        sumo_binary,
        "-c",
        str(selected["config"]),
        "--begin",
        str(selected["startSec"]),
        "--end",
        str(selected["endSec"]),
        "--step-length",
        "1",
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
        "--no-warnings",
        "true",
        "--log",
        "",
        "--summary-output",
        "",
        "--statistic-output",
        "",
        "--output-prefix",
        "",
        "--quit-on-end",
        "true",
    ]

    command = sumo_command_with_additional(command, selected)

    command_task: asyncio.Task[None] | None = None
    run_task: asyncio.Task[None] | None = None
    command_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    delay_ms = parse_delay_ms(websocket)
    is_running = False
    last_step = 0
    sim_process: asyncio.subprocess.Process | None = None
    run_started_at: float | None = None
    stop_requested = False

    try:
        (selected["dir"] / "output").mkdir(exist_ok=True)
        sumo_home = find_sumo_home()
        if sumo_home:
            os.environ["SUMO_HOME"] = str(sumo_home)

        await websocket.send_json(
            {
                "type": "hello",
                "backend": "sumo-subprocess",
                "scope": selected["key"],
                "window": {"startSec": selected["startSec"], "endSec": selected["endSec"]},
                "delayMs": delay_ms,
                "commands": ["start", "stop", "step", "reset", "delay"],
            }
        )

        async def receive_commands() -> None:
            while True:
                payload = await websocket.receive_json()
                await command_queue.put(payload)

        command_task = asyncio.create_task(receive_commands())

        async def send_sim_status(
            status: str,
            elapsed_sec: float | None = None,
            error: str | None = None,
        ) -> None:
            payload: dict[str, Any] = {
                "type": "simStatus",
                "status": status,
                "statusText": error or format_sim_status(status, elapsed_sec),
                "simSec": int(selected["startSec"]) + last_step,
                "step": last_step,
                "totalSteps": int(selected["endSec"] - selected["startSec"]),
                "delayMs": delay_ms,
                "running": is_running,
            }
            if elapsed_sec is not None:
                payload["elapsedSec"] = round(elapsed_sec, 3)
            await websocket.send_json(payload)

        async def run_plain_sumo() -> None:
            nonlocal is_running, last_step, run_started_at, sim_process, stop_requested
            is_running = True
            stop_requested = False
            last_step = 0
            run_started_at = time.perf_counter()
            await send_sim_status("running")

            sim_process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(selected["dir"]),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await sim_process.communicate()
            elapsed_sec = time.perf_counter() - run_started_at
            return_code = sim_process.returncode
            sim_process = None
            is_running = False

            if stop_requested:
                await send_sim_status("stopped", elapsed_sec)
                return

            if return_code == 0:
                last_step = int(selected["endSec"] - selected["startSec"])
                await send_sim_status("finished", elapsed_sec)
                await websocket.send_json({"type": "done", "simSec": selected["endSec"]})
                return

            output = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
            await send_sim_status(
                "failed",
                elapsed_sec,
                f"SUMO exited with code {return_code}: {output[-500:]}",
            )

        async def handle_command(payload: dict[str, Any]) -> None:
            nonlocal delay_ms, is_running, last_step, run_task, sim_process, stop_requested
            command_name = str(payload.get("command") or payload.get("type") or "").lower()
            if command_name == "start":
                if is_running:
                    await send_sim_status("running")
                    return
                run_task = asyncio.create_task(run_plain_sumo())
            elif command_name == "stop":
                stop_requested = True
                if sim_process and sim_process.returncode is None:
                    sim_process.terminate()
                is_running = False
                await send_sim_status("stopped")
            elif command_name == "step":
                await send_sim_status("step-unavailable")
            elif command_name == "reset":
                is_running = False
                last_step = 0
                stop_requested = True
                if sim_process and sim_process.returncode is None:
                    sim_process.terminate()
                await send_sim_status("idle")
            elif command_name == "delay":
                delay_ms = clamp_delay_ms(payload.get("delayMs"))
                await websocket.send_json({"type": "delay", "delayMs": delay_ms})
                await send_sim_status("running" if is_running else "idle")
            else:
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown SUMO command: {command_name}"}
                )

        await send_sim_status("idle")

        while True:
            handled_command = False
            while True:
                try:
                    payload = command_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                await handle_command(payload)
                handled_command = True

            if handled_command:
                continue

            if not is_running:
                await handle_command(await command_queue.get())
                continue

            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        return
    except Exception as error:
        await websocket.send_json({"type": "error", "message": str(error)})
    finally:
        if command_task and not command_task.done():
            command_task.cancel()
            try:
                await command_task
            except asyncio.CancelledError:
                pass
        if run_task and not run_task.done():
            run_task.cancel()
        if sim_process and sim_process.returncode is None:
            sim_process.terminate()


def seed_robotaxi_depot_fleet(connection: Any, selected: dict[str, Any]) -> dict[str, Any]:
    fleet_status: dict[str, Any] = {
        "requested": ROBOTAXI_FLEET_SIZE,
        "added": 0,
        "parkStopIssued": 0,
        "chargerCount": ROBOTAXI_DEPOT_CHARGER_COUNT,
        "chargingPowerKw": round(ROBOTAXI_DEPOT_CHARGING_POWER_W / 1000),
        "batteryCapacityKwh": round(ROBOTAXI_BATTERY_CAPACITY_WH / 1000),
        "initialChargeKwh": round(ROBOTAXI_INITIAL_CHARGE_WH / 1000),
        "errors": [],
    }
    try:
        connection.route.add(ROBOTAXI_ROUTE_ID, ROBOTAXI_DEPOT_ROUTE_EDGES)
    except Exception as error:
        fleet_status["errors"].append(f"route:{error}")

    try:
        connection.vehicletype.copy("DefaultVehicle", ROBOTAXI_TYPE_ID)
        connection.vehicletype.setVehicleClass(ROBOTAXI_TYPE_ID, "taxi")
        connection.vehicletype.setColor(ROBOTAXI_TYPE_ID, (255, 193, 7, 255))
        connection.vehicletype.setLength(ROBOTAXI_TYPE_ID, 4.2)
        connection.vehicletype.setWidth(ROBOTAXI_TYPE_ID, 1.85)
        connection.vehicletype.setShapeClass(ROBOTAXI_TYPE_ID, "passenger/sedan")
        connection.vehicletype.setEmissionClass(ROBOTAXI_TYPE_ID, "Energy/unknown")
        connection.vehicletype.setParameter(ROBOTAXI_TYPE_ID, "has.battery.device", "true")
        connection.vehicletype.setParameter(
            ROBOTAXI_TYPE_ID,
            "device.battery.capacity",
            str(ROBOTAXI_BATTERY_CAPACITY_WH),
        )
        connection.vehicletype.setParameter(
            ROBOTAXI_TYPE_ID,
            "device.battery.maximumBatteryCapacity",
            str(ROBOTAXI_BATTERY_CAPACITY_WH),
        )
        connection.vehicletype.setParameter(
            ROBOTAXI_TYPE_ID,
            "device.battery.actualBatteryCapacity",
            str(ROBOTAXI_INITIAL_CHARGE_WH),
        )
    except Exception as error:
        fleet_status["errors"].append(f"type:{error}")

    for index in range(ROBOTAXI_FLEET_SIZE):
        vehicle_id = f"{ROBOTAXI_ID_PREFIX}{index + 1:02d}"
        try:
            connection.vehicle.add(
                vehicle_id,
                ROBOTAXI_ROUTE_ID,
                typeID=ROBOTAXI_TYPE_ID,
                depart="now",
                departLane="best",
                departPos=str(82 + (index % 6) * 6),
                departSpeed="0",
            )
            connection.vehicle.setParameter(vehicle_id, "has.battery.device", "true")
            connection.vehicle.setParameter(
                vehicle_id,
                "device.battery.capacity",
                str(ROBOTAXI_BATTERY_CAPACITY_WH),
            )
            connection.vehicle.setParameter(
                vehicle_id,
                "device.battery.maximumBatteryCapacity",
                str(ROBOTAXI_BATTERY_CAPACITY_WH),
            )
            connection.vehicle.setParameter(
                vehicle_id,
                "device.battery.actualBatteryCapacity",
                str(ROBOTAXI_INITIAL_CHARGE_WH),
            )
            fleet_status["added"] += 1
            connection.vehicle.setParkingAreaStop(
                vehicle_id,
                ROBOTAXI_DEPOT_PARKING_ID,
                until=float(selected["endSec"]),
            )
            fleet_status["parkStopIssued"] += 1
        except Exception as error:
            fleet_status["errors"].append(f"{vehicle_id}:{error}")
            continue

    return fleet_status


def create_robotaxi_dispatch_state(
    fleet_status: dict[str, Any],
    selected: dict[str, Any],
    replacement_percent: int,
    demand_source: str,
) -> dict[str, Any]:
    if demand_source == "matsim":
        demand = load_matsim_person_demand_requests(
            str(MATSIM_DEFAULT_DEMAND_FILE),
            str(selected["net"]),
            int(selected["startSec"]),
            int(selected["endSec"]),
            MATSIM_MAX_STOP_DISTANCE_M,
        )
    else:
        demand = load_reachable_trip_replacement_requests(
            str(selected["route"]),
            str(selected["net"]),
            int(selected["startSec"]),
            int(selected["endSec"]),
            replacement_percent,
        )

    source_requests = demand["requests"]
    requests = []
    for request in source_requests:
        request_status = request.get("status", "scheduled")
        requests.append(
            {
                **request,
                "status": request_status,
                "assignedVehicleId": request.get("assignedVehicleId"),
                "pickupAtSec": request.get("pickupAtSec"),
                "completedAtSec": request.get("completedAtSec"),
                "error": request.get("error"),
            }
        )

    dispatchable_requests = [
        request
        for request in requests
        if request.get("status") == "scheduled"
        and request.get("pickupEdge")
        and request.get("dropoffEdge")
        and cybercab_can_serve_party(request.get("partySize"))
    ]
    rejected_request_count = int(demand.get("rejectedRequestCount", 0))
    reachable_request_count = int(
        demand.get(
            "reachableRequestCount",
            sum(1 for request in requests if request.get("status") == "scheduled"),
        )
    )

    return {
        "selectedStartSec": selected["startSec"],
        "selectedEndSec": selected["endSec"],
        "fleetInit": fleet_status,
        "replacement": {
            "source": demand_source,
            "percent": replacement_percent,
            "sourceTripCount": demand["sourceTripCount"],
            "eligibleTripCount": demand["eligibleTripCount"],
            "sampledRequestCount": demand.get("sampledRequestCount", len(requests)),
            "mappedRequestCount": demand.get("mappedRequestCount"),
            "reachableRequestCount": reachable_request_count,
            "validatedRequestCount": 0,
            "dispatchableRequestCount": len(dispatchable_requests),
            "unreachableRequestCount": demand.get("unreachableRequestCount", 0),
            "rejectedRequestCount": rejected_request_count,
            "rejectionCounts": demand.get("rejectionCounts", {}),
            "targetRequestCount": reachable_request_count,
            "reachabilityFiltered": demand.get("reachabilityFiltered", False),
            "usingFallbackDemand": False,
            "error": demand.get("error"),
            "demandFile": demand.get("sourceFile"),
            "sampleExpansionFactor": MATSIM_SAMPLE_EXPANSION_FACTOR
            if demand_source == "matsim"
            else None,
            "referenceConstraints": {
                "maxWaitSec": MATSIM_REFERENCE_MAX_WAIT_SEC,
                "maxTravelTimeFormula": (
                    f"{MATSIM_REFERENCE_MAX_TRAVEL_TIME_ALPHA} * direct_time + "
                    f"{MATSIM_REFERENCE_MAX_TRAVEL_TIME_BETA_SEC}"
                ),
            }
            if demand_source == "matsim"
            else None,
            "removedVehicles": sum(
                1 for request in requests if cybercab_can_serve_party(request.get("partySize"))
            )
            if demand_source == "sumo"
            else 0,
        },
        "replacedVehicleIds": set(),
        "removedVehicleIds": set(),
        "robotaxis": {
            f"{ROBOTAXI_ID_PREFIX}{index + 1:02d}": {
                "id": f"{ROBOTAXI_ID_PREFIX}{index + 1:02d}",
                "status": "staged",
                "requestId": None,
                "targetEdge": None,
                "phaseSinceSec": selected["startSec"],
                "lastEnergyUpdateSec": selected["startSec"],
                "batteryWh": float(ROBOTAXI_INITIAL_CHARGE_WH),
                "chargingSessionActive": False,
                "chargingSessions": 0,
                "locationEdge": scenario_staging_edge_id(selected, index),
                "error": None,
            }
            for index in range(ROBOTAXI_FLEET_SIZE)
        },
        "requests": requests,
        "routeCache": {},
        "metrics": {
            "servedRequests": 0,
            "servedPassengers": 0,
            "unservedCapacityRequests": 0,
            "unservedCapacityPassengers": 0,
            "passengerKm": 0.0,
            "vehicleKm": 0.0,
            "emptyKm": 0.0,
            "energyKwh": 0.0,
            "chargingSessions": 0,
        },
        "events": [],
    }


def safe_lane_stop_pos(connection: Any, edge_id: str, requested_pos: float) -> float:
    try:
        lane_length = float(connection.lane.getLength(f"{edge_id}_0"))
    except Exception:
        return max(1.0, requested_pos)
    return max(1.0, min(requested_pos, max(1.0, lane_length - 2.0)))


def current_vehicle_edge(connection: Any, vehicle_id: str) -> str:
    try:
        edge_id = str(connection.vehicle.getRoadID(vehicle_id))
    except Exception:
        return ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    if not edge_id or edge_id.startswith(":"):
        return ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    return edge_id


def cached_route_edges(
    connection: Any,
    dispatch_state: dict[str, Any],
    from_edge: str,
    to_edge: str,
) -> list[str]:
    return cached_route_plan(connection, dispatch_state, from_edge, to_edge)["edges"]


def cached_route_plan(
    connection: Any,
    dispatch_state: dict[str, Any],
    from_edge: str,
    to_edge: str,
) -> dict[str, Any]:
    if not from_edge or from_edge.startswith(":"):
        from_edge = ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    cache_key = f"{from_edge}|{to_edge}"
    route_cache: dict[str, dict[str, Any]] = dispatch_state["routeCache"]
    if cache_key not in route_cache:
        route = connection.simulation.findRoute(from_edge, to_edge)
        edges = [str(edge) for edge in route.edges]
        if not edges:
            raise RuntimeError(f"No route from {from_edge} to {to_edge}")
        distance_m = float(getattr(route, "length", 0.0) or 0.0)
        travel_time_sec = float(getattr(route, "travelTime", 0.0) or 0.0)
        if travel_time_sec <= 0 and distance_m > 0:
            travel_time_sec = distance_m / 8.33
        route_cache[cache_key] = {
            "edges": edges,
            "distanceM": max(0.0, distance_m),
            "travelTimeSec": max(0.0, travel_time_sec),
        }
    return route_cache[cache_key]


def cached_route_distance_m(
    connection: Any,
    dispatch_state: dict[str, Any],
    from_edge: str,
    to_edge: str,
) -> float:
    return float(cached_route_plan(connection, dispatch_state, from_edge, to_edge)["distanceM"])


def cached_route_travel_time_sec(
    connection: Any,
    dispatch_state: dict[str, Any],
    from_edge: str,
    to_edge: str,
) -> float:
    return float(cached_route_plan(connection, dispatch_state, from_edge, to_edge)["travelTimeSec"])


def best_depot_route_plan(
    connection: Any,
    dispatch_state: dict[str, Any],
    from_edge: str,
) -> tuple[str, dict[str, Any]]:
    best_target = ""
    best_plan: dict[str, Any] | None = None
    for depot_edge in ROBOTAXI_DEPOT_ROUTE_EDGES:
        try:
            plan = cached_route_plan(connection, dispatch_state, from_edge, depot_edge)
        except Exception:
            continue
        if best_plan is None or float(plan["travelTimeSec"]) < float(best_plan["travelTimeSec"]):
            best_target = depot_edge
            best_plan = plan
    if best_plan is None:
        raise RuntimeError(f"No route from {from_edge} to any depot edge")
    return best_target, best_plan


def deadline_route_travel_time_sec(
    connection: Any,
    dispatch_state: dict[str, Any],
    from_edge: str,
    to_edge: str,
) -> float:
    return (
        cached_route_travel_time_sec(connection, dispatch_state, from_edge, to_edge)
        * ROBOTAXI_DEADLINE_ROUTE_TIME_FACTOR
    )


def deadline_depot_travel_time_sec(
    connection: Any,
    dispatch_state: dict[str, Any],
    from_edge: str,
) -> float:
    _, plan = best_depot_route_plan(connection, dispatch_state, from_edge)
    return float(plan["travelTimeSec"]) * ROBOTAXI_DEADLINE_ROUTE_TIME_FACTOR


def validate_robotaxi_dispatch_requests(
    connection: Any,
    dispatch_state: dict[str, Any],
    selected: dict[str, Any],
) -> None:
    valid_source_vehicle_ids = set()
    validated_request_count = 0
    unreachable_count = 0
    for request in dispatch_state["requests"]:
        if request.get("status") != "scheduled":
            continue
        if not request.get("pickupEdge") or not request.get("dropoffEdge"):
            continue
        try:
            depot_to_pickup_sec = deadline_route_travel_time_sec(
                connection,
                dispatch_state,
                ROBOTAXI_DEPOT_ROUTE_EDGES[0],
                request["pickupEdge"],
            )
            pickup_to_dropoff_sec = deadline_route_travel_time_sec(
                connection,
                dispatch_state,
                request["pickupEdge"],
                request["dropoffEdge"],
            )
            dropoff_to_depot_sec = deadline_depot_travel_time_sec(
                connection,
                dispatch_state,
                request["dropoffEdge"],
            )
            required_sec = (
                depot_to_pickup_sec
                + pickup_to_dropoff_sec
                + dropoff_to_depot_sec
                + 2 * ROBOTAXI_SERVICE_HOLD_SEC
                + ROBOTAXI_FINAL_DEPOT_MARGIN_SEC
            )
            request["latestAssignableSec"] = float(selected["endSec"]) - required_sec
            validated_request_count += 1
            if (
                request.get("sourceVehicleId") is not None
                and cybercab_can_serve_party(request.get("partySize"))
            ):
                valid_source_vehicle_ids.add(str(request["sourceVehicleId"]))
        except Exception as error:
            request["status"] = "unreachable"
            request["error"] = str(error)
            unreachable_count += 1

    dispatch_state["replacedVehicleIds"] = valid_source_vehicle_ids
    replacement = dispatch_state["replacement"]
    demand_source = replacement.get("source", "sumo")
    prefiltered_unreachable_count = int(replacement.get("unreachableRequestCount", 0))
    replacement["validatedRequestCount"] = validated_request_count
    replacement["dispatchableRequestCount"] = sum(
        1
        for request in dispatch_state["requests"]
        if request.get("status") == "scheduled"
        and cybercab_can_serve_party(request.get("partySize"))
    )
    replacement["unreachableRequestCount"] = prefiltered_unreachable_count + unreachable_count
    replacement["targetRequestCount"] = validated_request_count
    replacement["removedVehicles"] = len(valid_source_vehicle_ids) if demand_source == "sumo" else 0


def issue_robotaxi_target(
    connection: Any,
    dispatch_state: dict[str, Any],
    vehicle_id: str,
    target_edge: str,
    stop_pos: float | None = None,
    stop_duration: float = 2.0,
    resume_first: bool = False,
) -> float:
    from_edge = current_vehicle_edge(connection, vehicle_id)
    route_plan = cached_route_plan(connection, dispatch_state, from_edge, target_edge)
    route_edges = route_plan["edges"]
    if resume_first:
        try:
            connection.vehicle.resume(vehicle_id)
        except Exception:
            pass
    connection.vehicle.setRoute(vehicle_id, route_edges)
    if stop_pos is not None:
        try:
            connection.vehicle.setStop(
                vehicle_id,
                target_edge,
                pos=safe_lane_stop_pos(connection, target_edge, stop_pos),
                laneIndex=0,
                duration=stop_duration,
            )
        except Exception:
            pass
    return float(route_plan.get("distanceM", 0.0))


def robotaxi_has_reached_edge(connection: Any, vehicle_id: str, edge_id: str) -> bool:
    try:
        return connection.vehicle.getRoadID(vehicle_id) == edge_id
    except Exception:
        return False


def robotaxi_has_reached_depot(connection: Any, vehicle_id: str) -> bool:
    try:
        return connection.vehicle.getRoadID(vehicle_id) in set(ROBOTAXI_DEPOT_ROUTE_EDGES)
    except Exception:
        return False


def robotaxi_request_by_id(
    dispatch_state: dict[str, Any],
    request_id: str | None,
) -> dict[str, Any] | None:
    if not request_id:
        return None
    for request in dispatch_state["requests"]:
        if request["id"] == request_id:
            return request
    return None


def robotaxi_ready_charge_wh() -> float:
    return ROBOTAXI_BATTERY_CAPACITY_WH * ROBOTAXI_CHARGE_READY_FRACTION


def update_robotaxi_charging(dispatch_state: dict[str, Any], sim_sec: float) -> None:
    for robotaxi in dispatch_state["robotaxis"].values():
        last_update_sec = float(robotaxi.get("lastEnergyUpdateSec", sim_sec))
        elapsed_sec = max(0.0, sim_sec - last_update_sec)
        robotaxi["lastEnergyUpdateSec"] = sim_sec

        if robotaxi["status"] != "charging" or elapsed_sec <= 0:
            continue

        charged_wh = (ROBOTAXI_DEPOT_CHARGING_POWER_W * elapsed_sec) / 3600.0
        robotaxi["batteryWh"] = min(
            float(ROBOTAXI_BATTERY_CAPACITY_WH),
            float(robotaxi.get("batteryWh", ROBOTAXI_INITIAL_CHARGE_WH)) + charged_wh,
        )


def set_robotaxi_status(robotaxi: dict[str, Any], status: str, sim_sec: float) -> None:
    if robotaxi.get("status") != status:
        robotaxi["status"] = status
        robotaxi["phaseSinceSec"] = sim_sec


def debit_robotaxi_route(
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
    distance_m: float,
    *,
    occupied: bool,
    passengers: int = 0,
) -> None:
    distance_m = max(0.0, float(distance_m))
    energy_wh = distance_m * ROBOTAXI_CONSUMPTION_WH_PER_M
    robotaxi["batteryWh"] = max(0.0, float(robotaxi.get("batteryWh", 0.0)) - energy_wh)

    metrics = dispatch_state["metrics"]
    metrics["vehicleKm"] += distance_m / 1000.0
    metrics["energyKwh"] += energy_wh / 1000.0
    if occupied:
        metrics["passengerKm"] += (distance_m / 1000.0) * max(0, int(passengers))
    else:
        metrics["emptyKm"] += distance_m / 1000.0


def request_trip_distance_m(
    connection: Any,
    dispatch_state: dict[str, Any],
    request: dict[str, Any],
) -> float:
    if request.get("tripDistanceM") is None:
        request["tripDistanceM"] = cached_route_distance_m(
            connection,
            dispatch_state,
            request["pickupEdge"],
            request["dropoffEdge"],
        )
    return float(request["tripDistanceM"])


def robotaxi_has_service_charge_for(
    connection: Any,
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
    request: dict[str, Any],
) -> bool:
    from_edge = current_vehicle_edge(connection, robotaxi["id"])
    empty_m = cached_route_distance_m(
        connection,
        dispatch_state,
        from_edge,
        request["pickupEdge"],
    )
    service_m = request_trip_distance_m(connection, dispatch_state, request)
    required_wh = (empty_m + service_m) * ROBOTAXI_CONSUMPTION_WH_PER_M
    return float(robotaxi.get("batteryWh", 0.0)) - required_wh >= ROBOTAXI_MIN_RESERVE_WH


def robotaxi_can_complete_request_before_close(
    connection: Any,
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
    request: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> bool:
    from_edge = current_vehicle_edge(connection, robotaxi["id"])
    empty_to_pickup_sec = deadline_route_travel_time_sec(
        connection,
        dispatch_state,
        from_edge,
        request["pickupEdge"],
    )
    pickup_to_dropoff_sec = deadline_route_travel_time_sec(
        connection,
        dispatch_state,
        request["pickupEdge"],
        request["dropoffEdge"],
    )
    dropoff_to_depot_sec = deadline_depot_travel_time_sec(
        connection,
        dispatch_state,
        request["dropoffEdge"],
    )
    required_sec = (
        empty_to_pickup_sec
        + pickup_to_dropoff_sec
        + dropoff_to_depot_sec
        + 2 * ROBOTAXI_SERVICE_HOLD_SEC
        + ROBOTAXI_FINAL_DEPOT_MARGIN_SEC
    )
    return sim_sec + required_sec <= float(selected["endSec"])


def start_robotaxi_charging(
    connection: Any,
    robotaxi: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> None:
    mark_robotaxi_charging_state(robotaxi, sim_sec)
    try:
        if connection.vehicle.getRoadID(robotaxi["id"]) == ROBOTAXI_DEPOT_ROUTE_EDGES[0]:
            connection.vehicle.setParkingAreaStop(
                robotaxi["id"],
                ROBOTAXI_DEPOT_PARKING_ID,
                until=float(selected["endSec"]),
            )
    except Exception:
        pass


def mark_robotaxi_charging_state(robotaxi: dict[str, Any], sim_sec: float) -> None:
    set_robotaxi_status(robotaxi, "charging", sim_sec)
    robotaxi["targetEdge"] = ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    robotaxi["locationEdge"] = ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    if not robotaxi.get("chargingSessionActive"):
        robotaxi["chargingSessionActive"] = True
        robotaxi["chargingSessions"] = int(robotaxi.get("chargingSessions", 0)) + 1


def mark_robotaxi_depot_state(robotaxi: dict[str, Any], sim_sec: float) -> None:
    robotaxi["requestId"] = None
    robotaxi["targetEdge"] = ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    robotaxi["locationEdge"] = ROBOTAXI_DEPOT_ROUTE_EDGES[0]
    if float(robotaxi.get("batteryWh", 0.0)) < robotaxi_ready_charge_wh():
        mark_robotaxi_charging_state(robotaxi, sim_sec)
        return
    set_robotaxi_status(robotaxi, "idle_at_depot", sim_sec)
    robotaxi["chargingSessionActive"] = False


def return_robotaxi_to_depot(
    connection: Any,
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> None:
    from_edge = current_vehicle_edge(connection, robotaxi["id"])
    if from_edge in set(ROBOTAXI_DEPOT_ROUTE_EDGES):
        mark_robotaxi_depot_state(robotaxi, sim_sec)
        return

    depot_edge, route_plan = best_depot_route_plan(connection, dispatch_state, from_edge)
    distance_m = float(route_plan.get("distanceM", 0.0))

    try:
        try:
            connection.vehicle.resume(robotaxi["id"])
        except Exception:
            pass
        connection.vehicle.setRoute(robotaxi["id"], route_plan["edges"])
    except Exception:
        try:
            connection.vehicle.changeTarget(robotaxi["id"], depot_edge)
        except Exception as error:
            raise RuntimeError(
                f"Depot return failed from {from_edge} to {depot_edge}: {error}"
            ) from error

    debit_robotaxi_route(dispatch_state, robotaxi, distance_m, occupied=False)
    robotaxi["status"] = "returning_to_depot"
    robotaxi["targetEdge"] = depot_edge
    robotaxi["phaseSinceSec"] = sim_sec
    if depot_edge == ROBOTAXI_DEPOT_ROUTE_EDGES[0]:
        try:
            connection.vehicle.setParkingAreaStop(
                robotaxi["id"],
                ROBOTAXI_DEPOT_PARKING_ID,
                until=float(selected["endSec"]),
            )
        except Exception:
            pass


def hold_robotaxi_locally(
    connection: Any,
    robotaxi: dict[str, Any],
    edge_id: str,
    stop_pos: float,
    sim_sec: float,
    selected: dict[str, Any],
) -> None:
    robotaxi["status"] = "staged"
    robotaxi["requestId"] = None
    robotaxi["targetEdge"] = edge_id
    robotaxi["locationEdge"] = edge_id
    robotaxi["phaseSinceSec"] = sim_sec


def assign_robotaxi_request(
    connection: Any,
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
    request: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> bool:
    if not cybercab_can_serve_party(request.get("partySize")):
        return False
    if not robotaxi_has_service_charge_for(connection, dispatch_state, robotaxi, request):
        return False
    if not robotaxi_can_complete_request_before_close(
        connection,
        dispatch_state,
        robotaxi,
        request,
        sim_sec,
        selected,
    ):
        return False

    vehicle_id = robotaxi["id"]
    distance_m = issue_robotaxi_target(
        connection,
        dispatch_state,
        vehicle_id,
        request["pickupEdge"],
        request["pickupPos"],
        stop_duration=ROBOTAXI_SERVICE_HOLD_SEC,
        resume_first=True,
    )
    debit_robotaxi_route(dispatch_state, robotaxi, distance_m, occupied=False)
    request["status"] = "assigned"
    request["assignedVehicleId"] = vehicle_id
    request["assignedAtSec"] = sim_sec
    robotaxi["status"] = "en_route_pickup"
    robotaxi["requestId"] = request["id"]
    robotaxi["targetEdge"] = request["pickupEdge"]
    robotaxi["phaseSinceSec"] = sim_sec
    robotaxi["chargingSessionActive"] = False
    return True


def mark_due_capacity_misses(dispatch_state: dict[str, Any], sim_sec: float) -> None:
    metrics = dispatch_state["metrics"]
    for request in dispatch_state["requests"]:
        if request["status"] != "scheduled" or sim_sec < request["requestedAtSec"]:
            continue
        if cybercab_can_serve_party(request.get("partySize")):
            request["status"] = "waiting"
            continue

        party_size = int(request.get("partySize") or 1)
        request["status"] = "capacity_miss"
        request["capacityMissAtSec"] = sim_sec
        request["error"] = (
            f"party_size {party_size} exceeds Cybercab {ROBOTAXI_CYBERCAB_SEATS}-seat capacity"
        )
        metrics["unservedCapacityRequests"] += 1
        metrics["unservedCapacityPassengers"] += party_size


def close_expired_service_requests(dispatch_state: dict[str, Any], sim_sec: float) -> None:
    for request in dispatch_state["requests"]:
        if request["status"] not in {"scheduled", "waiting"}:
            continue
        latest_assignable_sec = request.get("latestAssignableSec")
        if latest_assignable_sec is not None and sim_sec > float(latest_assignable_sec):
            close_robotaxi_request_for_service_end(request, sim_sec)


def has_waiting_robotaxi_demand(dispatch_state: dict[str, Any]) -> bool:
    return any(
        request["status"] == "waiting" and not request.get("assignedVehicleId")
        for request in dispatch_state["requests"]
    )


def robotaxi_return_eta_sec(
    connection: Any,
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
) -> float:
    from_edge = current_vehicle_edge(connection, robotaxi["id"])
    return deadline_depot_travel_time_sec(connection, dispatch_state, from_edge)


def robotaxi_should_return_to_depot(
    connection: Any,
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> bool:
    if float(robotaxi.get("batteryWh", 0.0)) <= ROBOTAXI_RETURN_RESERVE_WH:
        return True
    if robotaxi["status"] == "charging":
        return False
    return_eta_sec = robotaxi_return_eta_sec(connection, dispatch_state, robotaxi)
    return sim_sec + return_eta_sec + ROBOTAXI_FINAL_DEPOT_MARGIN_SEC >= float(selected["endSec"])


def close_robotaxi_request_for_service_end(request: dict[str, Any], sim_sec: float) -> None:
    if request["status"] not in {"scheduled", "waiting", "assigned"}:
        return
    request["status"] = "closed"
    request["closedAtSec"] = sim_sec
    request["rejectionReason"] = "service_window_ending"


def wind_down_robotaxi_service(
    connection: Any,
    dispatch_state: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> None:
    live_vehicle_ids = set(connection.vehicle.getIDList())
    for robotaxi in dispatch_state["robotaxis"].values():
        vehicle_id = robotaxi["id"]
        if vehicle_id not in live_vehicle_ids:
            if robotaxi["status"] == "returning_to_depot":
                mark_robotaxi_charging_state(robotaxi, sim_sec)
            continue

        request = robotaxi_request_by_id(dispatch_state, robotaxi.get("requestId"))
        if robotaxi["status"] == "en_route_pickup" and request:
            last_check_sec = float(robotaxi.get("lastDeadlineCheckSec", -ROBOTAXI_DEADLINE_RECHECK_SEC))
            if sim_sec - last_check_sec >= ROBOTAXI_DEADLINE_RECHECK_SEC:
                robotaxi["lastDeadlineCheckSec"] = sim_sec
                if not robotaxi_can_complete_request_before_close(
                    connection,
                    dispatch_state,
                    robotaxi,
                    request,
                    sim_sec,
                    selected,
                ):
                    close_robotaxi_request_for_service_end(request, sim_sec)
                    robotaxi["requestId"] = None
                    try:
                        return_robotaxi_to_depot(connection, dispatch_state, robotaxi, sim_sec, selected)
                    except Exception as error:
                        robotaxi["status"] = "failed"
                        robotaxi["error"] = str(error)
        elif robotaxi["status"] in {"idle", "staged"} and robotaxi_should_return_to_depot(
            connection,
            dispatch_state,
            robotaxi,
            sim_sec,
            selected,
        ):
            try:
                return_robotaxi_to_depot(connection, dispatch_state, robotaxi, sim_sec, selected)
            except Exception as error:
                robotaxi["status"] = "failed"
                robotaxi["error"] = str(error)


def assign_waiting_requests(
    connection: Any,
    dispatch_state: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> None:
    live_vehicle_ids = set(connection.vehicle.getIDList())
    waiting_requests = [
        request
        for request in dispatch_state["requests"]
        if request["status"] == "waiting" and not request.get("assignedVehicleId")
    ]
    waiting_requests.sort(key=lambda request: (request["requestedAtSec"], request["id"]))

    for robotaxi in dispatch_state["robotaxis"].values():
        if robotaxi["id"] not in live_vehicle_ids:
            continue
        if robotaxi["status"] not in ROBOTAXI_ASSIGNABLE_STATES:
            continue
        charging_below_ready = (
            robotaxi["status"] == "charging"
            and float(robotaxi.get("batteryWh", 0.0)) < robotaxi_ready_charge_wh()
        )
        if robotaxi["status"] in {"idle", "staged"} and robotaxi_should_return_to_depot(
            connection,
            dispatch_state,
            robotaxi,
            sim_sec,
            selected,
        ):
            try:
                return_robotaxi_to_depot(connection, dispatch_state, robotaxi, sim_sec, selected)
            except Exception as error:
                robotaxi["status"] = "failed"
                robotaxi["error"] = str(error)
            continue
        if not waiting_requests and robotaxi["status"] in {"idle", "staged"}:
            try:
                return_robotaxi_to_depot(connection, dispatch_state, robotaxi, sim_sec, selected)
            except Exception as error:
                robotaxi["status"] = "failed"
                robotaxi["error"] = str(error)
            continue

        assigned_request = False
        if waiting_requests and not charging_below_ready:
            current_edge = current_vehicle_edge(connection, robotaxi["id"])
            feasible_requests: list[tuple[float, dict[str, Any]]] = []
            for request in waiting_requests:
                try:
                    if not cybercab_can_serve_party(request.get("partySize")):
                        continue
                    if not robotaxi_has_service_charge_for(connection, dispatch_state, robotaxi, request):
                        continue
                    if not robotaxi_can_complete_request_before_close(
                        connection,
                        dispatch_state,
                        robotaxi,
                        request,
                        sim_sec,
                        selected,
                    ):
                        continue
                    pickup_eta_sec = cached_route_travel_time_sec(
                        connection,
                        dispatch_state,
                        current_edge,
                        request["pickupEdge"],
                    )
                    wait_sec = max(0.0, sim_sec - float(request["requestedAtSec"]))
                    score = pickup_eta_sec - min(wait_sec, ROBOTAXI_DEMAND_LOOKAHEAD_SEC) * 0.25
                    feasible_requests.append((score, request))
                except Exception:
                    continue

            if feasible_requests:
                _, request = min(feasible_requests, key=lambda item: item[0])
                try:
                    if assign_robotaxi_request(connection, dispatch_state, robotaxi, request, sim_sec, selected):
                        waiting_requests.remove(request)
                        assigned_request = True
                except Exception as error:
                    robotaxi["status"] = "failed"
                    robotaxi["error"] = str(error)
                    request["status"] = "vehicle_failed"
                    request["assignedVehicleId"] = robotaxi["id"]
                    request["error"] = str(error)
                    waiting_requests.remove(request)
            elif robotaxi["status"] in {"idle", "staged"}:
                try:
                    return_robotaxi_to_depot(connection, dispatch_state, robotaxi, sim_sec, selected)
                except Exception as error:
                    robotaxi["status"] = "failed"
                    robotaxi["error"] = str(error)
                continue

        needs_charge_for_waiting_demand = (
            not assigned_request
            and bool(waiting_requests)
            and robotaxi["status"] in {"idle", "staged"}
            and float(robotaxi.get("batteryWh", 0.0)) < robotaxi_ready_charge_wh()
        )
        if robotaxi["status"] in ROBOTAXI_ASSIGNABLE_STATES and (
            needs_charge_for_waiting_demand
        ):
            try:
                return_robotaxi_to_depot(connection, dispatch_state, robotaxi, sim_sec, selected)
            except Exception as error:
                robotaxi["status"] = "failed"
                robotaxi["error"] = str(error)


def update_robotaxi_dispatch(
    connection: Any,
    dispatch_state: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> None:
    update_robotaxi_charging(dispatch_state, sim_sec)
    live_vehicle_ids = set(connection.vehicle.getIDList())
    wind_down_robotaxi_service(connection, dispatch_state, sim_sec, selected)
    mark_due_capacity_misses(dispatch_state, sim_sec)
    close_expired_service_requests(dispatch_state, sim_sec)

    for robotaxi in dispatch_state["robotaxis"].values():
        vehicle_id = robotaxi["id"]
        if vehicle_id not in live_vehicle_ids:
            continue

        request = robotaxi_request_by_id(dispatch_state, robotaxi.get("requestId"))
        try:
            if robotaxi["status"] == "en_route_pickup" and request:
                if robotaxi_has_reached_edge(connection, vehicle_id, request["pickupEdge"]):
                    request["status"] = "onboard"
                    request["pickupAtSec"] = sim_sec
                    robotaxi["status"] = "with_passenger"
                    robotaxi["phaseSinceSec"] = sim_sec
                    robotaxi["targetEdge"] = request["dropoffEdge"]
                    distance_m = issue_robotaxi_target(
                        connection,
                        dispatch_state,
                        vehicle_id,
                        request["dropoffEdge"],
                        request["dropoffPos"],
                        stop_duration=ROBOTAXI_SERVICE_HOLD_SEC,
                        resume_first=True,
                    )
                    request["tripDistanceM"] = distance_m
                    debit_robotaxi_route(
                        dispatch_state,
                        robotaxi,
                        distance_m,
                        occupied=True,
                        passengers=int(request.get("partySize") or 1),
                    )
            elif robotaxi["status"] == "with_passenger" and request:
                if robotaxi_has_reached_edge(connection, vehicle_id, request["dropoffEdge"]):
                    request["status"] = "completed"
                    request["completedAtSec"] = sim_sec
                    metrics = dispatch_state["metrics"]
                    metrics["servedRequests"] += 1
                    metrics["servedPassengers"] += int(request.get("partySize") or 1)
                    robotaxi["requestId"] = None
                    robotaxi["phaseSinceSec"] = sim_sec
                    if has_waiting_robotaxi_demand(dispatch_state):
                        robotaxi["status"] = "idle"
                        robotaxi["requestId"] = None
                        robotaxi["targetEdge"] = request["dropoffEdge"]
                        robotaxi["locationEdge"] = request["dropoffEdge"]
                    else:
                        return_robotaxi_to_depot(
                            connection,
                            dispatch_state,
                            robotaxi,
                            sim_sec,
                            selected,
                        )
            elif robotaxi["status"] == "returning_to_depot":
                if robotaxi_has_reached_depot(connection, vehicle_id):
                    start_robotaxi_charging(connection, robotaxi, sim_sec, selected)
        except Exception as error:
            robotaxi["status"] = "failed"
            robotaxi["error"] = str(error)
            if request and request["status"] not in {"completed", "unreachable"}:
                request["status"] = "vehicle_failed"
                request["error"] = str(error)

    assign_waiting_requests(connection, dispatch_state, sim_sec, selected)


def serialize_robotaxi_dispatch(
    dispatch_state: dict[str, Any] | None,
    sim_sec: float,
    *,
    include_requests: bool = True,
) -> dict[str, Any]:
    if not dispatch_state:
        return {
            "fleetInit": {
                "requested": 0,
                "added": 0,
                "parkStopIssued": 0,
                "chargerCount": ROBOTAXI_DEPOT_CHARGER_COUNT,
                "chargingPowerKw": round(ROBOTAXI_DEPOT_CHARGING_POWER_W / 1000),
                "batteryCapacityKwh": round(ROBOTAXI_BATTERY_CAPACITY_WH / 1000),
                "initialChargeKwh": round(ROBOTAXI_INITIAL_CHARGE_WH / 1000),
                "errors": [],
            },
            "replacement": {
                "source": DEFAULT_DEMAND_SOURCE,
                "percent": 0,
                "sourceTripCount": 0,
                "targetRequestCount": 0,
                "rejectedRequestCount": 0,
                "rejectionCounts": {},
                "removedVehicles": 0,
                "usingFallbackDemand": False,
                "error": None,
            },
            "demand": {
                "source": DEFAULT_DEMAND_SOURCE,
                "percent": 0,
                "sourceTripCount": 0,
                "targetRequestCount": 0,
                "rejectedRequestCount": 0,
                "rejectionCounts": {},
                "removedVehicles": 0,
                "usingFallbackDemand": False,
                "error": None,
            },
            "robotaxis": [],
            "requests": [],
            "metrics": {
                "targetRequests": 0,
                "sourceTripCount": 0,
                "demandSource": DEFAULT_DEMAND_SOURCE,
                "replacementPercent": 0,
                "removedVehicles": 0,
                "rejectedRequests": 0,
                "requestStatusCounts": {},
                "requestOutcomeCounts": {
                    "completed": 0,
                    "open": 0,
                    "notServed": 0,
                    "finalized": 0,
                },
                "rejectionReasonCounts": {},
                "notServedRequests": 0,
                "serviceWindowRejected": 0,
                "unreachableRejected": 0,
                "reservationCanceled": 0,
                "dispatchFailed": 0,
                "completionRatePercent": 0.0,
                "waiting": 0,
                "assigned": 0,
                "onboard": 0,
                "completed": 0,
                "failed": 0,
                "servedRequests": 0,
                "servedPassengers": 0,
                "unservedCapacityRequests": 0,
                "unservedCapacityPassengers": 0,
                "passengerKm": 0.0,
                "vehicleKm": 0.0,
                "emptyKm": 0.0,
                "deadheadKm": 0.0,
                "energyKwh": 0.0,
                "chargingSessions": 0,
                "fleetStateCounts": {},
                "passengersCompleted": 0,
                "cybercabCapacityMisses": 0,
                "cybercabServeableRequests": 0,
                "seatKmWaste": 0.0,
                "deadheadingPercent": 0.0,
                "energyWhPerPassengerKm": None,
                "chargeSessions": 0,
                "depotUtilizationPercent": 0.0,
                "avgWaitSec": None,
                "activeRobotaxis": 0,
                "chargingRobotaxis": 0,
                "readyRobotaxis": 0,
                "lowBatteryReturns": 0,
                "chargingUnavailable": 0,
                "stagingTrips": 0,
                "maxWaitSec": None,
                "p95WaitSec": None,
                "openRequests": 0,
                "fleetAtDepot": 0,
                "fleetReadyAtDepot": 0,
                "serviceWindowComplete": False,
                "auditStatus": "pending",
                "auditWarnings": [],
            },
        }

    requests = []
    wait_times = []
    status_counts = Counter(str(request.get("status", "unknown")) for request in dispatch_state["requests"])
    rejection_reason_counts = Counter(
        str(request.get("rejectionReason") or request.get("status") or "unknown")
        for request in dispatch_state["requests"]
        if request.get("status") in {"unreachable", "vehicle_failed", "capacity_miss", "rejected"}
    )
    for request in dispatch_state["requests"]:
        wait_sec = None
        if request.get("pickupAtSec") is not None:
            wait_sec = max(0.0, float(request["pickupAtSec"]) - float(request["requestedAtSec"]))
            wait_times.append(wait_sec)
        elif request["status"] in {"waiting", "assigned"}:
            wait_sec = max(0.0, sim_sec - float(request["requestedAtSec"]))

        if include_requests:
            requests.append(
                {
                    "id": request["id"],
                    "status": request["status"],
                    "requestedAtSec": request["requestedAtSec"],
                    "pickupAtSec": request.get("pickupAtSec"),
                    "completedAtSec": request.get("completedAtSec"),
                    "expiredAtSec": request.get("expiredAtSec"),
                    "closedAtSec": request.get("closedAtSec"),
                    "assignedVehicleId": request.get("assignedVehicleId"),
                    "pickup": request["pickup"],
                    "dropoff": request["dropoff"],
                    "sourceMode": request.get("sourceMode"),
                    "rejectionReason": request.get("rejectionReason"),
                    "waitSec": round(wait_sec, 1) if wait_sec is not None else None,
                    "error": request.get("error"),
                }
            )

    robotaxis = []
    for robotaxi in dispatch_state["robotaxis"].values():
        battery_wh = float(robotaxi.get("batteryWh", 0.0))
        robotaxis.append(
            {
                **robotaxi,
                "batteryKwh": round(battery_wh / 1000.0, 2),
                "batteryPercent": round((battery_wh / ROBOTAXI_BATTERY_CAPACITY_WH) * 100, 1),
            }
        )
    fleet_state_counts: dict[str, int] = {}
    for robotaxi in robotaxis:
        status = str(robotaxi.get("status", "unknown"))
        fleet_state_counts[status] = fleet_state_counts.get(status, 0) + 1
    active_robotaxis = sum(
        1
        for robotaxi in robotaxis
        if robotaxi["status"] in ROBOTAXI_ACTIVE_STATES
    )
    charging_robotaxis = sum(
        1
        for robotaxi in robotaxis
        if robotaxi["status"] == "charging" and not robotaxi.get("error")
    )
    ready_robotaxis = sum(
        1
        for robotaxi in robotaxis
        if taxi_robotaxi_ready_for_service(robotaxi) and not robotaxi.get("error")
    )
    available_robotaxis = sum(
        1
        for robotaxi in robotaxis
        if robotaxi.get("status") in {"idle", "staged"}
        and taxi_robotaxi_ready_for_service(robotaxi)
        and not robotaxi.get("error")
    )
    failed = sum(
        1
        for request in dispatch_state["requests"]
        if request["status"] in {"unreachable", "vehicle_failed", "capacity_miss", "rejected"}
    )
    finalized = status_counts["completed"] + failed + status_counts["expired"]
    target_total = len(dispatch_state["requests"])
    completion_rate_percent = (
        (status_counts["completed"] / target_total) * 100.0 if target_total > 0 else 0.0
    )
    replacement = dict(dispatch_state["replacement"])
    replacement["removedVehicles"] = max(
        int(replacement.get("removedVehicles", 0)),
        len(dispatch_state.get("removedVehicleIds", set())),
    )
    cumulative_metrics = dispatch_state["metrics"]
    completed_requests = [
        request for request in dispatch_state["requests"] if request["status"] == "completed"
    ]
    capacity_misses = sum(
        1 for request in dispatch_state["requests"] if request["status"] == "capacity_miss"
    )
    cybercab_serveable_requests = sum(
        1
        for request in dispatch_state["requests"]
        if request.get("status") not in {"rejected", "unreachable"}
        and cybercab_can_serve_party(request.get("partySize"))
    )
    seat_km_waste = sum(
        max(0, ROBOTAXI_CYBERCAB_SEATS - int(request.get("partySize") or 1))
        * (float(request.get("tripDistanceM", 0.0)) / 1000.0)
        for request in completed_requests
    )
    vehicle_km = float(cumulative_metrics["vehicleKm"])
    empty_km = float(cumulative_metrics["emptyKm"])
    passenger_km = float(cumulative_metrics["passengerKm"])
    energy_kwh = float(cumulative_metrics["energyKwh"])
    charging_sessions = sum(int(robotaxi.get("chargingSessions", 0)) for robotaxi in robotaxis)
    deadheading_percent = (empty_km / vehicle_km) * 100.0 if vehicle_km > 0 else 0.0
    energy_wh_per_passenger_km = (
        (energy_kwh * 1000.0) / passenger_km if passenger_km > 0 else None
    )
    depot_utilization_percent = (
        (charging_robotaxis / ROBOTAXI_DEPOT_CHARGER_COUNT) * 100.0
        if ROBOTAXI_DEPOT_CHARGER_COUNT > 0
        else 0.0
    )
    sorted_wait_times = sorted(wait_times)
    max_wait_sec = sorted_wait_times[-1] if sorted_wait_times else None
    p95_wait_sec = (
        sorted_wait_times[min(len(sorted_wait_times) - 1, math.ceil(len(sorted_wait_times) * 0.95) - 1)]
        if sorted_wait_times
        else None
    )
    open_requests = status_counts["scheduled"] + status_counts["waiting"]
    accepted_requests = status_counts["assigned"] + status_counts["onboard"]
    active_requests = open_requests + accepted_requests
    fleet_at_depot = sum(
        1
        for robotaxi in robotaxis
        if str(robotaxi.get("locationEdge")) in set(ROBOTAXI_DEPOT_ROUTE_EDGES)
    )
    fleet_ready_at_depot = sum(
        1
        for robotaxi in robotaxis
        if str(robotaxi.get("locationEdge")) in set(ROBOTAXI_DEPOT_ROUTE_EDGES)
        and taxi_robotaxi_ready_for_service(robotaxi)
        and not robotaxi.get("error")
    )
    service_window_complete = sim_sec >= float(dispatch_state.get("selectedEndSec", SUMO_END_SEC))
    audit_warnings = []
    if service_window_complete and open_requests > 0:
        audit_warnings.append("open_requests")
    if service_window_complete and fleet_at_depot < len(robotaxis):
        audit_warnings.append("fleet_not_fully_recovered")
    if failed > 0:
        audit_warnings.append("unserved_or_failed_requests")
    audit_status = "pass" if service_window_complete and not audit_warnings else "review"

    payload = {
        "fleetInit": dispatch_state["fleetInit"],
        "replacement": replacement,
        "demand": replacement,
        "robotaxis": robotaxis,
        "metrics": {
            "targetRequests": replacement["targetRequestCount"],
            "sourceTripCount": replacement["sourceTripCount"],
            "demandSource": replacement.get("source", "sumo"),
            "replacementPercent": replacement["percent"],
            "removedVehicles": replacement["removedVehicles"],
            "rejectedRequests": int(replacement.get("rejectedRequestCount", 0)),
            "rejectionCounts": replacement.get("rejectionCounts", {}),
            "requestStatusCounts": dict(status_counts),
            "requestOutcomeCounts": {
                "completed": status_counts["completed"],
                "open": open_requests,
                "accepted": accepted_requests,
                "notServed": failed,
                "expired": status_counts["expired"],
                "finalized": finalized,
            },
            "rejectionReasonCounts": dict(rejection_reason_counts),
            "notServedRequests": failed,
            "expiredRequests": status_counts["expired"],
            "serviceWindowRejected": rejection_reason_counts["service_window_ending"],
            "unreachableRejected": rejection_reason_counts["unreachable_for_taxi_dispatch"],
            "reservationCanceled": rejection_reason_counts["taxi_reservation_canceled_before_pickup"],
            "dispatchFailed": rejection_reason_counts["dispatch_taxi_failed"],
            "completionRatePercent": round(completion_rate_percent, 1),
            "waiting": sum(1 for request in dispatch_state["requests"] if request["status"] == "waiting"),
            "assigned": sum(1 for request in dispatch_state["requests"] if request["status"] == "assigned"),
            "onboard": sum(1 for request in dispatch_state["requests"] if request["status"] == "onboard"),
            "completed": sum(1 for request in dispatch_state["requests"] if request["status"] == "completed"),
            "failed": failed,
            "capacityMisses": capacity_misses,
            "cybercabCapacityMisses": capacity_misses,
            "servedRequests": int(cumulative_metrics["servedRequests"]),
            "servedPassengers": int(cumulative_metrics["servedPassengers"]),
            "passengersCompleted": int(cumulative_metrics["servedPassengers"]),
            "unservedCapacityRequests": int(cumulative_metrics["unservedCapacityRequests"]),
            "unservedCapacityPassengers": int(cumulative_metrics["unservedCapacityPassengers"]),
            "cybercabServeableRequests": cybercab_serveable_requests,
            "passengerKm": round(passenger_km, 3),
            "vehicleKm": round(vehicle_km, 3),
            "emptyKm": round(empty_km, 3),
            "deadheadKm": round(empty_km, 3),
            "deadheadingPercent": round(deadheading_percent, 1),
            "seatKmWaste": round(seat_km_waste, 3),
            "energyKwh": round(energy_kwh, 3),
            "energyWhPerPassengerKm": round(energy_wh_per_passenger_km, 1)
            if energy_wh_per_passenger_km is not None
            else None,
            "chargingSessions": charging_sessions,
            "chargeSessions": charging_sessions,
            "depotUtilizationPercent": round(depot_utilization_percent, 1),
            "fleetStateCounts": fleet_state_counts,
            "avgWaitSec": round(sum(wait_times) / len(wait_times), 1) if wait_times else None,
            "maxWaitSec": round(max_wait_sec, 1) if max_wait_sec is not None else None,
            "p95WaitSec": round(p95_wait_sec, 1) if p95_wait_sec is not None else None,
            "activeRobotaxis": active_robotaxis,
            "chargingRobotaxis": charging_robotaxis,
            "readyRobotaxis": ready_robotaxis,
            "availableRobotaxis": available_robotaxis,
            "availableCabs": available_robotaxis,
            "lowBatteryReturns": int(cumulative_metrics.get("lowBatteryReturns", 0)),
            "chargingUnavailable": int(cumulative_metrics.get("chargingUnavailable", 0)),
            "stagingTrips": int(cumulative_metrics.get("stagingTrips", 0)),
            "openRequests": open_requests,
            "acceptedRequests": accepted_requests,
            "activeRequests": active_requests,
            "fleetAtDepot": fleet_at_depot,
            "fleetReadyAtDepot": fleet_ready_at_depot,
            "serviceWindowComplete": service_window_complete,
            "auditStatus": audit_status,
            "auditWarnings": audit_warnings,
        },
    }
    if include_requests:
        payload["requests"] = requests
    return payload


def format_time_label(sim_sec: float | int | None) -> str | None:
    if sim_sec is None:
        return None
    total_minutes = int(float(sim_sec)) // 60
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def dispatch_phase(metrics: dict[str, Any], sim_sec: float) -> str:
    if bool(metrics.get("serviceWindowComplete")):
        open_requests = int(metrics.get("openRequests") or 0)
        if open_requests > 0:
            return "winding_down"
        fleet_at_depot = int(metrics.get("fleetAtDepot") or 0)
        fleet_size = sum(int(count) for count in metrics.get("fleetStateCounts", {}).values())
        if fleet_size and fleet_at_depot < fleet_size:
            return "returning_to_depot"
        return "complete"
    if sim_sec >= SUMO_END_SEC:
        return "winding_down"
    return "running"


def robotaxi_label(vehicle_id: str) -> str:
    suffix = vehicle_id.replace(ROBOTAXI_ID_PREFIX, "").replace("-", "_")
    return f"Cybercab {suffix}" if suffix else vehicle_id


def build_contract_cab_rows(
    dispatch_payload: dict[str, Any],
    vehicles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    vehicles_by_id = {str(vehicle.get("id")): vehicle for vehicle in vehicles}
    rows = []
    for robotaxi in dispatch_payload.get("robotaxis", []):
        vehicle_id = str(robotaxi.get("id") or "")
        vehicle = vehicles_by_id.get(vehicle_id, {})
        speed = vehicle.get("speed")
        status = robotaxi.get("status")
        if status == "charging":
            # v1 hides charging entirely; a charging cab is just at the depot.
            status = "idle_at_depot"
        battery_percent = robotaxi.get("batteryPercent")
        rows.append(
            {
                "id": vehicle_id,
                "state": status,
                "battery": round(float(battery_percent)) if battery_percent is not None else None,
                "label": robotaxi_label(vehicle_id),
                "speedKph": round(float(speed) * 3.6, 1)
                if isinstance(speed, (int, float))
                else None,
                "etaSec": robotaxi.get("etaSec"),
                "target": robotaxi.get("targetEdge") or robotaxi.get("locationEdge"),
                "stopReason": robotaxi.get("stopReason") or robotaxi.get("error"),
                "requestId": robotaxi.get("requestId"),
                "requestContext": f"Request {robotaxi['requestId']}"
                if robotaxi.get("requestId")
                else None,
                "lon": vehicle.get("lon"),
                "lat": vehicle.get("lat"),
                "heading": vehicle.get("angle"),
            }
        )
    return rows


def request_marker_state(status: str) -> str | None:
    # "scheduled" requests have not been announced yet; they get no marker.
    if status == "waiting":
        return "open"
    if status in {"assigned", "onboard"}:
        return "accepted"
    if status == "completed":
        return "completed"
    if status == "expired":
        return "expired"
    return None


def build_contract_map_requests(dispatch_payload: dict[str, Any]) -> list[dict[str, Any]]:
    markers = []
    for request in dispatch_payload.get("requests", []):
        status = str(request.get("status") or "")
        marker_state = request_marker_state(status)
        pickup = request.get("pickup") if isinstance(request.get("pickup"), dict) else {}
        if not marker_state or "lon" not in pickup or "lat" not in pickup:
            continue
        markers.append(
            {
                "id": request.get("id"),
                "state": status,
                "markerState": marker_state,
                "lon": pickup.get("lon"),
                "lat": pickup.get("lat"),
                "assignedCabId": request.get("assignedVehicleId"),
                "expiredAtSec": request.get("expiredAtSec"),
            }
        )
    return markers


def build_contract_frame_fields(
    dispatch_payload: dict[str, Any],
    vehicles: list[dict[str, Any]],
    sim_sec: float,
) -> dict[str, Any]:
    metrics = dispatch_payload.get("metrics", {})
    request_counts = metrics.get("requestStatusCounts") or {}
    cab_rows = build_contract_cab_rows(dispatch_payload, vehicles)
    map_requests = build_contract_map_requests(dispatch_payload)
    rides_served = int(metrics.get("completed") or metrics.get("ridesServed") or 0)
    service_window_complete = bool(metrics.get("serviceWindowComplete"))
    return {
        "phase": dispatch_phase(metrics, sim_sec),
        "timeSec": sim_sec,
        "timeLabel": format_time_label(sim_sec),
        "cabsActive": int(metrics.get("activeRobotaxis") or 0),
        "ridesServed": rides_served,
        "requestCounts": request_counts,
        "cabRows": cab_rows,
        "mapVehicles": [vehicle for vehicle in vehicles if vehicle.get("kind") == "robotaxi"],
        "mapRequests": map_requests,
        "totals": {
            "ridesServed": rides_served,
            "totalDemand": int(metrics.get("targetRequests") or 0),
            "expiredRequests": int(metrics.get("expiredRequests") or 0),
            "rejectedRequests": int(metrics.get("rejectedRequests") or 0),
            "cabsReturned": int(metrics.get("fleetAtDepot") or 0) if service_window_complete else 0,
        },
        "finalAudit": None,
    }


def create_taxi_drt_dispatch_state(
    selected: dict[str, Any],
    replacement_percent: int,
    demand_source: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    generated = build_taxi_drt_route_file(selected, replacement_percent, demand_source, run_id)
    demand = generated["demand"]
    requests = generated["requests"]
    by_person_id = {request["personId"]: request for request in requests}
    replacement = {
        "source": demand_source,
        "percent": replacement_percent,
        "sourceTripCount": demand.get("sourceTripCount", 0),
        "eligibleTripCount": demand.get("eligibleTripCount", 0),
        "targetRequestCount": len(requests),
        "rejectedRequestCount": int(demand.get("rejectedRequestCount", 0)),
        "rejectionCounts": demand.get("rejectionCounts", {}),
        "removedVehicles": 0,
        "usingFallbackDemand": False,
        "error": demand.get("error"),
        "engine": "sumo-taxi-device",
    }
    return {
        "engine": "taxi",
        "selectedStartSec": selected["startSec"],
        "selectedEndSec": selected["endSec"],
        "runtimeEndSec": selected.get("runtimeEndSec", selected["endSec"]),
        "routePath": generated["routePath"],
        "runId": run_id or "",
        "fleetInit": {
            "requested": scenario_fleet_size(selected),
            "added": scenario_fleet_size(selected),
            "parkStopIssued": 0,
            "chargerCount": ROBOTAXI_DEPOT_CHARGER_COUNT,
            "chargingPowerKw": round(ROBOTAXI_DEPOT_CHARGING_POWER_W / 1000),
            "batteryCapacityKwh": round(ROBOTAXI_BATTERY_CAPACITY_WH / 1000),
            "initialChargeKwh": round(ROBOTAXI_INITIAL_CHARGE_WH / 1000),
            "errors": [],
        },
        "replacement": replacement,
        "requests": requests,
        "requestsByPersonId": by_person_id,
        "reservationToPersonId": {},
        "assignedRequestByVehicleId": {},
        "pendingReservationIds": [],
        "dispatchedReservationIds": set(),
        "lastStagingDecisionSecByVehicleId": {},
        "routeCache": {},
        "activeRouteCoordinatesCache": {},
        "robotaxis": {
            f"{ROBOTAXI_ID_PREFIX}{index + 1:02d}": {
                "id": f"{ROBOTAXI_ID_PREFIX}{index + 1:02d}",
                "status": "staged",
                "requestId": None,
                "targetEdge": (
                    str(selected["depotEdge"])
                    if selected.get("spawnAtDepot") and selected.get("depotEdge")
                    else scenario_staging_edge_id(selected, index)
                ),
                "phaseSinceSec": selected["startSec"],
                "lastEnergyUpdateSec": selected["startSec"],
                "batteryWh": float(ROBOTAXI_INITIAL_CHARGE_WH),
                "chargingSessionActive": False,
                "chargingSessions": 0,
                "lastChargeReturnReason": None,
                "stagingTargetEdge": None if selected.get("spawnAtDepot") else scenario_staging_edge_id(selected, index),
                "locationEdge": (
                    str(selected["depotEdge"])
                    if selected.get("spawnAtDepot") and selected.get("depotEdge")
                    else scenario_staging_edge_id(selected, index)
                ),
                "error": None,
            }
            for index in range(scenario_fleet_size(selected))
        },
        "metrics": {
            "servedRequests": 0,
            "servedPassengers": 0,
            "unservedCapacityRequests": 0,
            "unservedCapacityPassengers": 0,
            "passengerKm": 0.0,
            "vehicleKm": 0.0,
            "emptyKm": 0.0,
            "energyKwh": 0.0,
            "chargingSessions": 0,
            "lowBatteryReturns": 0,
            "chargingUnavailable": 0,
            "stagingTrips": 0,
        },
        "events": [],
    }


def taxi_reservation_can_complete_before_close(
    connection: Any,
    dispatch_state: dict[str, Any],
    vehicle_id: str,
    request: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> bool:
    # The ride itself must finish by service close; the depot return happens in
    # the post-close recovery window and must not block mid-window assignments.
    # Per-cab infeasibility only skips this cab: the request stays waiting for
    # other cabs and is cleaned up by expiry or the assignment cutoff.
    from_edge = current_vehicle_edge(connection, vehicle_id)
    pickup_edge = str(request["pickupEdge"])
    dropoff_edge = str(request["dropoffEdge"])
    try:
        required_sec = (
            deadline_route_travel_time_sec(connection, dispatch_state, from_edge, pickup_edge)
            + deadline_route_travel_time_sec(connection, dispatch_state, pickup_edge, dropoff_edge)
            + 2 * ROBOTAXI_SERVICE_HOLD_SEC
        )
    except Exception:
        return False
    # An accepted rider is driven home even if the drop-off lands after 19:00:
    # the ride must finish inside the post-close recovery window, not by the
    # assignment close itself. (By-19:00-sharp rejected every request after
    # ~18:15 at city scale, where a pickup+ride estimate runs 30-45 min.)
    return sim_sec + required_sec <= float(selected.get("runtimeEndSec", selected["endSec"]))


def route_empty_taxi_to_depot(
    connection: Any,
    dispatch_state: dict[str, Any],
    vehicle_id: str,
    *,
    reason: str | None = None,
    sim_sec: float | None = None,
) -> None:
    robotaxi = dispatch_state["robotaxis"].get(vehicle_id)
    if robotaxi and robotaxi.get("depotReturnRouted"):
        return
    # Use the raw road id: the shared helper falls back to the depot edge for
    # internal junctions/missing vehicles, which would flag a mid-junction cab
    # as already returned and strand it.
    try:
        from_edge = str(connection.vehicle.getRoadID(vehicle_id))
    except Exception:
        from_edge = ""
    if not from_edge or from_edge.startswith(":"):
        # Not routable this step; retry on the next dispatch pass.
        return
    if from_edge in set(ROBOTAXI_DEPOT_ROUTE_EDGES):
        if robotaxi is not None:
            robotaxi["depotReturnRouted"] = True
        return
    if robotaxi and reason == "low_battery":
        if robotaxi.get("lastChargeReturnReason") != "low_battery":
            dispatch_state["metrics"]["lowBatteryReturns"] += 1
        robotaxi["lastChargeReturnReason"] = "low_battery"
    depot_edge, route_plan = best_depot_route_plan(connection, dispatch_state, from_edge)
    if robotaxi and sim_sec is not None:
        set_robotaxi_status(robotaxi, "returning_to_depot", sim_sec)
        robotaxi["targetEdge"] = depot_edge
        robotaxi["stagingTargetEdge"] = None
    try:
        try:
            connection.vehicle.resume(vehicle_id)
        except Exception:
            pass
        try:
            # Drop any still-pending idle stop; otherwise the cab keeps its
            # curbside parking order, ignores the new route, and strands.
            connection.vehicle.replaceStop(vehicle_id, 0, "")
        except Exception:
            pass
        connection.vehicle.setRoute(vehicle_id, route_plan["edges"])
    except Exception:
        try:
            connection.vehicle.changeTarget(vehicle_id, depot_edge)
        except Exception:
            # Vehicle not routable this step (e.g. mid-junction); retry next step.
            return
    # Without a scheduled stop at the depot the taxi device immediately
    # re-parks the idle cab where it stands. The packaged corridor scenario has
    # no depot parking area, so fall back to a plain roadside parking stop.
    until_sec = float(dispatch_state.get("runtimeEndSec") or dispatch_state["selectedEndSec"])
    try:
        connection.vehicle.setParkingAreaStop(
            vehicle_id,
            ROBOTAXI_DEPOT_PARKING_ID,
            until=until_sec,
        )
    except Exception:
        try:
            connection.vehicle.setStop(
                vehicle_id,
                depot_edge,
                pos=safe_lane_stop_pos(connection, depot_edge, 40.0),
                laneIndex=0,
                flags=1,
                until=until_sec,
            )
        except Exception:
            return
    if robotaxi is not None:
        robotaxi["depotReturnRouted"] = True


def taxi_robotaxi_ready_for_service(robotaxi: dict[str, Any]) -> bool:
    battery_wh = float(robotaxi.get("batteryWh", 0.0))
    if robotaxi.get("status") == "charging" and battery_wh < robotaxi_ready_charge_wh():
        return False
    return battery_wh > ROBOTAXI_RETURN_RESERVE_WH


def choose_taxi_staging_target_edges(
    dispatch_state: dict[str, Any],
    sim_sec: float,
) -> list[str]:
    horizon_sec = sim_sec + ROBOTAXI_STAGING_LOOKAHEAD_SEC
    pickup_counts: Counter[str] = Counter()
    for request in dispatch_state["requests"]:
        if request.get("status") != "scheduled":
            continue
        requested_at = float(request.get("requestedAtSec", 0.0))
        if sim_sec <= requested_at <= horizon_sec:
            pickup_edge = str(request.get("pickupEdge") or "")
            if pickup_edge:
                pickup_counts[pickup_edge] += 1
    # Enough distinct hotspots for the whole fleet to spread; a fixed small
    # limit made fleet sizes 30 and 50 behave identically (cabs piled onto the
    # same few edges while outer districts starved).
    candidate_limit = max(
        ROBOTAXI_STAGING_CANDIDATE_LIMIT, len(dispatch_state.get("robotaxis", {}))
    )
    return [edge for edge, _ in pickup_counts.most_common(candidate_limit)]


@lru_cache(maxsize=4)
def load_service_edge_pool(scenario_dir_value: str, scenario_key: str) -> tuple[str, ...]:
    path = Path(scenario_dir_value) / f"{scenario_key}.service-edges.txt"
    if not path.exists():
        return ()
    edges: list[str] = []
    depot_edges = set(ROBOTAXI_DEPOT_ROUTE_EDGES)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            edge_id = line.strip()
            if edge_id and not edge_id.startswith(":") and edge_id not in depot_edges:
                edges.append(edge_id)
    return tuple(edges)


def choose_taxi_roam_target_edge(
    dispatch_state: dict[str, Any],
    selected: dict[str, Any],
    current_edge: str,
) -> str | None:
    pool = load_service_edge_pool(str(selected["dir"]), str(selected["key"]))
    if not pool:
        return None
    rng = dispatch_state.get("roamRng")
    if rng is None:
        rng = random.Random(dispatch_state.get("runId") or 0)
        dispatch_state["roamRng"] = rng
    for _ in range(6):
        candidate = rng.choice(pool)
        if candidate != current_edge:
            return candidate
    return None


def route_empty_taxi_to_staging(
    connection: Any,
    dispatch_state: dict[str, Any],
    vehicle_id: str,
    target_edge: str,
    sim_sec: float,
) -> None:
    if not target_edge or target_edge in set(ROBOTAXI_DEPOT_ROUTE_EDGES):
        return
    robotaxi = dispatch_state["robotaxis"].get(vehicle_id)
    if not robotaxi:
        return
    current_edge = current_vehicle_edge(connection, vehicle_id)
    if current_edge == target_edge or robotaxi.get("stagingTargetEdge") == target_edge:
        set_robotaxi_status(robotaxi, "staged", sim_sec)
        robotaxi["targetEdge"] = target_edge
        robotaxi["stagingTargetEdge"] = target_edge
        return
    try:
        route_plan = cached_route_plan(connection, dispatch_state, current_edge, target_edge)
        try:
            # A cab parked at the depot must resume before rerouting or it
            # stays physically parked while flapping staged/idle_at_depot.
            connection.vehicle.resume(vehicle_id)
        except Exception:
            pass
        try:
            # Clear a still-pending idle stop so the staging route is obeyed.
            connection.vehicle.replaceStop(vehicle_id, 0, "")
        except Exception:
            pass
        connection.vehicle.setRoute(vehicle_id, route_plan["edges"])
    except Exception:
        return
    set_robotaxi_status(robotaxi, "staged", sim_sec)
    robotaxi["targetEdge"] = target_edge
    robotaxi["stagingTargetEdge"] = target_edge
    robotaxi["lastChargeReturnReason"] = None
    robotaxi["depotReturnRouted"] = False
    dispatch_state["metrics"]["stagingTrips"] += 1


def taxi_request_for_vehicle(
    dispatch_state: dict[str, Any],
    vehicle_id: str,
    statuses: set[str] | None = None,
) -> dict[str, Any] | None:
    assigned_request_id = dispatch_state.get("assignedRequestByVehicleId", {}).get(vehicle_id)
    if assigned_request_id:
        request = robotaxi_request_by_id(dispatch_state, assigned_request_id)
        if request and (not statuses or request.get("status") in statuses):
            return request

    for request in dispatch_state["requests"]:
        if request.get("assignedVehicleId") != vehicle_id:
            continue
        if statuses and request.get("status") not in statuses:
            continue
        return request
    return None


def taxi_robotaxi_has_charge_for(
    connection: Any,
    dispatch_state: dict[str, Any],
    robotaxi: dict[str, Any],
    request: dict[str, Any],
) -> bool:
    from_edge = current_vehicle_edge(connection, robotaxi["id"])
    try:
        pickup_m = cached_route_distance_m(
            connection,
            dispatch_state,
            from_edge,
            str(request["pickupEdge"]),
        )
        service_m = request_trip_distance_m(connection, dispatch_state, request)
        return_m = cached_route_distance_m(
            connection,
            dispatch_state,
            str(request["dropoffEdge"]),
            ROBOTAXI_DEPOT_ROUTE_EDGES[0],
        )
    except Exception:
        return False
    required_wh = (pickup_m + service_m + return_m) * ROBOTAXI_CONSUMPTION_WH_PER_M
    return float(robotaxi.get("batteryWh", 0.0)) - required_wh >= ROBOTAXI_MIN_RESERVE_WH


def update_robotaxi_eta_and_stop_reason(
    connection: Any,
    dispatch_state: dict[str, Any],
    vehicle_id: str,
    robotaxi: dict[str, Any],
    speed_mps: float,
) -> None:
    status = robotaxi.get("status")
    target_edge = None
    if status == "en_route_pickup":
        request = taxi_request_for_vehicle(dispatch_state, vehicle_id, {"assigned", "waiting"})
        target_edge = request.get("pickupEdge") if request else None
    elif status == "with_passenger":
        request = taxi_request_for_vehicle(dispatch_state, vehicle_id, {"onboard"})
        target_edge = request.get("dropoffEdge") if request else None

    if target_edge:
        try:
            current_edge = str(connection.vehicle.getRoadID(vehicle_id))
        except Exception:
            current_edge = ""
        if current_edge and not current_edge.startswith(":"):
            # Internal-junction edges keep the previous ETA instead of
            # rerouting from a fake origin.
            if current_edge == target_edge:
                robotaxi["etaSec"] = 0.0
            else:
                try:
                    robotaxi["etaSec"] = round(
                        cached_route_travel_time_sec(
                            connection,
                            dispatch_state,
                            current_edge,
                            target_edge,
                        ),
                        1,
                    )
                except Exception:
                    robotaxi["etaSec"] = None
    else:
        robotaxi["etaSec"] = None

    if speed_mps > 0.3 or status not in {
        "en_route_pickup",
        "with_passenger",
        "returning_to_depot",
    }:
        # Staged/idle cabs are intentionally parked; that is a state, not a
        # stop reason.
        robotaxi["stopReason"] = None
        return
    try:
        stop_state = int(connection.vehicle.getStopState(vehicle_id))
    except Exception:
        stop_state = 0
    if stop_state:
        if status == "en_route_pickup":
            robotaxi["stopReason"] = "waiting_for_pickup"
        elif status == "with_passenger":
            robotaxi["stopReason"] = "dropping_off"
        else:
            robotaxi["stopReason"] = None
        return
    try:
        next_tls = connection.vehicle.getNextTLS(vehicle_id)
    except Exception:
        next_tls = []
    if next_tls:
        # Entries are (tlsID, tlsIndex, distanceM, state).
        _, _, tls_distance_m, tls_state = next_tls[0]
        if str(tls_state).lower() in {"r", "y", "u"} and float(tls_distance_m) < 40.0:
            robotaxi["stopReason"] = "red_light"
            return
    robotaxi["stopReason"] = "stopped"


def update_robotaxi_motion_metrics_from_traci(
    connection: Any,
    dispatch_state: dict[str, Any],
    sim_sec: float,
) -> None:
    for vehicle_id, robotaxi in dispatch_state["robotaxis"].items():
        if robotaxi.get("status") in {"charging", "idle_at_depot", "offline"}:
            robotaxi["lastMotionUpdateSec"] = sim_sec
            robotaxi["etaSec"] = None
            robotaxi["stopReason"] = None
            continue
        try:
            speed_mps = max(0.0, float(connection.vehicle.getSpeed(vehicle_id)))
        except Exception:
            continue

        update_robotaxi_eta_and_stop_reason(
            connection,
            dispatch_state,
            vehicle_id,
            robotaxi,
            speed_mps,
        )

        last_motion_update_sec = robotaxi.get("lastMotionUpdateSec")
        if last_motion_update_sec is None:
            robotaxi["lastMotionUpdateSec"] = sim_sec
            continue

        elapsed_sec = max(0.0, sim_sec - float(last_motion_update_sec))
        robotaxi["lastMotionUpdateSec"] = sim_sec
        delta_m = speed_mps * elapsed_sec
        if delta_m <= 0:
            continue

        request = taxi_request_for_vehicle(
            dispatch_state,
            vehicle_id,
            {"onboard", "completed"} if robotaxi.get("status") == "with_passenger" else None,
        )
        occupied = robotaxi.get("status") == "with_passenger"
        passengers = int(request.get("partySize") or 1) if request else 0
        debit_robotaxi_route(
            dispatch_state,
            robotaxi,
            delta_m,
            occupied=occupied,
            passengers=passengers if occupied else 0,
        )


def close_taxi_drt_service_window(
    connection: Any,
    dispatch_state: dict[str, Any],
    sim_sec: float,
) -> None:
    for request in dispatch_state["requests"]:
        if request.get("status") not in {"scheduled", "waiting"}:
            continue
        if request.get("assignedVehicleId"):
            continue
        request["status"] = "rejected"
        request["rejectionReason"] = "service_window_ending"
        request["closedAtSec"] = sim_sec
        person_id = request.get("personId")
        if person_id:
            try:
                connection.person.remove(str(person_id))
            except Exception:
                pass

    pending_reservation_ids: list[str] = dispatch_state["pendingReservationIds"]
    pending_reservation_ids[:] = [
        reservation_id
        for reservation_id in pending_reservation_ids
        if (
            dispatch_state["requestsByPersonId"]
            .get(dispatch_state["reservationToPersonId"].get(reservation_id, ""), {})
            .get("status")
            not in {"rejected", "vehicle_failed", "completed"}
        )
    ]


def taxi_drt_recovery_complete(
    dispatch_state: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> bool:
    if sim_sec < float(selected["endSec"]):
        return False
    active_requests = any(
        request.get("status") in {"waiting", "assigned", "onboard"}
        for request in dispatch_state["requests"]
    )
    if active_requests:
        return False
    depot_edges = set(ROBOTAXI_DEPOT_ROUTE_EDGES)
    return all(
        str(robotaxi.get("locationEdge")) in depot_edges
        for robotaxi in dispatch_state["robotaxis"].values()
    )


def update_taxi_drt_dispatch(
    connection: Any,
    dispatch_state: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> None:
    dispatch_profile = dispatch_state.setdefault("dispatchProfile", {})

    def add_profile_ms(key: str, started_at: float) -> None:
        dispatch_profile[key] = float(dispatch_profile.get(key, 0.0)) + (
            time.perf_counter() - started_at
        ) * 1000

    profile_started_at = time.perf_counter()
    update_robotaxi_charging(dispatch_state, sim_sec)
    live_person_ids = set(connection.person.getIDList())
    reservation_to_person_id: dict[str, str] = dispatch_state["reservationToPersonId"]
    pending_reservation_ids: list[str] = dispatch_state["pendingReservationIds"]
    winddown_sec = float(
        selected.get("assignmentWinddownSec")
        if selected.get("assignmentWinddownSec") is not None
        else ROBOTAXI_TAXI_DRT_WINDDOWN_SEC
    )
    assignment_closed = sim_sec + winddown_sec >= float(selected["endSec"])
    if assignment_closed:
        close_taxi_drt_service_window(connection, dispatch_state, sim_sec)
    add_profile_ms("setupMs", profile_started_at)

    profile_started_at = time.perf_counter()
    for reservation in connection.person.getTaxiReservations(1):
        reservation_id = str(reservation.id)
        person_id = str(reservation.persons[0]) if reservation.persons else ""
        request = dispatch_state["requestsByPersonId"].get(person_id)
        request_status = request.get("status") if request else None
        if assignment_closed and (not request or request_status in {"scheduled", "waiting"}):
            if request:
                request["reservationId"] = reservation_id
                request["status"] = "rejected"
                request["rejectionReason"] = "service_window_ending"
                request["closedAtSec"] = sim_sec
            try:
                connection.person.remove(person_id)
            except Exception:
                pass
            continue
        if not request:
            continue
        if request.get("reservationId") == reservation_id and request_status in {
            "waiting",
            "assigned",
            "onboard",
        }:
            reservation_to_person_id[reservation_id] = person_id
            if request_status == "waiting" and reservation_id not in pending_reservation_ids:
                pending_reservation_ids.append(reservation_id)
            continue
        if request_status not in {"scheduled", "waiting"}:
            # A late reservation must not resurrect a closed request
            # (rejected/expired/completed stay terminal).
            continue
        request["reservationId"] = reservation_id
        request["status"] = "waiting"
        request["reservationAtSec"] = sim_sec
        request["pickupEdge"] = str(reservation.fromEdge)
        request["dropoffEdge"] = str(reservation.toEdge)
        try:
            request_trip_distance_m(connection, dispatch_state, request)
        except Exception as error:
            request["status"] = "rejected"
            request["rejectionReason"] = "unreachable_for_taxi_dispatch"
            request["error"] = str(error)
            request["closedAtSec"] = sim_sec
            try:
                connection.person.remove(person_id)
            except Exception:
                pass
            continue
        reservation_to_person_id[reservation_id] = person_id
        if reservation_id not in pending_reservation_ids:
            pending_reservation_ids.append(reservation_id)
    add_profile_ms("reservationMs", profile_started_at)

    profile_started_at = time.perf_counter()
    request_expiry_sec = float(selected.get("requestExpirySec") or ROBOTAXI_REQUEST_EXPIRY_SEC)
    for person_id, request in dispatch_state["requestsByPersonId"].items():
        if request.get("status") != "waiting":
            continue
        requested_at = request.get("requestedAtSec")
        if requested_at is None:
            continue
        if sim_sec <= float(requested_at) + request_expiry_sec:
            continue
        request["status"] = "expired"
        request["expiredAtSec"] = sim_sec
        request["closedAtSec"] = sim_sec
        request["rejectionReason"] = f"expired_unassigned_{int(request_expiry_sec)}s"
        reservation_id = request.get("reservationId")
        if reservation_id in pending_reservation_ids:
            pending_reservation_ids.remove(reservation_id)
        try:
            connection.person.remove(person_id)
        except Exception:
            pass
    add_profile_ms("expiryMs", profile_started_at)

    profile_started_at = time.perf_counter()
    empty_set = set(connection.vehicle.getTaxiFleet(0))
    pickup_set = set(connection.vehicle.getTaxiFleet(1))
    occupied_set = set(connection.vehicle.getTaxiFleet(2))
    occupied_person_ids: dict[str, str] = {}
    for taxi_id in occupied_set:
        try:
            for person_id in connection.vehicle.getPersonIDList(taxi_id):
                occupied_person_ids[str(person_id)] = taxi_id
        except Exception:
            continue
    add_profile_ms("taxiFleetMs", profile_started_at)

    profile_started_at = time.perf_counter()
    for person_id, request in dispatch_state["requestsByPersonId"].items():
        status = request.get("status")
        if status in {"scheduled", "completed", "vehicle_failed", "capacity_miss", "rejected", "unreachable", "expired"}:
            continue
        if person_id in occupied_person_ids:
            if status != "onboard":
                request["status"] = "onboard"
                request["pickupAtSec"] = sim_sec
            request["assignedVehicleId"] = occupied_person_ids[person_id]
            dispatch_state["assignedRequestByVehicleId"][occupied_person_ids[person_id]] = request["id"]
            continue
        if person_id not in live_person_ids and status in {"waiting", "assigned", "onboard"}:
            if request.get("pickupAtSec") is not None or status == "onboard":
                request["status"] = "completed"
                request["completedAtSec"] = sim_sec
                metrics = dispatch_state["metrics"]
                metrics["servedRequests"] += 1
                metrics["servedPassengers"] += int(request.get("partySize") or 1)
                assigned_vehicle_id = request.get("assignedVehicleId")
                if assigned_vehicle_id:
                    dispatch_state["assignedRequestByVehicleId"].pop(str(assigned_vehicle_id), None)
            else:
                request["status"] = "vehicle_failed"
                request["rejectionReason"] = "taxi_reservation_canceled_before_pickup"
                request["error"] = "taxi reservation canceled before pickup"
    add_profile_ms("requestSyncMs", profile_started_at)

    profile_started_at = time.perf_counter()
    empty_fleet = list(empty_set)
    # Matching, staging and depot-return decisions run on a 3-sim-second
    # cadence, not every step: routing queries dominated live-run CPU, and a
    # sub-3-sim-second reaction is invisible at 60x.
    last_fleet_decision_sec = float(dispatch_state.get("lastFleetDecisionSec", -1e9))
    if sim_sec - last_fleet_decision_sec < 3.0:
        empty_fleet = []
    else:
        dispatch_state["lastFleetDecisionSec"] = sim_sec
    service_is_ending = assignment_closed
    # With taxi stands loaded, the taxi device's own taxistand idle algorithm
    # distributes empty cabs across the city — the python staging/roam layer
    # must stand down or the two fight over routes every few seconds.
    stands_mode = selected.get("additional") is not None
    staging_target_edges = (
        []
        if assignment_closed or stands_mode
        else choose_taxi_staging_target_edges(dispatch_state, sim_sec)
    )
    # Cabs already heading to a hotspot count against it so idle cabs spread
    # across the top hotspots instead of forming a convoy on the single hottest.
    staging_load: Counter[str] = Counter()
    for robotaxi in dispatch_state["robotaxis"].values():
        target = robotaxi.get("stagingTargetEdge")
        if target:
            staging_load[str(target)] += 1
    # Global-greedy matching plan. The old per-vehicle scan let whichever idle
    # cab iterated first grab a request even when another idle cab was much
    # closer — measured on the fleet-60 stands replay: 43% of assignments were
    # >1 km worse than the best idle cab (P50 6.5 km assigned vs 4.3 km best).
    # Scoring cost is identical (same vehicle x reservation routing calls);
    # only the pairing order changes: cheapest feasible pairs win globally.
    planned_assignment: dict[str, str] = {}
    if not assignment_closed and pending_reservation_ids and empty_fleet:
        scored_pairs: list[tuple[float, str, str]] = []
        for vehicle_id in empty_fleet:
            robotaxi = dispatch_state["robotaxis"].get(vehicle_id, {})
            if not taxi_robotaxi_ready_for_service(robotaxi):
                continue
            vehicle_edge = current_vehicle_edge(connection, vehicle_id)
            for reservation_id in pending_reservation_ids:
                person_id = reservation_to_person_id.get(reservation_id)
                request = dispatch_state["requestsByPersonId"].get(person_id or "")
                if not request:
                    continue
                if not taxi_robotaxi_has_charge_for(
                    connection, dispatch_state, robotaxi, request
                ):
                    continue
                if not taxi_reservation_can_complete_before_close(
                    connection, dispatch_state, vehicle_id, request, sim_sec, selected
                ):
                    continue
                try:
                    score = cached_route_travel_time_sec(
                        connection, dispatch_state, vehicle_edge, request["pickupEdge"]
                    )
                except Exception:
                    continue
                if score > ROBOTAXI_MAX_PICKUP_ROUTE_SEC:
                    continue
                scored_pairs.append((score, vehicle_id, reservation_id))
        scored_pairs.sort(key=lambda pair: pair[0])
        matched_vehicles: set[str] = set()
        matched_reservations: set[str] = set()
        for score, vehicle_id, reservation_id in scored_pairs:
            if vehicle_id in matched_vehicles or reservation_id in matched_reservations:
                continue
            planned_assignment[vehicle_id] = reservation_id
            matched_vehicles.add(vehicle_id)
            matched_reservations.add(reservation_id)
    for vehicle_id in empty_fleet:
        if assignment_closed or not pending_reservation_ids:
            if service_is_ending:
                try:
                    route_empty_taxi_to_depot(
                        connection,
                        dispatch_state,
                        vehicle_id,
                        reason="service_ending",
                        sim_sec=sim_sec,
                    )
                except Exception:
                    pass
                continue
            robotaxi = dispatch_state["robotaxis"].get(vehicle_id, {})
            last_staging_decision_sec = float(
                dispatch_state["lastStagingDecisionSecByVehicleId"].get(
                    vehicle_id,
                    selected["startSec"] - ROBOTAXI_STAGING_RECHECK_SEC,
                )
            )
            if staging_target_edges:
                if (
                    taxi_robotaxi_ready_for_service(robotaxi)
                    and sim_sec - last_staging_decision_sec >= ROBOTAXI_STAGING_RECHECK_SEC
                    and str(robotaxi.get("stagingTargetEdge") or "") not in staging_target_edges
                ):
                    # Least-loaded hotspot that is also reachable in a sane
                    # empty leg; if every hotspot is too far, the cab holds its
                    # region instead of deadheading across the city. The leg
                    # OUT of the depot is exempt — the initial deployment drive
                    # is long by design (Tegel -> city).
                    staging_edge = current_vehicle_edge(connection, vehicle_id)
                    depot_edges = {str(selected.get("depotEdge") or ""), *ROBOTAXI_DEPOT_ROUTE_EDGES}
                    staging_cap_sec = (
                        float("inf")
                        if staging_edge in depot_edges
                        else ROBOTAXI_MAX_STAGING_ROUTE_SEC
                    )
                    target_edge = None
                    for candidate in sorted(
                        staging_target_edges, key=lambda edge: staging_load[edge]
                    ):
                        try:
                            leg_sec = cached_route_travel_time_sec(
                                connection,
                                dispatch_state,
                                staging_edge,
                                candidate,
                            )
                        except Exception:
                            continue
                        if leg_sec <= staging_cap_sec:
                            target_edge = candidate
                            break
                    if target_edge is not None:
                        route_empty_taxi_to_staging(
                            connection,
                            dispatch_state,
                            vehicle_id,
                            target_edge,
                            sim_sec,
                        )
                        if robotaxi.get("stagingTargetEdge") == target_edge:
                            robotaxi["isRoaming"] = False
                            staging_load[target_edge] += 1
                    dispatch_state["lastStagingDecisionSecByVehicleId"][vehicle_id] = sim_sec
            elif (
                not stands_mode
                and robotaxi.get("status") in {"idle", "staged"}
                and taxi_robotaxi_ready_for_service(robotaxi)
                and sim_sec - float(robotaxi.get("phaseSinceSec", sim_sec)) >= ROBOTAXI_ROAM_IDLE_MIN_SEC
                and sim_sec - last_staging_decision_sec >= ROBOTAXI_ROAM_RECHECK_SEC
            ):
                current_edge = current_vehicle_edge(connection, vehicle_id)
                roam_edge = choose_taxi_roam_target_edge(dispatch_state, selected, current_edge)
                if roam_edge:
                    route_empty_taxi_to_staging(
                        connection,
                        dispatch_state,
                        vehicle_id,
                        roam_edge,
                        sim_sec,
                    )
                    if robotaxi.get("stagingTargetEdge") == roam_edge:
                        robotaxi["isRoaming"] = True
                    dispatch_state["lastStagingDecisionSecByVehicleId"][vehicle_id] = sim_sec
            continue

        current_edge = current_vehicle_edge(connection, vehicle_id)
        robotaxi = dispatch_state["robotaxis"].get(vehicle_id, {})
        if not taxi_robotaxi_ready_for_service(robotaxi):
            dispatch_state["metrics"]["chargingUnavailable"] += 1
            try:
                route_empty_taxi_to_depot(
                    connection,
                    dispatch_state,
                    vehicle_id,
                    reason="low_battery",
                    sim_sec=sim_sec,
                )
            except Exception:
                pass
            continue
        # The globally-planned pairing replaces the old per-vehicle scan (see
        # the plan pre-pass above); feasibility was already checked there.
        best_index: int | None = None
        planned_reservation = planned_assignment.get(vehicle_id)
        if planned_reservation is not None and planned_reservation in pending_reservation_ids:
            best_index = pending_reservation_ids.index(planned_reservation)

        if best_index is None:
            pending_reservation_ids[:] = [
                reservation_id
                for reservation_id in pending_reservation_ids
                if (
                    dispatch_state["requestsByPersonId"]
                    .get(reservation_to_person_id.get(reservation_id, ""), {})
                    .get("status")
                    not in {"rejected", "vehicle_failed", "completed", "expired"}
                )
            ]
            try:
                robotaxi = dispatch_state["robotaxis"].get(vehicle_id, {})
                # Only a genuinely low battery justifies leaving the zone for
                # the depot mid-shift. The old ready-charge threshold (88% of
                # pack) sent every lightly-used cab commuting to Tegel, which
                # wrecked waits and made the fleet look like depot ping-pong.
                if float(robotaxi.get("batteryWh", 0.0)) < ROBOTAXI_RETURN_RESERVE_WH:
                    route_empty_taxi_to_depot(
                        connection,
                        dispatch_state,
                        vehicle_id,
                        reason="low_battery",
                        sim_sec=sim_sec,
                    )
                elif not service_is_ending and staging_target_edges:
                    # A healthy cab parked at the depot serves nobody: it was
                    # too far for every pending request, and with requests
                    # pending it never used to get a staging leg either — the
                    # depot-sleeper trap. Push it into the city.
                    depot_edges = {
                        str(selected.get("depotEdge") or ""),
                        *ROBOTAXI_DEPOT_ROUTE_EDGES,
                    }
                    if current_edge in depot_edges:
                        target_edge = min(
                            staging_target_edges, key=lambda edge: staging_load[edge]
                        )
                        route_empty_taxi_to_staging(
                            connection,
                            dispatch_state,
                            vehicle_id,
                            target_edge,
                            sim_sec,
                        )
                        if robotaxi.get("stagingTargetEdge") == target_edge:
                            staging_load[target_edge] += 1
                        dispatch_state["lastStagingDecisionSecByVehicleId"][vehicle_id] = sim_sec
            except Exception:
                pass
            continue

        reservation_id = pending_reservation_ids.pop(best_index)
        person_id = reservation_to_person_id.get(reservation_id)
        request = dispatch_state["requestsByPersonId"].get(person_id or "")
        if not request:
            continue
        try:
            connection.vehicle.dispatchTaxi(vehicle_id, [reservation_id])
            request["status"] = "assigned"
            request["assignedVehicleId"] = vehicle_id
            request["assignedAtSec"] = sim_sec
            dispatch_state["assignedRequestByVehicleId"][vehicle_id] = request["id"]
            dispatch_state["dispatchedReservationIds"].add(reservation_id)
            empty_set.discard(vehicle_id)
            pickup_set.add(vehicle_id)
            robotaxi = dispatch_state["robotaxis"].get(vehicle_id)
            if robotaxi:
                robotaxi["stagingTargetEdge"] = None
                robotaxi["lastChargeReturnReason"] = None
                robotaxi["depotReturnRouted"] = False
        except Exception as error:
            request["status"] = "vehicle_failed"
            request["assignedVehicleId"] = vehicle_id
            request["rejectionReason"] = "dispatch_taxi_failed"
            request["error"] = str(error)
            dispatch_state["assignedRequestByVehicleId"].pop(vehicle_id, None)
    add_profile_ms("assignmentMs", profile_started_at)

    profile_started_at = time.perf_counter()
    for vehicle_id, robotaxi in dispatch_state["robotaxis"].items():
        # Internal-junction edges and lookup failures keep the previous known
        # edge; falling back to the depot edge here fakes "at depot" states.
        try:
            raw_edge = str(connection.vehicle.getRoadID(vehicle_id))
        except Exception:
            raw_edge = ""
        if raw_edge and not raw_edge.startswith(":"):
            vehicle_edge = raw_edge
        else:
            vehicle_edge = str(robotaxi.get("locationEdge") or "")
        if vehicle_id in occupied_set:
            set_robotaxi_status(robotaxi, "with_passenger", sim_sec)
            request = taxi_request_for_vehicle(dispatch_state, vehicle_id, {"onboard", "completed"})
            robotaxi["requestId"] = request.get("id") if request else robotaxi.get("requestId")
            robotaxi["chargingSessionActive"] = False
        elif vehicle_id in pickup_set:
            set_robotaxi_status(robotaxi, "en_route_pickup", sim_sec)
            request = taxi_request_for_vehicle(dispatch_state, vehicle_id, {"assigned", "waiting"})
            robotaxi["requestId"] = request.get("id") if request else robotaxi.get("requestId")
            robotaxi["chargingSessionActive"] = False
            robotaxi["stagingTargetEdge"] = None
        elif vehicle_id in empty_set:
            if vehicle_edge in set(ROBOTAXI_DEPOT_ROUTE_EDGES):
                mark_robotaxi_depot_state(robotaxi, sim_sec)
            elif service_is_ending:
                set_robotaxi_status(robotaxi, "returning_to_depot", sim_sec)
                robotaxi["requestId"] = None
                robotaxi["chargingSessionActive"] = False
                robotaxi["stagingTargetEdge"] = None
                # Return watchdog: depotReturnRouted is a one-shot guard, so a
                # return leg broken later (teleport, re-park) strands the cab
                # until the hard cap. Re-issue the depot route every few
                # minutes until the cab actually stands on a depot edge.
                if robotaxi.get("depotReturnRouted"):
                    last_reissue = robotaxi.get("lastDepotReissueSec")
                    if last_reissue is None:
                        robotaxi["lastDepotReissueSec"] = sim_sec
                    elif sim_sec - float(last_reissue) >= 240.0:
                        robotaxi["depotReturnRouted"] = False
                        robotaxi["lastDepotReissueSec"] = sim_sec
            elif robotaxi.get("stagingTargetEdge"):
                if robotaxi.get("isRoaming") and vehicle_edge == str(robotaxi.get("stagingTargetEdge")):
                    # Roam leg finished: cab parks curbside and reads as idle.
                    robotaxi["stagingTargetEdge"] = None
                    robotaxi["isRoaming"] = False
                    set_robotaxi_status(robotaxi, "idle", sim_sec)
                else:
                    set_robotaxi_status(
                        robotaxi,
                        "roaming" if robotaxi.get("isRoaming") else "staged",
                        sim_sec,
                    )
                robotaxi["requestId"] = None
                robotaxi["chargingSessionActive"] = False
            else:
                set_robotaxi_status(robotaxi, "idle", sim_sec)
                robotaxi["requestId"] = None
                robotaxi["chargingSessionActive"] = False
        else:
            set_robotaxi_status(robotaxi, "offline", sim_sec)
        robotaxi["locationEdge"] = vehicle_edge
    add_profile_ms("fleetStateMs", profile_started_at)

    profile_started_at = time.perf_counter()
    update_robotaxi_motion_metrics_from_traci(connection, dispatch_state, sim_sec)
    add_profile_ms("motionMetricsMs", profile_started_at)


def serialize_taxi_drt_dispatch(
    dispatch_state: dict[str, Any] | None,
    sim_sec: float,
    *,
    include_requests: bool = True,
) -> dict[str, Any]:
    payload = serialize_robotaxi_dispatch(dispatch_state, sim_sec, include_requests=include_requests)
    if dispatch_state:
        payload["engine"] = "sumo-taxi-device"
        payload["metrics"]["dispatchEngine"] = "SUMO taxi device"
    return payload


def build_robotaxi_run_audit(
    dispatch_state: dict[str, Any],
    sim_sec: float,
    selected: dict[str, Any],
) -> dict[str, Any]:
    dispatch_payload = serialize_taxi_drt_dispatch(
        dispatch_state,
        sim_sec,
        include_requests=False,
    )
    metrics = dispatch_payload["metrics"]
    robotaxis = dispatch_payload["robotaxis"]
    request_counts = metrics.get("requestStatusCounts", {})
    open_requests = int(metrics.get("requestOutcomeCounts", {}).get("open", 0))
    accepted_requests = int(metrics.get("requestOutcomeCounts", {}).get("accepted", 0))
    not_served = int(metrics.get("notServedRequests", 0))
    fleet_state_counts = dict(metrics.get("fleetStateCounts", {}))
    depot_edges = set(ROBOTAXI_DEPOT_ROUTE_EDGES)
    non_depot_robotaxis = [
        robotaxi["id"]
        for robotaxi in robotaxis
        if robotaxi.get("locationEdge") not in depot_edges
    ]
    at_depot = len(robotaxis) - len(non_depot_robotaxis)
    wait_values = [
        max(0.0, float(request["pickupAtSec"]) - float(request["requestedAtSec"]))
        for request in dispatch_state["requests"]
        if request.get("pickupAtSec") is not None
    ]
    all_fleet_recovered = not non_depot_robotaxis
    return {
        "window": scenario_window_label(selected),
        "startSec": selected["startSec"],
        "endSec": selected["endSec"],
        "simSec": sim_sec,
        "completed": int(metrics.get("completed", 0)),
        "openRequests": open_requests,
        "acceptedRequests": accepted_requests,
        "notServedRequests": not_served,
        "expiredRequests": int(metrics.get("expiredRequests", 0)),
        "requestStatusCounts": request_counts,
        "avgWaitSec": metrics.get("avgWaitSec"),
        "maxWaitSec": round(max(wait_values), 1) if wait_values else None,
        "vehicleKm": metrics.get("vehicleKm", 0.0),
        "deadheadKm": metrics.get("deadheadKm", 0.0),
        "deadheadingPercent": metrics.get("deadheadingPercent", 0.0),
        "energyKwh": metrics.get("energyKwh", 0.0),
        "energyWhPerPassengerKm": metrics.get("energyWhPerPassengerKm"),
        "chargingSessions": metrics.get("chargingSessions", 0),
        "lowBatteryReturns": metrics.get("lowBatteryReturns", 0),
        "stagingTrips": metrics.get("stagingTrips", 0),
        "fleetStateCounts": fleet_state_counts,
        "fleetAtDepot": at_depot,
        "fleetSize": len(robotaxis),
        "nonDepotRobotaxis": non_depot_robotaxis,
        "allFleetRecovered": all_fleet_recovered,
        "passed": open_requests == 0 and accepted_requests == 0 and all_fleet_recovered,
    }


def produce_sumo_taxi_drt_playback_chunks(
    traci: Any,
    command: list[str],
    connection_label: str,
    selected: dict[str, Any],
    playback_rate: int,
    replacement_percent: int,
    demand_source: str,
    playback_detail: str,
    frame_step_sec: float,
    visual_stride: int,
    message_queue: asyncio.Queue[dict[str, Any]],
    event_loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    chunk_index = 0
    chunk_frames: list[dict[str, Any]] = []
    recorded_frames = 0
    started_at = time.perf_counter()
    frames_per_chunk = PLAYBACK_CHUNK_VISUAL_FRAMES
    chunk_started_at = time.perf_counter()
    chunk_step_ms = 0.0
    chunk_frame_ms = 0.0
    chunk_dispatch_ms = 0.0
    chunk_vehicle_id_ms = 0.0
    chunk_vehicle_loop_ms = 0.0
    chunk_traffic_light_ms = 0.0
    chunk_vehicle_count = 0

    def emit(payload: dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(message_queue.put(payload), event_loop)
        future.result()

    def emit_chunk() -> None:
        nonlocal chunk_index, chunk_frames, recorded_frames
        nonlocal chunk_started_at, chunk_step_ms, chunk_frame_ms, chunk_vehicle_count
        nonlocal chunk_dispatch_ms, chunk_vehicle_id_ms, chunk_vehicle_loop_ms, chunk_traffic_light_ms
        if not chunk_frames:
            return

        frame_count = len(chunk_frames)
        recorded_frames += len(chunk_frames)
        dispatch_profile = {
            key: round(float(value), 2)
            for key, value in dispatch_state.get("dispatchProfile", {}).items()
        }
        emit(
            {
                "type": "chunk",
                "scope": selected["key"],
                "chunkIndex": chunk_index,
                "dispatchEngine": "taxi",
                "playbackRate": playback_rate,
                "dataFps": PLAYBACK_DATA_FPS,
                "frameStepSec": frame_step_sec,
                "visualStride": visual_stride,
                "chunkVisualFrames": frames_per_chunk,
                "chunkSimSeconds": frame_step_sec * visual_stride * frames_per_chunk,
                "startSimSec": chunk_frames[0]["simSec"],
                "endSimSec": chunk_frames[-1]["simSec"],
                "frames": chunk_frames,
                "profile": {
                    "frames": frame_count,
                    "vehicles": chunk_vehicle_count,
                    "stepMs": round(chunk_step_ms, 2),
                    "dispatchMs": round(chunk_dispatch_ms, 2),
                    "dispatchProfile": dispatch_profile,
                    "frameMs": round(chunk_frame_ms, 2),
                    "vehicleIdMs": round(chunk_vehicle_id_ms, 2),
                    "vehicleLoopMs": round(chunk_vehicle_loop_ms, 2),
                    "trafficLightMs": round(chunk_traffic_light_ms, 2),
                    "chunkMs": round((time.perf_counter() - chunk_started_at) * 1000, 2),
                },
            }
        )
        chunk_index += 1
        chunk_frames = []
        chunk_started_at = time.perf_counter()
        chunk_step_ms = 0.0
        chunk_frame_ms = 0.0
        chunk_dispatch_ms = 0.0
        chunk_vehicle_id_ms = 0.0
        chunk_vehicle_loop_ms = 0.0
        chunk_traffic_light_ms = 0.0
        chunk_vehicle_count = 0
        dispatch_state["dispatchProfile"] = {}

    dispatch_state = create_taxi_drt_dispatch_state(
        selected,
        replacement_percent,
        demand_source,
        uuid.uuid4().hex,
    )
    taxi_route_path = Path(dispatch_state["routePath"])
    taxi_command = [
        *command,
        "--route-files",
        f"{selected['route']},{taxi_route_path}",
        "--device.taxi.dispatch-algorithm",
        "traci",
        "--device.taxi.dispatch-period",
        "1",
        # A*: goal-directed routing without precomputation. Dijkstra made
        # dispatch findRoute ~29% of live-run CPU; CH was worse (its
        # hierarchy rebuilds turned dispatchTaxi into 90% of the run).
        "--routing-algorithm",
        "astar",
    ]
    if selected.get("additional") is not None:
        taxi_command.extend(["--device.taxi.idle-algorithm", "taxistand"])
    taxi_command = sumo_command_with_additional(taxi_command, selected)
    # Live visits get a fresh SUMO seed: every run is a genuinely different
    # evening (car-following draws, insertion jitter), not a replayed one.
    # Recordings pin the seed via ?sumoseed= for reproducible replays.
    sumo_seed = selected.get("sumoSeed")
    taxi_command.extend(["--seed", str(sumo_seed if sumo_seed is not None else random.randint(1, 2**31 - 1))])

    try:
        traci.start(taxi_command, label=connection_label)
        connection = traci.getConnection(connection_label)
        traci_constants = traci.constants
        net_offset, utm_zone = load_sumo_projection(str(selected["net"]))
        edge_line_shapes = load_sumo_edge_line_shapes(str(selected["net"]))
        traffic_light_ids = (
            list(connection.trafficlight.getIDList())
            if selected.get("includeTrafficLights", True)
            else []
        )
        for traffic_light_id in traffic_light_ids:
            connection.trafficlight.subscribe(
                traffic_light_id,
                [traci_constants.TL_RED_YELLOW_GREEN_STATE],
            )
        subscribed_vehicle_ids: set[str] = set()
        runtime_end_sec = float(selected.get("runtimeEndSec", selected["endSec"]))
        total_steps = int(round((runtime_end_sec - selected["startSec"]) / frame_step_sec))
        initial_dispatch_payload = serialize_taxi_drt_dispatch(
            dispatch_state,
            float(selected["startSec"]),
        )

        emit(
            {
                "type": "recording",
                "status": "running",
                "backend": "sumo-taxi-device",
                "dispatchEngine": "taxi",
                "scope": selected["key"],
                "startSimSec": selected["startSec"],
                "endSimSec": runtime_end_sec,
                "serviceEndSimSec": selected["endSec"],
                "totalSteps": total_steps,
                "playbackRate": playback_rate,
                "demandSource": demand_source,
                "replacementPercent": replacement_percent,
                "replacement": initial_dispatch_payload["replacement"],
                "demand": initial_dispatch_payload["demand"],
                "dataFps": PLAYBACK_DATA_FPS,
                "chunkVisualFrames": frames_per_chunk,
                "chunkSimSeconds": frame_step_sec * visual_stride * frames_per_chunk,
                "frameStepSec": frame_step_sec,
                "visualStride": visual_stride,
            }
        )

        internal_step_index = 0
        while not stop_event.is_set() and float(connection.simulation.getTime()) < runtime_end_sec - 1e-9:
            step_started_at = time.perf_counter()
            connection.simulationStep()
            chunk_step_ms += (time.perf_counter() - step_started_at) * 1000
            sim_sec = round(float(connection.simulation.getTime()), 3)
            dispatch_started_at = time.perf_counter()
            update_taxi_drt_dispatch(connection, dispatch_state, sim_sec, selected)
            chunk_dispatch_ms += (time.perf_counter() - dispatch_started_at) * 1000
            should_emit_visual_frame = internal_step_index % visual_stride == 0
            recovery_complete = taxi_drt_recovery_complete(dispatch_state, sim_sec, selected)
            if recovery_complete:
                should_emit_visual_frame = True
            internal_step_index += 1
            if not should_emit_visual_frame and sim_sec < runtime_end_sec:
                continue

            frame_started_at = time.perf_counter()
            frame_profile: dict[str, float] = {}
            include_dispatch_requests = recorded_frames % PLAYBACK_DATA_FPS == 0
            frame = build_compact_sumo_frame(
                connection,
                sim_sec,
                traci_constants,
                net_offset,
                utm_zone,
                edge_line_shapes,
                subscribed_vehicle_ids,
                traffic_light_ids,
                frame_profile,
                dispatch_state,
                include_dispatch_requests,
                "taxi",
                playback_detail,
            )
            chunk_frame_ms += (time.perf_counter() - frame_started_at) * 1000
            chunk_vehicle_id_ms += frame_profile.get("vehicleIdMs", 0.0)
            chunk_vehicle_loop_ms += frame_profile.get("vehicleLoopMs", 0.0)
            chunk_traffic_light_ms += frame_profile.get("trafficLightMs", 0.0)
            chunk_vehicle_count += len(frame.get("vehicles") or frame.get("cabs") or []) + len(frame.get("bg") or [])
            chunk_frames.append(frame)

            if len(chunk_frames) >= frames_per_chunk or recovery_complete:
                emit_chunk()
            if recovery_complete:
                break

        emit_chunk()
        elapsed_sec = round(time.perf_counter() - started_at, 3)
        final_sim_sec = round(float(connection.simulation.getTime()), 3)

        # Sync cab states with the recovery outcome so the last visual frame
        # agrees with the audit (no "returning" rows next to a "returned" result).
        depot_edges = set(ROBOTAXI_DEPOT_ROUTE_EDGES)
        depot_state_changed = False
        for robotaxi in dispatch_state["robotaxis"].values():
            if (
                str(robotaxi.get("locationEdge")) in depot_edges
                and robotaxi.get("status") != "idle_at_depot"
            ):
                mark_robotaxi_depot_state(robotaxi, final_sim_sec)
                robotaxi["etaSec"] = None
                robotaxi["stopReason"] = None
                depot_state_changed = True
        if depot_state_changed and not stop_event.is_set():
            frame_profile = {}
            chunk_frames.append(
                build_compact_sumo_frame(
                    connection,
                    final_sim_sec,
                    traci_constants,
                    net_offset,
                    utm_zone,
                    edge_line_shapes,
                    subscribed_vehicle_ids,
                    traffic_light_ids,
                    frame_profile,
                    dispatch_state,
                    True,
                    "taxi",
                    playback_detail,
                )
            )
            emit_chunk()

        final_dispatch_payload = serialize_taxi_drt_dispatch(
            dispatch_state,
            final_sim_sec,
            include_requests=True,
        )
        final_audit = build_robotaxi_run_audit(dispatch_state, final_sim_sec, selected)
        if stop_event.is_set():
            emit(
                {
                    "type": "stopped",
                    "scope": selected["key"],
                    "recordedFrames": recorded_frames,
                    "elapsedSec": elapsed_sec,
                    "audit": final_audit,
                    "finalDispatch": final_dispatch_payload,
                }
            )
            return

        emit(
            {
                "type": "done",
                "scope": selected["key"],
                "simSec": final_sim_sec,
                "serviceEndSimSec": selected["endSec"],
                "chunks": chunk_index,
                "recordedFrames": recorded_frames,
                "elapsedSec": elapsed_sec,
                "audit": final_audit,
                "finalDispatch": final_dispatch_payload,
            }
        )
    except Exception as error:
        emit({"type": "error", "message": str(error)})
    finally:
        try:
            traci.switch(connection_label)
            traci.close(False)
        except Exception:
            pass
        unlink_with_retries(taxi_route_path)


def produce_sumo_playback_chunks(
    traci: Any,
    command: list[str],
    connection_label: str,
    selected: dict[str, Any],
    playback_rate: int,
    replacement_percent: int,
    demand_source: str,
    playback_detail: str,
    frame_step_sec: float,
    visual_stride: int,
    message_queue: asyncio.Queue[dict[str, Any]],
    event_loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    chunk_index = 0
    chunk_frames: list[dict[str, Any]] = []
    recorded_frames = 0
    started_at = time.perf_counter()
    frames_per_chunk = PLAYBACK_CHUNK_VISUAL_FRAMES
    chunk_started_at = time.perf_counter()
    chunk_step_ms = 0.0
    chunk_frame_ms = 0.0
    chunk_dispatch_ms = 0.0
    chunk_vehicle_id_ms = 0.0
    chunk_vehicle_loop_ms = 0.0
    chunk_traffic_light_ms = 0.0
    chunk_vehicle_count = 0

    def emit(payload: dict[str, Any]) -> None:
        future = asyncio.run_coroutine_threadsafe(message_queue.put(payload), event_loop)
        future.result()

    def emit_chunk() -> None:
        nonlocal chunk_index, chunk_frames, recorded_frames
        nonlocal chunk_started_at, chunk_step_ms, chunk_frame_ms, chunk_vehicle_count
        nonlocal chunk_dispatch_ms, chunk_vehicle_id_ms, chunk_vehicle_loop_ms, chunk_traffic_light_ms
        if not chunk_frames:
            return

        frame_count = len(chunk_frames)
        recorded_frames += len(chunk_frames)
        emit(
            {
                "type": "chunk",
                "scope": selected["key"],
                "chunkIndex": chunk_index,
                "playbackRate": playback_rate,
                "dataFps": PLAYBACK_DATA_FPS,
                "frameStepSec": frame_step_sec,
                "visualStride": visual_stride,
                "chunkVisualFrames": frames_per_chunk,
                "chunkSimSeconds": frame_step_sec * visual_stride * frames_per_chunk,
                "startSimSec": chunk_frames[0]["simSec"],
                "endSimSec": chunk_frames[-1]["simSec"],
                "frames": chunk_frames,
                "profile": {
                    "frames": frame_count,
                    "vehicles": chunk_vehicle_count,
                    "stepMs": round(chunk_step_ms, 2),
                    "dispatchMs": round(chunk_dispatch_ms, 2),
                    "frameMs": round(chunk_frame_ms, 2),
                    "vehicleIdMs": round(chunk_vehicle_id_ms, 2),
                    "vehicleLoopMs": round(chunk_vehicle_loop_ms, 2),
                    "trafficLightMs": round(chunk_traffic_light_ms, 2),
                    "chunkMs": round((time.perf_counter() - chunk_started_at) * 1000, 2),
                },
            }
        )
        chunk_index += 1
        chunk_frames = []
        chunk_started_at = time.perf_counter()
        chunk_step_ms = 0.0
        chunk_frame_ms = 0.0
        chunk_dispatch_ms = 0.0
        chunk_vehicle_id_ms = 0.0
        chunk_vehicle_loop_ms = 0.0
        chunk_traffic_light_ms = 0.0
        chunk_vehicle_count = 0

    try:
        traci.start(command, label=connection_label)
        connection = traci.getConnection(connection_label)
        traci_constants = traci.constants
        net_offset, utm_zone = load_sumo_projection(str(selected["net"]))
        edge_line_shapes = load_sumo_edge_line_shapes(str(selected["net"]))
        fleet_status = seed_robotaxi_depot_fleet(connection, selected)
        dispatch_state = create_robotaxi_dispatch_state(
            fleet_status,
            selected,
            replacement_percent,
            demand_source,
        )
        validate_robotaxi_dispatch_requests(connection, dispatch_state, selected)
        traffic_light_ids = list(connection.trafficlight.getIDList())
        for traffic_light_id in traffic_light_ids:
            connection.trafficlight.subscribe(
                traffic_light_id,
                [traci_constants.TL_RED_YELLOW_GREEN_STATE],
            )
        subscribed_vehicle_ids: set[str] = set()
        total_steps = int(round((selected["endSec"] - selected["startSec"]) / frame_step_sec))
        initial_dispatch_payload = serialize_robotaxi_dispatch(
            dispatch_state,
            float(selected["startSec"]),
        )

        emit(
            {
                "type": "recording",
                "status": "running",
                "scope": selected["key"],
                "startSimSec": selected["startSec"],
                "endSimSec": selected["endSec"],
                "totalSteps": total_steps,
                "playbackRate": playback_rate,
                "demandSource": demand_source,
                "replacementPercent": replacement_percent,
                "replacement": initial_dispatch_payload["replacement"],
                "demand": initial_dispatch_payload["demand"],
                "dataFps": PLAYBACK_DATA_FPS,
                "chunkVisualFrames": frames_per_chunk,
                "chunkSimSeconds": frame_step_sec * visual_stride * frames_per_chunk,
                "frameStepSec": frame_step_sec,
                "visualStride": visual_stride,
            }
        )

        internal_step_index = 0
        while not stop_event.is_set() and float(connection.simulation.getTime()) < selected["endSec"] - 1e-9:
            step_started_at = time.perf_counter()
            connection.simulationStep()
            chunk_step_ms += (time.perf_counter() - step_started_at) * 1000
            sim_sec = round(float(connection.simulation.getTime()), 3)
            dispatch_started_at = time.perf_counter()
            update_robotaxi_dispatch(connection, dispatch_state, sim_sec, selected)
            chunk_dispatch_ms += (time.perf_counter() - dispatch_started_at) * 1000
            should_emit_visual_frame = internal_step_index % visual_stride == 0
            internal_step_index += 1
            if not should_emit_visual_frame and sim_sec < selected["endSec"]:
                continue

            frame_started_at = time.perf_counter()
            frame_profile: dict[str, float] = {}
            include_dispatch_requests = recorded_frames % PLAYBACK_DATA_FPS == 0
            frame = build_compact_sumo_frame(
                connection,
                sim_sec,
                traci_constants,
                net_offset,
                utm_zone,
                edge_line_shapes,
                subscribed_vehicle_ids,
                traffic_light_ids,
                frame_profile,
                dispatch_state,
                include_dispatch_requests,
                "custom",
                playback_detail,
            )
            chunk_frame_ms += (time.perf_counter() - frame_started_at) * 1000
            chunk_vehicle_id_ms += frame_profile.get("vehicleIdMs", 0.0)
            chunk_vehicle_loop_ms += frame_profile.get("vehicleLoopMs", 0.0)
            chunk_traffic_light_ms += frame_profile.get("trafficLightMs", 0.0)
            chunk_vehicle_count += len(frame.get("vehicles") or frame.get("cabs") or []) + len(frame.get("bg") or [])
            chunk_frames.append(frame)

            if len(chunk_frames) >= frames_per_chunk or sim_sec >= selected["endSec"]:
                emit_chunk()

        emit_chunk()
        elapsed_sec = round(time.perf_counter() - started_at, 3)
        if stop_event.is_set():
            emit(
                {
                    "type": "stopped",
                    "scope": selected["key"],
                    "recordedFrames": recorded_frames,
                    "elapsedSec": elapsed_sec,
                }
            )
            return

        emit(
            {
                "type": "done",
                "scope": selected["key"],
                "simSec": selected["endSec"],
                "chunks": chunk_index,
                "recordedFrames": recorded_frames,
                "elapsedSec": elapsed_sec,
            }
        )
    except Exception as error:
        emit({"type": "error", "message": str(error)})
    finally:
        try:
            traci.switch(connection_label)
            traci.close(False)
        except Exception:
            pass


def active_vehicle_route_coordinates(
    connection: Any,
    vehicle_id: str,
    edge_line_shapes: dict[str, list[list[float]]],
    dispatch_state: dict[str, Any] | None = None,
) -> list[list[float]]:
    try:
        route_edges = [str(edge) for edge in connection.vehicle.getRoute(vehicle_id)]
        route_index = int(connection.vehicle.getRouteIndex(vehicle_id))
    except Exception:
        return []

    if not route_edges:
        return []
    route_index = max(0, min(route_index, len(route_edges) - 1))
    cache_key = (tuple(route_edges), route_index)
    if dispatch_state is not None:
        route_cache = dispatch_state.setdefault("activeRouteCoordinatesCache", {})
        cached = route_cache.get(vehicle_id)
        if cached and cached.get("key") == cache_key:
            return cached["coordinates"]

    remaining_edges = route_edges[route_index:]
    coordinates: list[list[float]] = []
    for edge_id in remaining_edges:
        shape = edge_line_shapes.get(edge_id)
        if not shape:
            continue
        for point in shape:
            if coordinates and point == coordinates[-1]:
                continue
            coordinates.append(point)

    route_coordinates = [[round(float(lon), 7), round(float(lat), 7)] for lon, lat in coordinates[:240]]
    if dispatch_state is not None:
        route_cache = dispatch_state.setdefault("activeRouteCoordinatesCache", {})
        route_cache[vehicle_id] = {"key": cache_key, "coordinates": route_coordinates}
    return route_coordinates


def build_compact_sumo_frame(
    connection: Any,
    sim_sec: float,
    traci_constants: Any,
    net_offset: tuple[float, float],
    utm_zone: int,
    edge_line_shapes: dict[str, list[list[float]]],
    subscribed_vehicle_ids: set[str],
    traffic_light_ids: list[str],
    profile: dict[str, float],
    dispatch_state: dict[str, Any] | None = None,
    include_dispatch_requests: bool = True,
    dispatch_engine: str = "custom",
    playback_detail: str = DEFAULT_PLAYBACK_DETAIL,
) -> dict[str, Any]:
    vehicles = []
    vehicle_id_started_at = time.perf_counter()
    if playback_detail == "public":
        # Public frames are slim but self-sufficient: request state is present
        # every frame (as events + active markers), not on a 1-in-N stride.
        include_dispatch_requests = True
    all_vehicle_ids = set(connection.vehicle.getIDList())
    if playback_detail == "public":
        robotaxi_ids = {vehicle_id for vehicle_id in all_vehicle_ids if vehicle_id.startswith(ROBOTAXI_ID_PREFIX)}
        background_ids = sorted(
            (vehicle_id for vehicle_id in all_vehicle_ids if vehicle_id not in robotaxi_ids),
            key=stable_sample_key,
        )[:PUBLIC_BACKGROUND_VEHICLE_LIMIT]
        vehicle_ids = robotaxi_ids.union(background_ids)
    else:
        vehicle_ids = all_vehicle_ids
    vehicle_subscription_vars = [
        traci_constants.VAR_POSITION,
        traci_constants.VAR_ANGLE,
    ]
    for variable_name in ("VAR_SPEED", "VAR_LANE_ID", "VAR_ROAD_ID"):
        variable_id = getattr(traci_constants, variable_name, None)
        if variable_id is not None:
            vehicle_subscription_vars.append(variable_id)
    for vehicle_id in vehicle_ids - subscribed_vehicle_ids:
        connection.vehicle.subscribe(vehicle_id, vehicle_subscription_vars)
    subscribed_vehicle_ids.intersection_update(vehicle_ids)
    subscribed_vehicle_ids.update(vehicle_ids)
    profile["vehicleIdMs"] = (time.perf_counter() - vehicle_id_started_at) * 1000

    vehicle_loop_started_at = time.perf_counter()
    vehicle_results = connection.vehicle.getAllSubscriptionResults()
    for vehicle_id in vehicle_ids:
        vehicle_data = vehicle_results.get(vehicle_id)
        if not vehicle_data:
            continue
        position = vehicle_data.get(traci_constants.VAR_POSITION)
        if position is None:
            continue
        x, y = position
        lon, lat = sumo_xy_to_lonlat(float(x), float(y), net_offset, utm_zone)
        kind = "robotaxi" if vehicle_id.startswith(ROBOTAXI_ID_PREFIX) else "background"
        robotaxi_state = None
        if kind == "robotaxi" and dispatch_state:
            robotaxi_state = dispatch_state["robotaxis"].get(vehicle_id, {}).get("status")
        speed_var = getattr(traci_constants, "VAR_SPEED", None)
        lane_var = getattr(traci_constants, "VAR_LANE_ID", None)
        road_var = getattr(traci_constants, "VAR_ROAD_ID", None)
        vehicle = {
            "id": vehicle_id,
            "lon": round(float(lon), 7),
            "lat": round(float(lat), 7),
            "angle": round(float(vehicle_data.get(traci_constants.VAR_ANGLE, 0)), 2),
            "kind": kind,
            "state": robotaxi_state,
        }
        if speed_var is not None and speed_var in vehicle_data:
            vehicle["speed"] = round(float(vehicle_data.get(speed_var, 0.0)), 2)
        if playback_detail != "public":
            if lane_var is not None and lane_var in vehicle_data:
                vehicle["lane"] = str(vehicle_data.get(lane_var) or "")
            if road_var is not None and road_var in vehicle_data:
                vehicle["edge"] = str(vehicle_data.get(road_var) or "")
        if include_dispatch_requests and kind == "robotaxi" and robotaxi_state in {
            "en_route_pickup",
            "with_passenger",
            "returning_to_depot",
        }:
            route_coordinates = active_vehicle_route_coordinates(
                connection,
                vehicle_id,
                edge_line_shapes,
                dispatch_state,
            )
            if playback_detail == "public" and dispatch_state is not None:
                # Route polylines only when they change; the frontend keeps the
                # last one per cab, so identical resends are pure payload waste.
                cache_entry = dispatch_state.get("activeRouteCoordinatesCache", {}).get(vehicle_id)
                route_key = cache_entry.get("key") if cache_entry else None
                emitted_keys = dispatch_state.setdefault("emittedRouteKeyByVehicle", {})
                if route_coordinates and route_key is not None and emitted_keys.get(vehicle_id) != route_key:
                    vehicle["routeCoordinates"] = route_coordinates
                    emitted_keys[vehicle_id] = route_key
            elif route_coordinates:
                vehicle["routeCoordinates"] = route_coordinates
        elif kind == "robotaxi" and dispatch_state is not None:
            dispatch_state.get("emittedRouteKeyByVehicle", {}).pop(vehicle_id, None)
        vehicles.append(vehicle)

    # Parked vehicles drop out of SUMO's vehicle list, which would make
    # staged/parked cybercabs vanish from the map. Cache their last position
    # and emit a synthetic stationary vehicle instead.
    if dispatch_state:
        seen_robotaxi_ids = {
            vehicle["id"] for vehicle in vehicles if vehicle.get("kind") == "robotaxi"
        }
        for vehicle in vehicles:
            if vehicle.get("kind") != "robotaxi":
                continue
            robotaxi = dispatch_state["robotaxis"].get(vehicle["id"])
            if robotaxi is not None:
                robotaxi["lastLon"] = vehicle["lon"]
                robotaxi["lastLat"] = vehicle["lat"]
                robotaxi["lastAngle"] = vehicle["angle"]
        for vehicle_id, robotaxi in dispatch_state["robotaxis"].items():
            if vehicle_id in seen_robotaxi_ids:
                continue
            last_lon = robotaxi.get("lastLon")
            last_lat = robotaxi.get("lastLat")
            if last_lon is None or last_lat is None:
                continue
            vehicles.append(
                {
                    "id": vehicle_id,
                    "lon": last_lon,
                    "lat": last_lat,
                    "angle": robotaxi.get("lastAngle", 0.0),
                    "kind": "robotaxi",
                    "state": robotaxi.get("status"),
                    "speed": 0.0,
                    "parked": True,
                }
            )
    profile["vehicleLoopMs"] = (time.perf_counter() - vehicle_loop_started_at) * 1000

    traffic_light_started_at = time.perf_counter()
    traffic_lights = compact_traffic_light_states(
        connection,
        traffic_light_ids,
        traci_constants,
    )
    profile["trafficLightMs"] = (time.perf_counter() - traffic_light_started_at) * 1000

    dispatch_payload = (
        serialize_taxi_drt_dispatch(
            dispatch_state,
            sim_sec,
            include_requests=include_dispatch_requests,
        )
        if dispatch_engine == "taxi"
        else serialize_robotaxi_dispatch(
            dispatch_state,
            sim_sec,
            include_requests=include_dispatch_requests,
        )
    )

    contract_fields = build_contract_frame_fields(dispatch_payload, vehicles, sim_sec)
    if playback_detail == "public" and dispatch_state is not None:
        return build_public_slim_frame(
            dispatch_state,
            dispatch_payload,
            contract_fields,
            vehicles,
            traffic_lights,
            sim_sec,
        )
    return {
        "simSec": sim_sec,
        "vehicles": vehicles,
        "robotaxiCount": sum(1 for vehicle in vehicles if vehicle.get("kind") == "robotaxi"),
        "trafficLights": traffic_lights,
        "dispatch": dispatch_payload,
        **contract_fields,
    }


PUBLIC_CLOSED_MARKER_LINGER_SEC = 30.0


def build_public_slim_frame(
    dispatch_state: dict[str, Any],
    dispatch_payload: dict[str, Any],
    contract_fields: dict[str, Any],
    vehicles: list[dict[str, Any]],
    traffic_lights: dict[str, str],
    sim_sec: float,
) -> dict[str, Any]:
    """Slim per-frame payload for the public replay.

    Contract: full traffic-light snapshot on the first frame then deltas;
    request lifecycle as events (frontend accumulates the feed); markers only
    for active requests plus a short linger window after closure; no raw
    dispatch registry (94% of the legacy frame bytes).
    """
    request_events: list[dict[str, Any]] = []
    last_status_by_id = dispatch_state.setdefault("lastEmittedRequestStatusById", {})
    for request in dispatch_payload.get("requests", []):
        status = str(request.get("status") or "")
        if status == "scheduled":
            continue
        request_id = str(request.get("id") or "")
        previous_status = last_status_by_id.get(request_id)
        if previous_status == status:
            continue
        last_status_by_id[request_id] = status
        event: dict[str, Any] = {
            "id": request_id,
            "status": status,
            "atSec": sim_sec,
            "cab": request.get("assignedVehicleId"),
            "waitSec": request.get("waitSec"),
        }
        if previous_status is None:
            event["pickup"] = request.get("pickup")
            event["dropoff"] = request.get("dropoff")
            event["requestedAtSec"] = request.get("requestedAtSec")
            event["mode"] = request.get("sourceMode")
        request_events.append(event)

    markers: list[dict[str, Any]] = []
    for request in dispatch_payload.get("requests", []):
        status = str(request.get("status") or "")
        marker_state = request_marker_state(status)
        if not marker_state:
            continue
        if marker_state in {"completed", "expired"}:
            closed_at = request.get("closedAtSec") or request.get("completedAtSec") or request.get("expiredAtSec")
            if closed_at is None or sim_sec - float(closed_at) > PUBLIC_CLOSED_MARKER_LINGER_SEC:
                continue
        pickup = request.get("pickup") if isinstance(request.get("pickup"), dict) else {}
        if "lon" not in pickup or "lat" not in pickup:
            continue
        marker = {
            "id": request.get("id"),
            "state": status,
            "markerState": marker_state,
            "lon": pickup.get("lon"),
            "lat": pickup.get("lat"),
            "assignedCabId": request.get("assignedVehicleId"),
            "requestedAtSec": request.get("requestedAtSec"),
            "closedAtSec": request.get("closedAtSec"),
        }
        dropoff = request.get("dropoff") if isinstance(request.get("dropoff"), dict) else {}
        if "lon" in dropoff and "lat" in dropoff:
            marker["dropoffLon"] = dropoff.get("lon")
            marker["dropoffLat"] = dropoff.get("lat")
        markers.append(marker)

    # Background traffic as compact arrays [shortId, lon, lat, angle] with
    # per-recording interned integer ids; robotaxis stay full objects (10 of
    # them, and the UI needs their state/route detail).
    bg_id_by_full = dispatch_state.setdefault("publicBgIdByFullId", {})
    cabs: list[dict[str, Any]] = []
    background_rows: list[list[Any]] = []
    for vehicle in vehicles:
        if vehicle.get("kind") == "robotaxi":
            cabs.append(vehicle)
            continue
        full_id = str(vehicle["id"])
        short_id = bg_id_by_full.get(full_id)
        if short_id is None:
            short_id = len(bg_id_by_full) + 1
            bg_id_by_full[full_id] = short_id
        background_rows.append(
            [
                short_id,
                round(float(vehicle["lon"]), 5),
                round(float(vehicle["lat"]), 5),
                int(round(float(vehicle.get("angle") or 0.0))),
            ]
        )

    frame: dict[str, Any] = {
        "simSec": sim_sec,
        "cabs": cabs,
        "bg": background_rows,
        **contract_fields,
        "mapRequests": markers,
        "requestEvents": request_events,
    }
    frame.pop("mapVehicles", None)
    frame["cabRows"] = [
        {
            key: row.get(key)
            for key in ("id", "state", "battery", "speedKph", "etaSec", "requestId", "lon", "lat", "heading")
            if row.get(key) is not None
        }
        for row in contract_fields.get("cabRows", [])
    ]

    # City-scale scenarios stream no TL state at all: the frontend draws no
    # signal layer there, and 2.3k actuated signals delta-churned to 68% of
    # the replay bytes (250 MB raw) before this gate existed.
    if traffic_lights:
        last_traffic_lights = dispatch_state.setdefault("lastEmittedTrafficLightStates", {})
        if not last_traffic_lights:
            frame["trafficLights"] = traffic_lights
            last_traffic_lights.update(traffic_lights)
        else:
            delta = {
                light_id: state
                for light_id, state in traffic_lights.items()
                if last_traffic_lights.get(light_id) != state
            }
            if delta:
                frame["trafficLightsDelta"] = delta
                last_traffic_lights.update(delta)
    return frame


def compact_traffic_light_states(
    connection: Any,
    traffic_light_ids: list[str] | None = None,
    traci_constants: Any | None = None,
) -> dict[str, str]:
    if traci_constants is not None:
        results = connection.trafficlight.getAllSubscriptionResults()
        return {
            traffic_light_id: str(
                results.get(traffic_light_id, {}).get(
                    traci_constants.TL_RED_YELLOW_GREEN_STATE,
                    "",
                )
            )
            for traffic_light_id in (traffic_light_ids or results.keys())
        }

    ids = traffic_light_ids if traffic_light_ids is not None else connection.trafficlight.getIDList()
    return {
        traffic_light_id: connection.trafficlight.getRedYellowGreenState(traffic_light_id)
        for traffic_light_id in ids
    }


def build_sumo_frame(
    connection: Any,
    sim_sec: int,
    is_running: bool,
    delay_ms: int,
) -> dict[str, Any]:
    vehicle_ids = list(connection.vehicle.getIDList())
    vehicles = []
    traffic_lights = live_traffic_light_states(connection)

    for vehicle_id in vehicle_ids:
        x, y = connection.vehicle.getPosition(vehicle_id)
        lon, lat = connection.simulation.convertGeo(x, y)
        vehicle = {
            "id": vehicle_id,
            "lon": lon,
            "lat": lat,
            "angle": round(float(connection.vehicle.getAngle(vehicle_id)), 3),
            "speed": round(float(connection.vehicle.getSpeed(vehicle_id)), 3),
            "lane": connection.vehicle.getLaneID(vehicle_id),
            "route": connection.vehicle.getRouteID(vehicle_id),
            "kind": "robotaxi" if vehicle_id.startswith(ROBOTAXI_ID_PREFIX) else "background",
        }
        vehicles.append(vehicle)

    return {
        "type": "frame",
        "simSec": sim_sec,
        "vehicles": vehicles,
        "vehicleCount": len(vehicles),
        "robotaxiCount": sum(1 for vehicle in vehicles if vehicle.get("kind") == "robotaxi"),
        "departed": list(connection.simulation.getDepartedIDList()),
        "arrived": list(connection.simulation.getArrivedIDList()),
        "trafficLights": traffic_lights,
        "running": is_running,
        "delayMs": delay_ms,
    }


def format_sim_status(status: str, elapsed_sec: float | None = None) -> str:
    if status == "finished" and elapsed_sec is not None:
        return f"Finished in {elapsed_sec:.2f}s"
    if status == "running":
        return "Running"
    if status == "stopped":
        return "Stopped"
    if status == "stepped":
        return "Stepped"
    if status == "step-unavailable":
        return "Step requires TraCI"
    if status == "failed":
        return "Failed"
    return "Idle"


def live_traffic_light_states(connection: Any) -> dict[str, dict[str, Any]]:
    states = {}
    for traffic_light_id in connection.trafficlight.getIDList():
        raw_state = connection.trafficlight.getRedYellowGreenState(traffic_light_id)
        states[traffic_light_id] = {
            "state": raw_state,
            "display": display_traffic_light_state(raw_state),
            "phase": int(connection.trafficlight.getPhase(traffic_light_id)),
        }
    return states


def display_traffic_light_state(raw_state: str) -> str:
    if any(char in raw_state for char in "gG"):
        return "green"
    if any(char in raw_state for char in "yY"):
        return "yellow"
    if any(char in raw_state for char in "rRuUsS"):
        return "red"
    return "off"


def clamp_delay_ms(value: Any) -> int:
    try:
        delay_ms = int(float(value))
    except (TypeError, ValueError):
        delay_ms = DEFAULT_SUMO_DELAY_MS

    return max(0, min(delay_ms, MAX_SUMO_DELAY_MS))


def parse_delay_ms(websocket: WebSocket) -> int:
    configured_delay_ms = os.getenv("SUMO_DELAY_MS")
    raw_delay_ms = websocket.query_params.get("delayMs")
    if raw_delay_ms is not None:
        return clamp_delay_ms(raw_delay_ms)
    if configured_delay_ms is not None:
        return clamp_delay_ms(configured_delay_ms)
    return DEFAULT_SUMO_DELAY_MS
