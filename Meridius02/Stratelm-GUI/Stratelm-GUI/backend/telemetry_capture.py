"""
Live Telemetry MQTT bridge: configurable broker/topics/QoS, connect/disconnect,
and session recording -> clean -> Attempt.

The car's electrical/motion stream and its GPS fix are two separate MQTT
publishers on two separate topics in the real rig (see mqtt/log.py's TOPICS
list) -- this bridge subscribes to both but keeps them addressable
independently (separate topic fields, separate QoS is NOT split per-topic in
the real loggers either: log.py subscribes both its topics at one QoS, so
this mirrors that -- QoS is a connection-wide choice between "reliable"
(log.py, qos=1) and "fast" (logQos0.py, qos=0)).

Recording buffers every raw message (both topics) with a wall-clock
timestamp; on stop+save, mqtt/clean_telemetry.py's clean() runs immediately
(this is the "clean live" the team asked for -- true per-sample streaming
cleaning isn't meaningful for MAD/rolling-median detection, which needs the
whole series, so "immediately" means the moment the recording ends, not
"never" or "only if someone remembers to run a script later").
"""

import json
import os
import subprocess
import sys
import threading
import time
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

# Survives a backend process restart (e.g. `uvicorn --reload` picking up an
# edit) unlike SimulatorManager's in-memory self._proc handle -- see that
# class's docstring for why an orphaned simulate_field.py is a real, observed
# failure mode: `subprocess.Popen` children do NOT die with their parent (on
# Windows or POSIX), so every reload while a simulator was running leaked it.
# Multiple leaked copies all publish GPS fixes to the same shared broker/topic
# at once, and the live map shows the car "teleporting" between whichever
# leaked instance's message arrived last -- this file is what lets a freshly
# started SimulatorManager find and kill its predecessor's orphan on boot.
_SIMULATOR_PID_FILE = os.path.join(PROJECT_ROOT, ".simulator.pid")


def _pid_alive(pid: int) -> bool:
    """Cross-platform, psutil-free liveness check (existence only, no kill)."""
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _force_kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, check=False)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

import attempts as attempts_mod

try:
    import paho.mqtt.client as mqtt
    PAHO_AVAILABLE = True
except ImportError:
    PAHO_AVAILABLE = False

DEFAULT_BROKER_HOST = "broker.hivemq.com"
DEFAULT_BROKER_PORT = 1883
DEFAULT_CAR_TOPIC = "gabungan_datasensor"
DEFAULT_GPS_TOPIC = "race/falcon/gps"


class TelemetryBridge:
    def __init__(self):
        self._lock = threading.Lock()
        self.broker_host = DEFAULT_BROKER_HOST
        self.broker_port = DEFAULT_BROKER_PORT
        self.car_topic = DEFAULT_CAR_TOPIC
        self.gps_topic = DEFAULT_GPS_TOPIC
        self.qos = 1
        self.broker_connected = False
        self.connect_error: Optional[str] = None
        self.message_counts: dict = {}
        self.last_message_ts: dict = {}
        self.latest_values: dict = {}
        self._client = None
        self._client_seq = 0
        self.recording = False
        self.recording_started_at: Optional[float] = None
        self.recorded_rows: list = []

    # -- connection lifecycle --------------------------------------------
    def configure(self, broker_host=None, broker_port=None, car_topic=None,
                  gps_topic=None, qos=None):
        with self._lock:
            if broker_host is not None:
                self.broker_host = broker_host
            if broker_port is not None:
                self.broker_port = broker_port
            if car_topic is not None:
                self.car_topic = car_topic
            if gps_topic is not None:
                self.gps_topic = gps_topic
            if qos is not None:
                self.qos = qos

    def connect(self):
        if not PAHO_AVAILABLE:
            with self._lock:
                self.connect_error = "paho-mqtt not installed"
            return
        self.disconnect()
        with self._lock:
            self._client_seq += 1
            seq = self._client_seq
            host, port, car_topic, gps_topic, qos = (
                self.broker_host, self.broker_port, self.car_topic, self.gps_topic, self.qos)
            self.message_counts = {car_topic: 0, gps_topic: 0}
            self.last_message_ts = {car_topic: None, gps_topic: None}
            self.latest_values = {}
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                                  client_id=f"stratelm_gui_{int(time.time())}",
                                  clean_session=True)
            client.on_connect = lambda c, u, f, rc: self._on_connect(seq, c, rc)
            client.on_disconnect = lambda c, u, rc: self._on_disconnect(seq)
            client.on_message = lambda c, u, msg: self._on_message(seq, msg)
            with self._lock:
                self._client = client
            client.connect_async(host, port, keepalive=60)
            client.loop_start()
        except Exception as e:
            with self._lock:
                self.connect_error = str(e)

    def disconnect(self):
        with self._lock:
            client = self._client
            self._client = None
            self.broker_connected = False
            self._client_seq += 1  # invalidate any in-flight callbacks from the old client
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    def _on_connect(self, seq, client, rc):
        with self._lock:
            if seq != self._client_seq:
                return
            self.broker_connected = (rc == 0)
            self.connect_error = None if rc == 0 else f"connect rc={rc}"
            topics = [self.car_topic, self.gps_topic]
            qos = self.qos
        if rc == 0:
            for t in topics:
                client.subscribe(t, qos=qos)

    def _on_disconnect(self, seq):
        with self._lock:
            if seq != self._client_seq:
                return
            self.broker_connected = False

    def _on_message(self, seq, msg):
        with self._lock:
            if seq != self._client_seq:
                return
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(payload, dict):
            return
        now = time.time()
        with self._lock:
            self.message_counts[topic] = self.message_counts.get(topic, 0) + 1
            self.last_message_ts[topic] = now
            self.latest_values.update(payload)
            if self.recording:
                # _capture_ts (not "ts") and placed AFTER **payload so it always wins --
                # a GPS payload legitimately carries its own "ts" (epoch-ms int from
                # the publisher), which previously collided with and silently
                # overwrote this wall-clock float, producing a dtype clash
                # (int64 vs float64) when merge_asof later joined car+GPS rows.
                self.recorded_rows.append({"topic": topic, **payload, "_capture_ts": now})

    # -- recording ----------------------------------------------------------
    def start_recording(self):
        with self._lock:
            self.recording = True
            self.recording_started_at = time.time()
            self.recorded_rows = []

    def stop_recording(self):
        with self._lock:
            self.recording = False
            rows = self.recorded_rows
            self.recorded_rows = []
            car_topic, gps_topic = self.car_topic, self.gps_topic
            started_at = self.recording_started_at
        duration_s = (time.time() - started_at) if started_at else 0.0
        return rows, car_topic, gps_topic, duration_s

    def discard_recording(self):
        with self._lock:
            self.recording = False
            self.recorded_rows = []

    # -- status snapshot ------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            age = {t: (round(now - ts, 1) if ts else None) for t, ts in self.last_message_ts.items()}
            any_recent = any(a is not None and a < 10.0 for a in age.values())
            return {
                "broker_host": self.broker_host,
                "broker_port": self.broker_port,
                "car_topic": self.car_topic,
                "gps_topic": self.gps_topic,
                "qos": self.qos,
                "broker": f"{self.broker_host}:{self.broker_port}",
                "topics": [self.car_topic, self.gps_topic],
                "broker_connected": self.broker_connected,
                "connect_error": self.connect_error,
                "live": self.broker_connected and any_recent,
                "message_counts": dict(self.message_counts),
                "last_message_age_s": age,
                "latest": dict(self.latest_values),
                "recording": self.recording,
                "recording_seconds": round(now - self.recording_started_at, 1) if self.recording and self.recording_started_at else 0.0,
                "recorded_row_count": len(self.recorded_rows),
            }


def save_recording_as_attempt(rows: list, car_topic: str, gps_topic: str, *,
                               name: str, vehicle_id: str, track_id: Optional[str], notes: str = ""):
    """Split the raw buffered rows by topic, nearest-timestamp-merge GPS onto
    the car stream if any GPS rows exist, run mqtt/clean_telemetry.py's
    cleaner immediately, persist raw+cleaned CSVs + QC report, register the
    Attempt. Returns (attempt_dict, error_or_None)."""
    import pandas as pd
    import mqtt.clean_telemetry as clean_telemetry

    if not rows:
        return None, "no data was recorded -- nothing to save"

    car_rows = [r for r in rows if r["topic"] == car_topic]
    gps_rows = [r for r in rows if r["topic"] == gps_topic]

    if car_rows:
        base_df = pd.DataFrame(car_rows).sort_values("_capture_ts").reset_index(drop=True)
        has_gps = False
        if gps_rows:
            gps_df = pd.DataFrame(gps_rows).sort_values("_capture_ts").reset_index(drop=True)
            gps_cols = [c for c in gps_df.columns if c not in ("topic",)]
            merged = pd.merge_asof(base_df, gps_df[gps_cols], on="_capture_ts",
                                    direction="nearest", tolerance=5.0, suffixes=("", "_gps"))
            base_df = merged
            has_gps = True
    elif gps_rows:
        base_df = pd.DataFrame(gps_rows).sort_values("_capture_ts").reset_index(drop=True)
        has_gps = True
    else:
        return None, "no data was recorded -- nothing to save"

    base_df = base_df.drop(columns=["topic"], errors="ignore")

    try:
        # RULES' default lat/lon bounds are calibrated to Indonesia (Antasena's
        # home test track) -- wrong for Lusail or any other venue, and would
        # silently wipe every GPS point as "out of bounds". Widen to the whole
        # globe here; genuinely impossible fixes are still caught (values
        # outside real Earth coordinates), venue-specific ones are not assumed.
        cleaned_df, report = clean_telemetry.clean(
            base_df, ts_col="_capture_ts", lat_bounds=(-90.0, 90.0), lon_bounds=(-180.0, 180.0))
    except Exception as e:
        return None, f"cleaning failed: {e}"

    aid = attempts_mod.new_attempt_id()
    d = attempts_mod.attempt_dir(aid)
    raw_path = os.path.join(d, "telemetry_raw.csv")
    cleaned_path = os.path.join(d, "telemetry_cleaned.csv")
    report_path = os.path.join(d, "qc_report.json")
    base_df.to_csv(raw_path, index=False)
    cleaned_df.to_csv(cleaned_path, index=False)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    doc = attempts_mod.register_attempt(
        attempt_id=aid,
        name=name,
        source_type="real",
        algorithm=None,
        vehicle_id=vehicle_id,
        track_id=track_id,
        has_gps=has_gps,
        telemetry_csv_abs=cleaned_path,
        segment_targets_csv_abs=None,
        qc_report_abs=report_path,
        summary={"row_count": len(cleaned_df), "duration_s": None},
        notes=notes,
    )
    return doc, None


class SimulatorManager:
    """Starts/stops mqtt/simulate_field.py as an explicit, managed subprocess
    instead of it ever being a stray terminal process someone forgot about --
    the field simulator publishes to the SAME public broker.hivemq.com the
    real Live Telemetry bridge subscribes to, so an unmanaged copy left
    running (as happened during development) looks exactly like "the
    dashboard is always simulating," which it should never silently be."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._gps = False
        self._track_id: Optional[str] = None
        self._started_at: Optional[float] = None
        self._reap_stale_pidfile()

    def _reap_stale_pidfile(self):
        """Runs once per SimulatorManager instantiation, i.e. once per backend
        process start (including every --reload restart). This instance has no
        in-memory handle to any simulator yet, so if the pidfile names a PID
        that's still alive, it can only be a previous process generation's
        orphan (see the module-level docstring by _SIMULATOR_PID_FILE) --
        never something this instance itself started. Safe to kill outright."""
        try:
            with open(_SIMULATOR_PID_FILE) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            return
        if _pid_alive(pid):
            _force_kill_pid(pid)
        try:
            os.remove(_SIMULATOR_PID_FILE)
        except OSError:
            pass

    def start(self, gps: bool = True, track_id: Optional[str] = None):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False, "simulator already running"
            script = os.path.join(PROJECT_ROOT, "mqtt", "simulate_field.py")
            args = [sys.executable, script]
            if gps:
                args.append("--gps")
                if track_id:
                    args += ["--track", track_id]
            self._proc = subprocess.Popen(
                args, cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._gps = gps
            self._track_id = track_id if gps else None
            self._started_at = time.time()
            try:
                with open(_SIMULATOR_PID_FILE, "w") as f:
                    f.write(str(self._proc.pid))
            except OSError:
                pass
            return True, None

    def stop(self):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._proc = None
                return False, "simulator is not running"
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
            self._proc = None
            self._track_id = None
            self._started_at = None
            try:
                os.remove(_SIMULATOR_PID_FILE)
            except OSError:
                pass
            return True, None

    def status(self) -> dict:
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            if not running and self._proc is not None:
                self._proc = None  # process died on its own -- clear the handle
            return {
                "running": running,
                "gps": self._gps if running else None,
                "track_id": self._track_id if running else None,
                "pid": self._proc.pid if running else None,
                "running_seconds": round(time.time() - self._started_at, 1) if running and self._started_at else 0.0,
            }
