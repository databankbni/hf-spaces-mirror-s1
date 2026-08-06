"""
导出服务模块

负责将项目数据导出为ZIP文件。
"""

import io
import json
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent, AgentSkill, ProjectAgent, Skill
from app.models.chain import Chain, Packet
from app.models.deliverable import Deliverable
from app.models.group import Group, GroupMember
from app.models.memory import Memory
from app.models.project import Project
from app.models.resource import Resource
from app.models.tag import Tag
from app.models.task import Task, TaskAssignee


class ExportService:
    """导出服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def export_project(self, project_id: str) -> bytes:
        project = await self._get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        data = await self._collect_data(project_id)
        return self._create_zip(project, data)

    async def preview_project(self, project_id: str, selection: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        project = await self._get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        data = await self._collect_data(project_id, include_runtime=True)
        normalized = self._normalize_selection(selection)
        filtered, warnings = self._filter_data(data, normalized)
        counts = self._count_data(filtered)
        excluded = {
            key: max(0, len(data.get(key, [])) - len(filtered.get(key, [])))
            for key in ["agents", "skills", "groups", "tasks", "resources", "deliverables", "messages", "memories", "tags"]
        }

        return {
            "schema_version": "project_bundle.v1",
            "bundle_type": normalized["mode"],
            "selection": normalized,
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
            } if normalized.get("project_meta") else None,
            "counts": counts,
            "excluded": excluded,
            "warnings": warnings,
            "files": self._bundle_files(filtered),
        }

    async def export_project_bundle(self, project_id: str, selection: Optional[Dict[str, Any]] = None) -> bytes:
        project = await self._get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        data = await self._collect_data(project_id, include_runtime=True)
        normalized = self._normalize_selection(selection)
        filtered, warnings = self._filter_data(data, normalized)
        return self._create_bundle_zip(project, filtered, normalized, warnings)

    async def _collect_data(self, project_id: str, include_runtime: bool = False) -> Dict[str, Any]:
        data = {}
        data["agents"] = await self._get_project_agents(project_id)
        data["skills"] = await self._get_skills(project_id)
        data["groups"] = await self._get_groups(project_id)
        data["tasks"] = await self._get_tasks(project_id)
        data["deliverables"] = await self._get_deliverables(project_id)
        data["resources"] = await self._get_resources(project_id)
        data["memories"] = await self._get_memories(project_id)
        data["tags"] = await self._get_tags(project_id)
        data["messages"] = await self._get_messages(project_id) if include_runtime else []
        return data

    async def _get_project(self, project_id: str) -> Optional[Project]:
        query = select(Project).where(Project.id == project_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _get_project_agents(self, project_id: str) -> List[Dict[str, Any]]:
        query = (
            select(ProjectAgent, Agent)
            .join(Agent, Agent.id == ProjectAgent.agent_id)
            .where(ProjectAgent.project_id == project_id)
            .options(
                selectinload(Agent.tools),
                selectinload(Agent.skills),
            )
        )
        result = await self.db.execute(query)
        rows = result.all()

        agents = []
        for pa, agent in rows:
            agents.append({
                "id": pa.id,
                "agent_id": agent.id,
                "agent_name": agent.name,
                # v2 P3: 删除 agent_role 字段
                "agent_avatar": agent.avatar,
                "agent_description": agent.description,
                "system_prompt": agent.system_prompt,
                "llm_config": agent.llm_config,
                "capabilities": agent.capabilities,
                "override_config": pa.override_config,
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
                    }
                    for s in (agent.skills or [])
                ],
            })

        return agents

    async def _get_skills(self, project_id: str) -> List[Dict[str, Any]]:
        query = (
            select(Skill)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .join(ProjectAgent, ProjectAgent.agent_id == AgentSkill.agent_id)
            .where(ProjectAgent.project_id == project_id)
        )
        result = await self.db.execute(query)
        skills = list(result.scalars().unique().all())

        return [
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "skill_type": skill.skill_type,
                "content": skill.content,
                "config": skill.config,
            }
            for skill in skills
        ]

    async def _get_groups(self, project_id: str) -> List[Dict[str, Any]]:
        query = (
            select(Group)
            .where(Group.project_id == project_id)
            .order_by(Group.order_index)
        )
        result = await self.db.execute(query)
        groups = list(result.scalars().all())

        group_list = []
        for group in groups:
            members = await self._get_group_members(group.id)
            group_list.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "lead_agent_id": group.lead_agent_id,
                "status": group.status,
                "order_index": group.order_index,
                "autonomy_level": group.autonomy_level,
                "auto_advance": group.auto_advance,
                "members": members,
            })

        return group_list

    async def _get_group_members(self, group_id: str) -> List[Dict[str, Any]]:
        query = (
            select(GroupMember, ProjectAgent, Agent)
            .join(ProjectAgent, ProjectAgent.id == GroupMember.project_agent_id)
            .join(Agent, Agent.id == ProjectAgent.agent_id)
            .where(GroupMember.group_id == group_id)
        )
        result = await self.db.execute(query)
        rows = result.all()

        members = []
        for gm, pa, agent in rows:
            members.append({
                "id": gm.id,
                "project_agent_id": pa.id,
                "agent_name": agent.name,
                "role": gm.role,
            })

        return members

    async def _get_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        query = (
            select(Task, Group)
            .join(Group, Group.id == Task.group_id)
            .where(Group.project_id == project_id)
            .order_by(Group.order_index, Task.order_index)
        )
        result = await self.db.execute(query)
        rows = result.all()

        tasks = []
        for task, group in rows:
            assignees = await self._get_task_assignees(task.id)
            tasks.append({
                "id": task.id,
                "group_id": task.group_id,
                "group_name": group.name,
                "title": task.title,
                "description": task.description,
                "lead_agent_id": task.lead_agent_id,
                "status": task.status,
                "order_index": task.order_index,
                "acceptance_criteria": task.acceptance_criteria,
                "assignees": assignees,
            })

        return tasks

    async def _get_task_assignees(self, task_id: str) -> List[Dict[str, Any]]:
        query = (
            select(TaskAssignee, ProjectAgent, Agent)
            .join(ProjectAgent, ProjectAgent.id == TaskAssignee.project_agent_id)
            .join(Agent, Agent.id == ProjectAgent.agent_id)
            .where(TaskAssignee.task_id == task_id)
        )
        result = await self.db.execute(query)
        rows = result.all()

        assignees = []
        for ta, pa, agent in rows:
            assignees.append({
                "id": ta.id,
                "project_agent_id": pa.id,
                "agent_name": agent.name,
            })

        return assignees

    async def _get_deliverables(self, project_id: str) -> List[Dict[str, Any]]:
        query = (
            select(Deliverable, Group)
            .join(Group, Group.id == Deliverable.group_id)
            .where(Group.project_id == project_id)
        )
        result = await self.db.execute(query)
        rows = result.all()

        deliverables = []
        for d, group in rows:
            deliverables.append({
                "id": d.id,
                "group_id": d.group_id,
                "group_name": group.name,
                "task_id": d.task_id,
                "title": d.title,
                "content": d.content,
                "content_type": d.content_type,
                "type": d.type,
                "tags": d.tags,
                "scope": d.scope,
                "version": d.version,
                "filename": f"deliverables/{d.id}.md",
            })

        return deliverables

    async def _get_resources(self, project_id: str) -> List[Dict[str, Any]]:
        query = select(Resource).where(Resource.project_id == project_id)
        result = await self.db.execute(query)
        resources = list(result.scalars().all())

        resource_list = []
        for r in resources:
            resource_list.append({
                "id": r.id,
                "group_id": r.group_id,
                "title": r.title,
                "content": r.content,
                "content_type": r.content_type,
                "type": r.type,
                "tags": r.tags,
                "is_required": r.is_required,
                "created_by": r.created_by,
                "filename": f"resources/{r.id}.md",
            })

        return resource_list

    async def _get_memories(self, project_id: str) -> List[Dict[str, Any]]:
        query = (
            select(Memory, Agent)
            .join(Agent, Agent.id == Memory.agent_id)
            .where(Memory.project_id == project_id)
        )
        result = await self.db.execute(query)
        rows = result.all()

        memories = []
        for m, agent in rows:
            memories.append({
                "id": m.id,
                "agent_id": m.agent_id,
                "agent_name": agent.name,
                "content": m.content,
                "tags": m.tags,
                "filename": f"memories/{m.id}.md",
            })

        return memories

    async def _get_messages(self, project_id: str) -> List[Dict[str, Any]]:
        query = (
            select(Packet, Chain, Group)
            .join(Chain, Chain.id == Packet.chain_id)
            .join(Group, Group.id == Chain.group_id)
            .where(Group.project_id == project_id)
            .order_by(Group.order_index, Packet.created_at)
        )
        result = await self.db.execute(query)
        rows = result.all()

        messages = []
        for packet, chain, group in rows:
            messages.append({
                "id": packet.id,
                "chain_id": packet.chain_id,
                "task_id": chain.task_id,
                "group_id": group.id,
                "group_name": group.name,
                "sender_id": packet.sender_id,
                "sender_type": packet.sender_type,
                "sender_name": packet.sender_name,
                "content": packet.content,
                "content_type": packet.content_type,
                "metadata": packet.metadata_json,
                "created_at": packet.created_at.isoformat() if packet.created_at else None,
                "filename": f"messages/{packet.id}.md",
            })

        return messages

    async def _get_tags(self, project_id: str) -> List[Dict[str, Any]]:
        query = select(Tag).where(Tag.project_id == project_id)
        result = await self.db.execute(query)
        tags = list(result.scalars().all())

        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "suggested_template": t.suggested_template,
                "color": t.color,
            }
            for t in tags
        ]

    def _normalize_selection(self, selection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        raw = selection or {}
        mode = raw.get("mode") or raw.get("bundle_type") or "custom"
        presets = {
            "share": {
                "project_meta": True,
                "agents": True,
                "skills": True,
                "groups": True,
                "tasks": True,
                "resources": True,
                "deliverables": False,
                "messages": False,
                "memories": False,
                "tags": True,
            },
            "template": {
                "project_meta": True,
                "agents": True,
                "skills": True,
                "groups": True,
                "tasks": True,
                "resources": True,
                "deliverables": False,
                "messages": False,
                "memories": False,
                "tags": True,
            },
            "backup": {
                "project_meta": True,
                "agents": True,
                "skills": True,
                "groups": True,
                "tasks": True,
                "resources": True,
                "deliverables": True,
                "messages": True,
                "memories": True,
                "tags": True,
            },
            "custom": {
                "project_meta": True,
                "agents": True,
                "skills": True,
                "groups": False,
                "tasks": False,
                "resources": True,
                "deliverables": False,
                "messages": False,
                "memories": False,
                "tags": True,
            },
        }
        normalized = {**presets.get(mode, presets["custom"]), **raw}
        normalized["mode"] = mode if mode in presets else "custom"

        for key in ["agents", "skills", "groups", "tasks", "deliverables", "messages", "memories", "tags"]:
            normalized[key] = self._normalize_item_selection(normalized.get(key))

        resources = normalized.get("resources")
        if isinstance(resources, dict):
            normalized["resources"] = {
                "include": resources.get("include", True),
                "types": resources.get("types") or [],
                "ids": resources.get("ids") or [],
                "required_only": bool(resources.get("required_only", False)),
            }
        else:
            normalized["resources"] = {
                "include": bool(resources),
                "types": [],
                "ids": [],
                "required_only": False,
            }

        normalized["options"] = normalized.get("options") or {}
        return normalized

    def _normalize_item_selection(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return {
                "include": bool(value.get("include", True)),
                "ids": value.get("ids") or [],
                "group_ids": value.get("group_ids") or [],
                "task_ids": value.get("task_ids") or [],
            }
        return {
            "include": bool(value),
            "ids": [],
            "group_ids": [],
            "task_ids": [],
        }

    def _selection_enabled(self, selection: Dict[str, Any], key: str) -> bool:
        value = selection.get(key)
        if isinstance(value, dict):
            return bool(value.get("include"))
        return bool(value)

    def _selection_ids(self, selection: Dict[str, Any], key: str, id_key: str = "ids") -> set[str]:
        value = selection.get(key)
        if isinstance(value, dict):
            return set(value.get(id_key) or [])
        return set()

    def _filter_by_selection(self, items: List[Dict[str, Any]], selection: Dict[str, Any], key: str, aliases: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if not self._selection_enabled(selection, key):
            return []

        ids = self._selection_ids(selection, key)
        if not ids:
            return items

        alias_keys = aliases or ["id"]
        return [
            item for item in items
            if any(item.get(alias) in ids for alias in alias_keys)
        ]

    def _filter_data(self, data: Dict[str, Any], selection: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
        warnings = []
        filtered: Dict[str, Any] = {}

        filtered["agents"] = self._filter_by_selection(data.get("agents", []), selection, "agents", ["id", "agent_id"])
        filtered["skills"] = self._filter_by_selection(data.get("skills", []), selection, "skills")
        filtered["groups"] = self._filter_by_selection(data.get("groups", []), selection, "groups")
        filtered["memories"] = self._filter_by_selection(data.get("memories", []), selection, "memories")
        filtered["tags"] = self._filter_by_selection(data.get("tags", []), selection, "tags")

        group_ids = {group["id"] for group in filtered["groups"]}
        filtered["tasks"] = self._filter_by_selection(data.get("tasks", []), selection, "tasks")
        if group_ids and not self._selection_ids(selection, "tasks"):
            filtered["tasks"] = [task for task in filtered["tasks"] if task.get("group_id") in group_ids]

        task_ids = {task["id"] for task in filtered["tasks"]}
        filtered["deliverables"] = self._filter_by_selection(data.get("deliverables", []), selection, "deliverables")
        deliverable_ids = self._selection_ids(selection, "deliverables")
        if not deliverable_ids:
            if group_ids:
                filtered["deliverables"] = [item for item in filtered["deliverables"] if item.get("group_id") in group_ids]
            if task_ids:
                filtered["deliverables"] = [item for item in filtered["deliverables"] if not item.get("task_id") or item.get("task_id") in task_ids]

        filtered["messages"] = self._filter_by_selection(data.get("messages", []), selection, "messages")
        message_ids = self._selection_ids(selection, "messages")
        message_group_ids = self._selection_ids(selection, "messages", "group_ids") or group_ids
        message_task_ids = self._selection_ids(selection, "messages", "task_ids") or task_ids
        if not message_ids:
            if message_group_ids:
                filtered["messages"] = [item for item in filtered["messages"] if item.get("group_id") in message_group_ids]
            if message_task_ids:
                filtered["messages"] = [item for item in filtered["messages"] if not item.get("task_id") or item.get("task_id") in message_task_ids]

        resource_selection = selection.get("resources", {})
        resources = data.get("resources", []) if resource_selection.get("include") else []
        resource_types = set(resource_selection.get("types") or [])
        resource_ids = set(resource_selection.get("ids") or [])

        if resource_types:
            resources = [resource for resource in resources if resource.get("type") in resource_types]
        if resource_ids:
            resources = [resource for resource in resources if resource.get("id") in resource_ids]
        if resource_selection.get("required_only"):
            resources = [resource for resource in resources if resource.get("is_required")]

        filtered["resources"] = resources

        if self._selection_enabled(selection, "messages") and not self._selection_enabled(selection, "groups"):
            warnings.append("聊天记录依赖群聊结构，建议同时导出群聊。")
        if self._selection_enabled(selection, "tasks") and not self._selection_enabled(selection, "groups"):
            warnings.append("任务依赖群聊结构，建议同时导出群聊。")
        if self._selection_enabled(selection, "skills") and not self._selection_enabled(selection, "agents"):
            warnings.append("Skill 来自项目 Agent 绑定关系，未导出 Agent 时只能作为独立 Skill 参考。")
        if selection.get("mode") == "template" and (self._selection_enabled(selection, "messages") or self._selection_enabled(selection, "deliverables")):
            warnings.append("模板模式通常不包含聊天记录或交付物，当前选择会保留运行态内容。")

        return filtered, warnings

    def _count_data(self, data: Dict[str, Any]) -> Dict[str, int]:
        return {
            "agents": len(data.get("agents", [])),
            "skills": len(data.get("skills", [])),
            "groups": len(data.get("groups", [])),
            "tasks": len(data.get("tasks", [])),
            "resources": len(data.get("resources", [])),
            "deliverables": len(data.get("deliverables", [])),
            "messages": len(data.get("messages", [])),
            "memories": len(data.get("memories", [])),
            "tags": len(data.get("tags", [])),
        }

    def _bundle_files(self, data: Dict[str, Any]) -> Dict[str, List[str]]:
        return {
            "resources": [r["filename"] for r in data.get("resources", [])],
            "deliverables": [d["filename"] for d in data.get("deliverables", [])],
            "memories": [m["filename"] for m in data.get("memories", [])],
            "messages": [m["filename"] for m in data.get("messages", [])],
        }

    def _create_zip(self, project: Project, data: Dict[str, Any]) -> bytes:
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            manifest = self._create_manifest(project, data)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

            for d in data.get("deliverables", []):
                zf.writestr(d["filename"], d["content"])

            for r in data.get("resources", []):
                zf.writestr(r["filename"], r["content"])

            for m in data.get("memories", []):
                zf.writestr(m["filename"], m["content"])

        buffer.seek(0)
        return buffer.getvalue()

    def _create_bundle_zip(self, project: Project, data: Dict[str, Any], selection: Dict[str, Any], warnings: List[str]) -> bytes:
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            manifest = self._create_bundle_manifest(project, data, selection, warnings)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr("data/agents.json", json.dumps(data.get("agents", []), ensure_ascii=False, indent=2))
            zf.writestr("data/skills.json", json.dumps(data.get("skills", []), ensure_ascii=False, indent=2))
            zf.writestr("data/groups.json", json.dumps(data.get("groups", []), ensure_ascii=False, indent=2))
            zf.writestr("data/tasks.json", json.dumps(data.get("tasks", []), ensure_ascii=False, indent=2))
            zf.writestr("data/tags.json", json.dumps(data.get("tags", []), ensure_ascii=False, indent=2))

            for d in data.get("deliverables", []):
                zf.writestr(d["filename"], d["content"] or "")

            for r in data.get("resources", []):
                zf.writestr(r["filename"], r["content"] or "")

            for m in data.get("memories", []):
                zf.writestr(m["filename"], m["content"] or "")

            for message in data.get("messages", []):
                zf.writestr(message["filename"], message.get("content") or "")

        buffer.seek(0)
        return buffer.getvalue()

    def _create_manifest(self, project: Project, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "cover_color": project.cover_color,
                "tags": project.tags,
                "status": project.status,
                "workflow_config": project.workflow_config,
            },
            "structure": {
                "agents": data.get("agents", []),
                "groups": [
                    {
                        "id": g["id"],
                        "name": g["name"],
                        "description": g.get("description"),
                        "order_index": g["order_index"],
                        "status": g["status"],
                        "autonomy_level": g.get("autonomy_level"),
                        "members": g.get("members", []),
                    }
                    for g in data.get("groups", [])
                ],
                "tasks": [
                    {
                        "id": t["id"],
                        "group_id": t["group_id"],
                        "title": t["title"],
                        "description": t.get("description"),
                        "status": t["status"],
                        "acceptance_criteria": t.get("acceptance_criteria"),
                        "assignees": t.get("assignees", []),
                    }
                    for t in data.get("tasks", [])
                ],
            },
            "files": {
                "deliverables": [d["filename"] for d in data.get("deliverables", [])],
                "resources": [r["filename"] for r in data.get("resources", [])],
                "memories": [m["filename"] for m in data.get("memories", [])],
            },
            "tags": data.get("tags", []),
            "statistics": {
                "agent_count": len(data.get("agents", [])),
                "group_count": len(data.get("groups", [])),
                "task_count": len(data.get("tasks", [])),
                "deliverable_count": len(data.get("deliverables", [])),
                "resource_count": len(data.get("resources", [])),
                "memory_count": len(data.get("memories", [])),
            },
        }

    def _create_bundle_manifest(self, project: Project, data: Dict[str, Any], selection: Dict[str, Any], warnings: List[str]) -> Dict[str, Any]:
        return {
            "schema_version": "project_bundle.v1",
            "bundle_type": selection.get("mode", "custom"),
            "created_at": datetime.utcnow().isoformat(),
            "source_app": "vov",
            "selection": selection,
            "contents": self._count_data(data),
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "cover_color": project.cover_color,
                "tags": project.tags,
                "status": project.status,
                "workflow_config": project.workflow_config,
            } if selection.get("project_meta") else None,
            "structure": {
                "agents": data.get("agents", []),
                "skills": data.get("skills", []),
                "groups": data.get("groups", []),
                "tasks": data.get("tasks", []),
            },
            "files": self._bundle_files(data),
            "tags": data.get("tags", []),
            "warnings": warnings,
        }
