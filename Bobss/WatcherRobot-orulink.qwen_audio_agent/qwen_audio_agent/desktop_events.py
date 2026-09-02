"""Project safe Qwen status events onto the managed Desktop channel."""

from __future__ import annotations

import json


FORWARDED_EVENT_TYPES = frozenset(
    {
        "error",
        "turn.started",
        "response.started",
        "response.interrupted",
        "transcript.delta",
        "transcript.final",
        "transcript.discard",
        "voice.connection",
        "voice.deactivated",
        "voice.ownership",
        "voice.ready",
        "voice.state",
        "voice.sleep",
    }
)


def encode_desktop_gateway_event(event: object) -> str | None:
    """Return compact JSON for status/UI events, never for media payloads."""

    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    if not isinstance(event_type, str) or not (
        event_type in FORWARDED_EVENT_TYPES or event_type.startswith("task.")
    ):
        return None
    if _contains_audio_payload(event):
        return None
    try:
        return json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _contains_audio_payload(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key == "audio" or _contains_audio_payload(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_audio_payload(item) for item in value)
    return False
