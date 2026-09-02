"""Environment-backed configuration with secure transport defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_VAD_START_RMS = 600
DEFAULT_VAD_STOP_RMS = 350
DEFAULT_VAD_START_FRAMES = 3
DEFAULT_VAD_SILENCE_MS = 1000
DEFAULT_VAD_PRE_ROLL_MS = 300
DEFAULT_VAD_MAX_UTTERANCE_MS = 60_000
DEFAULT_DIAGNOSTICS_PORT = 8768
DEFAULT_DAEMON_CONTROL_URL = "http://127.0.0.1:8767"
DEFAULT_TOUCH_INTERRUPT_DEBOUNCE_MS = 500
DEFAULT_GATEWAY_URL = (
    "ws://127.0.0.1:3101/api/realtime?sessionId=watcherobot-main"
)
DEFAULT_TOUCH_INTERRUPT_SOURCES = frozenset({"back_touch"})
SUPPORTED_TOUCH_INTERRUPT_SOURCES = frozenset({"back_touch", "screen_touch"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ConfigurationError(ValueError):
    """Raised when bridge configuration is missing or unsafe."""


@dataclass(frozen=True)
class BridgeConfiguration:
    gateway_url: str
    provider: str = "dashscope"
    client_label: str = "WatcheRobot"
    takeover: bool = True
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    connect_timeout_seconds: float = 15.0
    response_timeout_seconds: float = 90.0
    response_start_timeout_seconds: float = 15.0
    vad_enabled: bool = True
    vad_start_rms: int = DEFAULT_VAD_START_RMS
    vad_stop_rms: int = DEFAULT_VAD_STOP_RMS
    vad_start_frames: int = DEFAULT_VAD_START_FRAMES
    vad_silence_ms: int = DEFAULT_VAD_SILENCE_MS
    vad_pre_roll_ms: int = DEFAULT_VAD_PRE_ROLL_MS
    vad_max_utterance_ms: int = DEFAULT_VAD_MAX_UTTERANCE_MS
    diagnostics_enabled: bool = True
    diagnostics_port: int = DEFAULT_DIAGNOSTICS_PORT
    daemon_control_url: str = DEFAULT_DAEMON_CONTROL_URL
    wake_word_enabled: bool = False
    touch_interrupt_enabled: bool = True
    touch_interrupt_sources: frozenset[str] = DEFAULT_TOUCH_INTERRUPT_SOURCES
    touch_interrupt_debounce_ms: int = DEFAULT_TOUCH_INTERRUPT_DEBOUNCE_MS

    def __post_init__(self) -> None:
        if self.vad_stop_rms > self.vad_start_rms:
            raise ConfigurationError(
                "QWEN_AGENT_VAD_STOP_RMS must not exceed QWEN_AGENT_VAD_START_RMS"
            )
        _validate_daemon_control_url(self.daemon_control_url)
        if not self.touch_interrupt_sources <= SUPPORTED_TOUCH_INTERRUPT_SOURCES:
            raise ConfigurationError(
                "QWEN_AGENT_TOUCH_INTERRUPT_SOURCES supports only "
                "back_touch and screen_touch"
            )
        if self.touch_interrupt_enabled and not self.touch_interrupt_sources:
            raise ConfigurationError(
                "QWEN_AGENT_TOUCH_INTERRUPT_SOURCES must not be empty when enabled"
            )
        if not 100 <= self.touch_interrupt_debounce_ms <= 3000:
            raise ConfigurationError(
                "QWEN_AGENT_TOUCH_INTERRUPT_DEBOUNCE_MS must be between 100 and 3000"
            )

    @classmethod
    def from_environment(cls) -> "BridgeConfiguration":
        gateway_url = os.environ.get(
            "QWEN_AGENT_GATEWAY_URL", DEFAULT_GATEWAY_URL
        ).strip()
        if not gateway_url:
            raise ConfigurationError("QWEN_AGENT_GATEWAY_URL must not be empty")
        _validate_gateway_url(gateway_url)
        provider = os.environ.get("QWEN_AGENT_PROVIDER", "dashscope").strip()
        client_label = os.environ.get(
            "QWEN_AGENT_CLIENT_LABEL", "WatcheRobot"
        ).strip()
        if not provider:
            raise ConfigurationError("QWEN_AGENT_PROVIDER must not be empty")
        if not client_label:
            raise ConfigurationError("QWEN_AGENT_CLIENT_LABEL must not be empty")
        daemon_control_url = os.environ.get(
            "QWEN_AGENT_DAEMON_CONTROL_URL",
            os.environ.get("WATCHER_APP_CONTROL_URL", DEFAULT_DAEMON_CONTROL_URL),
        ).strip().rstrip("/")
        _validate_daemon_control_url(daemon_control_url)
        return cls(
            gateway_url=gateway_url,
            provider=provider,
            client_label=client_label,
            takeover=_environment_bool("QWEN_AGENT_TAKEOVER", True),
            max_response_bytes=_environment_int(
                "QWEN_AGENT_MAX_RESPONSE_BYTES",
                DEFAULT_MAX_RESPONSE_BYTES,
                minimum=2,
                maximum=4 * 1024 * 1024,
            ),
            connect_timeout_seconds=float(
                _environment_int(
                    "QWEN_AGENT_CONNECT_TIMEOUT_SECONDS", 15, minimum=1, maximum=60
                )
            ),
            response_timeout_seconds=float(
                _environment_int(
                    "QWEN_AGENT_RESPONSE_TIMEOUT_SECONDS",
                    90,
                    minimum=5,
                    maximum=300,
                )
            ),
            response_start_timeout_seconds=float(
                _environment_int(
                    "QWEN_AGENT_RESPONSE_START_TIMEOUT_SECONDS",
                    15,
                    minimum=5,
                    maximum=60,
                )
            ),
            vad_enabled=_environment_bool("QWEN_AGENT_VAD_ENABLED", True),
            vad_start_rms=_environment_int(
                "QWEN_AGENT_VAD_START_RMS",
                DEFAULT_VAD_START_RMS,
                minimum=1,
                maximum=32767,
            ),
            vad_stop_rms=_environment_int(
                "QWEN_AGENT_VAD_STOP_RMS",
                DEFAULT_VAD_STOP_RMS,
                minimum=0,
                maximum=32767,
            ),
            vad_start_frames=_environment_int(
                "QWEN_AGENT_VAD_START_FRAMES",
                DEFAULT_VAD_START_FRAMES,
                minimum=1,
                maximum=20,
            ),
            vad_silence_ms=_environment_int(
                "QWEN_AGENT_VAD_SILENCE_MS",
                DEFAULT_VAD_SILENCE_MS,
                minimum=120,
                maximum=3000,
            ),
            vad_pre_roll_ms=_environment_int(
                "QWEN_AGENT_VAD_PRE_ROLL_MS",
                DEFAULT_VAD_PRE_ROLL_MS,
                minimum=60,
                maximum=2000,
            ),
            vad_max_utterance_ms=_environment_int(
                "QWEN_AGENT_VAD_MAX_UTTERANCE_MS",
                DEFAULT_VAD_MAX_UTTERANCE_MS,
                minimum=1000,
                maximum=60000,
            ),
            diagnostics_enabled=_environment_bool(
                "QWEN_AGENT_DIAGNOSTICS_ENABLED", True
            ),
            diagnostics_port=_environment_int(
                "QWEN_AGENT_DIAGNOSTICS_PORT",
                DEFAULT_DIAGNOSTICS_PORT,
                minimum=1024,
                maximum=65535,
            ),
            daemon_control_url=daemon_control_url,
            wake_word_enabled=_environment_bool(
                "QWEN_AGENT_WAKE_WORD_ENABLED", False
            ),
            touch_interrupt_enabled=_environment_bool(
                "QWEN_AGENT_TOUCH_INTERRUPT_ENABLED", True
            ),
            touch_interrupt_sources=_environment_touch_interrupt_sources(),
            touch_interrupt_debounce_ms=_environment_int(
                "QWEN_AGENT_TOUCH_INTERRUPT_DEBOUNCE_MS",
                DEFAULT_TOUCH_INTERRUPT_DEBOUNCE_MS,
                minimum=100,
                maximum=3000,
            ),
        )


def _validate_gateway_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in ("ws", "wss") or not parsed.hostname:
        raise ConfigurationError("Qwen Gateway URL must use ws:// or wss://")
    if parsed.path != "/api/realtime":
        raise ConfigurationError("Qwen Gateway URL path must be /api/realtime")
    session_ids = parse_qs(parsed.query).get("sessionId", [])
    if not session_ids or not session_ids[0].strip():
        raise ConfigurationError("Qwen Gateway URL requires a non-empty sessionId")
    if parsed.hostname.lower() not in LOOPBACK_HOSTS:
        raise ConfigurationError(
            "MVP Qwen Gateway must use a loopback host until client authentication exists"
        )


def _validate_daemon_control_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.hostname.lower() not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ConfigurationError(
            "Daemon control URL must be an HTTP loopback origin without credentials"
        )


def _environment_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ConfigurationError(f"{name} must be a boolean")


def _environment_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.environ.get(name)
    try:
        value = default if raw is None else int(raw.strip())
    except (AttributeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _environment_touch_interrupt_sources() -> frozenset[str]:
    raw = os.environ.get("QWEN_AGENT_TOUCH_INTERRUPT_SOURCES")
    if raw is None:
        return DEFAULT_TOUCH_INTERRUPT_SOURCES
    sources = frozenset(part.strip().lower() for part in raw.split(",") if part.strip())
    if not sources or not sources <= SUPPORTED_TOUCH_INTERRUPT_SOURCES:
        raise ConfigurationError(
            "QWEN_AGENT_TOUCH_INTERRUPT_SOURCES supports only "
            "back_touch and screen_touch"
        )
    return sources
