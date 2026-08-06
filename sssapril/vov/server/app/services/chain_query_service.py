"""
链查询服务模块

提供链相关的统一查询抽象，消除 chains.py / chat_service.py 中的链回溯逻辑重复。
"""

import json
import logging
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.chain import Chain, Packet

logger = logging.getLogger(__name__)


def extract_inject_from_tool_call(tc: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """从 page_inject 工具的 tool_call 记录中提取 inject_js / inject_description。

    优先读顶层字段（新版采集器/后端直填），否则从 result 字符串/字典里解析。
    """
    inject_js = tc.get("inject_js")
    inject_description = tc.get("inject_description")
    if inject_js:
        return inject_js, inject_description

    result_raw = tc.get("result")
    parsed: Optional[Dict[str, Any]] = None
    if isinstance(result_raw, dict):
        parsed = result_raw
    elif isinstance(result_raw, str) and result_raw.strip().startswith("{"):
        try:
            parsed = json.loads(result_raw)
        except (ValueError, TypeError):
            parsed = None

    if isinstance(parsed, dict):
        inject_js = parsed.get("inject_js") or inject_js
        if not inject_description:
            inject_description = parsed.get("description")

    return inject_js, inject_description


class ChainQueryService:
    """
    链查询统一服务

    封装链回溯（rollover）逻辑和序列化逻辑，消除 chains.py / chat_service.py
    中的重复代码。链交接（rollover）后，旧链变为 completed，新链通过
    rollover_from_chain_id 引用旧链。查询消息历史时需要沿此字段回溯，
    把所有历史链的包一并返回。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 链回溯 ──

    async def collect_chain_ids_with_rollover(self, chain_id: str) -> List[str]:
        """
        收集链及其所有历史链 ID（沿 rollover_from_chain_id 回溯）。

        Args:
            chain_id: 起始链 ID

        Returns:
            链 ID 列表，第一个为当前链，后续为历史链（由新到旧）
        """
        chain_ids: List[str] = [chain_id]
        visited: set = {chain_id}

        current_id = chain_id
        while True:
            result = await self.db.execute(
                select(Chain.rollover_from_chain_id).where(Chain.id == current_id)
            )
            rollover_id = result.scalar_one_or_none()
            if not rollover_id or rollover_id in visited:
                break
            chain_ids.append(rollover_id)
            visited.add(rollover_id)
            current_id = rollover_id

        return chain_ids

    # ── 序列化 ──

    @staticmethod
    def serialize_chain(chain: Chain) -> dict:
        """序列化链为前端格式"""
        return {
            "id": chain.id,
            "parent_chain_id": chain.parent_chain_id,
            "chain_type": chain.chain_type,
            "group_id": chain.group_id,
            "task_id": chain.task_id,
            "agent_id": chain.agent_id,
            "status": chain.status,
            "head_packet_id": chain.head_packet_id,
            "tail_packet_id": chain.tail_packet_id,
            "description": chain.description,
            "packet_count": chain.packet_count,
            "sub_chain_count": chain.sub_chain_count,
            "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
            "created_at": chain.created_at.isoformat() if chain.created_at else None,
        }

    @staticmethod
    def serialize_packet(packet: Packet) -> dict:
        """序列化包为前端格式

        兜底从 tool_calls 里提取 page_inject 的 inject_js，方便老数据
        在前端也能渲染 InjectJsBlock（不依赖 chat_service 当场写 metadata）。
        """
        metadata = packet.metadata_json or {}
        if isinstance(metadata, dict) and not metadata.get("inject_js"):
            tool_calls = metadata.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    inject_js, inject_desc = extract_inject_from_tool_call(tc)
                    if inject_js:
                        metadata["inject_js"] = inject_js
                        if inject_desc:
                            metadata["inject_description"] = inject_desc
                        break

        return {
            "id": packet.id,
            "chain_id": packet.chain_id,
            "prev_packet_id": packet.prev_packet_id,
            "packet_type": packet.packet_type,
            "sender_type": packet.sender_type,
            "sender_id": packet.sender_id,
            "sender_name": packet.sender_name,
            "content": packet.content,
            "content_type": packet.content_type,
            "sub_chain_id": packet.sub_chain_id,
            "metadata": metadata,
            "created_at": packet.created_at.isoformat() if packet.created_at else None,
        }
