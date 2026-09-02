"""Async client for the Qwen Audio Agent frontend Gateway protocol."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .protocol import (
    build_audio_append,
    build_connect,
    build_input_commit,
    build_input_mute,
    build_input_unmute,
    build_interrupt,
    build_playback_event,
    build_sleep,
)


class GatewayConnectionError(RuntimeError):
    """Raised when the Gateway connection cannot satisfy its contract."""


class QwenGatewayClient:
    """Small transport owner; conversation policy lives in the controller."""

    def __init__(
        self,
        gateway_url: str,
        *,
        client_label: str,
        provider: str,
        takeover: bool,
        connect_timeout_seconds: float = 15.0,
        max_message_bytes: int = 3 * 1024 * 1024,
        wake_word_enabled: bool = False,
    ) -> None:
        if max_message_bytes < 128:
            raise ValueError("max_message_bytes must be at least 128")
        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")
        self._gateway_url = gateway_url
        self._client_label = client_label
        self._provider = provider
        self._takeover = takeover
        self._connect_timeout_seconds = connect_timeout_seconds
        self._max_message_bytes = max_message_bytes
        self._wake_word_enabled = wake_word_enabled
        self._websocket: Any | None = None
        self._send_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._websocket is not None

    async def connect(self) -> None:
        if self._websocket is not None:
            raise GatewayConnectionError("Gateway is already connected")
        try:
            self._websocket = await connect(
                self._gateway_url,
                max_size=self._max_message_bytes,
                open_timeout=self._connect_timeout_seconds,
                close_timeout=min(5.0, self._connect_timeout_seconds),
                ping_interval=10,
                ping_timeout=10,
            )
            await self._send(
                build_connect(
                    client_label=self._client_label,
                    provider=self._provider,
                    takeover=self._takeover,
                )
            )
        except Exception as exc:
            await self.close()
            raise GatewayConnectionError("failed to connect to Qwen Gateway") from exc

    async def receive(self) -> dict[str, Any]:
        websocket = self._require_connection()
        try:
            raw = await websocket.recv()
        except ConnectionClosed as exc:
            await self.close()
            raise GatewayConnectionError("Qwen Gateway connection closed") from exc
        if not isinstance(raw, str):
            raise GatewayConnectionError("Qwen Gateway message must be JSON text")
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GatewayConnectionError("Qwen Gateway sent invalid JSON") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise GatewayConnectionError("Qwen Gateway JSON event requires type")
        return event

    async def set_input_enabled(self, enabled: bool) -> None:
        event = (
            build_input_unmute(takeover=self._takeover)
            if enabled
            else build_input_mute()
        )
        await self._send(event)

    async def send_audio(self, pcm: bytes) -> None:
        await self._send(build_audio_append(pcm))

    async def commit_input(self) -> None:
        await self._send(build_input_commit())

    async def enter_wake_word_sleep(self) -> None:
        if not self._wake_word_enabled:
            return
        await self._send(build_sleep())

    async def send_playback(self, event_type: str, response_id: str) -> None:
        await self._send(build_playback_event(event_type, response_id))

    async def send_interrupt(self) -> None:
        await self._send(build_interrupt())

    async def close(self) -> None:
        websocket = self._websocket
        self._websocket = None
        if websocket is not None:
            try:
                await websocket.close()
            except Exception:
                pass

    async def _send(self, event: dict[str, Any]) -> None:
        websocket = self._require_connection()
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        try:
            async with self._send_lock:
                await asyncio.wait_for(
                    websocket.send(payload),
                    timeout=self._connect_timeout_seconds,
                )
        except TimeoutError as exc:
            await self.close()
            raise GatewayConnectionError("Qwen Gateway send timed out") from exc
        except ConnectionClosed as exc:
            await self.close()
            raise GatewayConnectionError("Qwen Gateway connection closed") from exc

    def _require_connection(self) -> Any:
        if self._websocket is None:
            raise GatewayConnectionError("Qwen Gateway is not connected")
        return self._websocket
