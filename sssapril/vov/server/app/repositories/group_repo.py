"""
群聊Repository模块

提供群聊(Group)和群聊成员(GroupMember)的数据访问操作。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.group import Group, GroupMember
from app.models.task import Task
from app.models.agent import Agent, AgentTool, Skill
from app.models.chain import Chain
from app.models.deliverable import Deliverable
from .base import BaseRepository


class GroupRepository(BaseRepository[Group]):
    """
    群聊Repository

    提供群聊相关的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Group, db)

    async def get_by_project(self, project_id: str) -> List[Dict[str, Any]]:
        """
        获取项目的群聊列表（含统计信息）

        Args:
            project_id: 项目ID

        Returns:
            List[Dict]: 群聊列表，含member_count/task_count/message_count/done_task_count/deliverable_count
        """
        member_count_sq = (
            select(func.count(GroupMember.id))
            .where(GroupMember.group_id == Group.id)
            .correlate(Group)
            .scalar_subquery()
        )
        task_count_sq = (
            select(func.count(Task.id))
            .where(and_(Task.group_id == Group.id, Task.deleted_at.is_(None)))
            .correlate(Group)
            .scalar_subquery()
        )
        done_task_count_sq = (
            select(func.count(Task.id))
            .where(and_(
                Task.group_id == Group.id,
                Task.deleted_at.is_(None),
                Task.status == "completed",
            ))
            .correlate(Group)
            .scalar_subquery()
        )
        deliverable_count_sq = (
            select(func.count(Deliverable.id))
            .where(and_(Deliverable.group_id == Group.id, Deliverable.deleted_at.is_(None)))
            .correlate(Group)
            .scalar_subquery()
        )

        # 消息数：统计群下所有链的 packet_count 总和
        message_count_sq = (
            select(func.coalesce(func.sum(Chain.packet_count), 0))
            .where(and_(
                Chain.group_id == Group.id,
                Chain.deleted_at.is_(None),
            ))
            .correlate(Group)
            .scalar_subquery()
        )

        query = (
            select(
                Group,
                member_count_sq.label("member_count"),
                task_count_sq.label("task_count"),
                done_task_count_sq.label("done_task_count"),
                deliverable_count_sq.label("deliverable_count"),
                message_count_sq.label("message_count"),
            )
            .where(and_(
                Group.project_id == project_id,
                Group.deleted_at.is_(None)
            ))
            .order_by(Group.order_index)
        )
        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "id": group.id,
                "project_id": group.project_id,
                "name": group.name,
                "description": group.description,
                "status": group.status,
                "order_index": group.order_index,
                "autonomy_level": group.autonomy_level,
                "member_count": member_count,
                "task_count": task_count,
                "done_task_count": done_task_count,
                "deliverable_count": deliverable_count,
                "message_count": message_count,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "updated_at": group.updated_at.isoformat() if group.updated_at else None,
            }
            for group, member_count, task_count, done_task_count, deliverable_count, message_count in rows
        ]

    async def get_with_details(self, id: str) -> Optional[dict]:
        """
        获取群聊详情（包含关联数据）

        Args:
            id: 群聊ID

        Returns:
            Optional[dict]: 群聊详情（字典格式）
        """
        from app.models.agent import ProjectAgent
        from app.models.task import Task as TaskModel, TaskAssignee
        query = (
            select(Group)
            .where(and_(Group.id == id, Group.deleted_at.is_(None)))
            .options(
                selectinload(Group.lead_agent).selectinload(ProjectAgent.agent).selectinload(Agent.tools),
                selectinload(Group.lead_agent).selectinload(ProjectAgent.agent).selectinload(Agent.skills),
                selectinload(Group.members).selectinload(GroupMember.project_agent).selectinload(ProjectAgent.agent).selectinload(Agent.tools),
                selectinload(Group.members).selectinload(GroupMember.project_agent).selectinload(ProjectAgent.agent).selectinload(Agent.skills),
                # 任务的关联数据（负责人 / 指派 / 链 / 交付物）
                selectinload(Group.tasks).selectinload(TaskModel.lead_agent).selectinload(ProjectAgent.agent),
                selectinload(Group.tasks).selectinload(TaskModel.assignees).selectinload(TaskAssignee.project_agent).selectinload(ProjectAgent.agent),
                selectinload(Group.tasks).selectinload(TaskModel.chain),
                selectinload(Group.tasks).selectinload(TaskModel.deliverable),
                selectinload(Group.resources),
                selectinload(Group.deliverables),
            )
        )
        result = await self.db.execute(query)
        group = result.scalar_one_or_none()
        if not group:
            return None

        def fmt_dt(dt):
            if not dt:
                return None
            iso = dt.isoformat()
            # If already has timezone, don't append Z
            if iso.endswith('+00:00'):
                return iso[:-6] + 'Z'
            return iso + 'Z'

        def serialize_agent(agent):
            if not agent:
                return None
            return {
                "id": agent.id,
                "name": agent.name,
                # v2 P3: 删除 role 字段
                "avatar": agent.avatar,
                "description": agent.description,
                "system_prompt": agent.system_prompt,
                "llm_config": agent.llm_config or {},
                "capabilities": agent.capabilities or [],
                "is_active": agent.is_active,
                "tools": [
                    {
                        "id": t.id,
                        "agent_id": t.agent_id,
                        "name": t.name,
                        "description": t.description,
                        "tool_type": t.tool_type,
                        "config": t.config or {},
                    }
                    for t in (agent.tools or [])
                ],
                "skills": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "skill_type": s.skill_type,
                        "content": s.content,
                        "config": s.config or {},
                        "created_at": fmt_dt(s.created_at),
                        "updated_at": fmt_dt(s.updated_at),
                    }
                    for s in (agent.skills or [])
                ],
                "created_at": fmt_dt(agent.created_at),
                "updated_at": fmt_dt(agent.updated_at),
            }

        def serialize_project_agent(pa):
            if not pa:
                return None
            return {
                "id": pa.id,
                "project_id": pa.project_id,
                "agent_id": pa.agent_id,
                "agent": serialize_agent(pa.agent),
                "override_config": pa.override_config or {},
                "created_at": fmt_dt(pa.created_at),
            }

        def serialize_member(m):
            return {
                "id": m.id,
                "group_id": m.group_id,
                "project_agent_id": m.project_agent_id,
                "role": m.role,
                "agent": serialize_agent(m.project_agent.agent if m.project_agent else None),
                "created_at": fmt_dt(m.created_at),
            }

        def serialize_task(t):
            # 任务主导 Agent（ProjectAgent 级别，关联到具体项目）
            lead = None
            if t.lead_agent and t.lead_agent.agent:
                lead = {
                    "id": t.lead_agent.id,
                    "name": t.lead_agent.agent.name,
                    "avatar": t.lead_agent.agent.avatar,
                }
            # 任务指派列表（每个 assignee 关联到 ProjectAgent.agent）
            assignees = []
            for a in (t.assignees or []):
                if a.project_agent and a.project_agent.agent:
                    assignees.append({
                        "id": a.id,
                        "project_agent_id": a.project_agent_id,
                        "name": a.project_agent.agent.name,
                        "avatar": a.project_agent.agent.avatar,
                    })
            # 任务链摘要（id + 状态 + 包数），避免在卡片/弹窗里暴露整条链
            chain_summary = None
            if t.chain:
                chain_summary = {
                    "id": t.chain.id,
                    "status": t.chain.status,
                    "packet_count": t.chain.packet_count,
                }
            # 交付物（仅前端需要的元数据）
            deliverable_summary = None
            if t.deliverable:
                deliverable_summary = {
                    "id": t.deliverable.id,
                    "title": t.deliverable.title,
                    "content_type": t.deliverable.content_type,
                    "type": t.deliverable.type,
                }
            return {
                "id": t.id,
                "group_id": t.group_id,
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "order_index": t.order_index,
                "lead_agent_id": t.lead_agent_id,
                "lead_agent": lead,
                "assignees": assignees,
                "acceptance_criteria": t.acceptance_criteria,
                "context_data": {},
                "started_at": fmt_dt(t.started_at),
                "completed_at": fmt_dt(t.completed_at),
                "created_at": fmt_dt(t.created_at),
                "updated_at": fmt_dt(t.updated_at),
                # v2 P2: 任务链是否继承主链截至分支点的历史
                "inherit_main_chain": bool(t.inherit_main_chain),
                # 链与交付物的轻量摘要
                "chain_id": t.chain.id if t.chain else None,
                "chain": chain_summary,
                "deliverable": deliverable_summary,
            }

        def serialize_resource(r):
            return {
                "id": r.id,
                "project_id": r.project_id,
                "group_id": r.group_id,
                "title": r.title,
                "content": r.content,
                "content_type": r.content_type,
                "type": r.type,
                "tags": r.tags or [],
                "is_required": r.is_required,
                "created_by": r.created_by,
                "created_at": fmt_dt(r.created_at),
                "updated_at": fmt_dt(r.updated_at),
            }

        def serialize_deliverable(d):
            return {
                "id": d.id,
                "chain_id": d.chain_id,
                "group_id": d.group_id,
                "task_id": d.task_id,
                "title": d.title,
                "content": d.content,
                "content_type": d.content_type,
                "type": d.type,
                "tags": d.tags or [],
                "author_id": d.author_id,
                "participant_ids": d.participant_ids or [],
                "metadata_json": d.metadata_json if hasattr(d, 'metadata_json') else {},
                "scope": d.scope,
                "version": d.version,
                "created_at": fmt_dt(d.created_at),
                "updated_at": fmt_dt(d.updated_at),
            }

        return {
            "id": group.id,
            "project_id": group.project_id,
            "name": group.name,
            "description": group.description,
            "lead_agent_id": group.lead_agent_id,
            "status": group.status,
            "order_index": group.order_index,
            "autonomy_level": group.autonomy_level,
            "auto_advance": group.auto_advance,
            "bypass_deliverable_required": group.bypass_deliverable_required,
            "lead_agent": serialize_project_agent(group.lead_agent),
            "members": [serialize_member(m) for m in group.members],
            "tasks": [serialize_task(t) for t in group.tasks],
            "resources": [serialize_resource(r) for r in group.resources],
            "deliverables": [serialize_deliverable(d) for d in group.deliverables],
            "created_at": fmt_dt(group.created_at),
            "updated_at": fmt_dt(group.updated_at),
        }

    async def reorder(self, project_id: str, ordered_ids: List[str]) -> None:
        """
        重新排序群聊

        Args:
            project_id: 项目ID
            ordered_ids: 排序后的群聊ID列表
        """
        for index, group_id in enumerate(ordered_ids):
            query = (
                select(Group)
                .where(and_(
                    Group.id == group_id,
                    Group.project_id == project_id,
                    Group.deleted_at.is_(None)
                ))
            )
            result = await self.db.execute(query)
            group = result.scalar_one_or_none()
            if group:
                group.order_index = index

        await self.db.flush()

    async def get_max_order(self, project_id: str) -> int:
        """
        获取项目中群聊的最大排序索引

        Args:
            project_id: 项目ID

        Returns:
            int: 最大排序索引
        """
        query = (
            select(func.max(Group.order_index))
            .where(and_(
                Group.project_id == project_id,
                Group.deleted_at.is_(None)
            ))
        )
        result = await self.db.execute(query)
        return result.scalar() or 0


class GroupMemberRepository(BaseRepository[GroupMember]):
    """
    群聊成员Repository

    提供群聊成员的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(GroupMember, db)

    async def get_by_group(self, group_id: str) -> List[GroupMember]:
        """
        获取群聊的成员列表

        Args:
            group_id: 群聊ID

        Returns:
            List[GroupMember]: 成员列表
        """
        query = (
            select(GroupMember)
            .where(GroupMember.group_id == group_id)
            .options(selectinload(GroupMember.project_agent))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_group_and_agent(self, group_id: str, project_agent_id: str) -> Optional[GroupMember]:
        """
        根据群聊和Agent获取成员记录

        Args:
            group_id: 群聊ID
            project_agent_id: 项目Agent ID

        Returns:
            Optional[GroupMember]: 成员记录
        """
        query = select(GroupMember).where(and_(
            GroupMember.group_id == group_id,
            GroupMember.project_agent_id == project_agent_id
        ))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def is_member(self, group_id: str, project_agent_id: str) -> bool:
        """
        检查Agent是否是群聊成员

        Args:
            group_id: 群聊ID
            project_agent_id: 项目Agent ID

        Returns:
            bool: 是否是成员
        """
        member = await self.get_by_group_and_agent(group_id, project_agent_id)
        return member is not None
