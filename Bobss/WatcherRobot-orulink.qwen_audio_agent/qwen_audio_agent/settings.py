"""Persistent, validated Application settings owned by the Qwen integration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping
from urllib.parse import urlparse

from .configuration import (
    DEFAULT_VAD_MAX_UTTERANCE_MS,
    DEFAULT_VAD_PRE_ROLL_MS,
    DEFAULT_VAD_SILENCE_MS,
    DEFAULT_VAD_START_FRAMES,
    DEFAULT_VAD_START_RMS,
    DEFAULT_VAD_STOP_RMS,
    DEFAULT_TOUCH_INTERRUPT_DEBOUNCE_MS,
    DEFAULT_TOUCH_INTERRUPT_SOURCES,
    SUPPORTED_TOUCH_INTERRUPT_SOURCES,
)


VAD_SETTINGS_ENV = "QWEN_AGENT_VAD_SETTINGS_FILE"
DEFAULT_VAD_SETTINGS_FILE = Path(__file__).parents[2] / "runtime" / "vad-settings.json"
TOUCH_INTERRUPT_SETTINGS_ENV = "QWEN_AGENT_TOUCH_INTERRUPT_SETTINGS_FILE"
DEFAULT_TOUCH_INTERRUPT_SETTINGS_FILE = (
    Path(__file__).parents[2] / "runtime" / "touch-interrupt-settings.json"
)
GATEWAY_SETTINGS_ENV = "QWEN_AGENT_GATEWAY_SETTINGS_FILE"
DEFAULT_GATEWAY_SETTINGS_FILE = (
    Path(__file__).parents[2] / "runtime" / "gateway-settings.json"
)
DEFAULT_REALTIME_MODEL = "qwen-audio-3.0-realtime-plus"
REALTIME_MODEL_CATALOG = (
    {
        "id": "qwen3.5-omni-flash-realtime",
        "label": "Qwen3.5 Omni Flash Realtime",
        "family": "omni",
    },
    {
        "id": "qwen3.5-omni-plus-realtime",
        "label": "Qwen3.5 Omni Plus Realtime",
        "family": "omni",
    },
    {
        "id": DEFAULT_REALTIME_MODEL,
        "label": "Qwen Audio 3.0 Realtime Plus",
        "family": "audio",
    },
    {
        "id": "qwen-audio-3.0-realtime-flash",
        "label": "Qwen Audio 3.0 Realtime Flash",
        "family": "audio",
    },
)
SUPPORTED_REALTIME_MODELS = frozenset(item["id"] for item in REALTIME_MODEL_CATALOG)
BACKEND_CATALOG = (
    {"id": "none", "label": "仅前台聊天", "supports_external": False},
    {"id": "codex", "label": "Codex", "supports_external": False},
    {"id": "openclaw", "label": "OpenClaw", "supports_external": True},
    {"id": "opencode", "label": "OpenCode", "supports_external": False},
    {"id": "qwen", "label": "Qwen Code", "supports_external": False},
    {"id": "qoder", "label": "Qoder", "supports_external": False},
    {"id": "kimi", "label": "Kimi Code", "supports_external": False},
    {"id": "hermes", "label": "Hermes", "supports_external": False},
    {"id": "codebuddy", "label": "CodeBuddy", "supports_external": False},
    {"id": "claude", "label": "Claude Code", "supports_external": False},
    {"id": "deepseek", "label": "DeepSeek", "supports_external": False},
)
SUPPORTED_BACKENDS = frozenset(item["id"] for item in BACKEND_CATALOG)
EXTERNAL_BACKENDS = frozenset(
    item["id"] for item in BACKEND_CATALOG if item["supports_external"]
)
MANAGED_GATEWAY_ENVIRONMENT = frozenset(
    {
        "DASHSCOPE_API_KEY",
        "QWEN_AUDIO_REALTIME_API_KEY",
        "QWEN_AUDIO_REALTIME_MODEL",
        "AGENT_PROTOCOL",
        "QWEN_AUDIO_AGENT_BACKEND_MODEL",
        "QWEN_AUDIO_AGENT_BACKEND_PERMISSION_MODE",
        "QWEN_AUDIO_AGENT_BACKEND_OWNERSHIP",
        "OPENCLAW_BASE_URL",
        "OPENCLAW_GATEWAY_TOKEN",
    }
)
_SUPPORTED_FIELDS = frozenset(
    {
        "enabled",
        "start_rms",
        "stop_rms",
        "start_frames",
        "silence_ms",
        "pre_roll_ms",
        "max_utterance_ms",
    }
)


class VadSettingsError(ValueError):
    """Raised when a persisted or submitted VAD profile is invalid."""


class TouchInterruptSettingsError(ValueError):
    """Raised when touch interrupt settings are invalid."""


class GatewaySettingsError(ValueError):
    """Raised when persisted or submitted Gateway settings are invalid."""


@dataclass(frozen=True)
class GatewaySettings:
    """Validated settings for one Application-owned Gateway runtime."""

    dashscope_api_key: str = ""
    realtime_model: str = DEFAULT_REALTIME_MODEL
    agent_protocol: str = "none"
    backend_model: str = ""
    backend_permission_mode: str = "native"
    backend_ownership: str = "owned"
    backend_url: str = ""
    backend_credential: str = ""

    def __post_init__(self) -> None:
        for name, maximum in (
            ("dashscope_api_key", 4096),
            ("realtime_model", 160),
            ("agent_protocol", 40),
            ("backend_model", 256),
            ("backend_permission_mode", 20),
            ("backend_ownership", 20),
            ("backend_url", 2048),
            ("backend_credential", 4096),
        ):
            _validate_gateway_text(name, getattr(self, name), maximum=maximum)
        if self.realtime_model not in SUPPORTED_REALTIME_MODELS:
            raise GatewaySettingsError(
                f"不支持的 Realtime 模型：{self.realtime_model}"
            )
        if self.agent_protocol not in SUPPORTED_BACKENDS:
            raise GatewaySettingsError(f"不支持的后台 Agent：{self.agent_protocol}")
        if self.backend_permission_mode not in {"native", "full"}:
            raise GatewaySettingsError("后台权限模式只支持 native 或 full")
        if self.backend_ownership not in {"owned", "external"}:
            raise GatewaySettingsError("后台进程归属只支持 owned 或 external")
        if self.backend_ownership == "external":
            if self.agent_protocol not in EXTERNAL_BACKENDS:
                raise GatewaySettingsError(
                    f"后台 Agent {self.agent_protocol} 不支持外部连接"
                )
            if not self.backend_url:
                raise GatewaySettingsError("外部后台连接必须提供服务地址")
        if self.backend_url:
            _validate_backend_url(self.backend_url)
        if self.agent_protocol != "openclaw" and (
            self.backend_url or self.backend_credential
        ):
            raise GatewaySettingsError("当前后台 Agent 不支持外部连接配置")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "GatewaySettings":
        source = os.environ if environment is None else environment
        protocol = str(source.get("AGENT_PROTOCOL", "none") or "none").strip().lower()
        if not protocol:
            protocol = "none"
        backend_url = (
            str(source.get("OPENCLAW_BASE_URL", "") or "").strip()
            if protocol == "openclaw"
            else ""
        )
        requested_ownership = str(
            source.get("QWEN_AUDIO_AGENT_BACKEND_OWNERSHIP", "") or ""
        ).strip().lower()
        ownership = requested_ownership or (
            "external" if protocol == "openclaw" and backend_url else "owned"
        )
        return cls(
            dashscope_api_key=str(
                source.get("DASHSCOPE_API_KEY")
                or source.get("QWEN_AUDIO_REALTIME_API_KEY")
                or ""
            ).strip(),
            realtime_model=str(
                source.get("QWEN_AUDIO_REALTIME_MODEL", DEFAULT_REALTIME_MODEL)
                or DEFAULT_REALTIME_MODEL
            ).strip(),
            agent_protocol=protocol,
            backend_model=str(
                source.get("QWEN_AUDIO_AGENT_BACKEND_MODEL", "") or ""
            ).strip(),
            backend_permission_mode=str(
                source.get("QWEN_AUDIO_AGENT_BACKEND_PERMISSION_MODE", "native")
                or "native"
            ).strip().lower(),
            backend_ownership=ownership,
            backend_url=backend_url,
            backend_credential=(
                str(source.get("OPENCLAW_GATEWAY_TOKEN", "") or "").strip()
                if protocol == "openclaw"
                else ""
            ),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GatewaySettings":
        fields = {
            "dashscope_api_key",
            "realtime_model",
            "agent_protocol",
            "backend_model",
            "backend_permission_mode",
            "backend_ownership",
            "backend_url",
            "backend_credential",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise GatewaySettingsError(
                "Gateway settings file does not match the supported schema"
            )
        return cls(**{name: payload[name] for name in fields})

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, str | bool]:
        return {
            "dashscope_api_key_configured": bool(self.dashscope_api_key),
            "realtime_model": self.realtime_model,
            "agent_protocol": self.agent_protocol,
            "backend_model": self.backend_model,
            "backend_permission_mode": self.backend_permission_mode,
            "backend_ownership": self.backend_ownership,
            "backend_url": self.backend_url,
            "backend_credential_configured": bool(self.backend_credential),
        }

    def environment(self) -> dict[str, str]:
        values = {
            "QWEN_AUDIO_REALTIME_MODEL": self.realtime_model,
            "AGENT_PROTOCOL": self.agent_protocol,
            "QWEN_AUDIO_AGENT_BACKEND_MODEL": self.backend_model,
            "QWEN_AUDIO_AGENT_BACKEND_PERMISSION_MODE": (
                self.backend_permission_mode
            ),
            "QWEN_AUDIO_AGENT_BACKEND_OWNERSHIP": self.backend_ownership,
        }
        if self.dashscope_api_key:
            values["DASHSCOPE_API_KEY"] = self.dashscope_api_key
            values["QWEN_AUDIO_REALTIME_API_KEY"] = self.dashscope_api_key
        if self.agent_protocol == "openclaw" and self.backend_url:
            values["OPENCLAW_BASE_URL"] = self.backend_url
        if self.agent_protocol == "openclaw" and self.backend_credential:
            values["OPENCLAW_GATEWAY_TOKEN"] = self.backend_credential
        return values


class GatewaySettingsStore:
    """Load and atomically save private Gateway credentials and selections."""

    def __init__(self, path: Path | str = DEFAULT_GATEWAY_SETTINGS_FILE) -> None:
        self.path = Path(path).expanduser().resolve()

    @classmethod
    def from_environment(cls) -> "GatewaySettingsStore":
        configured = os.environ.get(GATEWAY_SETTINGS_ENV, "").strip()
        return cls(configured or DEFAULT_GATEWAY_SETTINGS_FILE)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def load(
        self,
        environment: Mapping[str, str] | None = None,
    ) -> GatewaySettings:
        if not self.exists:
            return GatewaySettings.from_environment(environment)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GatewaySettingsError(
                f"failed to read Gateway settings: {exc}"
            ) from exc
        return GatewaySettings.from_mapping(payload)

    def save(self, settings: GatewaySettings) -> None:
        _atomic_save_json(self.path, settings.to_dict())
        if os.name != "nt":
            self.path.chmod(0o600)


def merge_gateway_settings(
    current: GatewaySettings,
    payload: Mapping[str, Any],
) -> GatewaySettings:
    """Merge a redacted management request without accidentally erasing secrets."""

    required = {
        "realtime_model",
        "agent_protocol",
        "backend_model",
        "backend_permission_mode",
        "backend_ownership",
        "backend_url",
    }
    optional = {
        "dashscope_api_key",
        "clear_dashscope_api_key",
        "backend_credential",
        "clear_backend_credential",
    }
    if not isinstance(payload, Mapping):
        raise GatewaySettingsError("Gateway settings must be a JSON object")
    missing = required - set(payload)
    unknown = set(payload) - required - optional
    if missing:
        raise GatewaySettingsError(
            f"缺少 Gateway 配置字段：{', '.join(sorted(missing))}"
        )
    if unknown:
        raise GatewaySettingsError(
            f"不支持的 Gateway 配置字段：{', '.join(sorted(unknown))}"
        )
    for clear_name in ("clear_dashscope_api_key", "clear_backend_credential"):
        if clear_name in payload and not isinstance(payload[clear_name], bool):
            raise GatewaySettingsError(f"{clear_name} must be a boolean")
    if payload.get("clear_dashscope_api_key") and "dashscope_api_key" in payload:
        raise GatewaySettingsError("API Key 不能同时替换和清除")
    if payload.get("clear_backend_credential") and "backend_credential" in payload:
        raise GatewaySettingsError("后台令牌不能同时替换和清除")
    dashscope_api_key = current.dashscope_api_key
    if payload.get("clear_dashscope_api_key"):
        dashscope_api_key = ""
    elif "dashscope_api_key" in payload:
        dashscope_api_key = payload["dashscope_api_key"]
    backend_credential = current.backend_credential
    if payload.get("clear_backend_credential"):
        backend_credential = ""
    elif "backend_credential" in payload:
        backend_credential = payload["backend_credential"]
    agent_protocol = payload["agent_protocol"]
    if agent_protocol != "openclaw":
        backend_credential = ""
    return GatewaySettings(
        dashscope_api_key=dashscope_api_key,
        realtime_model=payload["realtime_model"],
        agent_protocol=agent_protocol,
        backend_model=payload["backend_model"],
        backend_permission_mode=payload["backend_permission_mode"],
        backend_ownership=payload["backend_ownership"],
        backend_url=payload["backend_url"],
        backend_credential=backend_credential,
    )


def apply_gateway_settings_to_environment(
    settings: GatewaySettings,
    environment: dict[str, str] | None = None,
) -> dict[str, str]:
    target = os.environ if environment is None else environment
    for name in MANAGED_GATEWAY_ENVIRONMENT:
        target.pop(name, None)
    target.update(settings.environment())
    return target


@dataclass(frozen=True)
class TouchInterruptSettings:
    enabled: bool = True
    sources: tuple[str, ...] = tuple(sorted(DEFAULT_TOUCH_INTERRUPT_SOURCES))
    debounce_ms: int = DEFAULT_TOUCH_INTERRUPT_DEBOUNCE_MS

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TouchInterruptSettingsError("enabled must be a boolean")
        if not isinstance(self.sources, tuple) or not self.sources:
            raise TouchInterruptSettingsError("sources must be a non-empty array")
        normalized = tuple(dict.fromkeys(self.sources))
        if (
            normalized != self.sources
            or any(not isinstance(source, str) for source in self.sources)
            or not set(self.sources) <= SUPPORTED_TOUCH_INTERRUPT_SOURCES
        ):
            raise TouchInterruptSettingsError(
                "sources supports only back_touch and screen_touch without duplicates"
            )
        _validate_touch_integer(
            "debounce_ms", self.debounce_ms, minimum=100, maximum=3000
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TouchInterruptSettings":
        supported = {"enabled", "sources", "debounce_ms"}
        if not isinstance(payload, Mapping):
            raise TouchInterruptSettingsError("touch settings must be a JSON object")
        if set(payload) != supported:
            raise TouchInterruptSettingsError(
                "touch settings require enabled, sources and debounce_ms"
            )
        sources = payload["sources"]
        if not isinstance(sources, list):
            raise TouchInterruptSettingsError("sources must be an array")
        return cls(
            enabled=payload["enabled"],
            sources=tuple(sources),
            debounce_ms=payload["debounce_ms"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "sources": list(self.sources),
            "debounce_ms": self.debounce_ms,
        }

    def environment(self) -> dict[str, str]:
        return {
            "QWEN_AGENT_TOUCH_INTERRUPT_ENABLED": "true" if self.enabled else "false",
            "QWEN_AGENT_TOUCH_INTERRUPT_SOURCES": ",".join(self.sources),
            "QWEN_AGENT_TOUCH_INTERRUPT_DEBOUNCE_MS": str(self.debounce_ms),
        }


class TouchInterruptSettingsStore:
    """Load and atomically save the local touch interrupt profile."""

    def __init__(self, path: Path | str = DEFAULT_TOUCH_INTERRUPT_SETTINGS_FILE) -> None:
        self.path = Path(path).expanduser().resolve()

    @classmethod
    def from_environment(cls) -> "TouchInterruptSettingsStore":
        configured = os.environ.get(TOUCH_INTERRUPT_SETTINGS_ENV, "").strip()
        return cls(configured or DEFAULT_TOUCH_INTERRUPT_SETTINGS_FILE)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> TouchInterruptSettings:
        if not self.exists:
            return TouchInterruptSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TouchInterruptSettingsError(
                f"failed to read touch interrupt settings: {exc}"
            ) from exc
        return TouchInterruptSettings.from_mapping(payload)

    def save(self, settings: TouchInterruptSettings) -> None:
        _atomic_save_json(self.path, settings.to_dict())


@dataclass(frozen=True)
class VadSettings:
    enabled: bool = True
    start_rms: int = DEFAULT_VAD_START_RMS
    stop_rms: int = DEFAULT_VAD_STOP_RMS
    start_frames: int = DEFAULT_VAD_START_FRAMES
    silence_ms: int = DEFAULT_VAD_SILENCE_MS
    pre_roll_ms: int = DEFAULT_VAD_PRE_ROLL_MS
    max_utterance_ms: int = DEFAULT_VAD_MAX_UTTERANCE_MS

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise VadSettingsError("enabled must be a boolean")
        _validate_integer("start_rms", self.start_rms, minimum=1, maximum=32767)
        _validate_integer("stop_rms", self.stop_rms, minimum=0, maximum=32767)
        _validate_integer("start_frames", self.start_frames, minimum=1, maximum=20)
        _validate_integer("silence_ms", self.silence_ms, minimum=120, maximum=3000)
        _validate_integer("pre_roll_ms", self.pre_roll_ms, minimum=60, maximum=2000)
        _validate_integer(
            "max_utterance_ms",
            self.max_utterance_ms,
            minimum=1000,
            maximum=60000,
        )
        if self.stop_rms > self.start_rms:
            raise VadSettingsError("stop_rms must not exceed start_rms")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "VadSettings":
        if not isinstance(payload, Mapping):
            raise VadSettingsError("VAD settings must be a JSON object")
        unknown = set(payload) - _SUPPORTED_FIELDS
        if unknown:
            raise VadSettingsError(
                f"unsupported VAD settings: {', '.join(sorted(unknown))}"
            )
        missing = _SUPPORTED_FIELDS - set(payload)
        if missing:
            raise VadSettingsError(
                f"missing VAD settings: {', '.join(sorted(missing))}"
            )
        return cls(**{field: payload[field] for field in _SUPPORTED_FIELDS})

    def to_dict(self) -> dict[str, bool | int]:
        return asdict(self)

    def environment(self) -> dict[str, str]:
        return {
            "QWEN_AGENT_VAD_ENABLED": "true" if self.enabled else "false",
            "QWEN_AGENT_VAD_START_RMS": str(self.start_rms),
            "QWEN_AGENT_VAD_STOP_RMS": str(self.stop_rms),
            "QWEN_AGENT_VAD_START_FRAMES": str(self.start_frames),
            "QWEN_AGENT_VAD_SILENCE_MS": str(self.silence_ms),
            "QWEN_AGENT_VAD_PRE_ROLL_MS": str(self.pre_roll_ms),
            "QWEN_AGENT_VAD_MAX_UTTERANCE_MS": str(self.max_utterance_ms),
        }


class VadSettingsStore:
    """Load and atomically save the local VAD profile."""

    def __init__(self, path: Path | str = DEFAULT_VAD_SETTINGS_FILE) -> None:
        self.path = Path(path).expanduser().resolve()

    @classmethod
    def from_environment(cls) -> "VadSettingsStore":
        configured = os.environ.get(VAD_SETTINGS_ENV, "").strip()
        return cls(configured or DEFAULT_VAD_SETTINGS_FILE)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> VadSettings:
        if not self.exists:
            return VadSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VadSettingsError(f"failed to read VAD settings: {exc}") from exc
        return VadSettings.from_mapping(payload)

    def save(self, settings: VadSettings) -> None:
        _atomic_save_json(self.path, settings.to_dict())


def _atomic_save_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(f"{serialized}\n")
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def apply_vad_settings_to_environment(store: VadSettingsStore) -> VadSettings:
    settings = store.load()
    for name, value in settings.environment().items():
        os.environ[name] = value
    return settings


def apply_touch_interrupt_settings_to_environment(
    store: TouchInterruptSettingsStore,
) -> TouchInterruptSettings:
    settings = store.load()
    for name, value in settings.environment().items():
        os.environ[name] = value
    return settings


def _validate_integer(name: str, value: object, *, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VadSettingsError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise VadSettingsError(f"{name} must be between {minimum} and {maximum}")


def _validate_touch_integer(
    name: str, value: object, *, minimum: int, maximum: int
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TouchInterruptSettingsError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise TouchInterruptSettingsError(
            f"{name} must be between {minimum} and {maximum}"
        )


def _validate_gateway_text(name: str, value: object, *, maximum: int) -> None:
    if not isinstance(value, str):
        raise GatewaySettingsError(f"{name} must be a string")
    if len(value) > maximum:
        raise GatewaySettingsError(f"{name} exceeds {maximum} characters")
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise GatewaySettingsError(f"{name} contains invalid whitespace")


def _validate_backend_url(value: str) -> None:
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise GatewaySettingsError(f"外部后台地址无效：{exc}") from exc
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
        raise GatewaySettingsError("外部后台地址只支持 HTTP、HTTPS、WS 或 WSS")
    if parsed.username or parsed.password:
        raise GatewaySettingsError(
            "外部后台地址不能包含用户名或密码，请使用独立令牌"
        )
    if parsed.query or parsed.fragment:
        raise GatewaySettingsError(
            "外部后台地址不能包含查询参数或片段，请使用独立令牌"
        )
    if port is not None and not 1 <= port <= 65535:
        raise GatewaySettingsError("外部后台地址端口必须在 1 到 65535 之间")
