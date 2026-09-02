"""Translate device/Desktop interaction into Application-owned media turns."""

from __future__ import annotations

import json
from typing import Any, Protocol

from .conversation import ConversationStateError


MICROPHONE_OPEN = "ctrl.microphone.open"
MICROPHONE_CLOSE = "ctrl.microphone.close"


class ListeningService(Protocol):
    async def start_listening(self) -> None: ...

    async def stop_listening(self) -> None: ...

    async def handle_touch_interrupt(
        self,
        *,
        source: str,
        action: str,
        timestamp_ms: int | None = None,
    ) -> bool: ...


async def handle_input_event(
    event: object,
    service: ListeningService,
    *,
    manual_enabled: bool = True,
) -> bool:
    """Route touch input to PTT or playback-only interruption policy."""

    source = getattr(event, "source", None)
    action = getattr(event, "action", None)
    if source == "screen_touch":
        return await service.handle_touch_interrupt(
            source=source,
            action=str(action or ""),
            timestamp_ms=getattr(event, "timestamp_ms", None),
        )
    if source != "back_touch":
        return False
    if action == "press":
        interrupted = await service.handle_touch_interrupt(
            source=source,
            action=action,
            timestamp_ms=getattr(event, "timestamp_ms", None),
        )
        if interrupted:
            return True
        if not manual_enabled:
            return False
        await service.start_listening()
        return True
    if action == "release":
        if not manual_enabled:
            return False
        await service.stop_listening()
        return True
    return False


async def handle_desktop_frame(
    frame: str | bytes,
    service: ListeningService,
    *,
    manual_enabled: bool = True,
) -> dict[str, Any] | None:
    """Terminate microphone controls in the active Application."""

    if not isinstance(frame, str):
        return None
    try:
        message = json.loads(frame)
    except json.JSONDecodeError:
        return None
    if not isinstance(message, dict):
        return None
    message_type = message.get("type")
    if message_type not in (MICROPHONE_OPEN, MICROPHONE_CLOSE):
        return None
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    command_id = data.get("command_id")
    normalized_command_id = command_id if isinstance(command_id, str) else ""
    if not manual_enabled:
        return _command_result(
            message_type,
            normalized_command_id,
            accepted=False,
            reason="vad_enabled",
        )
    try:
        if message_type == MICROPHONE_OPEN:
            await service.start_listening()
        else:
            await service.stop_listening()
    except ConversationStateError:
        return _command_result(
            message_type,
            normalized_command_id,
            accepted=False,
            reason="busy",
        )
    return _command_result(
        message_type,
        normalized_command_id,
        accepted=True,
    )


def _command_result(
    command_type: str,
    command_id: str,
    *,
    accepted: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "type": command_type,
        "command_id": command_id,
    }
    if reason:
        data["reason"] = reason
    return {
        "type": "sys.ack" if accepted else "sys.nack",
        "code": 0 if accepted else 1,
        "data": data,
    }
