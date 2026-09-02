"""Schedule safe restarts outside the SDK-managed Application process tree."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping
from urllib.request import Request, urlopen


RESTART_REQUEST_FILE_ENV = "QWEN_AGENT_RESTART_REQUEST_FILE"


class ServiceRestartError(RuntimeError):
    """Raised when a service restart cannot be safely scheduled."""


class ServiceRestartScheduler:
    """Notify the external supervisor, or restart this app in standalone mode."""

    def __init__(
        self,
        *,
        daemon_control_url: str,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._daemon_control_url = daemon_control_url.rstrip("/")
        self._environment = dict(os.environ if environment is None else environment)

    def schedule(self) -> None:
        request_file = self._environment.get(RESTART_REQUEST_FILE_ENV, "").strip()
        if request_file:
            self._write_supervisor_request(Path(request_file))
            return
        thread = threading.Thread(
            target=self._restart_application_after_response,
            name="qwen-application-restart",
            daemon=True,
        )
        thread.start()

    def _write_supervisor_request(self, requested_path: Path) -> None:
        path = requested_path.expanduser().resolve()
        if path.exists() and not path.is_file():
            raise ServiceRestartError("服务重启请求目标不是普通文件")
        temporary_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(
                    {
                        "action": "restart-application-stack",
                        "requested_at": time.time(),
                    },
                    temporary,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                temporary.write("\n")
                temporary_path = Path(temporary.name)
            if os.name != "nt":
                temporary_path.chmod(0o600)
            temporary_path.replace(path)
        except OSError as exc:
            raise ServiceRestartError(f"无法写入服务重启请求：{exc}") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

    def _restart_application_after_response(self) -> None:
        time.sleep(0.35)
        request = Request(
            f"{self._daemon_control_url}/daemon/application/restart",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5):  # noqa: S310 - validated loopback URL
                pass
        except OSError:
            # The Daemon may close the Application before a response is observed.
            return
