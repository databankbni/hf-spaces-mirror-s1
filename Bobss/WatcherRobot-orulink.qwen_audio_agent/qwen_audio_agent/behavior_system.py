"""Application-owned robot behavior state coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class BehaviorState(str, Enum):
    """User-visible product states rendered with v0.3.5 standard resources."""

    STARTING = "starting"
    READY = "ready"
    LISTENING = "listening"
    THINKING = "thinking"
    AGENT_WORKING = "agent_working"
    WAITING_USER = "waiting_user"
    SPEAKING = "speaking"
    SUCCESS = "success"
    RECOVERING = "recovering"
    ERROR = "error"


class BehaviorEvent(str, Enum):
    """Stable semantic events accepted from runtime and media services."""

    SESSION_CONNECTING = "session_connecting"
    SESSION_DISCONNECTED = "session_disconnected"
    SESSION_FAILED = "session_failed"
    GATEWAY_READY = "gateway_ready"
    VAD_MONITORING = "vad_monitoring"
    DEVICE_UNAVAILABLE = "device_unavailable"
    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"
    RESPONSE_STARTED = "response_started"
    AGENT_STARTED = "agent_started"
    PERMISSION_REQUESTED = "permission_requested"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    PLAYBACK_STARTED = "playback_started"
    PLAYBACK_ENDED = "playback_ended"
    PLAYBACK_FAILED = "playback_failed"
    PLAYBACK_INTERRUPTED = "playback_interrupted"


@dataclass(frozen=True)
class StatePresentation:
    domain: str
    resource_id: str


# Long-lived states use firmware behavior-state IDs so the device owns their
# lifecycle and UI arbitration. The terminal success state deliberately uses
# the raw official animation: the matching ``happy`` behavior also schedules a
# local sound effect, which can be captured by the microphone when VAD resumes.
STATE_PRESENTATION: dict[BehaviorState, StatePresentation] = {
    BehaviorState.STARTING: StatePresentation("behavior", "processing"),
    BehaviorState.READY: StatePresentation("behavior", "awake_idle"),
    BehaviorState.LISTENING: StatePresentation("behavior", "listening"),
    BehaviorState.THINKING: StatePresentation("behavior", "thinking"),
    BehaviorState.AGENT_WORKING: StatePresentation("behavior", "custom3"),
    BehaviorState.WAITING_USER: StatePresentation("behavior", "speechless"),
    BehaviorState.SPEAKING: StatePresentation("behavior", "speaking"),
    BehaviorState.SUCCESS: StatePresentation("animation", "happy"),
    BehaviorState.RECOVERING: StatePresentation("behavior", "disconnect"),
    BehaviorState.ERROR: StatePresentation("behavior", "error"),
}
DEFAULT_RENDER_START_TIMEOUT_SECONDS = 2.0


class RobotBehaviorStateMachine:
    """Derive visible state from readiness and ordered business events."""

    def __init__(self, *, requires_vad: bool = True) -> None:
        self.state = BehaviorState.STARTING
        self._requires_vad = requires_vad
        self._gateway_ready = False
        self._device_ready = not requires_vad

    @property
    def operational(self) -> bool:
        return self._gateway_ready and self._device_ready

    def transition(self, event: BehaviorEvent) -> BehaviorState:
        if event is BehaviorEvent.SESSION_CONNECTING:
            self._gateway_ready = False
            self._device_ready = not self._requires_vad
            self.state = BehaviorState.STARTING
            return self.state
        if event is BehaviorEvent.GATEWAY_READY:
            self._gateway_ready = True
            self.state = self._ready_or_current()
            return self.state
        if event is BehaviorEvent.VAD_MONITORING:
            self._device_ready = True
            if not self.operational:
                self.state = BehaviorState.STARTING
            else:
                # Background Agent tasks never own the foreground voice loop.
                self.state = BehaviorState.READY
            return self.state
        if event is BehaviorEvent.DEVICE_UNAVAILABLE:
            self._device_ready = False
            if self.state is not BehaviorState.ERROR:
                self.state = BehaviorState.RECOVERING
            return self.state
        if event in {
            BehaviorEvent.SESSION_DISCONNECTED,
            BehaviorEvent.SESSION_FAILED,
        }:
            self._gateway_ready = False
            self.state = BehaviorState.RECOVERING
            return self.state

        if (
            self.state is BehaviorState.ERROR
            and event is BehaviorEvent.SPEECH_STARTED
            and self.operational
        ):
            self.state = BehaviorState.LISTENING
            return self.state
        if self.state in {BehaviorState.RECOVERING, BehaviorState.ERROR}:
            return self.state

        if event is BehaviorEvent.RESPONSE_STARTED and self.state is BehaviorState.AGENT_WORKING:
            return self.state
        if event is BehaviorEvent.AGENT_STARTED and self.state in {
            BehaviorState.LISTENING,
            BehaviorState.SPEAKING,
        }:
            return self.state
        if event in {BehaviorEvent.AGENT_COMPLETED, BehaviorEvent.AGENT_FAILED}:
            # Terminal background events are announced by the voice layer. They
            # must not repaint an unrelated foreground turn or idle face.
            return self.state

        event_states = {
            BehaviorEvent.SPEECH_STARTED: BehaviorState.LISTENING,
            BehaviorEvent.SPEECH_ENDED: BehaviorState.THINKING,
            BehaviorEvent.RESPONSE_STARTED: BehaviorState.THINKING,
            BehaviorEvent.AGENT_STARTED: BehaviorState.AGENT_WORKING,
            BehaviorEvent.PERMISSION_REQUESTED: BehaviorState.WAITING_USER,
            BehaviorEvent.AGENT_COMPLETED: BehaviorState.THINKING,
            BehaviorEvent.AGENT_FAILED: BehaviorState.ERROR,
            BehaviorEvent.PLAYBACK_STARTED: BehaviorState.SPEAKING,
            BehaviorEvent.PLAYBACK_ENDED: BehaviorState.SUCCESS,
            BehaviorEvent.PLAYBACK_FAILED: BehaviorState.ERROR,
            BehaviorEvent.PLAYBACK_INTERRUPTED: BehaviorState.READY,
        }
        self.state = event_states[event]
        return self.state

    def force_error(self) -> BehaviorState:
        self.state = BehaviorState.ERROR
        return self.state

    def force_operational_state(self) -> BehaviorState:
        self.state = (
            BehaviorState.READY
            if self.operational
            else BehaviorState.RECOVERING
        )
        return self.state

    def _ready_or_current(self) -> BehaviorState:
        if self.operational:
            return BehaviorState.READY
        if self.state in {BehaviorState.RECOVERING, BehaviorState.ERROR}:
            return self.state
        return BehaviorState.STARTING


class RobotBehaviorSystem:
    """Serialize state decisions and render through public SDK domains."""

    def __init__(
        self,
        robot: Any,
        *,
        logger: Any | None = None,
        diagnostics: Any | None = None,
        requires_vad: bool = True,
        success_hold_seconds: float = 0.8,
        error_hold_seconds: float = 1.5,
        recovery_timeout_seconds: float = 15.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        render_start_timeout_seconds: float = DEFAULT_RENDER_START_TIMEOUT_SECONDS,
    ) -> None:
        self._robot = robot
        self._logger = logger
        self._diagnostics = diagnostics
        self._success_hold_seconds = success_hold_seconds
        self._error_hold_seconds = error_hold_seconds
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._sleep = sleep
        self._render_start_timeout_seconds = render_start_timeout_seconds
        self._machine = RobotBehaviorStateMachine(requires_vad=requires_vad)
        self._applied: StatePresentation | None = None
        self._applied_state: BehaviorState | None = None
        self._attempted: StatePresentation | None = None
        self._attempted_state: BehaviorState | None = None
        self._terminal_task: asyncio.Task[None] | None = None
        self._recovery_task: asyncio.Task[None] | None = None
        self._deferred_ready = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BehaviorState:
        return self._machine.state

    async def transition(self, event: BehaviorEvent) -> BehaviorState:
        async with self._lock:
            desired = self._machine.transition(event)

            if desired is not BehaviorState.RECOVERING:
                self._cancel_recovery_timeout()

            if self._terminal_active():
                if event is BehaviorEvent.SPEECH_STARTED:
                    self._cancel_terminal_hold()
                elif desired is BehaviorState.READY:
                    self._deferred_ready = True
                    return desired
                else:
                    self._cancel_terminal_hold()

            await self._apply(desired, event=event)
            if desired is BehaviorState.SUCCESS:
                self._start_terminal_hold(self._success_hold_seconds)
            elif desired is BehaviorState.ERROR and event in {
                BehaviorEvent.AGENT_FAILED,
                BehaviorEvent.PLAYBACK_FAILED,
            }:
                self._start_terminal_hold(self._error_hold_seconds)
            elif desired is BehaviorState.RECOVERING:
                self._start_recovery_timeout()
            return desired

    async def close(self) -> None:
        tasks = [self._terminal_task, self._recovery_task]
        self._terminal_task = None
        self._recovery_task = None
        for task in tasks:
            if task is not None:
                task.cancel()
        if any(task is not None for task in tasks):
            await asyncio.gather(
                *(task for task in tasks if task is not None),
                return_exceptions=True,
            )

    def _terminal_active(self) -> bool:
        return self._terminal_task is not None and not self._terminal_task.done()

    def _start_terminal_hold(self, seconds: float) -> None:
        self._cancel_terminal_hold()
        self._deferred_ready = False
        self._terminal_task = asyncio.create_task(
            self._release_terminal_state(seconds),
            name="qwen-agent-expression-hold",
        )

    def _cancel_terminal_hold(self) -> None:
        if self._terminal_task is not None:
            self._terminal_task.cancel()
        self._terminal_task = None
        self._deferred_ready = False

    async def _release_terminal_state(self, seconds: float) -> None:
        try:
            await self._sleep(seconds)
            async with self._lock:
                self._terminal_task = None
                self._deferred_ready = False
                desired = self._machine.force_operational_state()
                await self._apply(desired, event=None, force=True)
                if desired is BehaviorState.RECOVERING:
                    self._start_recovery_timeout()
        except asyncio.CancelledError:
            raise

    def _start_recovery_timeout(self) -> None:
        if self._recovery_task is not None and not self._recovery_task.done():
            return
        self._recovery_task = asyncio.create_task(
            self._expire_recovery(),
            name="qwen-agent-recovery-timeout",
        )

    def _cancel_recovery_timeout(self) -> None:
        if self._recovery_task is not None:
            self._recovery_task.cancel()
        self._recovery_task = None

    async def _expire_recovery(self) -> None:
        try:
            await self._sleep(self._recovery_timeout_seconds)
            async with self._lock:
                self._recovery_task = None
                if self._machine.state is not BehaviorState.RECOVERING:
                    return
                desired = self._machine.force_error()
                await self._apply(desired, event=None)
        except asyncio.CancelledError:
            raise

    async def _apply(
        self,
        state: BehaviorState,
        *,
        event: BehaviorEvent | None,
        force: bool = False,
    ) -> None:
        presentation = STATE_PRESENTATION[state]
        if not force and state is self._attempted_state and presentation == self._attempted:
            return
        self._attempted = presentation
        self._attempted_state = state
        domain = getattr(self._robot, presentation.domain, None)
        play = getattr(domain, "play", None)
        if not callable(play):
            self._applied = None
            self._applied_state = None
            self._log_warning(
                "机器人状态资源域不可用：state=%s domain=%s",
                state.value,
                presentation.domain,
            )
            return
        try:
            job = await asyncio.to_thread(play, presentation.resource_id)
            await self._wait_until_render_started(job)
        except Exception as exc:
            self._applied = None
            self._applied_state = None
            self._log_warning(
                "机器人状态切换失败：state=%s domain=%s resource=%s error=%s",
                state.value,
                presentation.domain,
                presentation.resource_id,
                self._exception_detail(exc),
            )
            if self._diagnostics is not None:
                detail = (
                    f"{state.value} / {presentation.domain}:{presentation.resource_id} / "
                    f"{self._exception_detail(exc)}"
                )
                self._diagnostics.set_status("behavior", "error", detail)
                self._diagnostics.record(
                    "behavior.render_failed",
                    detail=detail,
                    level="error",
                )
            return
        self._applied = presentation
        self._applied_state = state
        self._record_applied_state(state, presentation, event)

    async def _wait_until_render_started(self, job: Any) -> None:
        if not hasattr(job, "state"):
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._render_start_timeout_seconds
        while True:
            state = getattr(job.state, "value", str(job.state)).lower()
            if state in {"running", "completed"}:
                return
            if state in {"failed", "cancelled"}:
                reason = str(getattr(job, "reason", "") or state)
                raise RuntimeError(
                    f"animation job {getattr(job, 'id', '?')} {state}: {reason}"
                )
            if loop.time() >= deadline:
                raise TimeoutError(
                    f"animation job {getattr(job, 'id', '?')} remained {state}"
                )
            await asyncio.sleep(0.02)

    @staticmethod
    def _exception_detail(exc: Exception) -> str:
        message = str(exc).strip()
        return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    def _record_applied_state(
        self,
        state: BehaviorState,
        presentation: StatePresentation,
        event: BehaviorEvent | None,
    ) -> None:
        detail = (
            f"awake_idle={presentation.resource_id}"
            if state is BehaviorState.READY
            else f"{presentation.domain}={presentation.resource_id}"
        )
        diagnostics_state = (
            "ready"
            if state is BehaviorState.READY
            else "error" if state is BehaviorState.ERROR else "update"
        )
        if self._diagnostics is not None:
            self._diagnostics.set_status(
                "behavior",
                diagnostics_state,
                (
                    f"{state.value} / awake_idle:{presentation.resource_id}"
                    if state is BehaviorState.READY
                    else f"{state.value} / {presentation.domain}:{presentation.resource_id}"
                ),
            )
            self._diagnostics.record(
                f"behavior.{state.value}",
                detail=detail,
                level="error" if state is BehaviorState.ERROR else "ok",
            )
        if self._logger is not None:
            self._logger.info(
                "机器人状态：state=%s domain=%s resource=%s event=%s",
                state.value,
                presentation.domain,
                presentation.resource_id,
                event.value if event is not None else "timeout",
            )

    def _log_warning(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.warning(message, *args)
