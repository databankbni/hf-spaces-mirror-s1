from __future__ import annotations

import re
from typing import Iterable, Optional

from ..packet import InfoPacket, PacketType
from ..plugin import Plugin


class ReasoningFilterPlugin(Plugin):
    def __init__(
        self,
        name: Optional[str] = None,
        reasoning_markers: Optional[Iterable[tuple[str, str]]] = None,
        preserve_final_answer: bool = True,
    ):
        super().__init__(name)
        self.reasoning_markers = list(reasoning_markers or [("<think>", "</think>")])
        self.preserve_final_answer = preserve_final_answer

    def clone(self) -> "ReasoningFilterPlugin":
        return ReasoningFilterPlugin(
            name=self.name,
            reasoning_markers=list(self.reasoning_markers),
            preserve_final_answer=self.preserve_final_answer,
        )

    def sanitize_packet_content(self, packet: InfoPacket, rendered_text: str) -> str:
        if packet.type != PacketType.NORMAL:
            return rendered_text
        if packet.sender_id == "user":
            return rendered_text
        return self.sanitize_text(rendered_text)

    def sanitize_text(self, text: str) -> str:
        sanitized = text
        for start_marker, end_marker in self.reasoning_markers:
            if not start_marker or not end_marker:
                continue
            pattern = re.escape(start_marker) + r".*?" + re.escape(end_marker)
            sanitized = re.sub(pattern, "", sanitized, flags=re.DOTALL | re.IGNORECASE)

        sanitized = self._cleanup_text(sanitized)
        if sanitized or not self.preserve_final_answer:
            return sanitized
        return text

    def _cleanup_text(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n")
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()
