from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json

from .dataset_store import store, rel_packet

PACKET_VERSION = "football_dataset_only_v1"


def _packet_size_kb(packet: dict[str, Any]) -> float:
    return round(len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) / 1024, 2)


def build_match_packet(match_id: str, day: str | None = None, company_ids: str | None = None, save: bool = True) -> dict[str, Any]:
    """Dataset-only compatibility lookup; live Titan007 collection is forbidden."""
    del company_ids, save
    day = day or datetime.now(timezone.utc).date().isoformat()
    packet = store.load_json(rel_packet(day, str(match_id)), prefer_remote=True)
    if not packet:
        raise LookupError(f"dataset_packet_not_found:{day}:{match_id}")
    packet = dict(packet)
    meta = dict(packet.get("packet_meta", {}))
    meta.update({
        "packet_version": PACKET_VERSION,
        "dataset_only": True,
        "external_fetch_performed": False,
        "source_date": day,
        "packet_size_kb": _packet_size_kb(packet),
    })
    packet["packet_meta"] = meta
    packet["hf_decision_boundary"] = {
        "hf_final_pick_allowed": False,
        "hf_stake_allowed": False,
        "hf_bankroll_allowed": False,
        "hermes_local_decision_required": True,
        "reason": "HF Data Hub only serves locally collected Dataset artifacts.",
    }
    return packet
