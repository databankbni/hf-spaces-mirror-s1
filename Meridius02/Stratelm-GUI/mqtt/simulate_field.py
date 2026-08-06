"""
simulate_field.py — physically consistent telemetry simulator for the Antasena SEM car.

Matches the REAL MCU schema seen on race day (attempts 2-4, 2026-07-13/14):
payload keys `Batt Voltage, Battery Current, Velocity, Distance, H2 Leak,
PowerW, EnergiWh, kmPerkWh, Time(s)` published as JSON on topic
`gabungan_datasensor` at ~3.2 Hz. The car is a battery EV now — no fuel cell.

Signatures of the real logger that are reproduced here:
  - Distance is METERS, quantized to the wheel circumference (1.57 m steps)
  - Velocity is km/h, quantized to 0.097968 km/h (wheel pulse counting)
  - PowerW = Batt Voltage * Battery Current exactly, 7 significant figures
  - EnergiWh is the cumulative integral of PowerW since MCU boot
  - kmPerkWh is CUMULATIVE efficiency (total Distance / total EnergiWh since
    boot), NOT instantaneous — matches attempt 2 row 1: 17.27 m / 0.247 Wh
  - Time(s) is integer MCU uptime; ~3 rows share each second (low-res clock)
  - logging starts tens of seconds after boot, sometimes with the car already
    moving (attempt 2 first row: t=44 s, v=9.7 km/h, 0.247 Wh already burned)
  - battery sag: ~36.6 V open-circuit, ~0.37 ohm (36.5 V idle -> 34.8 V @ 4.7 A)
  - burn-and-coast between ~22 and ~33.5 km/h, burn ~150 W / glide ~3 W aux

Worst-case field faults are injected at the SEND layer only — the internal
state is never corrupted, exactly like a real car whose sensors glitch while
the car itself keeps driving:
  - packet loss            (row never sent -> Time(s) gap)
  - network latency        (2-5 s stall -> Time(s) gap)
  - sensor spike           (Velocity 999.9)
  - velocity zero-dropout  (0.0 sent while the car is moving — 11 of these
                            were found in the real attempt 2 data)
  - QoS1 duplicate         (same payload delivered twice)

Usage:
    python simulate_field.py                     # publish live to MQTT broker
    python simulate_field.py --gps                # also publish GPS on the gps topic
    python simulate_field.py --offline 1000      # write 1000 rows straight to CSV
    python simulate_field.py --offline 1000 -o data/race_day/exampleAttempt/sim_attempt.csv

Offline output goes to data/race_day/exampleAttempt/ by default — simulated
files must NEVER be written into a real attempt_XX folder.

GPS (--gps): the real car's electrical/motion telemetry (this file's default
behavior) and its GPS fix are two SEPARATE MQTT topics/publishers in the real
rig (see mqtt/log.py's TOPICS list) -- a session with only the car topic and
no GPS fix is the common case, not an edge case, so Stratelm-GUI's Live
Telemetry / Strategy tabs must degrade gracefully (flag has_gps=false) rather
than assume location data exists. --gps opts into replaying a synthetic GPS
trace on a second thread/topic so the round-trip can be exercised end-to-end
too -- see GpsReplay below for how that trace is built.

--track TRACK_ID (optional): which registered track (data/tracks.json) to
replay GPS against; defaults to the first/only registered track, falling
back further to digital_twin.track's own module-level CSV constants if the
registry file isn't found, so this script still runs standalone.
"""

import argparse
import json
import math
import os
import random
import threading
import time

import numpy as np

BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC = "gabungan_datasensor"
GPS_TOPIC = "race/falcon/gps"
TRACKS_JSON = os.path.join(os.path.dirname(__file__), "..", "data", "tracks.json")


def resolve_track_paths(track_id=None):
    """Resolve a track's coordinate/turns/edges CSVs to absolute paths under
    the digital_twin physics package's OWN root -- that's what those CSVs'
    relative paths (both digital_twin.track's module constants and this
    repo's data/tracks.json entries) are written against, not mqtt/'s own
    location. This is what used to be wrong: the old hardcoded path resolved
    relative to this file, into Stratelm-GUI-Repo/data/, where the track
    coordinate CSV doesn't exist -- GpsReplay() raised FileNotFoundError
    inside a daemon thread with stdout/stderr piped to DEVNULL by
    SimulatorManager, so GPS silently never published at all."""
    import digital_twin
    import digital_twin.track as track_mod

    physics_root = os.path.dirname(os.path.dirname(os.path.abspath(digital_twin.__file__)))

    track = None
    if os.path.isfile(TRACKS_JSON):
        try:
            with open(TRACKS_JSON, "r") as f:
                tracks = json.load(f)
            if track_id and track_id in tracks:
                track = tracks[track_id]
            elif tracks:
                track = next(iter(tracks.values()))
        except (json.JSONDecodeError, OSError):
            track = None

    if track:
        coords = os.path.join(physics_root, track["coordinates_csv"])
        turns = os.path.join(physics_root, track["turns_csv"])
        edges = os.path.join(physics_root, track["edges_csv"])
    else:
        coords = os.path.join(physics_root, track_mod.COORDINATES_CSV)
        turns = os.path.join(physics_root, track_mod.TURNS_CSV)
        edges = os.path.join(physics_root, track_mod.EDGES_CSV)
    return coords, turns, edges

FIELDS = ["Batt Voltage", "Battery Current", "Velocity", "Distance",
          "H2 Leak", "PowerW", "EnergiWh", "kmPerkWh", "Time(s)"]


def _sig7(x):
    """Reproduce the MCU's 7-significant-figure float printing
    (35.91245, 93.74679, 127.3089, 0.247487...)."""
    return float(f"{x:.7g}")


class FalconSimulator:
    """Stateful physics model of the car. step(dt) advances it and returns
    one clean telemetry sample (faults are applied elsewhere)."""

    # vehicle constants (SEM prototype class, battery EV)
    MASS = 120.0          # kg, car + driver
    CRR = 0.004           # rolling resistance coefficient
    CDA = 0.05            # drag area Cd*A, m^2 (SEM bodywork is very slippery)
    RHO = 1.2             # air density
    G = 9.81
    BURN_POWER = 148.0    # W electrical during a burn (real burns: 130-165 W)
    DRIVE_EFF = 0.85      # electrical -> wheel efficiency
    F_MAX = 30.0          # N, wheel force cap (move-off from standstill)
    AUX_POWER = 2.9       # W, electronics baseline (real glide: ~0.08 A)
    BATT_OCV = 36.6       # V, battery open-circuit voltage
    BATT_R = 0.37         # ohm, internal resistance (sag seen in attempt 2)
    BURN_HI = 33.5 / 3.6  # m/s, coast starts here (real max: 34.0 km/h)
    BURN_LO = 22.0 / 3.6  # m/s, burn starts here

    # sensor quantization (measured from attempts 2-4)
    WHEEL_C = 1.57        # m, distance advances in whole wheel circumferences
    VEL_Q = 0.097968      # km/h, velocity pulse-counting step

    def __init__(self):
        self.v = 0.0                    # m/s, true velocity
        self.dist_m = 0.0               # m, true distance
        self.energy = 0.0               # Wh, since MCU boot
        self.time_s = 0.0               # s, MCU uptime
        self.burning = True
        # the driver launches the car some tens of seconds after MCU boot
        self.drive_start = random.uniform(10.0, 45.0)

    def step(self, dt):
        # driver: burn-and-coast between the two speed thresholds
        if self.burning and self.v >= self.BURN_HI:
            self.burning = False
        elif not self.burning and self.v <= self.BURN_LO:
            self.burning = True
        driving = self.time_s >= self.drive_start and self.burning

        p_drive = self.BURN_POWER + random.gauss(0, 4.0) if driving else 0.0
        f_drive = min(p_drive * self.DRIVE_EFF / max(self.v, 0.5), self.F_MAX)

        f_resist = self.MASS * self.G * self.CRR + 0.5 * self.RHO * self.CDA * self.v ** 2
        accel = (f_drive - f_resist) / self.MASS
        self.v = max(0.0, self.v + accel * dt)

        p_elec = self.AUX_POWER + p_drive + random.gauss(0, 0.3)
        p_elec = max(self.AUX_POWER * 0.5, p_elec)

        # battery sag: V = OCV - R*I, solved with one refinement pass
        current = p_elec / self.BATT_OCV
        vbat = self.BATT_OCV - self.BATT_R * current + random.gauss(0, 0.02)
        current = p_elec / vbat

        self.dist_m += self.v * dt
        self.time_s += dt

        # ----- what the MCU actually reports (quantized / derived) -----
        vbat_r = round(vbat, 5)
        current_r = _sig7(current)
        vel_r = round(round(self.v * 3.6 / self.VEL_Q) * self.VEL_Q, 6)
        dist_r = round(math.floor(self.dist_m / self.WHEEL_C) * self.WHEEL_C, 2)
        power_r = _sig7(vbat_r * current_r)
        self.energy += power_r * dt / 3600.0        # MCU integrates its own PowerW
        energy_r = _sig7(self.energy)
        # cumulative efficiency since boot — NOT instantaneous (attempt 2 quirk)
        km_per_kwh = _sig7(dist_r / energy_r) if energy_r > 1e-6 and dist_r > 0 else 0.0

        return {
            "Batt Voltage": vbat_r,
            "Battery Current": current_r,
            "Velocity": vel_r,
            "Distance": dist_r,
            "H2 Leak": False,
            "PowerW": power_r,
            "EnergiWh": energy_r,
            "kmPerkWh": km_per_kwh,
            "Time(s)": int(self.time_s),
        }


def inject_fault(data, inject=False):
    """Corrupt the OUTGOING payload only if explicitly enabled. Returns (rows_to_send, delay_s, note)."""
    if not inject:
        return [data], 0.0, None
    r = random.random()
    if r < 0.02:
        return [], 0.0, "packet loss: row dropped"
    if r < 0.04:
        return [data], random.uniform(2.0, 5.0), "network latency: 2-5 s stall"
    if r < 0.05:
        bad = dict(data)
        bad["Velocity"] = 999.9
        return [bad], 0.0, "sensor spike: Velocity=999.9"
    return [data], 0.0, None


class GpsReplay:
    """Interpolates a lat/lon/altitude fix along the real track's drivable
    corridor, looping past one lap length -- a cheap stand-in for a real GPS
    fix, not a full physics model, but track-accurate and continuous:

      1. Interpolate the raw Shell GPS backbone by cumulative distance (as
         before), plus this point's heading, altitude, and measured corridor
         width (w_left_m/w_right_m) from the satellite-imagery width
         digitization (data/track_edges_imagery.csv).
      2. Shift to the TRUE corridor midline via centerline_shift_m (the raw
         Shell trace hugs one edge / cuts corners in places -- see
         digital_twin/track.py's join_track_widths docstring).
      3. Apply a bounded, mean-reverting (Ornstein-Uhlenbeck) lateral wander
         within that corridor's own measured width -- this is what makes the
         "random" part of the trace physically plausible: it changes
         smoothly tick-to-tick (never teleports from centerline to the far
         edge) and never exceeds the track's actual drivable width.

    Both shifts are applied perpendicular to the local heading, using the
    same meters-per-degree constants digital_twin/track.py's
    join_track_widths already uses, so the math stays consistent with the
    rest of the app.
    """

    LATERAL_THETA = 0.15   # 1/s, mean-reversion rate back toward the corridor midline
    LATERAL_SIGMA = 0.15   # m / sqrt(s), wander noise scale
    LATERAL_MARGIN = 0.85  # stay within this fraction of the measured half-width each side

    def __init__(self, track_id=None):
        import digital_twin.track as track_mod

        coords_csv, turns_csv, edges_csv = resolve_track_paths(track_id)
        profile = track_mod.build_track_profile(
            save=False, coordinates_csv=coords_csv, turns_csv=turns_csv, edges_csv=edges_csv,
        )
        self.dist_m = profile["distance_m"].to_numpy()
        self.lat = profile["latitude"].to_numpy()
        self.lon = profile["longitude"].to_numpy()
        self.alt = profile["altitude_m"].to_numpy()
        self.heading_deg = profile["heading_deg"].to_numpy()
        self.w_left_m = profile["w_left_m"].to_numpy()
        self.w_right_m = profile["w_right_m"].to_numpy()
        self.centerline_shift_m = profile["centerline_shift_m"].to_numpy()
        self.lap_len_m = float(self.dist_m[-1]) if len(self.dist_m) else 1.0
        self._lateral_offset_m = 0.0

    @staticmethod
    def _perp_offset(lat_deg, heading_deg, offset_m):
        """Offset `offset_m` to the RIGHT of `heading_deg` (negative = left)
        -> (d_lat, d_lon) in degrees, using a local flat-Earth approximation
        (fine at this scale -- same constants as join_track_widths)."""
        lat_rad = math.radians(lat_deg)
        mlat = 111132.954 - 559.822 * math.cos(2 * lat_rad)
        mlon = 111412.84 * math.cos(lat_rad)
        bearing_rad = math.radians(heading_deg + 90.0)
        d_lat = (offset_m * math.cos(bearing_rad)) / mlat
        d_lon = (offset_m * math.sin(bearing_rad)) / mlon
        return d_lat, d_lon

    def _advance_lateral(self, dt, w_left_m, w_right_m):
        dt = max(dt, 1e-6)
        self._lateral_offset_m += (
            -self.LATERAL_THETA * self._lateral_offset_m * dt
            + self.LATERAL_SIGMA * math.sqrt(dt) * random.gauss(0.0, 1.0)
        )
        lo = -self.LATERAL_MARGIN * w_left_m
        hi = self.LATERAL_MARGIN * w_right_m
        self._lateral_offset_m = max(lo, min(hi, self._lateral_offset_m))
        return self._lateral_offset_m

    def at_distance(self, dist_m, dt=1.0):
        d = dist_m % self.lap_len_m if self.lap_len_m > 0 else 0.0
        lat = float(np.interp(d, self.dist_m, self.lat))
        lon = float(np.interp(d, self.dist_m, self.lon))
        alt = float(np.interp(d, self.dist_m, self.alt))
        heading = float(np.interp(d, self.dist_m, self.heading_deg))
        w_left = float(np.interp(d, self.dist_m, self.w_left_m))
        w_right = float(np.interp(d, self.dist_m, self.w_right_m))
        shift = float(np.interp(d, self.dist_m, self.centerline_shift_m))

        # centerline_shift_m is how far LEFT the true corridor midline sits
        # from the raw Shell backbone -- negate it in our right-positive convention
        d_lat, d_lon = self._perp_offset(lat, heading, -shift)
        lat, lon = lat + d_lat, lon + d_lon

        lateral = self._advance_lateral(dt, w_left, w_right)
        d_lat, d_lon = self._perp_offset(lat, heading, lateral)
        lat, lon = lat + d_lat, lon + d_lon

        return lat, lon, alt


def _gps_publish_loop(client, sim, stop_event, track_id=None):
    """Runs on its own thread at ~1 Hz -- real GPS fixes update far slower
    than the ~3.2 Hz electrical/motion stream."""
    replay = GpsReplay(track_id=track_id)
    last = time.time()
    while not stop_event.is_set():
        now = time.time()
        dt = now - last
        last = now
        lat, lon, alt = replay.at_distance(sim.dist_m, dt=dt if dt > 0 else 1.0)
        payload = json.dumps({
            "latitude": round(lat, 8),
            "longitude": round(lon, 8),
            "wgsAltitude": round(alt, 2),
            "ts": int(time.time() * 1000),
        })
        client.publish(GPS_TOPIC, payload, qos=1)
        print(f"[GPS] Published: {payload}")
        stop_event.wait(1.0)


def _warmup(sim):
    """Advance the sim from MCU boot to the moment logging starts, without
    emitting rows — the real logs begin at t=44 s (attempt 2) or later."""
    log_start = random.uniform(25.0, 60.0)
    while sim.time_s < log_start:
        sim.step(random.uniform(0.28, 0.35))


def run_mqtt(gps=False, track_id=None):
    import paho.mqtt.client as mqtt

    # CallbackAPIVersion.VERSION1 to match log.py's implementation
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    sim = FalconSimulator()
    _warmup(sim)
    gps_stop = threading.Event()
    gps_thread = None
    try:
        client.connect(BROKER, PORT, 60)
        client.loop_start()
        print(f"Connected to MQTT Broker: {BROKER}:{PORT}")
        print(f"Publishing simulation data to topic: {TOPIC}\n")
        if gps:
            gps_thread = threading.Thread(target=_gps_publish_loop, args=(client, sim, gps_stop, track_id), daemon=True)
            gps_thread.start()
            print(f"Also publishing synthetic GPS to topic: {GPS_TOPIC} (track: {track_id or 'default'})\n")

        last = time.time()
        while True:
            time.sleep(random.uniform(0.28, 0.35))     # real MCU: ~3.2 Hz
            now = time.time()
            data = sim.step(now - last)
            last = now

            rows, delay, note = inject_fault(data)
            if note:
                print(f"[SIMULATION - WORST CASE] {note}")
            if delay:
                time.sleep(delay)
            for row in rows:
                payload = json.dumps(row)
                client.publish(TOPIC, payload, qos=1)
                print(f"Published: {payload}")
    except KeyboardInterrupt:
        print("\nStopping simulation...")
    finally:
        gps_stop.set()
        if gps_thread:
            gps_thread.join(timeout=2.0)
        client.loop_stop()
        client.disconnect()
        print("Disconnected.")


def run_offline(n_rows, out_path):
    """Generate n_rows without a broker: same physics, same faults, but the
    clock is simulated so it finishes instantly. Output matches the raw
    logger CSVs (attempt2.csv / gabungan_datasensor.csv) column-for-column."""
    sim = FalconSimulator()
    _warmup(sim)
    written = 0
    faults = 0
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        while written < n_rows:
            dt = random.uniform(0.28, 0.35)
            data = sim.step(dt)

            rows, delay, note = inject_fault(data)
            if note:
                faults += 1
            if delay:
                sim.step(delay)         # latency shows up as a Time(s) gap
            for row in rows:
                writer.writerow(row)
                written += 1
                if written >= n_rows:
                    break
    print(f"wrote {written} rows to {out_path} ({faults} fault events injected)")


def main():
    ap = argparse.ArgumentParser(description="Simulate Antasena telemetry "
                                             "(real race-day MCU schema)")
    ap.add_argument("--offline", type=int, metavar="N",
                    help="skip MQTT and write N rows directly to CSV")
    ap.add_argument("-o", "--out",
                    default="data/race_day/exampleAttempt/sim_attempt.csv",
                    help="offline output CSV (default: "
                         "data/race_day/exampleAttempt/sim_attempt.csv — "
                         "never a real attempt_XX folder)")
    ap.add_argument("--gps", action="store_true",
                    help="also publish a synthetic GPS trace on race/falcon/gps "
                         "(live mode only -- the real rig's GPS fix is a separate "
                         "publisher from the car's electrical/motion stream)")
    ap.add_argument("--track", default=None, metavar="TRACK_ID",
                    help="registered track (data/tracks.json) to replay GPS against "
                         "(--gps only; default: first/only registered track)")
    args = ap.parse_args()

    if args.offline:
        run_offline(args.offline, args.out)
    else:
        run_mqtt(gps=args.gps, track_id=args.track)


if __name__ == "__main__":
    main()
