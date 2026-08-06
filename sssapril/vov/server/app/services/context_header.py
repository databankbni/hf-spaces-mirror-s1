"""
群聊上下文头消息

职责: 给 agent 提供当前群聊的基本信息（群 id + 群目标），不写角色/成员/任务/上下游。
agent 想看更多数据自己调 get_group / list_tasks / get_group_members 等工具。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group


async def build_group_context_header(
    db: AsyncSession,
    group_id: str,
    agent_id: Optional[str] = None,
) -> str:
    """
    拼极简群聊头消息 (2-3 行):
      [群: {name} (id: {id})]
      [你的 Agent ID: {agent_id}]          ← 仅当传入 agent_id 时出现
      目标: {description 前 200 字}

    不写角色/成员/任务/上下游。
    agent_id 用于让 agent 调用 set_memory/get_memory 等需要自身 ID 的工具。
    """
    group = (await db.execute(
        select(Group).where(Group.id == group_id)
    )).scalar_one_or_none()

    if not group:
        return ""

    goal = (group.description or "").strip()[:200]
    header = f"[群: {group.name} (id: {group.id})]"
    if agent_id:
        header += f"\n[你的 Agent ID: {agent_id}]"
    header += f"\n目标: {goal}"
    return header