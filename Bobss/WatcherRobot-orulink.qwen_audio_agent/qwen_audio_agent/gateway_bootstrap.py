"""Install and supervise the pinned local Qwen Audio Agent Gateway."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CONTRACT_FILE = Path(__file__).parents[1] / "runtime-dependencies.json"
DEFAULT_RUNTIME_DIR = Path(__file__).parents[2] / "runtime" / "qwen-gateway"
DEFAULT_NPM_REGISTRY = "https://registry.npmjs.org/"
DEFAULT_START_TIMEOUT_SECONDS = 45.0
SUPPORTED_SERVICE_FIELDS = frozenset(
    {
        "id",
        "package_manager",
        "package",
        "version",
        "integrity",
        "command",
        "health_url",
        "node",
        "npm",
    }
)
PINNED_SERVICE_VALUES = {
    "id": "qwen-audio-agent-gateway",
    "package_manager": "npm",
    "package": "qwen-audio-agent",
    "command": "qwenaudio",
    "health_url": "http://127.0.0.1:3101/api/health",
}


class GatewayBootstrapError(RuntimeError):
    """Raised when the pinned Gateway cannot be installed or started safely."""


@dataclass(frozen=True)
class GatewayDependency:
    package: str
    version: str
    integrity: str
    health_url: str
    node_requirement: str
    npm_requirement: str

    @property
    def specifier(self) -> str:
        return f"{self.package}@{self.version}"


def load_gateway_dependency(path: Path = DEFAULT_CONTRACT_FILE) -> GatewayDependency:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GatewayBootstrapError(f"cannot read runtime dependency contract: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "services"}:
        raise GatewayBootstrapError("runtime dependency contract has unknown fields")
    if payload["schema_version"] != 1:
        raise GatewayBootstrapError("unsupported runtime dependency schema")
    services = payload["services"]
    if not isinstance(services, list) or len(services) != 1:
        raise GatewayBootstrapError("runtime dependency contract requires one service")
    service = services[0]
    if not isinstance(service, dict):
        raise GatewayBootstrapError("runtime dependency service must be an object")
    unknown = set(service) - SUPPORTED_SERVICE_FIELDS
    missing = SUPPORTED_SERVICE_FIELDS - set(service)
    if unknown:
        raise GatewayBootstrapError(f"runtime dependency has unknown fields: {sorted(unknown)}")
    if missing:
        raise GatewayBootstrapError(f"runtime dependency is missing fields: {sorted(missing)}")
    for key, expected in PINNED_SERVICE_VALUES.items():
        if service[key] != expected:
            raise GatewayBootstrapError(f"runtime dependency {key} must be {expected}")
    version = str(service["version"])
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise GatewayBootstrapError("runtime dependency version must be exact")
    integrity = str(service["integrity"])
    if not integrity.startswith("sha512-"):
        raise GatewayBootstrapError("runtime dependency integrity must use sha512")
    return GatewayDependency(
        package=str(service["package"]),
        version=version,
        integrity=integrity,
        health_url=str(service["health_url"]),
        node_requirement=str(service["node"]),
        npm_requirement=str(service["npm"]),
    )


class GatewayRuntimeManager:
    """Ensure one pinned loopback Gateway exists without installing globally."""

    def __init__(
        self,
        dependency: GatewayDependency,
        *,
        runtime_dir: Path = DEFAULT_RUNTIME_DIR,
        auto_install: bool = True,
        auto_start: bool = True,
        npm_registry: str = DEFAULT_NPM_REGISTRY,
        command_runner: Callable[..., Any] = subprocess.run,
        process_factory: Callable[..., Any] = subprocess.Popen,
        health_probe: Callable[[str], Mapping[str, Any] | None] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        wait: Callable[[float], None] = time.sleep,
        start_timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
    ) -> None:
        self.dependency = dependency
        self.runtime_dir = runtime_dir
        self.auto_install = auto_install
        self.auto_start = auto_start
        self.npm_registry = npm_registry
        self._command_runner = command_runner
        self._process_factory = process_factory
        self._health_probe = health_probe or _probe_health
        self._which = which
        self._wait = wait
        self._start_timeout_seconds = start_timeout_seconds
        self._process: Any | None = None

    @classmethod
    def from_environment(cls) -> "GatewayRuntimeManager":
        return cls(
            load_gateway_dependency(),
            runtime_dir=Path(
                os.environ.get("QWEN_AGENT_RUNTIME_DIR", str(DEFAULT_RUNTIME_DIR))
            ).expanduser(),
            auto_install=_environment_bool("QWEN_AGENT_GATEWAY_AUTO_INSTALL", True),
            auto_start=_environment_bool("QWEN_AGENT_GATEWAY_AUTO_START", True),
            npm_registry=_validated_registry(
                os.environ.get("QWEN_AGENT_NPM_REGISTRY", DEFAULT_NPM_REGISTRY)
            ),
        )

    @property
    def owns_process(self) -> bool:
        return self._process is not None

    def ensure_ready(self) -> str:
        if self._health_probe(self.dependency.health_url) is not None:
            return "reused"
        node = self._require_tool("node")
        npm = self._require_tool("npm")
        self._validate_tool_versions(node, npm)
        if not self.has_exact_install():
            if not self.auto_install:
                raise GatewayBootstrapError(
                    "Qwen Gateway is not installed. Enable "
                    "QWEN_AGENT_GATEWAY_AUTO_INSTALL or run: "
                    f"npm install --prefix {self.runtime_dir} --save-exact "
                    f"{self.dependency.specifier}"
                )
            self._install(npm)
        if not self.auto_start:
            raise GatewayBootstrapError(
                "Qwen Gateway is not running. Enable QWEN_AGENT_GATEWAY_AUTO_START "
                "or start the private qwenaudio CLI manually."
            )
        self._start(node)
        self._wait_until_ready()
        return "started"

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)

    def _require_tool(self, command: str) -> str:
        executable = self._which(command)
        if not executable:
            raise GatewayBootstrapError(
                f"{command} is required. Install Node.js 22.22.2+ or 24.15.0+."
            )
        return executable

    def _validate_tool_versions(self, node: str, npm: str) -> None:
        node_version = self._tool_version(node)
        npm_version = self._tool_version(npm)
        if not _node_version_supported(node_version):
            raise GatewayBootstrapError(
                f"Node.js {node_version} is incompatible; required "
                f"{self.dependency.node_requirement}."
            )
        if _major_version(npm_version) < 10:
            raise GatewayBootstrapError(
                f"npm {npm_version} is incompatible; required {self.dependency.npm_requirement}."
            )

    def _tool_version(self, executable: str) -> str:
        result = self._command_runner(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            shell=False,
        )
        return str(result.stdout).strip().removeprefix("v")

    def has_exact_install(self) -> bool:
        package_root = self._package_root()
        try:
            package = json.loads(package_root.joinpath("package.json").read_text(encoding="utf-8"))
            lockfile = json.loads(
                self.runtime_dir.joinpath("package-lock.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            return False
        locked_package = lockfile.get("packages", {}).get(
            f"node_modules/{self.dependency.package}", {}
        )
        return (
            package.get("version") == self.dependency.version
            and locked_package.get("version") == self.dependency.version
            and locked_package.get("integrity") == self.dependency.integrity
            and package_root.joinpath("cli", "bin", "qwenaudio.mjs").is_file()
        )

    def _install(self, npm: str) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        command = [
            npm,
            "install",
            "--prefix",
            str(self.runtime_dir),
            "--no-audit",
            "--no-fund",
            "--save-exact",
            "--registry",
            self.npm_registry,
            self.dependency.specifier,
        ]
        try:
            self._command_runner(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GatewayBootstrapError(f"failed to install {self.dependency.specifier}: {exc}") from exc
        if not self.has_exact_install():
            raise GatewayBootstrapError(
                f"npm did not produce the pinned {self.dependency.specifier} install"
            )

    def _start(self, node: str) -> None:
        cli = self._package_root() / "cli" / "bin" / "qwenaudio.mjs"
        environment = dict(os.environ)
        environment["HOST"] = "127.0.0.1"
        environment["PORT"] = "3101"
        _append_no_proxy(environment, "127.0.0.1", "localhost", "::1")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = self._process_factory(
            [node, str(cli), "gateway"],
            cwd=str(self.runtime_dir),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creationflags,
        )

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self._start_timeout_seconds
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                self.close()
                raise GatewayBootstrapError(
                    "Qwen Gateway exited during startup. Run the private qwenaudio CLI "
                    "manually to inspect its configuration and DASHSCOPE_API_KEY."
                )
            if self._health_probe(self.dependency.health_url) is not None:
                return
            self._wait(0.2)
        self.close()
        raise GatewayBootstrapError(
            "Qwen Gateway did not become reachable within 45 seconds. "
            "Check DASHSCOPE_API_KEY and the Gateway user configuration."
        )

    def _package_root(self) -> Path:
        return self.runtime_dir / "node_modules" / self.dependency.package


def _probe_health(url: str) -> Mapping[str, Any] | None:
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=1.5) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read(1024 * 1024).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
    except (OSError, URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("backend"), dict) else None


def _major_version(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except ValueError as exc:
        raise GatewayBootstrapError(f"invalid tool version: {version}") from exc


def _node_version_supported(version: str) -> bool:
    parts = version.split(".")
    try:
        major, minor, patch = (int(part) for part in parts[:3])
    except (ValueError, TypeError) as exc:
        raise GatewayBootstrapError(f"invalid Node.js version: {version}") from exc
    return (
        (major == 22 and (minor, patch) >= (22, 2))
        or (major == 24 and (minor, patch) >= (15, 0))
        or major >= 26
    )


def _environment_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise GatewayBootstrapError(f"{name} must be a boolean")


def _validated_registry(value: str) -> str:
    normalized = value.strip()
    if normalized != DEFAULT_NPM_REGISTRY:
        raise GatewayBootstrapError(
            f"QWEN_AGENT_NPM_REGISTRY must be {DEFAULT_NPM_REGISTRY}"
        )
    return normalized


def _append_no_proxy(environment: dict[str, str], *hosts: str) -> None:
    for key in ("NO_PROXY", "no_proxy"):
        existing = [part.strip() for part in environment.get(key, "").split(",") if part.strip()]
        environment[key] = ",".join(dict.fromkeys([*existing, *hosts]))
