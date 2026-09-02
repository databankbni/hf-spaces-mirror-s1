"""Bounded per-response output audio buffering for SDK media protocol v1."""

from __future__ import annotations

import base64
import binascii

from .protocol import OUTPUT_SAMPLE_RATE_HZ


class AudioBufferError(ValueError):
    """Raised when output audio cannot safely be buffered for playback."""


class ResponseAudioBuffer:
    """Assemble exactly one Qwen response before calling SDK ``play_pcm``."""

    def __init__(self, *, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._active_response_id: str | None = None
        self._data = bytearray()

    @property
    def active_response_id(self) -> str | None:
        return self._active_response_id

    @property
    def size_bytes(self) -> int:
        return len(self._data)

    def append(
        self,
        response_id: str,
        encoded_audio: str,
        *,
        sample_rate_hz: int,
    ) -> None:
        normalized_response_id = response_id.strip()
        if not normalized_response_id:
            raise AudioBufferError("responseId is required")
        if sample_rate_hz != OUTPUT_SAMPLE_RATE_HZ:
            raise AudioBufferError(
                f"output audio requires {OUTPUT_SAMPLE_RATE_HZ} Hz"
            )
        if self._active_response_id not in (None, normalized_response_id):
            raise AudioBufferError(
                f"active response is {self._active_response_id}, not {normalized_response_id}"
            )
        try:
            pcm = base64.b64decode(encoded_audio, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AudioBufferError("invalid Base64 audio delta") from exc
        if not pcm or len(pcm) % 2:
            raise AudioBufferError("audio delta is not complete PCM16")
        if len(self._data) + len(pcm) > self._max_bytes:
            self.cancel()
            raise AudioBufferError("response audio exceeds configured limit")
        if self._active_response_id is None:
            self._active_response_id = normalized_response_id
        self._data.extend(pcm)

    def finish(self, response_id: str) -> bytes:
        normalized_response_id = response_id.strip()
        if self._active_response_id is None:
            raise AudioBufferError("response is not active")
        if self._active_response_id != normalized_response_id:
            raise AudioBufferError(
                f"active response is {self._active_response_id}, not {normalized_response_id}"
            )
        result = bytes(self._data)
        self.cancel()
        if not result:
            raise AudioBufferError("response audio is empty")
        return result

    def cancel(self) -> None:
        self._active_response_id = None
        self._data.clear()
