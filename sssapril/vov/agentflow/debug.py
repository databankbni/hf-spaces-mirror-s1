from __future__ import annotations

import json
from typing import Any, Dict, List, Union

from .manager import InfoManager
from .packet import InfoPacket


def _resolve_manager(source: Union[InfoManager, Any]) -> InfoManager:
    if isinstance(source, InfoManager):
        return source
    manager = getattr(source, "info_manager", None)
    if isinstance(manager, InfoManager):
        return manager
    raise TypeError("Expected an InfoManager or an object exposing an 'info_manager' property.")


def get_chain_packets(source: Union[InfoManager, Any], chain_id: str) -> List[InfoPacket]:
    manager = _resolve_manager(source)
    packets = manager.get_by_chain_id(chain_id)
    packets.sort(key=lambda item: item.timestamp)
    return packets


def chain_packets_to_dicts(source: Union[InfoManager, Any], chain_id: str) -> List[Dict[str, Any]]:
    return [packet.to_dict() for packet in get_chain_packets(source, chain_id)]


def format_chain_trace(
    source: Union[InfoManager, Any],
    chain_id: str,
    preview_chars: int = 120,
    include_metadata: bool = False,
) -> str:
    lines = []
    for packet in get_chain_packets(source, chain_id):
        preview = packet.content
        if isinstance(preview, dict):
            preview = json.dumps(preview, ensure_ascii=False, sort_keys=True)
        preview = str(preview).replace("\n", " ")
        if len(preview) > preview_chars:
            preview = f"{preview[: preview_chars - 3]}..."

        line = (
            f"- {packet.type.value:<9} sender={packet.sender_id:<24} "
            f"parent={packet.parent_id or '-':<26} content={preview}"
        )
        if include_metadata and packet.metadata:
            line = f"{line} metadata={json.dumps(packet.metadata, ensure_ascii=False, sort_keys=True)}"
        lines.append(line)

    return "\n".join(lines)
