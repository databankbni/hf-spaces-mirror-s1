"""
Subscriber 调度器

职责: 把事件触发的消息注入到订阅者（群或 agent）。
- subscriber_type=group → 直接调 chat_service.send_message_stream
- subscriber_type=agent → 查 agent 所在的群，注入到该群

设计原则:
- 复用现有 chat_service 的 user_message dispatch 流程
- 不引入新的执行路径（避免破坏现有流式机制）
- 失败不重试（避免循环），仅记录日志
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import ProjectAgent
from app.models.group import GroupMember
from sqlalchemy import select

logger = logging.getLogger(__name__)


class SubscriberDispatcher:
    """把事件消息注入到订阅者。"""

    def __init__(self, chat_service):
        """
        Args:
            chat_service: ChatService 实例（用于调 send_message_stream）
        """
        self.chat_service = chat_service

    async def dispatch(
        self,
        subscriber_type: str,
        subscriber_id: str,
        message: str,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """把消息注入到订阅者。

        Args:
            subscriber_type: group / agent
            subscriber_id: 群 ID 或 agent ID
            message: 要注入的消息内容
            session: 可选 DB session（用于查 agent 所在群）

        Returns:
            bool: 是否成功注入
        """
        try:
            if subscriber_type == "group":
                return await self._dispatch_to_group(subscriber_id, message)
            if subscriber_type == "agent":
                return await self._dispatch_to_agent(
                    subscriber_id, message, session
                )
            logger.warning(
                "[subscriber_dispatch] unknown subscriber_type: %s",
                subscriber_type,
            )
            return False
        except Exception as e:
            logger.warning(
                "[subscriber_dispatch] failed to dispatch to %s=%s: %s",
                subscriber_type, subscriber_id[:8], e,
            )
            return False

    async def _dispatch_to_group(self, group_id: str, message: str) -> bool:
        """注入到群（作为 user_message）"""
        # 调 chat_service.send_message_stream
        # 注意: send_message_stream 会启动后台 LLM task, 立即返回
        result = await self.chat_service.send_message_stream(
            group_id=group_id,
            user_content=message,
            target_agent_id=None,
        )
        if result.get("error"):
            logger.warning(
                "[subscriber_dispatch] group=%s send_message_stream error: %s",
                group_id[:8], result["error"],
            )
            return False
        logger.info(
            "[subscriber_dispatch] dispatched to group=%s (chain=%s)",
            group_id[:8],
            (result.get("chain_id") or "-")[:8],
        )
        return True

    async def _dispatch_to_agent(
        self,
        agent_id: str,
        message: str,
        session: Optional[AsyncSession],
    ) -> bool:
        """注入到 agent（查 agent 所在群，注入到该群）"""
        if session is None:
            logger.warning(
                "[subscriber_dispatch] cannot dispatch to agent=%s without db session",
                agent_id[:8],
            )
            return False

        # 查 ProjectAgent 找到 agent 所在的群
        # 先查 ProjectAgent（项目级 agent 关联表）
        result = await session.execute(
            select(GroupMember.group_id)
            .where(GroupMember.project_agent_id == agent_id)
            .limit(1)
        )
        group_id = result.scalar_one_or_none()
        if not group_id:
            # agent 不在任何群
            logger.warning(
                "[subscriber_dispatch] agent=%s not in any group, skip",
                agent_id[:8],
            )
            return False

        # 复用群注入逻辑（带 target_agent_id）
        try:
            result = await self.chat_service.send_message_stream(
                group_id=group_id,
                user_content=message,
                target_agent_id=agent_id,
            )
        except Exception as e:
            logger.warning(
                "[subscriber_dispatch] failed send_message to agent=%s in group=%s: %s",
                agent_id[:8], group_id[:8], e,
            )
            return False

        if result.get("error"):
            logger.warning(
                "[subscriber_dispatch] agent=%s send_message_stream error: %s",
                agent_id[:8], result["error"],
            )
            return False

        logger.info(
            "[subscriber_dispatch] dispatched to agent=%s in group=%s (chain=%s)",
            agent_id[:8], group_id[:8],
            (result.get("chain_id") or "-")[:8],
        )
        return True
