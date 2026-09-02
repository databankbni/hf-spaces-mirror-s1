"""Pure half-duplex conversation state machine."""

from __future__ import annotations

from enum import Enum


class ConversationState(str, Enum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    LISTENING = "listening"
    WAITING_RESPONSE = "waiting_response"
    BUFFERING_AUDIO = "buffering_audio"
    BUFFERED_AUDIO = "buffered_audio"
    PLAYING = "playing"


class ConversationStateError(RuntimeError):
    """Raised when an event is invalid for the current conversation state."""


class HalfDuplexConversation:
    """Enforce one recorder or one speaker owner, never both."""

    def __init__(self) -> None:
        self._state = ConversationState.DISCONNECTED
        self._active_response_id: str | None = None
        self._generation = 0

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def active_response_id(self) -> str | None:
        return self._active_response_id

    @property
    def generation(self) -> int:
        return self._generation

    def mark_connected(self) -> None:
        if self._state is not ConversationState.DISCONNECTED:
            raise self._invalid("mark_connected")
        self._state = ConversationState.READY

    def mark_disconnected(self) -> None:
        self._state = ConversationState.DISCONNECTED
        self._active_response_id = None
        self._generation += 1

    def start_listening(self) -> None:
        if self._state is not ConversationState.READY:
            raise self._invalid("start_listening")
        self._state = ConversationState.LISTENING

    def finish_listening(self) -> None:
        if self._state is not ConversationState.LISTENING:
            raise self._invalid("finish_listening")
        self._state = ConversationState.WAITING_RESPONSE

    def begin_audio_response(self, response_id: str) -> None:
        normalized_response_id = self._response_id(response_id)
        if self._state not in (
            ConversationState.READY,
            ConversationState.WAITING_RESPONSE,
        ):
            raise self._invalid("begin_audio_response")
        self._active_response_id = normalized_response_id
        self._state = ConversationState.BUFFERING_AUDIO

    def finish_audio_response(self, response_id: str) -> None:
        self._require_response(response_id)
        if self._state is not ConversationState.BUFFERING_AUDIO:
            raise self._invalid("finish_audio_response")
        self._state = ConversationState.BUFFERED_AUDIO

    def mark_playback_started(self, response_id: str) -> None:
        self._require_response(response_id)
        if self._state is not ConversationState.BUFFERED_AUDIO:
            raise self._invalid("mark_playback_started")
        self._state = ConversationState.PLAYING

    def mark_playback_ended(
        self,
        response_id: str,
        *,
        await_more: bool = False,
    ) -> None:
        self._require_response(response_id)
        if self._state is not ConversationState.PLAYING:
            raise self._invalid("mark_playback_ended")
        self._active_response_id = None
        self._state = (
            ConversationState.WAITING_RESPONSE
            if await_more
            else ConversationState.READY
        )

    def cancel_response(self) -> None:
        if self._state in (
            ConversationState.BUFFERING_AUDIO,
            ConversationState.BUFFERED_AUDIO,
            ConversationState.PLAYING,
            ConversationState.WAITING_RESPONSE,
        ):
            self._active_response_id = None
            self._state = ConversationState.READY

    def _require_response(self, response_id: str) -> None:
        normalized_response_id = self._response_id(response_id)
        if normalized_response_id != self._active_response_id:
            raise ConversationStateError(
                f"active response is {self._active_response_id}, not {normalized_response_id}"
            )

    @staticmethod
    def _response_id(response_id: str) -> str:
        normalized_response_id = response_id.strip()
        if not normalized_response_id:
            raise ConversationStateError("responseId is required")
        return normalized_response_id

    def _invalid(self, operation: str) -> ConversationStateError:
        return ConversationStateError(
            f"{operation} is invalid while state is {self._state.name}"
        )
