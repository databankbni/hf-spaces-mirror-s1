"""Device/Qwen media orchestration for reliable half-duplex conversation."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Any, Protocol

from watcherobot.errors import CommandError, WatcheRobotError

from .audio_buffer import AudioBufferError, ResponseAudioBuffer
from .behavior_system import BehaviorEvent, RobotBehaviorSystem
from .configuration import BridgeConfiguration
from .conversation import (
    ConversationState,
    ConversationStateError,
    HalfDuplexConversation,
)
from .diagnostics import DiagnosticsState
from .protocol import INPUT_SAMPLE_RATE_HZ, OUTPUT_SAMPLE_RATE_HZ, decode_audio_delta
from .vad import ThresholdVad


PCM_SAMPLE_WIDTH_BYTES = 2
PCM_CHANNELS = 1
MICROPHONE_FRAME_DURATION_MS = 60
MICROPHONE_FRAME_BYTES = (
    INPUT_SAMPLE_RATE_HZ
    * PCM_CHANNELS
    * PCM_SAMPLE_WIDTH_BYTES
    * MICROPHONE_FRAME_DURATION_MS
    // 1000
)
MAX_SUPPRESSED_RESPONSES = 32
MAX_STALE_RESPONSES = 64
VAD_MICROPHONE_QUEUE_SIZE = 16
MICROPHONE_CAPACITY_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
ACTIVE_AGENT_TASK_STATES = frozenset(
    {
        "accepted",
        "started",
        "running",
        "progress",
        "permission.requested",
        "delegated",
        "finalizing",
        "cancelling",
    }
)
TERMINAL_AGENT_TASK_STATES = frozenset({"completed", "failed", "cancelled"})
ANONYMOUS_AGENT_TASK_ID = "__anonymous_task__"


class GatewayPort(Protocol):
    async def set_input_enabled(self, enabled: bool) -> None: ...

    async def send_audio(self, pcm: bytes) -> None: ...

    async def commit_input(self) -> None: ...

    async def send_playback(self, event_type: str, response_id: str) -> None: ...

    async def enter_wake_word_sleep(self) -> None: ...

    async def send_interrupt(self) -> None: ...


class HalfDuplexBridgeService:
    """Coordinate SDK media APIs without teaching the Daemon business events."""

    def __init__(
        self,
        robot: Any,
        gateway: GatewayPort,
        configuration: BridgeConfiguration,
        *,
        logger: Any | None = None,
        diagnostics: DiagnosticsState | None = None,
        behavior_system: RobotBehaviorSystem | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._robot = robot
        self._gateway = gateway
        self._configuration = configuration
        self._logger = logger
        self._diagnostics = diagnostics
        self._behavior_system = behavior_system
        self._conversation = HalfDuplexConversation()
        self._audio_buffer = ResponseAudioBuffer(
            max_bytes=configuration.max_response_bytes
        )
        self._microphone_session: Any | None = None
        self._capture_task: asyncio.Task[None] | None = None
        self._playback_task: asyncio.Task[None] | None = None
        self._device_audio_active = False
        self._response_start_watchdog_task: asyncio.Task[None] | None = None
        self._waiting_for_response_start = False
        self._capture_stop = asyncio.Event()
        self._microphone_closed = asyncio.Event()
        self._microphone_closed.set()
        self._microphone_frames_sent = 0
        self._last_microphone_sequence = 0
        self._failure_event = asyncio.Event()
        self._background_failure: BaseException | None = None
        self._device_unavailable_reported = False
        self._microphone_busy_reported = False
        self._microphone_capacity_reject_count = 0
        self._disconnecting = False
        self._sleep = sleep
        self._suppressed_response_ids: set[str] = set()
        self._stale_response_ids: set[str] = set()
        self._stale_response_order: deque[str] = deque()
        self._active_agent_task_ids: set[str] = set()
        self._agent_interim_response_ids: set[str] = set()
        self._wake_word_sleeping = False
        self._operation_lock = asyncio.Lock()
        self._last_touch_interrupt_at = float("-inf")

    @property
    def conversation(self) -> HalfDuplexConversation:
        return self._conversation

    @property
    def audio_buffer(self) -> ResponseAudioBuffer:
        return self._audio_buffer

    def mark_gateway_ready(self, input_sample_rate_hz: int) -> None:
        if input_sample_rate_hz != INPUT_SAMPLE_RATE_HZ:
            raise ValueError(
                f"Qwen Gateway input rate must be {INPUT_SAMPLE_RATE_HZ} Hz"
            )
        was_disconnected = self._conversation.state is ConversationState.DISCONNECTED
        if was_disconnected:
            self._conversation.mark_connected()
        self._disconnecting = False
        self._set_status("conversation", "ready", "等待语音输入")
        if was_disconnected or self._microphone_session is None:
            self._set_status("device_audio", "update", "准备打开设备麦克风")

    async def enter_wake_word_sleep(self) -> None:
        """Move Gateway to local KWS sleep before streaming idle microphone PCM."""

        if not self._configuration.wake_word_enabled:
            return
        await self._gateway.enter_wake_word_sleep()
        self._wake_word_sleeping = True
        self._set_status("conversation", "ready", "等待唤醒词 watcher")
        self._record(
            "wake_word.sleeping",
            detail="PC 本地 sherpa-onnx 正在等待 watcher",
        )

    async def wait_for_failure(self) -> None:
        """Raise when an otherwise detached media worker fails."""

        await self._failure_event.wait()
        failure = self._background_failure
        if failure is None:
            raise RuntimeError("media worker stopped without a failure reason")
        raise RuntimeError("Qwen media worker failed") from failure

    async def start_listening(self) -> None:
        if self._configuration.vad_enabled:
            raise ConversationStateError(
                "manual microphone control is disabled while Python VAD is enabled"
            )
        async with self._operation_lock:
            if self._conversation.state is not ConversationState.READY:
                raise ConversationStateError(
                    "start_listening is invalid while state is "
                    f"{self._conversation.state.name}"
                )
            session = await asyncio.to_thread(
                self._robot.microphone.open_pcm,
                queue_size=64,
            )
            self._microphone_closed.clear()
            self._conversation.start_listening()
            try:
                await self._gateway.set_input_enabled(True)
            except Exception:
                await self._close_microphone_session(
                    session,
                    context="Gateway 输入启用失败",
                )
                self._microphone_closed.set()
                self._conversation.mark_disconnected()
                raise
            self._microphone_session = session
            self._capture_stop.clear()
            self._microphone_frames_sent = 0
            self._last_microphone_sequence = 0
            self._capture_task = asyncio.create_task(
                self._capture_microphone(session),
                name="qwen-agent-microphone-capture",
            )
            self._begin_turn("手动开始录音")
            self._set_status("device_audio", "ready", "麦克风采集中")
            self._set_status("conversation", "update", "正在接收语音")
            self._log_info("Qwen 麦克风采集开始：sample_rate_hz=%d", INPUT_SAMPLE_RATE_HZ)
            await self._express(BehaviorEvent.SPEECH_STARTED)

    async def run_vad(self) -> None:
        """Continuously monitor PCM and create turns from Python RMS thresholds."""

        if not self._configuration.vad_enabled:
            raise RuntimeError("Python VAD is disabled")
        while True:
            if self._conversation.state is not ConversationState.READY:
                await asyncio.sleep(0.05)
                continue
            await self._monitor_one_vad_turn()

    async def stop_listening(self) -> None:
        async with self._operation_lock:
            if self._conversation.state is not ConversationState.LISTENING:
                raise ConversationStateError(
                    "stop_listening is invalid while state is "
                    f"{self._conversation.state.name}"
                )
            session = self._microphone_session
            capture_task = self._capture_task
            # The user has released push-to-talk. Accept and buffer a response
            # as soon as the explicit input commit reaches the Gateway.
            self._conversation.finish_listening()
            self._capture_stop.set()
            try:
                if capture_task is not None:
                    await asyncio.wait_for(
                        capture_task,
                        timeout=min(
                            5.0,
                            self._configuration.connect_timeout_seconds,
                        ),
                    )
            finally:
                if session is not None:
                    await self._close_microphone_session(
                        session,
                        context="停止监听",
                    )
                self._microphone_session = None
                self._capture_task = None
            self._waiting_for_response_start = True
            await self._gateway.commit_input()
            self._start_response_watchdog()
            await self._gateway.set_input_enabled(False)
            self._microphone_closed.set()
            self._record(
                "capture.upload_finished",
                detail="上行音频发送完成",
                metrics={"frames": self._microphone_frames_sent},
            )
            self._set_status("device_audio", "update", "等待回复音频")
            self._set_status("conversation", "update", "等待模型回复")
            await self._express(BehaviorEvent.SPEECH_ENDED)

    async def handle_gateway_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "response.started":
            self._waiting_for_response_start = False
            self._cancel_response_start_watchdog()
        if isinstance(event_type, str) and event_type.startswith("task."):
            self._update_agent_activity(event)
            task_state = event_type.removeprefix("task.")
            if (
                task_state in {"failed", "cancelled"}
                and not self._active_agent_task_ids
                and self._conversation.state is ConversationState.WAITING_RESPONSE
            ):
                self._conversation.cancel_response()
                self._set_status("conversation", "error", f"Agent {task_state}")
                self._end_turn(
                    "agent.failed",
                    detail=f"Agent {task_state}",
                    level="error",
                )
        if event_type == "voice.ready":
            self.mark_gateway_ready(int(event.get("inputSampleRate", 0)))
            return
        if event_type == "voice.sleep":
            sleep_state = str(event.get("state") or "")
            if sleep_state == "detected":
                self._wake_word_sleeping = False
                self._set_status("conversation", "ready", "已检测到 watcher，等待语音")
                self._record(
                    "wake_word.detected",
                    detail="PC 本地 sherpa-onnx 检测到 watcher",
                )
            elif sleep_state == "sleeping":
                self._wake_word_sleeping = True
            return
        if event_type == "audio.delta":
            delta = decode_audio_delta(event)
            if delta.response_id in self._stale_response_ids:
                return
            if self._conversation.state in (
                ConversationState.LISTENING,
                ConversationState.BUFFERED_AUDIO,
                ConversationState.PLAYING,
            ):
                if (
                    delta.response_id not in self._suppressed_response_ids
                    and len(self._suppressed_response_ids)
                    >= MAX_SUPPRESSED_RESPONSES
                ):
                    raise AudioBufferError("too many suppressed Qwen responses")
                self._suppressed_response_ids.add(delta.response_id)
                return
            if self._audio_buffer.active_response_id is None:
                self._conversation.begin_audio_response(delta.response_id)
                if self._active_agent_task_ids:
                    self._agent_interim_response_ids.add(delta.response_id)
                self._record(
                    "response.audio_started",
                    detail="收到首帧回复音频",
                    response_id=delta.response_id,
                )
                self._set_status("conversation", "update", "正在接收回复音频")
            try:
                self._audio_buffer.append(
                    delta.response_id,
                    event["audio"],
                    sample_rate_hz=delta.sample_rate_hz,
                )
            except AudioBufferError as exc:
                # A malformed or oversized response is scoped to this media
                # item.  Reconnecting the Gateway here also tears down the
                # device microphone and used to leave older firmware unable
                # to acquire it again.  Tombstone only the bad response and
                # return the conversation to READY for the next turn.
                self._remember_stale_response(delta.response_id)
                self._log_warning(
                    "取消异常 Qwen 音频响应并保持会话：response_id=%s error=%s",
                    delta.response_id,
                    exc,
                )
                await self.cancel_current_response(str(exc))
            return
        if event_type == "audio.done":
            response_id = event.get("responseId")
            if not isinstance(response_id, str) or not response_id.strip():
                raise AudioBufferError("audio.done responseId is required")
            response_id = response_id.strip()
            if response_id in self._stale_response_ids:
                return
            if response_id in self._suppressed_response_ids:
                self._suppressed_response_ids.remove(response_id)
                self._remember_stale_response(response_id)
                await self._gateway.send_playback(
                    "playback.cancelled",
                    response_id,
                )
                return
            if self._audio_buffer.active_response_id is None:
                # Tool-only Realtime responses legitimately contain no audio
                # deltas.  Keep waiting for the asynchronous Agent result;
                # treating this audio.done as a media protocol failure would
                # disconnect the Gateway before its announcement can arrive.
                self._remember_stale_response(response_id)
                if self._logger is not None:
                    self._logger.info(
                        "Qwen 响应无音频结束，继续等待 Agent 结果：response_id=%s",
                        response_id,
                    )
                return
            try:
                pcm = self._audio_buffer.finish(response_id)
            except AudioBufferError as exc:
                # A terminal event for a different/invalid response must not
                # poison the active Gateway session.  Keep any valid active
                # response intact and reject only this terminal event.
                self._remember_stale_response(response_id)
                self._log_warning(
                    "忽略异常 Qwen 音频结束事件：response_id=%s error=%s",
                    response_id,
                    exc,
                )
                await self._gateway.send_playback(
                    "playback.cancelled",
                    response_id,
                )
                return
            # A completed Gateway response is single-use. Tombstone it before
            # the detached playback worker runs so late deltas cannot race the
            # transition back to READY and start a second playback.
            self._remember_stale_response(response_id)
            self._conversation.finish_audio_response(response_id)
            self._record(
                "response.audio_finished",
                detail="回复音频接收完成",
                response_id=response_id,
                metrics={"bytes": len(pcm)},
            )
            if self._playback_task is not None:
                raise RuntimeError("a device playback worker is already active")
            self._playback_task = asyncio.create_task(
                self._play_response_worker(response_id, pcm),
                name=f"qwen-agent-playback-{response_id}",
            )
            return
        if event_type == "playback.clear":
            await self.cancel_current_response(
                str(event.get("reason") or "gateway_playback_clear")
            )
            return
        if event_type == "voice.connection" and event.get("state") in (
            "unavailable",
            "disconnected",
        ):
            if self._diagnostics is not None and self._diagnostics.active_turn_id is not None:
                self._end_turn(
                    "gateway.interrupted",
                    detail=f"Realtime 连接中断：{event.get('state')}",
                    level="error",
                )
            await self.disconnect()

    async def cancel_current_response(self, reason: str = "cancelled") -> None:
        del reason
        async with self._operation_lock:
            active_response_id = self._conversation.active_response_id
            playback_task = self._playback_task
            stale_candidates = {
                active_response_id,
                self._audio_buffer.active_response_id,
                *self._suppressed_response_ids,
            }
            for candidate in stale_candidates:
                if candidate:
                    self._remember_stale_response(candidate)
            if playback_task is not None:
                playback_task.cancel()
            if self._conversation.state in (
                ConversationState.BUFFERING_AUDIO,
                ConversationState.BUFFERED_AUDIO,
                ConversationState.PLAYING,
            ):
                await self._stop_device_audio(context="取消当前回复")
            if playback_task is not None:
                await asyncio.gather(playback_task, return_exceptions=True)
                if self._playback_task is playback_task:
                    self._playback_task = None
            self._audio_buffer.cancel()
            self._conversation.cancel_response()
            if active_response_id:
                await self._gateway.send_playback(
                    "playback.cancelled", active_response_id
                )

    async def handle_touch_interrupt(
        self,
        *,
        source: str,
        action: str,
        timestamp_ms: int | None = None,
    ) -> bool:
        """Interrupt foreground device playback without cancelling Agent work."""

        self._record(
            "input.touch.received",
            detail=f"source={source} action={action}",
            metrics={"source": source, "action": action, "timestamp_ms": timestamp_ms},
        )
        expected_action = "press" if source == "back_touch" else "tap"
        if not self._configuration.touch_interrupt_enabled:
            return self._ignore_touch_interrupt("disabled", source, action)
        if source not in self._configuration.touch_interrupt_sources:
            return self._ignore_touch_interrupt("source_disabled", source, action)
        if action != expected_action:
            return self._ignore_touch_interrupt("action_ignored", source, action)
        now = time.monotonic()
        debounce_seconds = self._configuration.touch_interrupt_debounce_ms / 1000
        if now - self._last_touch_interrupt_at < debounce_seconds:
            return self._ignore_touch_interrupt("debounced", source, action)
        async with self._operation_lock:
            if self._conversation.state is not ConversationState.PLAYING:
                return self._ignore_touch_interrupt(
                    f"state_{self._conversation.state.value}", source, action
                )
            self._last_touch_interrupt_at = now
            active_response_id = self._conversation.active_response_id
            playback_task = self._playback_task
            if active_response_id:
                self._remember_stale_response(active_response_id)
            self._record(
                "interrupt.accepted",
                detail="用户触摸打断设备播放",
                response_id=active_response_id,
                metrics={"source": source, "action": action},
            )
            if playback_task is not None:
                playback_task.cancel()
            self._record(
                "device.playback.stop_requested",
                detail="请求停止设备扬声器",
                response_id=active_response_id,
            )
            await self._stop_device_audio(context="用户触摸打断")
            self._record(
                "device.playback.stopped",
                detail="设备扬声器已停止",
                response_id=active_response_id,
            )
            if playback_task is not None:
                await asyncio.gather(playback_task, return_exceptions=True)
                if self._playback_task is playback_task:
                    self._playback_task = None
            self._agent_interim_response_ids.discard(active_response_id or "")
            self._audio_buffer.cancel()
            self._conversation.cancel_response()
            if active_response_id:
                await self._gateway.send_playback(
                    "playback.cancelled", active_response_id
                )
                self._record(
                    "gateway.playback_cancelled",
                    detail="已回报设备播放取消",
                    response_id=active_response_id,
                    metrics={"reason": "user_interruption"},
                )
            await self._gateway.send_interrupt()
            self._record(
                "gateway.interrupt_sent",
                detail="已请求 Qwen 取消当前前台回复",
                response_id=active_response_id,
            )
            self._waiting_for_response_start = False
            self._cancel_response_start_watchdog()
            self._set_status("device_audio", "ready", "VAD 即将恢复监听")
            self._set_status("conversation", "ready", "用户已打断，可继续对话")
            self._end_turn(
                "conversation.ready",
                detail="触摸打断完成，语音轮次已释放",
                response_id=active_response_id,
            )
            await self._express(BehaviorEvent.PLAYBACK_INTERRUPTED)
            return True

    def _ignore_touch_interrupt(self, reason: str, source: str, action: str) -> bool:
        self._record(
            "interrupt.ignored",
            detail=reason,
            level="update",
            metrics={"source": source, "action": action, "reason": reason},
        )
        return False

    async def disconnect(self) -> None:
        self._disconnecting = True
        async with self._operation_lock:
            self._waiting_for_response_start = False
            self._cancel_response_start_watchdog()
            self._capture_stop.set()
            session = self._microphone_session
            capture_task = self._capture_task
            playback_task = self._playback_task
            active_response_id = self._conversation.active_response_id
            stale_candidates = {
                active_response_id,
                self._audio_buffer.active_response_id,
                *self._suppressed_response_ids,
            }
            for candidate in stale_candidates:
                if candidate:
                    self._remember_stale_response(candidate)
            if capture_task is not None:
                capture_task.cancel()
            if session is not None:
                await self._close_microphone_session(
                    session,
                    context="断开会话",
                )
            self._microphone_closed.set()
            if capture_task is not None:
                await asyncio.gather(capture_task, return_exceptions=True)
            if playback_task is not None:
                playback_task.cancel()
            if self._conversation.state in (
                ConversationState.BUFFERED_AUDIO,
                ConversationState.PLAYING,
            ):
                await self._stop_device_audio(context="断开会话")
            if playback_task is not None:
                await asyncio.gather(playback_task, return_exceptions=True)
            self._microphone_session = None
            self._capture_task = None
            self._playback_task = None
            self._audio_buffer.cancel()
            self._suppressed_response_ids.clear()
            self._conversation.mark_disconnected()
            self._set_status("device_audio", "update", "设备媒体已释放")
            self._set_status("conversation", "update", "等待会话重连")
            if active_response_id:
                try:
                    await self._gateway.send_playback(
                        "playback.cancelled",
                        active_response_id,
                    )
                except Exception as exc:
                    self._log_warning(
                        "Qwen 断线清理回报播放取消失败：%s",
                        exc,
                    )

    async def _capture_microphone(self, session: Any) -> None:
        try:
            while not self._capture_stop.is_set():
                try:
                    frame = await asyncio.to_thread(session.read, 0.05)
                except TimeoutError:
                    continue
                except RuntimeError:
                    if self._capture_stop.is_set():
                        return
                    raise
                pcm = bytes(frame.data)
                if not pcm:
                    continue
                await self._gateway.send_audio(pcm)
                self._microphone_frames_sent += 1
                self._last_microphone_sequence = int(
                    getattr(frame, "sequence", self._last_microphone_sequence)
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._background_failure = exc
            self._log_warning("Qwen 麦克风采集后台任务失败：%s", exc)
            self._failure_event.set()

    async def _monitor_one_vad_turn(self) -> None:
        if self._disconnecting:
            return
        detector = ThresholdVad(
            start_rms=self._configuration.vad_start_rms,
            stop_rms=self._configuration.vad_stop_rms,
            start_frames=self._configuration.vad_start_frames,
            silence_frames=math.ceil(
                self._configuration.vad_silence_ms / MICROPHONE_FRAME_DURATION_MS
            ),
            pre_roll_frames=math.ceil(
                self._configuration.vad_pre_roll_ms / MICROPHONE_FRAME_DURATION_MS
            ),
            max_speech_frames=math.ceil(
                self._configuration.vad_max_utterance_ms
                / MICROPHONE_FRAME_DURATION_MS
            ),
        )
        try:
            async with self._operation_lock:
                if (
                    self._disconnecting
                    or self._conversation.state is not ConversationState.READY
                ):
                    return
                session = await asyncio.to_thread(
                    self._robot.microphone.open_pcm,
                    queue_size=VAD_MICROPHONE_QUEUE_SIZE,
                )
                self._microphone_session = session
                if self._device_unavailable_reported:
                    self._record(
                        "capture.device_recovered",
                        detail="设备麦克风已恢复",
                    )
                elif self._microphone_busy_reported:
                    self._record(
                        "capture.device_ready",
                        detail="设备麦克风资源已释放，恢复监听",
                    )
                self._device_unavailable_reported = False
                self._microphone_busy_reported = False
                self._microphone_capacity_reject_count = 0
                self._microphone_closed.clear()
                self._microphone_frames_sent = 0
                self._last_microphone_sequence = 0
        except (TimeoutError, RuntimeError, WatcheRobotError) as exc:
            # Device availability is independent of the cloud voice session.
            # Keep the Gateway connected while an offline/rebooting device is
            # reacquired, instead of rebuilding DashScope every backoff cycle.
            # SDK command rejections are also device-scoped here: an older
            # microphone session may still be draining after reconnect.
            error_detail = str(exc).strip() or type(exc).__name__
            is_no_capacity = (
                isinstance(exc, CommandError) and exc.reason == "no_capacity"
            )
            is_transient_busy = (
                isinstance(exc, CommandError) and exc.reason == "busy"
            ) or "rejected: busy" in error_detail.lower()
            if is_no_capacity or is_transient_busy:
                self._microphone_capacity_reject_count += 1
                retry_seconds = MICROPHONE_CAPACITY_RETRY_DELAYS_SECONDS[
                    min(
                        self._microphone_capacity_reject_count - 1,
                        len(MICROPHONE_CAPACITY_RETRY_DELAYS_SECONDS) - 1,
                    )
                ]
                if is_transient_busy:
                    status_detail = (
                        "麦克风资源正在排空，"
                        f"{retry_seconds:g} 秒后重试（连续 busy "
                        f"{self._microphone_capacity_reject_count} 次）"
                    )
                else:
                    status_detail = (
                        "麦克风资源被旧会话占用，"
                        f"{retry_seconds:g} 秒后重试（连续拒绝 "
                        f"{self._microphone_capacity_reject_count} 次）"
                    )
            else:
                self._microphone_capacity_reject_count = 0
                retry_seconds = 1.0
                status_detail = f"麦克风不可用：{error_detail}"
            self._log_warning(
                "Python VAD 等待设备麦克风恢复：%s；%.1f 秒后重试",
                exc,
                retry_seconds,
            )
            if is_transient_busy:
                self._set_status("device_audio", "update", status_detail)
                if not self._microphone_busy_reported:
                    self._record(
                        "capture.device_busy",
                        detail=error_detail,
                        level="update",
                        metrics={
                            "reason": "busy",
                            "retry_seconds": retry_seconds,
                            "reject_count": self._microphone_capacity_reject_count,
                        },
                    )
                    self._microphone_busy_reported = True
                await self._sleep(retry_seconds)
                return
            self._set_status("device_audio", "error", status_detail)
            if not self._device_unavailable_reported:
                await self._express(BehaviorEvent.DEVICE_UNAVAILABLE)
                self._record(
                    "capture.device_unavailable",
                    detail=error_detail,
                    level="error",
                    metrics={
                        "reason": "no_capacity" if is_no_capacity else error_detail,
                        "retry_seconds": retry_seconds,
                        "reject_count": self._microphone_capacity_reject_count,
                    },
                )
                self._device_unavailable_reported = True
            await self._sleep(retry_seconds)
            return
        turn_finished = False
        speech_started_at: float | None = None
        last_speech_rms = 0
        if self._diagnostics is not None:
            self._diagnostics.reset_rms()
        self._log_info(
            "Python VAD 监测开始：start_rms=%d stop_rms=%d",
            self._configuration.vad_start_rms,
            self._configuration.vad_stop_rms,
        )
        self._set_status("device_audio", "ready", "VAD 正在监听")
        self._set_status("conversation", "ready", "等待检测语音")
        self._record("capture.monitoring", detail="设备麦克风已进入 VAD 监听")
        await self._express(BehaviorEvent.VAD_MONITORING)
        if self._configuration.wake_word_enabled:
            await self.enter_wake_word_sleep()
        try:
            while self._conversation.state in (
                ConversationState.READY,
                ConversationState.LISTENING,
            ):
                try:
                    frame = await asyncio.to_thread(session.read, 0.05)
                except TimeoutError:
                    if (
                        speech_started_at is not None
                        and time.monotonic() - speech_started_at
                        >= self._configuration.vad_max_utterance_ms / 1000
                    ):
                        self._conversation.finish_listening()
                        turn_finished = True
                        await self._finish_vad_speech(
                            rms=last_speech_rms,
                            forced=True,
                            reason="wall_clock_timeout",
                        )
                        break
                    continue
                except RuntimeError:
                    if self._microphone_session is not session:
                        return
                    raise
                pcm = bytes(frame.data)
                if not pcm:
                    continue
                if self._wake_word_sleeping:
                    await self._gateway.send_audio(pcm)
                    continue
                decision = detector.process(pcm)
                if self._diagnostics is not None:
                    self._diagnostics.update_rms(
                        decision.rms,
                        in_speech=detector.in_speech,
                    )
                if decision.started:
                    speech_started_at = time.monotonic()
                    last_speech_rms = decision.rms
                    try:
                        self._conversation.start_listening()
                    except ConversationStateError:
                        break
                    await self._gateway.set_input_enabled(True)
                    self._begin_turn(
                        "Python VAD 检测到语音",
                        metrics={
                            "rms": decision.rms,
                            "pre_roll_frames": len(decision.audio_frames),
                        },
                    )
                    self._set_status("device_audio", "ready", "麦克风采集中")
                    self._set_status("conversation", "update", "正在接收语音")
                    self._log_info(
                        "Python VAD 检测到语音：rms=%d pre_roll_frames=%d",
                        decision.rms,
                        len(decision.audio_frames),
                    )
                    await self._express(BehaviorEvent.SPEECH_STARTED)
                if self._conversation.state is ConversationState.LISTENING:
                    last_speech_rms = decision.rms
                    for audio_frame in decision.audio_frames:
                        await self._gateway.send_audio(audio_frame)
                        self._microphone_frames_sent += 1
                    self._last_microphone_sequence = int(
                        getattr(frame, "sequence", self._last_microphone_sequence)
                    )
                if decision.ended:
                    self._conversation.finish_listening()
                    turn_finished = True
                    await self._finish_vad_speech(
                        rms=decision.rms,
                        forced=decision.forced,
                    )
                    break
        finally:
            await self._close_microphone_session(
                session,
                context="结束 VAD 监听",
            )
            if self._microphone_session is session:
                self._microphone_session = None
            if not turn_finished:
                self._microphone_closed.set()
        if turn_finished:
            self._waiting_for_response_start = True
            await self._gateway.commit_input()
            self._start_response_watchdog()
            await self._gateway.set_input_enabled(False)
            self._microphone_closed.set()
            self._record(
                "capture.upload_finished",
                detail="上行音频发送完成",
                metrics={"frames": self._microphone_frames_sent},
            )
            self._set_status("device_audio", "update", "等待回复音频")
            self._set_status("conversation", "update", "等待模型回复")

    async def _finish_vad_speech(
        self,
        *,
        rms: int,
        forced: bool,
        reason: str | None = None,
    ) -> None:
        self._log_info(
            "Python VAD 检测到语音结束：rms=%d forced=%d reason=%s",
            rms,
            1 if forced else 0,
            reason or "threshold",
        )
        metrics: dict[str, Any] = {"rms": rms, "forced": forced}
        if reason is not None:
            metrics["reason"] = reason
        self._record(
            "capture.speech_ended",
            detail="Python VAD 检测到语音结束",
            metrics=metrics,
        )
        await self._express(BehaviorEvent.SPEECH_ENDED)

    def _start_response_watchdog(self) -> None:
        self._cancel_response_start_watchdog()
        if not self._waiting_for_response_start:
            return
        self._response_start_watchdog_task = asyncio.create_task(
            self._wait_for_response_start(),
            name="qwen-agent-response-start-watchdog",
        )

    def _cancel_response_start_watchdog(self) -> None:
        task = self._response_start_watchdog_task
        self._response_start_watchdog_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _wait_for_response_start(self) -> None:
        try:
            await asyncio.sleep(self._configuration.response_start_timeout_seconds)
            if (
                not self._waiting_for_response_start
                or self._conversation.state is not ConversationState.WAITING_RESPONSE
            ):
                return
            self._waiting_for_response_start = False
            timeout = TimeoutError(
                "Realtime did not start a response after the input commit"
            )
            self._set_status("device_audio", "error", "等待回复超时")
            self._set_status("conversation", "error", "Realtime 未开始回复")
            self._end_turn(
                "response.timeout",
                detail="显式提交后未收到模型首个响应",
                level="error",
            )
            self._background_failure = timeout
            self._failure_event.set()
        finally:
            if self._response_start_watchdog_task is asyncio.current_task():
                self._response_start_watchdog_task = None

    async def _play_response(self, response_id: str, pcm: bytes) -> None:
        self._log_info(
            "Qwen 回复开始下发设备：response_id=%s bytes=%d",
            response_id,
            len(pcm),
        )
        self._record(
            "playback.queued",
            detail="回复音频准备下发设备",
            response_id=response_id,
            metrics={"bytes": len(pcm)},
        )
        try:
            # Reserve cleanup ownership before handing work to a thread. If
            # the coroutine is cancelled while play_pcm is still returning,
            # disconnect must still issue one best-effort stop.
            self._device_audio_active = True
            playback = await asyncio.to_thread(
                self._robot.audio.play_pcm,
                pcm,
                sample_rate_hz=OUTPUT_SAMPLE_RATE_HZ,
                channels=PCM_CHANNELS,
                sample_width_bytes=PCM_SAMPLE_WIDTH_BYTES,
            )
            await self._wait_for_playback_running(playback)
            self._conversation.mark_playback_started(response_id)
            self._set_status("device_audio", "ready", "设备正在播放回复")
            self._set_status("conversation", "update", "正在播放回复")
            self._record(
                "playback.started",
                detail="设备开始播放回复",
                response_id=response_id,
            )
            await self._express(BehaviorEvent.PLAYBACK_STARTED)
            await self._gateway.send_playback("playback.started", response_id)
            await asyncio.to_thread(
                playback.wait,
                self._configuration.response_timeout_seconds,
            )
            self._device_audio_active = False
            agent_interim_response = response_id in self._agent_interim_response_ids
            self._agent_interim_response_ids.discard(response_id)
            self._conversation.mark_playback_ended(
                response_id,
                await_more=False,
            )
            await self._gateway.send_playback("playback.ended", response_id)
            if agent_interim_response:
                self._set_status("device_audio", "ready", "VAD 即将恢复监听")
                self._set_status("conversation", "ready", "任务已下放，可继续语音交互")
                self._end_turn(
                    "playback.task_detached",
                    detail="任务已转入后台执行，语音轮次已释放",
                    response_id=response_id,
                )
                self._log_info(
                    "Qwen 任务提示播放完成，语音轮次已释放：response_id=%s",
                    response_id,
                )
                await self._express(BehaviorEvent.PLAYBACK_ENDED)
                return
            self._set_status("device_audio", "ready", "VAD 即将恢复监听")
            self._set_status("conversation", "ready", "本轮对话完成")
            self._end_turn(
                "playback.ended",
                detail="设备播放完成",
                response_id=response_id,
            )
            self._log_info("Qwen 回复播放完成：response_id=%s", response_id)
            await self._express(BehaviorEvent.PLAYBACK_ENDED)
        except Exception:
            self._agent_interim_response_ids.discard(response_id)
            await self._stop_device_audio(context="失败播放清理")
            self._conversation.cancel_response()
            await self._gateway.send_playback("playback.cancelled", response_id)
            self._set_status("device_audio", "error", "设备播放失败")
            self._set_status("conversation", "error", "本轮回复未完成")
            self._end_turn(
                "playback.failed",
                detail="设备播放失败",
                level="error",
                response_id=response_id,
            )
            await self._express(BehaviorEvent.PLAYBACK_FAILED)
            raise

    async def _play_response_worker(self, response_id: str, pcm: bytes) -> None:
        current_task = asyncio.current_task()
        try:
            # A very short response can complete while stop_listening() is
            # still draining the recorder.  Preserve strict half-duplex by
            # waiting until the device microphone has closed and input is muted.
            await self._microphone_closed.wait()
            await self._play_response(response_id, pcm)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._log_warning("Qwen 设备播放后台任务失败：%s", exc)
        finally:
            if self._playback_task is current_task:
                self._playback_task = None

    async def _wait_for_playback_running(self, playback: Any) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + min(
            5.0, self._configuration.response_timeout_seconds
        )
        while loop.time() < deadline:
            state = getattr(playback.state, "value", str(playback.state)).lower()
            if state == "running":
                return
            if state in ("completed", "failed", "cancelled"):
                raise RuntimeError(f"playback became {state} before starting")
            await asyncio.sleep(0.02)
        raise TimeoutError("device playback did not enter running state")

    async def _close_microphone_session(
        self,
        session: Any,
        *,
        context: str,
    ) -> None:
        try:
            await asyncio.to_thread(session.close)
        except Exception as exc:
            # The device may already be gone. Local ownership still has to be
            # released so a later SDK connection can create a fresh session.
            self._log_warning("%s时关闭设备麦克风失败：%s", context, exc)
        finally:
            self._log_microphone_statistics(session)

    async def _stop_device_audio(self, *, context: str) -> None:
        if not self._device_audio_active:
            return
        # Consume local ownership before awaiting the device command. A touch
        # cancellation and a concurrent Gateway disconnect can otherwise both
        # observe PLAYING and issue duplicate stop commands.
        self._device_audio_active = False
        try:
            await asyncio.to_thread(self._robot.audio.stop)
        except Exception as exc:
            # Treat remote cleanup as best effort during disconnect/cancel;
            # local response state must never remain wedged behind an offline
            # device transport.
            self._log_warning("%s时停止设备音频失败：%s", context, exc)

    def _log_microphone_statistics(self, session: Any) -> None:
        self._log_info(
            "Qwen 麦克风采集结束：frames_sent=%d last_sequence=%d "
            "dropped_frames=%d decode_failures=%d",
            self._microphone_frames_sent,
            self._last_microphone_sequence,
            int(getattr(session, "dropped_frames", 0)),
            int(getattr(session, "decode_failures", 0)),
        )

    def _log_info(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.info(message, *args)

    def _log_warning(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.warning(message, *args)

    def _remember_stale_response(self, response_id: str) -> None:
        if response_id in self._stale_response_ids:
            return
        while len(self._stale_response_order) >= MAX_STALE_RESPONSES:
            expired = self._stale_response_order.popleft()
            self._stale_response_ids.discard(expired)
        self._stale_response_order.append(response_id)
        self._stale_response_ids.add(response_id)

    def _update_agent_activity(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        task_state = event_type.removeprefix("task.")
        task = event.get("task")
        raw_task_id = task.get("id") if isinstance(task, dict) else None
        task_id = (
            raw_task_id.strip()
            if isinstance(raw_task_id, str) and raw_task_id.strip()
            else ANONYMOUS_AGENT_TASK_ID
        )
        if task_state in ACTIVE_AGENT_TASK_STATES:
            self._active_agent_task_ids.add(task_id)
        elif task_state in TERMINAL_AGENT_TASK_STATES:
            self._active_agent_task_ids.discard(task_id)

    def _set_status(self, component: str, state: str, detail: str) -> None:
        if self._diagnostics is not None:
            self._diagnostics.set_status(component, state, detail)

    async def _express(self, event: BehaviorEvent) -> None:
        if self._behavior_system is not None:
            await self._behavior_system.transition(event)

    def _record(
        self,
        stage: str,
        *,
        detail: str = "",
        level: str = "ok",
        response_id: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        if self._diagnostics is not None:
            self._diagnostics.record(
                stage,
                detail=detail,
                level=level,
                response_id=response_id,
                metrics=metrics,
            )

    def _begin_turn(
        self,
        detail: str,
        *,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        if self._diagnostics is not None:
            self._diagnostics.begin_turn(detail, metrics=metrics)

    def _end_turn(
        self,
        stage: str,
        *,
        detail: str,
        level: str = "ok",
        response_id: str | None = None,
    ) -> None:
        if self._diagnostics is not None:
            self._diagnostics.end_turn(
                stage,
                detail=detail,
                level=level,
                response_id=response_id,
            )
