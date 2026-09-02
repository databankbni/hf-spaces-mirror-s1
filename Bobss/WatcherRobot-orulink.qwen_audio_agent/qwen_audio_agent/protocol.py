"""Qwen Audio Agent Gateway client protocol primitives."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any


INPUT_SAMPLE_RATE_HZ = 16000
OUTPUT_SAMPLE_RATE_HZ = 24000
PLAYBACK_EVENT_TYPES = frozenset(
    {"playback.started", "playback.ended", "playback.cancelled"}
)


class ProtocolError(ValueError):
    """Raised when a Gateway event violates the frozen bridge contract."""


@dataclass(frozen=True)
class AudioDelta:
    """One decoded Qwen output PCM chunk."""

    response_id: str
    sample_rate_hz: int
    pcm: bytes


def build_connect(
    *,
    client_label: str,
    provider: str,
    takeover: bool,
) -> dict[str, Any]:
    """Declare a half-duplex WatcheRobot voice client."""

    if not client_label.strip():
        raise ProtocolError("client label is required")
    if not provider.strip():
        raise ProtocolError("provider is required")
    return {
        "type": "connect",
        # The frozen Gateway only recognizes desktop, cli, and web.  This
        # headless hardware bridge is semantically a CLI-class client.
        "clientType": "cli",
        "clientLabel": client_label.strip(),
        "voiceEnabled": True,
        "inputEnabled": False,
        "outputEnabled": True,
        "provider": provider.strip(),
        "takeover": bool(takeover),
        "inputMode": "manual",
    }


def build_audio_append(pcm: bytes) -> dict[str, str]:
    """Encode signed-16-bit little-endian PCM for the Gateway."""

    payload = bytes(pcm)
    if not payload:
        raise ProtocolError("PCM payload must not be empty")
    if len(payload) % 2:
        raise ProtocolError("PCM payload ends with a partial 16-bit sample")
    return {
        "type": "audio.append",
        "audio": base64.b64encode(payload).decode("ascii"),
    }


def build_input_unmute(*, takeover: bool) -> dict[str, Any]:
    return {"type": "input.unmute", "takeover": bool(takeover)}


def build_input_mute() -> dict[str, str]:
    return {"type": "input.mute"}


def build_input_commit() -> dict[str, str]:
    return {"type": "input.commit"}


def build_sleep() -> dict[str, str]:
    return {"type": "sleep"}


def build_interrupt() -> dict[str, str]:
    """Cancel only the active foreground Realtime response."""

    return {"type": "interrupt"}


def build_playback_event(event_type: str, response_id: str) -> dict[str, str]:
    if event_type not in PLAYBACK_EVENT_TYPES:
        raise ProtocolError(f"unsupported playback event: {event_type}")
    normalized_response_id = response_id.strip()
    if not normalized_response_id:
        raise ProtocolError("responseId is required")
    return {"type": event_type, "responseId": normalized_response_id}


def decode_audio_delta(event: object) -> AudioDelta:
    """Decode and validate one 24 kHz mono PCM Gateway delta."""

    if not isinstance(event, dict) or event.get("type") != "audio.delta":
        raise ProtocolError("event is not audio.delta")
    response_id = event.get("responseId")
    if not isinstance(response_id, str) or not response_id.strip():
        raise ProtocolError("audio.delta responseId is required")
    sample_rate = event.get("sampleRate")
    if sample_rate != OUTPUT_SAMPLE_RATE_HZ:
        raise ProtocolError(
            f"audio.delta requires {OUTPUT_SAMPLE_RATE_HZ} Hz output"
        )
    encoded = event.get("audio")
    if not isinstance(encoded, str) or not encoded:
        raise ProtocolError("audio.delta audio is required")
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("audio.delta contains invalid Base64") from exc
    if not pcm or len(pcm) % 2:
        raise ProtocolError("audio.delta contains invalid PCM16 bytes")
    return AudioDelta(response_id.strip(), sample_rate, pcm)
