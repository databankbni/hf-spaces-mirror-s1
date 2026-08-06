from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from ..id_generator import IDGenerator
from ..llm.base import ChatMessage, LLMResponse, MessageRole
from ..packet import InfoPacket, PacketType
from ..plugin import Plugin
from .memory_plugin import MemoryPlugin

if TYPE_CHECKING:
    from ..agent import Agent
    from ..manager import InfoManager
    from ..processor import Processor


class ContextRolloverPlugin(Plugin):
    def __init__(
        self,
        name: Optional[str] = None,
        max_history_chars: int = 12000,
        trigger_ratio: float = 0.7,
        summary_prompt: str = "Please summarize the current chain state for the next chain.",
        rollover_metadata_key: str = "rollover_from_chain",
        history_query_mode: str = "chain-switch",
        read_only_previous_chain: bool = True,
    ):
        super().__init__(name)
        self.max_history_chars = max_history_chars
        self.trigger_ratio = trigger_ratio
        self.summary_prompt = summary_prompt
        self.rollover_metadata_key = rollover_metadata_key
        self.history_query_mode = history_query_mode
        self.read_only_previous_chain = read_only_previous_chain

    def clone(self) -> "ContextRolloverPlugin":
        return ContextRolloverPlugin(
            name=self.name,
            max_history_chars=self.max_history_chars,
            trigger_ratio=self.trigger_ratio,
            summary_prompt=self.summary_prompt,
            rollover_metadata_key=self.rollover_metadata_key,
            history_query_mode=self.history_query_mode,
            read_only_previous_chain=self.read_only_previous_chain,
        )

    def post_process(self, packet: InfoPacket, output_list: list) -> tuple:
        if not self._should_consider_rollover(packet):
            return packet, output_list

        manager = self._get_manager()
        if manager is None:
            return packet, output_list

        with manager._lock:
            if self._has_rollover_successor(packet.chain_id, manager):
                return packet, output_list

            chain_packets = [
                current
                for current in manager.get_by_chain_id(packet.chain_id)
                if current.type != PacketType.STREAM and not current.get_metadata("rollover_handoff")
            ]
            if not chain_packets:
                return packet, output_list

            if self._estimate_chain_chars(chain_packets) < int(self.max_history_chars * self.trigger_ratio):
                return packet, output_list

            summary_text = self._build_summary_text(chain_packets)
            successor_chain_id = IDGenerator.generate_chain_id()

            summary_packet = InfoPacket(
                id=IDGenerator.generate_packet_id(self._processor.sender_id, PacketType.NORMAL.value),
                sender_id=self._processor.sender_id,
                parent_id=packet.id,
                chain_id=successor_chain_id,
                content=summary_text,
                type=PacketType.NORMAL,
                timestamp=datetime.now(),
            )
            summary_packet.add_metadata(self.rollover_metadata_key, packet.chain_id)
            summary_packet.add_metadata("rollover_summary", True)
            summary_packet.add_metadata("rollover_depth", self._calculate_rollover_depth(chain_packets))
            summary_packet.add_metadata("history_query_mode", self.history_query_mode)
            summary_packet.add_metadata("read_only_previous_chain", self.read_only_previous_chain)
            manager.save(summary_packet)

            handoff_packet = packet.create_child(
                sender_id=self._processor.sender_id,
                content=f"[Rollover] Continue on chain {successor_chain_id}",
                packet_type=PacketType.NORMAL,
                inherit_metadata=False,
            )
            handoff_packet.add_metadata("rollover_handoff", True)
            handoff_packet.add_metadata("rollover_to_chain", successor_chain_id)
            handoff_packet.add_metadata("rollover_summary_packet_id", summary_packet.id)
            manager.save(handoff_packet)

        return packet, output_list

    def _should_consider_rollover(self, packet: InfoPacket) -> bool:
        if self._processor is None:
            return False
        if packet.type != PacketType.NORMAL:
            return False
        if packet.get_metadata("rollover_summary") or packet.get_metadata("rollover_handoff"):
            return False
        return hasattr(self._processor, "llm")

    def _get_manager(self) -> Optional["InfoManager"]:
        if self._processor is None:
            return None
        memory_plugins = self._processor.get_plugins(MemoryPlugin)
        if not memory_plugins:
            return None
        return memory_plugins[0].manager

    def _has_rollover_successor(self, chain_id: str, manager: "InfoManager") -> bool:
        return bool(manager.search_by_metadata(self.rollover_metadata_key, chain_id))

    def _estimate_chain_chars(self, packets: List[InfoPacket]) -> int:
        return sum(len(self._packet_text(packet)) for packet in packets)

    def _packet_text(self, packet: InfoPacket) -> str:
        content = packet.content
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        if isinstance(content, dict):
            import json

            return json.dumps(content, ensure_ascii=False, sort_keys=True)
        return str(content)

    def _build_summary_text(self, chain_packets: List[InfoPacket]) -> str:
        agent = self._processor if hasattr(self._processor, "llm") else None
        transcript = self._format_transcript(chain_packets)
        if agent is None or getattr(agent, "llm", None) is None:
            return transcript[-2000:]

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=self.summary_prompt),
            ChatMessage(role=MessageRole.USER, content=transcript),
        ]
        try:
            response = asyncio.run(agent.llm.chat(messages, tools=None))
        except Exception:
            return transcript[-2000:]

        if not isinstance(response, LLMResponse) or not response.content.strip():
            return transcript[-2000:]
        return response.content.strip()

    def _format_transcript(self, chain_packets: List[InfoPacket]) -> str:
        lines = []
        for packet in chain_packets:
            role = "assistant" if packet.sender_id == self._processor.sender_id else "user"
            lines.append(f"{role}: {self._packet_text(packet)}")
        return "\n".join(lines)

    def _calculate_rollover_depth(self, chain_packets: List[InfoPacket]) -> int:
        depths = [int(packet.get_metadata("rollover_depth", 0)) for packet in chain_packets if packet.has_metadata("rollover_depth")]
        return (max(depths) if depths else 0) + 1
