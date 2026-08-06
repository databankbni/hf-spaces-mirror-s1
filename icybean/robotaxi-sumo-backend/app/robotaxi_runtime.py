"""Robotaxi runtime contract and controller scaffolding.

This module is intentionally pure: it does not create SUMO vehicles, move cabs,
or read live scenario files. Runtime activation must be gated by validated
package and demand data plus real TraCI controller wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SCENARIO_KEY = "charlottenburg-moabit-tiergarten"
SERVICE_START_SEC = 64_800
SERVICE_END_SEC = 75_600
FLEET_SIZE = 5
REQUEST_EXPIRY_SEC = 600
ROBOTAXI_READY_STATUS = "ready"
ROBOTAXI_CONTROLLER_READY = False
ROBOTAXI_CONTROLLER_NOTE = "Backend robotaxi run controller is not wired yet."

ROBOTAXI_PHASES = [
    "unavailable",
    "idle",
    "running",
    "winding_down",
    "returning_to_depot",
    "complete",
    "error",
]
ROBOTAXI_STATUS_FIELDS = ["timeSec", "timeLabel", "cabsActive", "ridesServed", "phase"]

CAB_STATES = [
    "staged",
    "idle",
    "en_route_pickup",
    "waiting_pickup",
    "with_passenger",
    "returning_to_depot",
    "at_depot",
    "out_of_service",
]
REQUEST_STATES = ["scheduled", "open", "assigned", "onboard", "completed", "expired", "rejected"]


@dataclass(frozen=True)
class RuntimeConfig:
    scope: str
    fleet_size: int
    start_sec: int
    end_sec: int
    request_expiry_sec: int
    depot_edge: str | None


@dataclass(frozen=True)
class CabSnapshot:
    id: str
    state: str
    lon: float | None = None
    lat: float | None = None
    heading: float | None = None
    speed_kph: float | None = None
    eta_sec: int | None = None
    target: str | None = None
    stop_reason: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class RequestSnapshot:
    id: str
    state: str
    depart_sec: int
    mode: str
    pickup_edge: str
    dropoff_edge: str
    origin_lon: float | None = None
    origin_lat: float | None = None
    destination_lon: float | None = None
    destination_lat: float | None = None
    assigned_cab_id: str | None = None


@dataclass(frozen=True)
class RouteEstimate:
    cab_id: str
    request_id: str
    eta_to_pickup_sec: float
    pickup_to_dropoff_sec: float
    route_distance_m: float | None = None


def format_clock_label(sim_sec: int | float | None) -> str | None:
    if sim_sec is None:
        return None
    total_minutes = int(float(sim_sec)) // 60
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def config_from_scenario(scenario: dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        scope=str(scenario["key"]),
        fleet_size=int(scenario.get("fleetSize") or FLEET_SIZE),
        start_sec=int(scenario.get("startSec", SERVICE_START_SEC)),
        end_sec=int(scenario.get("endSec", SERVICE_END_SEC)),
        request_expiry_sec=int(scenario.get("requestExpirySec", REQUEST_EXPIRY_SEC)),
        depot_edge=scenario.get("depotEdge"),
    )


def cab_display_state(raw_state: str) -> str:
    return {
        "staged": "Staged",
        "idle": "Available",
        "en_route_pickup": "To pickup",
        "waiting_pickup": "Waiting",
        "with_passenger": "On trip",
        "returning_to_depot": "Returning",
        "at_depot": "Depot",
        "out_of_service": "Unavailable",
    }.get(raw_state, "Unknown")


def request_display_state(raw_state: str) -> str:
    return {
        "scheduled": "Scheduled",
        "open": "Open",
        "assigned": "Accepted",
        "onboard": "On trip",
        "completed": "Served",
        "expired": "Expired",
        "rejected": "Rejected",
    }.get(raw_state, "Unknown")


def initial_cabs(config: RuntimeConfig) -> list[CabSnapshot]:
    return [
        CabSnapshot(
            id=f"cybercab-{index:02d}",
            state="staged",
            stop_reason="awaiting_validated_demand",
        )
        for index in range(1, config.fleet_size + 1)
    ]


def cab_row(cab: CabSnapshot) -> dict[str, Any]:
    return {
        "id": cab.id,
        "state": cab.state,
        "label": cab_display_state(cab.state),
        "speedKph": cab.speed_kph,
        "etaSec": cab.eta_sec,
        "target": cab.target,
        "stopReason": cab.stop_reason,
        "requestId": cab.request_id,
        "lon": cab.lon,
        "lat": cab.lat,
        "heading": cab.heading,
    }


def cab_map_vehicle(cab: CabSnapshot) -> dict[str, Any] | None:
    if cab.lon is None or cab.lat is None:
        return None
    return {
        "id": cab.id,
        "kind": "cybercab",
        "lon": cab.lon,
        "lat": cab.lat,
        "heading": cab.heading,
        "state": cab.state,
        "label": cab_display_state(cab.state),
    }


def request_marker(request: RequestSnapshot) -> dict[str, Any]:
    marker_state = "accepted" if request.state in {"assigned", "onboard", "completed"} else "open"
    return {
        "id": request.id,
        "state": request.state,
        "displayState": request_display_state(request.state),
        "markerState": marker_state,
        "departSec": request.depart_sec,
        "origin": {"lon": request.origin_lon, "lat": request.origin_lat},
        "destination": {"lon": request.destination_lon, "lat": request.destination_lat},
        "pickupEdge": request.pickup_edge,
        "dropoffEdge": request.dropoff_edge,
        "assignedCabId": request.assigned_cab_id,
    }


def request_counts(requests: list[RequestSnapshot]) -> dict[str, int]:
    counts = {state: 0 for state in REQUEST_STATES}
    for request in requests:
        counts[request.state] = counts.get(request.state, 0) + 1
    counts["total"] = len(requests)
    return counts


def cabs_active(cabs: list[CabSnapshot]) -> int:
    return sum(1 for cab in cabs if cab.state not in {"staged", "at_depot", "out_of_service"})


def rides_served(requests: list[RequestSnapshot]) -> int:
    return sum(1 for request in requests if request.state == "completed")


def status_frame(
    config: RuntimeConfig,
    *,
    phase: str,
    time_sec: int | float | None = None,
    cabs: list[CabSnapshot] | None = None,
    requests: list[RequestSnapshot] | None = None,
    final_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frame_cabs = cabs or initial_cabs(config)
    frame_requests = requests or []
    selected_time_sec = config.start_sec if time_sec is None else time_sec
    safe_phase = phase if phase in ROBOTAXI_PHASES else "error"
    vehicles = [vehicle for vehicle in (cab_map_vehicle(cab) for cab in frame_cabs) if vehicle]
    return {
        "type": "status",
        "scope": config.scope,
        "timeSec": selected_time_sec,
        "timeLabel": format_clock_label(selected_time_sec),
        "phase": safe_phase,
        "cabsActive": cabs_active(frame_cabs),
        "ridesServed": rides_served(frame_requests),
        "requestCounts": request_counts(frame_requests),
        "cabRows": [cab_row(cab) for cab in frame_cabs],
        "mapVehicles": vehicles,
        "mapRequests": [request_marker(request) for request in frame_requests],
        "totals": {
            "totalDemand": len(frame_requests),
            "ridesServed": rides_served(frame_requests),
            "expiredRequests": sum(1 for request in frame_requests if request.state == "expired"),
            "rejectedRequests": sum(1 for request in frame_requests if request.state == "rejected"),
            "cabsReturned": sum(1 for cab in frame_cabs if cab.state == "at_depot"),
        },
        "finalAudit": final_audit,
    }


def final_audit_payload(config: RuntimeConfig, cabs: list[CabSnapshot], requests: list[RequestSnapshot]) -> dict[str, Any]:
    return {
        "scope": config.scope,
        "timeSec": config.end_sec,
        "timeLabel": format_clock_label(config.end_sec),
        "phase": "complete",
        "ridesServed": rides_served(requests),
        "totalDemand": len(requests),
        "expiredRequests": sum(1 for request in requests if request.state == "expired"),
        "rejectedRequests": sum(1 for request in requests if request.state == "rejected"),
        "cabsReturned": sum(1 for cab in cabs if cab.state == "at_depot"),
        "source": "backend-controller-audit",
    }


def can_accept_new_assignments(now_sec: int | float, config: RuntimeConfig) -> bool:
    return config.start_sec <= float(now_sec) < config.end_sec


def is_request_expired(request: RequestSnapshot, now_sec: int | float, config: RuntimeConfig) -> bool:
    return float(now_sec) - request.depart_sec > config.request_expiry_sec


def assignment_score(
    request: RequestSnapshot,
    estimate: RouteEstimate,
    now_sec: int | float,
    config: RuntimeConfig,
) -> float | None:
    if request.state != "open":
        return None
    if not can_accept_new_assignments(now_sec, config):
        return None
    projected_wait = float(now_sec) - request.depart_sec + estimate.eta_to_pickup_sec
    if projected_wait > config.request_expiry_sec:
        return None
    route_distance = estimate.route_distance_m or 0.0
    return estimate.eta_to_pickup_sec * 2.0 + estimate.pickup_to_dropoff_sec + route_distance / 50.0


def choose_assignments(
    cabs: list[CabSnapshot],
    requests: list[RequestSnapshot],
    estimates: list[RouteEstimate],
    now_sec: int | float,
    config: RuntimeConfig,
) -> list[dict[str, Any]]:
    available_cab_ids = {
        cab.id for cab in cabs if cab.state in {"staged", "idle"} and cab.lon is not None and cab.lat is not None
    }
    estimate_by_pair = {(estimate.cab_id, estimate.request_id): estimate for estimate in estimates}
    candidates: list[tuple[float, str, str, RouteEstimate]] = []
    for cab_id in available_cab_ids:
        for request in requests:
            estimate = estimate_by_pair.get((cab_id, request.id))
            if estimate is None:
                continue
            score = assignment_score(request, estimate, now_sec, config)
            if score is not None:
                candidates.append((score, cab_id, request.id, estimate))

    assignments = []
    used_cabs: set[str] = set()
    used_requests: set[str] = set()
    for score, cab_id, request_id, estimate in sorted(candidates, key=lambda item: item[0]):
        if cab_id in used_cabs or request_id in used_requests:
            continue
        assignments.append(
            {
                "cabId": cab_id,
                "requestId": request_id,
                "score": round(score, 3),
                "etaToPickupSec": estimate.eta_to_pickup_sec,
                "pickupToDropoffSec": estimate.pickup_to_dropoff_sec,
            }
        )
        used_cabs.add(cab_id)
        used_requests.add(request_id)
    return assignments


def phase_for_run(
    now_sec: int | float,
    config: RuntimeConfig,
    *,
    can_start: bool,
    active_rides: int = 0,
    returning_cabs: int = 0,
) -> str:
    if not can_start:
        return "unavailable"
    if float(now_sec) < config.start_sec:
        return "idle"
    if float(now_sec) < config.end_sec:
        return "running"
    if active_rides > 0:
        return "winding_down"
    if returning_cabs > 0:
        return "returning_to_depot"
    return "complete"
