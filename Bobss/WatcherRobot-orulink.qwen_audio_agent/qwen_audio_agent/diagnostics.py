"""Application-owned, loopback-only status and voice trace diagnostics."""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from .settings import (
    BACKEND_CATALOG,
    REALTIME_MODEL_CATALOG,
    GatewaySettings,
    GatewaySettingsError,
    GatewaySettingsStore,
    TouchInterruptSettings,
    TouchInterruptSettingsError,
    TouchInterruptSettingsStore,
    VadSettings,
    VadSettingsError,
    VadSettingsStore,
    merge_gateway_settings,
)
from .service_restart import ServiceRestartError, ServiceRestartScheduler


DEFAULT_COMPONENTS = (
    "application",
    "gateway",
    "device_audio",
    "conversation",
    "agent",
    "behavior",
)
MAX_DETAIL_LENGTH = 300
SAFE_LEVELS = frozenset({"ok", "update", "error"})
SAFE_STATES = frozenset({"ready", "update", "error"})
STATIC_DIR = Path(__file__).with_name("static")
PAIRING_TARGET_MODE = "python_sdk"
DEFAULT_GATEWAY_HEALTH_URL = "http://127.0.0.1:3101/api/health"
MAX_REQUEST_BODY_BYTES = 16 * 1024


class DiagnosticsState:
    """Keep a bounded, sanitized trace without retaining audio or transcripts."""

    def __init__(self, *, max_events: int = 256) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._components = {
            name: {
                "state": "update",
                "detail": "等待状态",
                "updated_at": _timestamp(),
            }
            for name in DEFAULT_COMPONENTS
        }
        self._started_at = time.monotonic()
        self._instance_id = secrets.token_hex(16)
        self._next_event_id = 1
        self._next_turn_id = 1
        self._active_turn_id: int | None = None
        self._rms = {
            "value": 0,
            "peak": 0,
            "in_speech": False,
            "sample_count": 0,
        }

    @property
    def active_turn_id(self) -> int | None:
        with self._lock:
            return self._active_turn_id

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def set_status(self, component: str, state: str, detail: str = "") -> None:
        if component not in self._components:
            raise ValueError(f"unknown diagnostics component: {component}")
        normalized_state = state if state in SAFE_STATES else "update"
        with self._lock:
            self._components[component] = {
                "state": normalized_state,
                "detail": _sanitize_detail(detail),
                "updated_at": _timestamp(),
            }

    def update_rms(self, value: int, *, in_speech: bool) -> None:
        """Store one compact RMS snapshot without retaining PCM or history."""

        normalized = max(0, min(32767, int(value)))
        with self._lock:
            self._rms["value"] = normalized
            self._rms["peak"] = max(int(self._rms["peak"]), normalized)
            self._rms["in_speech"] = bool(in_speech)
            self._rms["sample_count"] = int(self._rms["sample_count"]) + 1

    def reset_rms(self) -> None:
        with self._lock:
            self._rms = {
                "value": 0,
                "peak": 0,
                "in_speech": False,
                "sample_count": 0,
            }

    def begin_turn(
        self,
        detail: str = "检测到语音",
        *,
        metrics: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            turn_id = self._next_turn_id
            self._next_turn_id += 1
            self._active_turn_id = turn_id
            self._append_event_locked(
                "capture.speech_started",
                detail=detail,
                level="ok",
                turn_id=turn_id,
                response_id=None,
                metrics=metrics,
            )
            return turn_id

    def end_turn(
        self,
        stage: str,
        *,
        detail: str = "",
        level: str = "ok",
        response_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            turn_id = self._active_turn_id
            event_id = self._append_event_locked(
                stage,
                detail=detail,
                level=level,
                turn_id=turn_id,
                response_id=response_id,
                metrics=metrics,
            )
            self._active_turn_id = None
            return event_id

    def record(
        self,
        stage: str,
        *,
        detail: str = "",
        level: str = "ok",
        turn_id: int | None = None,
        response_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            return self._append_event_locked(
                stage,
                detail=detail,
                level=level,
                turn_id=self._active_turn_id if turn_id is None else turn_id,
                response_id=response_id,
                metrics=metrics,
            )

    def snapshot(self, *, after_id: int = 0) -> dict[str, Any]:
        with self._lock:
            events = [dict(event) for event in self._events if event["id"] > after_id]
            last_event_id = self._next_event_id - 1
            return {
                "schema_version": 1,
                "diagnostics_instance_id": self._instance_id,
                "uptime_seconds": round(time.monotonic() - self._started_at, 1),
                "components": {
                    name: dict(status) for name, status in self._components.items()
                },
                "active_turn_id": self._active_turn_id,
                "rms": dict(self._rms),
                "events": events,
                "last_event_id": last_event_id,
            }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._active_turn_id = None

    def _append_event_locked(
        self,
        stage: str,
        *,
        detail: str,
        level: str,
        turn_id: int | None,
        response_id: str | None,
        metrics: dict[str, Any] | None,
    ) -> int:
        event_id = self._next_event_id
        self._next_event_id += 1
        self._events.append(
            {
                "id": event_id,
                "timestamp": _timestamp(),
                "turn_id": turn_id,
                "stage": _sanitize_detail(stage),
                "level": level if level in SAFE_LEVELS else "update",
                "detail": _sanitize_detail(detail),
                "response_id": _sanitize_detail(response_id or ""),
                "metrics": _sanitize_metrics(metrics),
            }
        )
        return event_id


class ApplicationDiagnosticsServer:
    """Serve Application diagnostics on a dedicated loopback endpoint."""

    def __init__(
        self,
        state: DiagnosticsState,
        *,
        host: str = "127.0.0.1",
        port: int = 8768,
        static_dir: Path = STATIC_DIR,
        daemon_control_url: str = "http://127.0.0.1:8767",
        settings_store: VadSettingsStore | None = None,
        active_vad_settings: VadSettings | None = None,
        touch_settings_store: TouchInterruptSettingsStore | None = None,
        active_touch_settings: TouchInterruptSettings | None = None,
        gateway_settings_store: GatewaySettingsStore | None = None,
        active_gateway_settings: GatewaySettings | None = None,
        gateway_health_url: str = DEFAULT_GATEWAY_HEALTH_URL,
        gateway_health_probe: Any | None = None,
        restart_scheduler: Any | None = None,
    ) -> None:
        if host != "127.0.0.1":
            raise ValueError("Application diagnostics must bind to 127.0.0.1")
        self._state = state
        self._host = host
        self._port = port
        self._static_dir = static_dir
        self._daemon_control_url = daemon_control_url.rstrip("/")
        self._settings_store = settings_store or VadSettingsStore.from_environment()
        self._active_vad_settings = active_vad_settings or self._settings_store.load()
        self._touch_settings_store = (
            touch_settings_store or TouchInterruptSettingsStore.from_environment()
        )
        self._active_touch_settings = (
            active_touch_settings or self._touch_settings_store.load()
        )
        self._gateway_settings_store = (
            gateway_settings_store or GatewaySettingsStore.from_environment()
        )
        self._active_gateway_settings = (
            active_gateway_settings or self._gateway_settings_store.load()
        )
        self._gateway_health_probe = gateway_health_probe or (
            lambda: _probe_gateway_health(gateway_health_url)
        )
        self._restart_scheduler = restart_scheduler or ServiceRestartScheduler(
            daemon_control_url=self._daemon_control_url
        ).schedule
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("diagnostics server is not running")
        return int(self._httpd.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self.port}"

    def start(self) -> None:
        if self._httpd is not None:
            return
        handler = _create_handler(
            self._state,
            self._static_dir,
            self._daemon_control_url,
            self._settings_store,
            self._active_vad_settings,
            self._touch_settings_store,
            self._active_touch_settings,
            self._gateway_settings_store,
            self._active_gateway_settings,
            self._gateway_health_probe,
            self._restart_scheduler,
        )
        httpd = ThreadingHTTPServer((self._host, self._port), handler)
        httpd.daemon_threads = True
        thread = threading.Thread(
            target=httpd.serve_forever,
            name="qwen-application-diagnostics",
            daemon=True,
        )
        self._httpd = httpd
        self._thread = thread
        thread.start()

    def close(self) -> None:
        httpd = self._httpd
        thread = self._thread
        if httpd is None:
            return
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=2)
        self._httpd = None
        self._thread = None


def _create_handler(
    state: DiagnosticsState,
    static_dir: Path,
    daemon_control_url: str,
    settings_store: VadSettingsStore,
    active_vad_settings: VadSettings,
    touch_settings_store: TouchInterruptSettingsStore,
    active_touch_settings: TouchInterruptSettings,
    gateway_settings_store: GatewaySettingsStore,
    active_gateway_settings: GatewaySettings,
    gateway_health_probe: Any,
    restart_scheduler: Any,
) -> type[BaseHTTPRequestHandler]:
    class DiagnosticsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if not self._request_target_allowed():
                return
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/trace/")
                self._finish_headers(content_length=0)
                return
            if parsed.path == "/api/snapshot":
                try:
                    after_id = max(
                        0,
                        int(parse_qs(parsed.query).get("after", ["0"])[0]),
                    )
                except ValueError:
                    self._send_json(
                        {"error": "after must be an integer"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(state.snapshot(after_id=after_id))
                return
            if parsed.path == "/api/config":
                self._send_json(
                    {
                        "daemon_control_url": daemon_control_url,
                        "pairing_target_mode": PAIRING_TARGET_MODE,
                        "diagnostics_instance_id": state.instance_id,
                    }
                )
                return
            if parsed.path == "/api/status/gateway":
                self._send_json(
                    {"gateway": _gateway_runtime_payload(gateway_health_probe)}
                )
                return
            if parsed.path == "/api/settings/vad":
                try:
                    settings = settings_store.load()
                except VadSettingsError as exc:
                    self._send_json(
                        {"error": "vad_settings_invalid", "message": str(exc)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(
                    {
                        "settings": settings.to_dict(),
                        "defaults": VadSettings().to_dict(),
                        "restart_required": settings != active_vad_settings,
                    }
                )
                return
            if parsed.path == "/api/settings/touch-interrupt":
                try:
                    settings = touch_settings_store.load()
                except TouchInterruptSettingsError as exc:
                    self._send_json(
                        {
                            "error": "touch_interrupt_settings_invalid",
                            "message": str(exc),
                        },
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(
                    {
                        "settings": settings.to_dict(),
                        "defaults": TouchInterruptSettings().to_dict(),
                        "restart_required": settings != active_touch_settings,
                    }
                )
                return
            if parsed.path == "/api/settings/gateway":
                try:
                    settings = gateway_settings_store.load(
                        active_gateway_settings.environment()
                    )
                except GatewaySettingsError as exc:
                    self._send_json(
                        {"error": "gateway_settings_invalid", "message": str(exc)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(
                    _gateway_settings_payload(
                        settings,
                        active_gateway_settings=active_gateway_settings,
                        health_probe=gateway_health_probe,
                    )
                )
                return
            static_files = {
                "/trace/": ("index.html", "text/html; charset=utf-8"),
                "/assets/trace.css": ("trace.css", "text/css; charset=utf-8"),
                "/assets/trace.js": ("trace.js", "text/javascript; charset=utf-8"),
            }
            static_file = static_files.get(parsed.path)
            if static_file is None:
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            filename, media_type = static_file
            try:
                body = (static_dir / filename).read_bytes()
            except OSError:
                self._send_json(
                    {"error": "diagnostics_asset_missing"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", media_type)
            self._finish_headers(content_length=len(body))
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if not self._request_target_allowed():
                return
            path = urlparse(self.path).path
            if path == "/api/services/restart":
                if not self._same_origin_write_allowed():
                    return
                try:
                    self._read_json_object()
                    restart_scheduler()
                except RequestBodyError as exc:
                    self._send_json(
                        {"error": "invalid_restart_request", "message": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                except ServiceRestartError as exc:
                    self._send_json(
                        {"error": "restart_schedule_failed", "message": str(exc)},
                        status=HTTPStatus.CONFLICT,
                    )
                    return
                self._send_json({"restart_scheduled": True})
                return
            if path != "/api/traces/clear":
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            state.clear()
            self._send_json({"cleared": True})

        def do_PUT(self) -> None:  # noqa: N802
            if not self._request_target_allowed() or not self._same_origin_write_allowed():
                return
            path = urlparse(self.path).path
            if path == "/api/settings/gateway":
                try:
                    current = gateway_settings_store.load(
                        active_gateway_settings.environment()
                    )
                    settings = merge_gateway_settings(
                        current,
                        self._read_json_object(),
                    )
                    gateway_settings_store.save(settings)
                except (RequestBodyError, GatewaySettingsError) as exc:
                    self._send_json(
                        {"error": "invalid_gateway_settings", "message": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                except OSError as exc:
                    self._send_json(
                        {"error": "gateway_settings_write_failed", "message": str(exc)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(
                    _gateway_settings_payload(
                        settings,
                        active_gateway_settings=active_gateway_settings,
                        health_probe=gateway_health_probe,
                    )
                )
                return
            if path == "/api/settings/touch-interrupt":
                try:
                    payload = self._read_json_object()
                    settings = TouchInterruptSettings.from_mapping(payload)
                    touch_settings_store.save(settings)
                except (RequestBodyError, TouchInterruptSettingsError) as exc:
                    self._send_json(
                        {
                            "error": "invalid_touch_interrupt_settings",
                            "message": str(exc),
                        },
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                except OSError as exc:
                    self._send_json(
                        {
                            "error": "touch_interrupt_settings_write_failed",
                            "message": str(exc),
                        },
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(
                    {
                        "settings": settings.to_dict(),
                        "defaults": TouchInterruptSettings().to_dict(),
                        "restart_required": settings != active_touch_settings,
                    }
                )
                return
            if path != "/api/settings/vad":
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                payload = self._read_json_object()
                settings = VadSettings.from_mapping(payload)
                settings_store.save(settings)
            except (RequestBodyError, VadSettingsError) as exc:
                self._send_json(
                    {"error": "invalid_vad_settings", "message": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            except OSError as exc:
                self._send_json(
                    {"error": "vad_settings_write_failed", "message": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json(
                {
                    "settings": settings.to_dict(),
                    "defaults": VadSettings().to_dict(),
                    "restart_required": settings != active_vad_settings,
                }
            )

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

        def _send_json(
            self,
            payload: dict[str, Any],
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._finish_headers(content_length=len(body))
            self.wfile.write(body)

        def _read_json_object(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                content_length = int(raw_length)
            except ValueError as exc:
                raise RequestBodyError("invalid Content-Length") from exc
            if content_length < 2 or content_length > MAX_REQUEST_BODY_BYTES:
                raise RequestBodyError(
                    f"JSON request body must be between 2 and {MAX_REQUEST_BODY_BYTES} bytes"
                )
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RequestBodyError("request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise RequestBodyError("request body must be a JSON object")
            return payload

        def _request_target_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            try:
                parsed = urlparse(f"//{host}")
                port = parsed.port or 80
            except ValueError:
                parsed = urlparse("//invalid")
                port = 0
            server_port = int(self.server.server_address[1])
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or port != server_port:
                self._send_json(
                    {"error": "invalid_host"},
                    status=HTTPStatus.FORBIDDEN,
                )
                return False
            return True

        def _same_origin_write_allowed(self) -> bool:
            origin = self.headers.get("Origin", "").strip()
            if not origin:
                return True
            try:
                parsed = urlparse(origin)
                port = parsed.port or (80 if parsed.scheme == "http" else 443)
            except ValueError:
                parsed = urlparse("invalid://")
                port = 0
            allowed = (
                parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and port == int(self.server.server_address[1])
            )
            if not allowed:
                self._send_json(
                    {"error": "cross_origin_write_rejected"},
                    status=HTTPStatus.FORBIDDEN,
                )
            return allowed

        def _finish_headers(self, *, content_length: int) -> None:
            self.send_header("Content-Length", str(content_length))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                _content_security_policy(daemon_control_url),
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()

    return DiagnosticsHandler


class RequestBodyError(ValueError):
    """Raised when a diagnostics settings request body is malformed."""


def _gateway_settings_payload(
    settings: GatewaySettings,
    *,
    active_gateway_settings: GatewaySettings,
    health_probe: Any,
) -> dict[str, Any]:
    gateway = _gateway_runtime_payload(health_probe)
    return {
        "settings": settings.to_public_dict(),
        "defaults": GatewaySettings().to_public_dict(),
        "catalogs": {
            "realtime_models": [dict(item) for item in REALTIME_MODEL_CATALOG],
            "backends": [dict(item) for item in BACKEND_CATALOG],
            "permission_modes": ["native", "full"],
            "ownership_modes": ["owned", "external"],
        },
        "gateway": gateway,
        "restart_required": settings != active_gateway_settings,
    }


def _gateway_runtime_payload(health_probe: Any) -> dict[str, Any]:
    try:
        raw_health = health_probe()
    except Exception as exc:  # noqa: BLE001 - health failures are diagnostic data
        gateway = {
            "ok": False,
            "error": _sanitize_detail(str(exc) or type(exc).__name__),
            "realtime": {"connected": False},
            "backend": {"enabled": False, "connected": False},
        }
    else:
        return _sanitize_gateway_health(raw_health)
    return gateway


def _probe_gateway_health(url: str = DEFAULT_GATEWAY_HEALTH_URL) -> dict[str, Any]:
    request = Request(
        url,
        headers={"Accept": "application/json"},
    )
    with urlopen(request, timeout=1.5) as response:  # noqa: S310 - fixed loopback URL
        payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Gateway health response must be an object")
    return payload


def _sanitize_gateway_health(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error": "Gateway health response is invalid",
            "realtime": {"connected": False},
            "backend": {"enabled": False, "connected": False},
        }
    voice_clients = payload.get("voiceClients")
    if not isinstance(voice_clients, dict):
        voice_clients = {}
    realtime_clients = voice_clients.get("realtime")
    if not isinstance(realtime_clients, dict):
        realtime_clients = {}
    backend = payload.get("backend")
    if not isinstance(backend, dict):
        backend = {}
    protocol = backend.get("kind") or backend.get("protocol") or "none"
    backend_enabled = backend.get("enabled") is not False and protocol != "none"
    return {
        "ok": payload.get("ok") is True,
        "instance_id": _sanitize_detail(str(payload.get("gatewayInstanceId", ""))),
        "started_at": _sanitize_detail(str(payload.get("gatewayStartedAt", ""))),
        "voice_configured": payload.get("voiceConfigured") is True,
        "realtime": {
            "provider": _sanitize_detail(str(payload.get("realtimeProvider", ""))),
            "model": _sanitize_detail(str(payload.get("realtimeModel", ""))),
            "connected": _positive_count(realtime_clients.get("connected")),
        },
        "backend": {
            "enabled": backend_enabled,
            "protocol": _sanitize_detail(str(protocol)),
            "status": _sanitize_detail(str(backend.get("status", "unknown"))),
            "connected": backend_enabled
            and (backend.get("ok") is True or backend.get("connected") is True),
            "ownership": _sanitize_detail(str(backend.get("ownership", ""))),
            "model": _sanitize_detail(str(backend.get("model", ""))),
        },
    }


def _positive_count(value: Any) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _sanitize_detail(value: str) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= MAX_DETAIL_LENGTH:
        return text
    return f"{text[: MAX_DETAIL_LENGTH - 1]}…"


def _content_security_policy(daemon_control_url: str) -> str:
    return (
        "default-src 'self'; "
        f"connect-src 'self' {daemon_control_url}; "
        "img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )


def _sanitize_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    if not metrics:
        return {}
    return {
        _sanitize_detail(str(key)): value
        for key, value in metrics.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
