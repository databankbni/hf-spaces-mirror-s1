"""
统一导出服务

所有资源类型使用统一的 manifest 格式导出为 ZIP。
支持混合导出：skill、agent、项目资料等可在同一个 ZIP 中。
"""

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent, AgentSkill, ProjectAgent, Skill
from app.models.group import Group, GroupMember
from app.models.task import Task, TaskAssignee
from app.models.deliverable import Deliverable
from app.models.resource import Resource
from app.models.memory import Memory
from app.models.tag import Tag
from app.models.chain import Chain, Packet
from app.models.project import Project


MANIFEST_SCHEMA = "vov/export.v1"


class UnifiedExportService:
    """统一导出服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def export(self, items_request: List[Dict[str, Any]]) -> bytes:
        """
        按请求列表导出资源为 ZIP。

        items_request 格式:
        [{"type": "skill", "id": "xxx"}, {"type": "agent", "id": "yyy"}, ...]
        """
        items = []
        for req in items_request:
            res_type = req.get("type")
            res_id = req.get("id")
            if not res_type or not res_id:
                continue

            if res_type == "skill":
                item = await self._export_skill(res_id)
            elif res_type == "agent":
                item = await self._export_agent(res_id)
            elif res_type == "project":
                project_items = await self._export_project(res_id, req.get("selection", {}))
                items.extend(project_items)
                continue
            else:
                continue

            if item:
                items.append(item)

        return self._create_zip(items)

    async def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有全局 skill"""
        result = await self.db.execute(select(Skill).order_by(Skill.name))
        skills = result.scalars().all()
        return [
            {
                "id": s.id,
                "type": "skill",
                "name": s.name,
                "description": s.description,
                "skill_type": s.skill_type,
            }
            for s in skills
        ]

    async def list_agents(self) -> List[Dict[str, Any]]:
        """列出所有全局 agent"""
        result = await self.db.execute(
            select(Agent).options(selectinload(Agent.skills)).order_by(Agent.name)
        )
        agents = result.scalars().all()
        return [
            {
                "id": a.id,
                "type": "agent",
                "name": a.name,
                # v2 P3: 删除 role 字段
                "description": a.description,
                "skill_names": [s.name for s in (a.skills or [])],
            }
            for a in agents
        ]

    async def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目"""
        result = await self.db.execute(select(Project).order_by(Project.name))
        projects = result.scalars().all()
        return [
            {
                "id": p.id,
                "type": "project",
                "name": p.name,
                "description": p.description,
            }
            for p in projects
        ]

    async def _export_skill(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """导出单个 skill"""
        result = await self.db.execute(select(Skill).where(Skill.id == skill_id))
        skill = result.scalar_one_or_none()
        if not skill:
            return None

        return {
            "type": "skill",
            "scope": "global",
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "skill_type": skill.skill_type,
            "config": skill.config or {},
            "content": skill.content or "",
            "files": skill.files or {},
        }

    async def _export_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """导出单个 agent（含工具和 skill 引用）"""
        result = await self.db.execute(
            select(Agent)
            .options(selectinload(Agent.tools), selectinload(Agent.skills))
            .where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return None

        tools = []
        for t in (agent.tools or []):
            tools.append({
                "name": t.name,
                "kind": t.kind or t.name,
                "tool_type": t.tool_type,
                "description": t.description,
                "config": t.config or {},
            })

        return {
            "type": "agent",
            "scope": "global",
            "id": agent.id,
            "name": agent.name,
            # v2 P3: 删除 role 字段
            "avatar": agent.avatar,
            "description": agent.description,
            "system_prompt": agent.system_prompt or "",
            "llm_config": agent.llm_config or {},
            "capabilities": agent.capabilities or [],
            "tools": tools,
            "skill_refs": [s.name for s in (agent.skills or [])],
        }

    async def _export_project(self, project_id: str, selection: Dict[str, Any]) -> List[Dict[str, Any]]:
        """导出项目及关联资源"""
        result = await self.db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return []

        items: List[Dict[str, Any]] = []

        # 项目元数据
        items.append({
            "type": "project",
            "scope": "project",
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "cover_color": project.cover_color,
            "tags": project.tags or [],
            "status": project.status,
            "workflow_config": project.workflow_config or {},
        })

        # 项目关联的 agents
        if selection.get("agents", True):
            pa_result = await self.db.execute(
                select(ProjectAgent, Agent)
                .join(Agent, Agent.id == ProjectAgent.agent_id)
                .where(ProjectAgent.project_id == project_id)
                .options(selectinload(Agent.tools), selectinload(Agent.skills))
            )
            for pa, agent in pa_result.all():
                tools = [{"name": t.name, "kind": t.kind or t.name, "tool_type": t.tool_type,
                          "description": t.description, "config": t.config or {}} for t in (agent.tools or [])]
                items.append({
                    "type": "agent",
                    "scope": f"project:{project_id}",
                    "id": agent.id,
                    "project_agent_id": pa.id,
                    "name": agent.name,
                    # v2 P3: 删除 role 字段
                    "avatar": agent.avatar,
                    "description": agent.description,
                    "system_prompt": agent.system_prompt or "",
                    "llm_config": agent.llm_config or {},
                    "capabilities": agent.capabilities or [],
                    "tools": tools,
                    "skill_refs": [s.name for s in (agent.skills or [])],
                    "override_config": pa.override_config or {},
                })

        # 项目关联的 skills
        if selection.get("skills", True):
            skill_result = await self.db.execute(
                select(Skill)
                .join(AgentSkill, AgentSkill.skill_id == Skill.id)
                .join(ProjectAgent, ProjectAgent.agent_id == AgentSkill.agent_id)
                .where(ProjectAgent.project_id == project_id)
            )
            for skill in skill_result.scalars().unique().all():
                items.append({
                    "type": "skill",
                    "scope": f"project:{project_id}",
                    "id": skill.id,
                    "name": skill.name,
                    "description": skill.description,
                    "skill_type": skill.skill_type,
                    "config": skill.config or {},
                    "content": skill.content or "",
                    "files": skill.files or {},
                })

        # 群聊
        if selection.get("groups", True):
            group_result = await self.db.execute(
                select(Group).where(Group.project_id == project_id).order_by(Group.order_index)
            )
            for group in group_result.scalars().all():
                members_result = await self.db.execute(
                    select(GroupMember, ProjectAgent, Agent)
                    .join(ProjectAgent, ProjectAgent.id == GroupMember.project_agent_id)
                    .join(Agent, Agent.id == ProjectAgent.agent_id)
                    .where(GroupMember.group_id == group.id)
                )
                members = [
                    {"agent_name": agent.name, "role": gm.role}
                    for gm, pa, agent in members_result.all()
                ]
                items.append({
                    "type": "group",
                    "scope": f"project:{project_id}",
                    "id": group.id,
                    "name": group.name,
                    "description": group.description,
                    "status": group.status,
                    "order_index": group.order_index,
                    "autonomy_level": group.autonomy_level,
                    "members": members,
                })

        # 任务
        if selection.get("tasks", True):
            task_result = await self.db.execute(
                select(Task, Group)
                .join(Group, Group.id == Task.group_id)
                .where(Group.project_id == project_id)
                .order_by(Task.order_index)
            )
            for task, group in task_result.all():
                items.append({
                    "type": "task",
                    "scope": f"project:{project_id}",
                    "id": task.id,
                    "group_id": task.group_id,
                    "group_name": group.name,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status,
                    "order_index": task.order_index,
                    "acceptance_criteria": task.acceptance_criteria,
                })

        # 资料
        if selection.get("resources", True):
            res_result = await self.db.execute(
                select(Resource).where(Resource.project_id == project_id)
            )
            for r in res_result.scalars().all():
                items.append({
                    "type": "resource",
                    "scope": f"project:{project_id}",
                    "id": r.id,
                    "title": r.title,
                    "content": r.content or "",
                    "content_type": r.content_type,
                    "resource_type": r.type,
                    "tags": r.tags or [],
                    "is_required": r.is_required,
                })

        # 标签
        if selection.get("tags", True):
            tag_result = await self.db.execute(
                select(Tag).where(Tag.project_id == project_id)
            )
            for t in tag_result.scalars().all():
                items.append({
                    "type": "tag",
                    "scope": f"project:{project_id}",
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "color": t.color,
                })

        return items

    def _create_zip(self, items: List[Dict[str, Any]]) -> bytes:
        """创建包含 manifest 的 ZIP"""
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source": "global",
            "items": items,
        }

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        buffer.seek(0)
        return buffer.getvalue()
