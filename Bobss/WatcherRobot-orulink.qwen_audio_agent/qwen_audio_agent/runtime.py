"""Application-owned runtime loops for the Qwen Audio Agent bridge."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .behavior_system import BehaviorEvent, RobotBehaviorSystem
from .configuration import BridgeConfiguration
from .conversation import ConversationStateError
from .desktop_events import encode_desktop_gateway_event
from .diagnostics import DiagnosticsState
from .gateway_client import GatewayConnectionError, QwenGatewayClient
from .service import HalfDuplexBridgeService
from .triggers import handle_desktop_frame, handle_input_event


GatewayFactory = Callable[[BridgeConfiguration], Any]
ServiceFactory = Callable[..., Any]
DESKTOP_OUTPUT_QUEUE_SIZE = 64
DESKTOP_PROGRESS_INTERVAL_SECONDS = 5.0
SHUTDOWN_MEDIA_CLEANUP_TIMEOUT_SECONDS = 4.0
TERMINAL_TASK_EVENTS = {
    "task.completed",
    "task.failed",
    "task.cancelled",
}
ANONYMOUS_TASK_PROGRESS_KEY = "__anonymous_task__"


class BridgeApplicationRuntime:
    """Run one Gateway session and reconnect without changing Daemon routing."""

    def __init__(
        self,
        application: Any,
        configuration: BridgeConfiguration,
        *,
        gateway_factory: GatewayFactory | None = None,
        service_factory: ServiceFactory = HalfDuplexBridgeService,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        diagnostics: DiagnosticsState | None = None,
    ) -> None:
        self._application = application
        self._configuration = configuration
        self._gateway_factory = gateway_factory or _create_gateway
        self._service_factory = service_factory
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_desktop_progress_at: dict[str, float] = {}
        self._diagnostics = diagnostics
        self.last_service: Any | None = None
        self.last_behavior_system: RobotBehaviorSystem | None = None

    def should_forward_desktop_event(self, event: dict[str, Any]) -> bool:
        """Bound non-terminal progress traffic without hiding final state."""

        event_type = event.get("type")
        task = event.get("task")
        task_id = task.get("id") if isinstance(task, dict) else None
        task_key = (
            task_id
            if isinstance(task_id, str) and task_id
            else ANONYMOUS_TASK_PROGRESS_KEY
        )
        if event_type in TERMINAL_TASK_EVENTS:
            self._last_desktop_progress_at.pop(task_key, None)
            return True
        if event_type != "task.progress":
            return True
        now = self._monotonic()
        last_sent_at = self._last_desktop_progress_at.get(task_key)
        if (
            last_sent_at is not None
            and now - last_sent_at < DESKTOP_PROGRESS_INTERVAL_SECONDS
        ):
            return False
        self._last_desktop_progress_at[task_key] = now
        return True

    async def run_session(self) -> None:
        """Run a single connection until a loop fails or the task is cancelled."""

        gateway = self._gateway_factory(self._configuration)
        behavior_system = RobotBehaviorSystem(
            self._application.robot,
            logger=self._application.logger,
            diagnostics=self._diagnostics,
            requires_vad=self._configuration.vad_enabled,
        )
        self.last_behavior_system = behavior_system
        service_arguments: dict[str, Any] = {
            "logger": self._application.logger,
            "behavior_system": behavior_system,
        }
        if self._diagnostics is not None:
            service_arguments["diagnostics"] = self._diagnostics
        service = self._service_factory(
            self._application.robot,
            gateway,
            self._configuration,
            **service_arguments,
        )
        self.last_service = service
        tasks: set[asyncio.Task[None]] = set()
        desktop_output: asyncio.Queue[str] = asyncio.Queue(
            maxsize=DESKTOP_OUTPUT_QUEUE_SIZE
        )
        session_failed = False
        try:
            await behavior_system.transition(BehaviorEvent.SESSION_CONNECTING)
            self._set_diagnostics_status("application", "ready", "Application 运行中")
            self._set_diagnostics_status("gateway", "update", "正在连接本地 Gateway")
            self._record_diagnostics(
                "gateway.connecting",
                detail="连接本地 Realtime Gateway",
            )
            await gateway.connect()
            self._record_diagnostics(
                "gateway.connected",
                detail="Gateway WebSocket 已连接",
            )
            tasks = {
                asyncio.create_task(
                    self._gateway_loop(
                        gateway,
                        service,
                        desktop_output,
                    ),
                    name="qwen-agent-gateway",
                ),
                asyncio.create_task(
                    self._desktop_loop(service, desktop_output),
                    name="qwen-agent-desktop-input",
                ),
                asyncio.create_task(
                    self._desktop_output_loop(desktop_output),
                    name="qwen-agent-desktop-output",
                ),
                asyncio.create_task(
                    self._input_loop(service),
                    name="qwen-agent-device-input",
                ),
            }
            if self._configuration.vad_enabled:
                run_vad = getattr(service, "run_vad", None)
                if not callable(run_vad):
                    raise RuntimeError("Python VAD service is unavailable")
                tasks.add(
                    asyncio.create_task(
                        run_vad(),
                        name="qwen-agent-python-vad",
                    )
                )
            wait_for_failure = getattr(service, "wait_for_failure", None)
            if callable(wait_for_failure):
                tasks.add(
                    asyncio.create_task(
                        wait_for_failure(),
                        name="qwen-agent-media-health",
                    )
                )
            shutdown_task = asyncio.create_task(
                self._wait_for_application_shutdown(),
                name="qwen-agent-application-shutdown",
            )
            tasks.add(shutdown_task)
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown_task in done and self._shutdown_requested():
                return
            for task in done:
                error = task.exception()
                if error is not None:
                    raise error
            raise GatewayConnectionError("Qwen bridge loop ended unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception:
            session_failed = True
            await behavior_system.transition(BehaviorEvent.SESSION_FAILED)
            raise
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if self._shutdown_requested():
                    await asyncio.wait_for(
                        service.disconnect(),
                        timeout=SHUTDOWN_MEDIA_CLEANUP_TIMEOUT_SECONDS,
                    )
                else:
                    await service.disconnect()
            except asyncio.TimeoutError:
                self._application.logger.warning(
                    "Application 停止时设备媒体资源清理超时，继续关闭进程"
                )
            except Exception:
                self._application.logger.exception(
                    "Qwen 会话关闭时清理设备媒体资源失败"
                )
            self._set_diagnostics_status("gateway", "update", "会话中断，等待重连")
            self._set_diagnostics_status("conversation", "update", "等待 Gateway 恢复")
            self._record_diagnostics(
                "gateway.disconnected",
                detail="Realtime 会话结束，准备重连",
                level="update",
            )
            if not session_failed and not self._shutdown_requested():
                await behavior_system.transition(BehaviorEvent.SESSION_DISCONNECTED)
            await gateway.close()
            await behavior_system.close()

    async def run_forever(self) -> None:
        """Reconnect with capped exponential backoff until the Application stops."""

        delay_seconds = 1.0
        while not self._shutdown_requested():
            try:
                await self.run_session()
                delay_seconds = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set_diagnostics_status("gateway", "error", str(exc))
                self._record_diagnostics(
                    "gateway.error",
                    detail=str(exc),
                    level="error",
                )
                self._application.logger.warning(
                    "Qwen Gateway 会话中断，%.1f 秒后重连：%s",
                    delay_seconds,
                    exc,
                )
                await self._sleep_until_restart_or_shutdown(delay_seconds)
                delay_seconds = min(delay_seconds * 2.0, 30.0)

    def _shutdown_requested(self) -> bool:
        return bool(getattr(self._application, "shutdown_requested", False))

    async def _wait_for_application_shutdown(self) -> None:
        while not self._shutdown_requested():
            await asyncio.sleep(0.05)

    async def _sleep_until_restart_or_shutdown(self, delay_seconds: float) -> None:
        remaining = delay_seconds
        while remaining > 0 and not self._shutdown_requested():
            interval = min(0.1, remaining)
            await self._sleep(interval)
            remaining -= interval

    async def _gateway_loop(
        self,
        gateway: Any,
        service: Any,
        desktop_output: asyncio.Queue[str],
    ) -> None:
        while True:
            event = await gateway.receive()
            observable_event = self.should_forward_desktop_event(event)
            if observable_event:
                self._record_gateway_event(event)
                self._application.logger.info(
                    "收到 Qwen Gateway 事件：%s",
                    event.get("type", "unknown"),
                )
            desktop_frame = None
            if observable_event:
                desktop_frame = encode_desktop_gateway_event(event)
            if desktop_frame is not None:
                try:
                    desktop_output.put_nowait(desktop_frame)
                except asyncio.QueueFull:
                    self._application.logger.warning(
                        "Desktop 状态输出队列已满，丢弃 Qwen 事件：%s",
                        event.get("type", "unknown"),
                    )
            await service.handle_gateway_event(event)
            behavior_event = self._gateway_behavior_event(event)
            if behavior_event is not None:
                await self._transition_behavior(behavior_event)

    def _record_gateway_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "unknown")
        if event_type == "voice.ready":
            self._set_diagnostics_status("gateway", "ready", "Qwen realtime ready")
            self._set_diagnostics_status("conversation", "ready", "等待语音输入")
            self._record_diagnostics("gateway.ready", detail="Realtime 会话准备完成")
            return
        if event_type == "voice.connection":
            state = str(event.get("state") or "unknown")
            level = "error" if state in {"unavailable", "disconnected"} else "update"
            self._set_diagnostics_status("gateway", level, f"voice.connection={state}")
            self._record_diagnostics(
                "gateway.voice_connection",
                detail=f"state={state}",
                level=level,
            )
            return
        if event_type == "response.started":
            self._set_diagnostics_status("conversation", "update", "模型正在生成回复")
            self._record_diagnostics("response.started", detail="模型开始生成回复")
            return
        if event_type == "turn.started":
            self._record_diagnostics(
                "realtime.turn_started",
                detail="Realtime 已接受语音轮次",
            )
            return
        if event_type == "transcript.discard":
            reason = str(event.get("reason") or "empty_transcript")
            self._record_diagnostics(
                "realtime.transcript_discarded",
                detail=reason,
                level="error",
            )
            return
        if event_type == "error":
            detail = str(event.get("message") or "Realtime 未知错误")
            self._set_diagnostics_status("gateway", "error", detail)
            self._record_diagnostics(
                "realtime.error",
                detail=detail,
                level="error",
            )
            return
        if event_type.startswith("task."):
            task_state = event_type.removeprefix("task.")
            terminal = task_state in {"completed", "failed", "cancelled"}
            failed = task_state in {"failed", "cancelled"}
            status = "error" if failed else ("ready" if terminal else "update")
            self._set_diagnostics_status("agent", status, f"Agent {task_state}")
            self._record_diagnostics(
                f"agent.{task_state}",
                detail="Agent 任务状态更新",
                level="error" if failed else ("ok" if terminal else "update"),
            )

    @staticmethod
    def _gateway_behavior_event(event: dict[str, Any]) -> BehaviorEvent | None:
        event_type = str(event.get("type") or "")
        if event_type == "voice.ready":
            return BehaviorEvent.GATEWAY_READY
        if event_type == "response.started":
            return BehaviorEvent.RESPONSE_STARTED
        if not event_type.startswith("task."):
            return None
        task_state = event_type.removeprefix("task.")
        if task_state in {"started", "running"}:
            return BehaviorEvent.AGENT_STARTED
        if task_state in {"accepted", "progress", "delegated", "finalizing"}:
            return None
        if task_state == "permission.requested":
            return BehaviorEvent.PERMISSION_REQUESTED
        if task_state in {"completed", "failed", "cancelled"}:
            return None
        return None

    async def _transition_behavior(self, event: BehaviorEvent) -> None:
        if self.last_behavior_system is not None:
            await self.last_behavior_system.transition(event)

    def _set_diagnostics_status(self, component: str, state: str, detail: str) -> None:
        if self._diagnostics is not None:
            self._diagnostics.set_status(component, state, detail)

    def _record_diagnostics(
        self,
        stage: str,
        *,
        detail: str = "",
        level: str = "ok",
    ) -> None:
        if self._diagnostics is not None:
            self._diagnostics.record(stage, detail=detail, level=level)

    async def _input_loop(self, service: Any) -> None:
        inputs = self._application.robot.inputs
        while True:
            try:
                event = await asyncio.to_thread(inputs.wait, 0.5)
            except TimeoutError:
                await asyncio.sleep(0)
                continue
            try:
                await handle_input_event(
                    event,
                    service,
                    manual_enabled=not self._configuration.vad_enabled,
                )
            except ConversationStateError as exc:
                self._application.logger.info("忽略忙碌状态下的设备输入：%s", exc)

    async def _desktop_loop(
        self,
        service: Any,
        desktop_output: asyncio.Queue[str],
    ) -> None:
        desktop = self._application.desktop
        while True:
            try:
                frame = await desktop.receive(timeout=0.5)
            except TimeoutError:
                await asyncio.sleep(0)
                continue
            response = await handle_desktop_frame(
                frame,
                service,
                manual_enabled=not self._configuration.vad_enabled,
            )
            if response is not None:
                await desktop_output.put(
                    json.dumps(
                        response,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )

    async def _desktop_output_loop(
        self,
        desktop_output: asyncio.Queue[str],
    ) -> None:
        desktop = self._application.desktop
        while True:
            frame = await desktop_output.get()
            try:
                await desktop.send(frame)
            except Exception as exc:
                self._application.logger.warning(
                    "Qwen 状态事件发送 Desktop 失败：%s",
                    exc,
                )
            finally:
                desktop_output.task_done()


def _create_gateway(configuration: BridgeConfiguration) -> QwenGatewayClient:
    encoded_audio_bytes = ((configuration.max_response_bytes + 2) // 3) * 4
    return QwenGatewayClient(
        configuration.gateway_url,
        client_label=configuration.client_label,
        provider=configuration.provider,
        takeover=configuration.takeover,
        connect_timeout_seconds=configuration.connect_timeout_seconds,
        max_message_bytes=encoded_audio_bytes + 64 * 1024,
        wake_word_enabled=configuration.wake_word_enabled,
    )
