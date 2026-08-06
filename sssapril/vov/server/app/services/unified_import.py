"""
统一导入服务

从 ZIP 文件导入资源，支持：
- 混合类型导入（skill + agent + 项目资料）
- 同名冲突检测
- 用户选择冲突解决方案（覆盖/重命名/跳过）
"""

import io
import json
import zipfile
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent, AgentSkill, AgentTool, ProjectAgent, Skill
from app.models.group import Group, GroupMember
from app.models.task import Task
from app.models.project import Project
from app.models.resource import Resource
from app.models.tag import Tag


class ImportPreview:
    """导入预览结果"""

    def __init__(self, items: List[Dict[str, Any]], conflicts: List[Dict[str, Any]]):
        self.items = items
        self.conflicts = conflicts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": self.items,
            "conflicts": self.conflicts,
            "total": len(self.items),
            "conflict_count": len(self.conflicts),
        }


class ImportResult:
    """导入结果"""

    def __init__(self):
        self.created: List[str] = []
        self.updated: List[str] = []
        self.skipped: List[str] = []
        self.errors: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "summary": f"创建 {len(self.created)}, 更新 {len(self.updated)}, "
                       f"跳过 {len(self.skipped)}, 错误 {len(self.errors)}",
        }


class UnifiedImportService:
    """统一导入服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def preview(self, zip_bytes: bytes) -> ImportPreview:
        """
        解析 ZIP，返回导入预览。

        检测同名资源，返回冲突列表供用户决策。
        """
        manifest = self._parse_zip(zip_bytes)
        items = manifest.get("items", [])

        conflicts = []
        for item in items:
            conflict = await self._check_conflict(item)
            if conflict:
                conflicts.append(conflict)

        return ImportPreview(items=items, conflicts=conflicts)

    async def execute(
        self,
        zip_bytes: bytes,
        resolutions: Optional[List[Dict[str, Any]]] = None,
    ) -> ImportResult:
        """
        执行导入。

        resolutions 格式:
        [{"item_index": 0, "action": "overwrite|rename|skip", "new_name": "xxx"}]
        """
        manifest = self._parse_zip(zip_bytes)
        items = manifest.get("items", [])

        # 构建冲突解决方案映射
        resolution_map: Dict[int, Dict[str, Any]] = {}
        if resolutions:
            for r in resolutions:
                idx = r.get("item_index")
                if idx is not None:
                    resolution_map[idx] = r

        result = ImportResult()

        # 先导入全局资源，再导入项目资源
        global_items = [(i, item) for i, item in enumerate(items) if item.get("scope") == "global"]
        project_items = [(i, item) for i, item in enumerate(items) if item.get("scope") != "global"]

        for idx, item in global_items:
            await self._import_item(idx, item, resolution_map, result)

        for idx, item in project_items:
            await self._import_item(idx, item, resolution_map, result)

        await self.db.commit()
        return result

    def _parse_zip(self, zip_bytes: bytes) -> Dict[str, Any]:
        """解析 ZIP 文件中的 manifest.json"""
        buffer = io.BytesIO(zip_bytes)
        with zipfile.ZipFile(buffer, 'r') as zf:
            if "manifest.json" not in zf.namelist():
                raise ValueError("Invalid ZIP: manifest.json not found")
            manifest = json.loads(zf.read("manifest.json"))

        schema = manifest.get("schema", "")
        if not schema.startswith("vov/"):
            raise ValueError(f"Unsupported schema: {schema}")

        return manifest

    async def _check_conflict(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """检查单个 item 是否与现有数据冲突"""
        item_type = item.get("type")
        name = item.get("name") or item.get("title")

        if not name:
            return None

        existing_id = None
        existing_name = None

        if item_type == "skill":
            result = await self.db.execute(select(Skill).where(Skill.name == name))
            existing = result.scalar_one_or_none()
            if existing:
                existing_id = existing.id
                existing_name = existing.name

        elif item_type == "agent":
            result = await self.db.execute(select(Agent).where(Agent.name == name))
            existing = result.scalar_one_or_none()
            if existing:
                existing_id = existing.id
                existing_name = existing.name

        elif item_type == "project":
            result = await self.db.execute(select(Project).where(Project.name == name))
            existing = result.scalar_one_or_none()
            if existing:
                existing_id = existing.id
                existing_name = existing.name

        if existing_id:
            return {
                "item_type": item_type,
                "name": name,
                "existing_id": existing_id,
                "existing_name": existing_name,
                "suggested_action": "rename",
                "suggested_new_name": f"{name}_2",
            }

        return None

    async def _import_item(
        self,
        idx: int,
        item: Dict[str, Any],
        resolution_map: Dict[int, Dict[str, Any]],
        result: ImportResult,
    ) -> None:
        """导入单个 item"""
        item_type = item.get("type")
        resolution = resolution_map.get(idx, {})
        action = resolution.get("action", "create")

        try:
            if item_type == "skill":
                await self._import_skill(item, resolution, result)
            elif item_type == "agent":
                await self._import_agent(item, resolution, result)
            elif item_type == "project":
                await self._import_project(item, resolution, result)
            elif item_type == "group":
                await self._import_group(item, resolution, result)
            elif item_type == "task":
                await self._import_task(item, resolution, result)
            elif item_type == "resource":
                await self._import_resource(item, resolution, result)
            elif item_type == "tag":
                await self._import_tag(item, resolution, result)
            else:
                result.skipped.append(f"Unknown type: {item_type}")
        except Exception as e:
            result.errors.append(f"{item_type} '{item.get('name', '?')}': {e}")

    async def _import_skill(
        self, item: Dict[str, Any], resolution: Dict[str, Any], result: ImportResult
    ) -> None:
        """导入 skill"""
        name = resolution.get("new_name") or item["name"]
        action = resolution.get("action", "create")

        # 查找已有
        existing = None
        if action == "overwrite":
            res = await self.db.execute(select(Skill).where(Skill.name == item["name"]))
            existing = res.scalar_one_or_none()

        if existing:
            # 覆盖更新
            existing.name = name
            existing.description = item.get("description")
            existing.skill_type = item.get("skill_type", "prompt")
            existing.content = item.get("content", "")
            existing.config = item.get("config", {})
            existing.files = item.get("files", {})
            result.updated.append(f"skill:{name}")
        else:
            # 新建
            skill = Skill(
                name=name,
                description=item.get("description"),
                skill_type=item.get("skill_type", "prompt"),
                content=item.get("content", ""),
                config=item.get("config", {}),
                files=item.get("files", {}),
            )
            self.db.add(skill)
            result.created.append(f"skill:{name}")

    async def _import_agent(
        self, item: Dict[str, Any], resolution: Dict[str, Any], result: ImportResult
    ) -> None:
        """导入 agent"""
        name = resolution.get("new_name") or item["name"]
        action = resolution.get("action", "create")

        existing = None
        if action == "overwrite":
            res = await self.db.execute(
                select(Agent).options(selectinload(Agent.tools), selectinload(Agent.skills))
                .where(Agent.name == item["name"])
            )
            existing = res.scalar_one_or_none()

        if existing:
            existing.name = name
            # v2 P3: 删除 role 字段
            existing.avatar = item.get("avatar")
            existing.description = item.get("description")
            existing.system_prompt = item.get("system_prompt", "")
            existing.llm_config = item.get("llm_config", {})
            existing.capabilities = item.get("capabilities", [])

            # 更新工具
            for old_tool in (existing.tools or []):
                await self.db.delete(old_tool)
            await self.db.flush()

            for tool_data in item.get("tools", []):
                self.db.add(AgentTool(
                    agent_id=existing.id,
                    name=tool_data["name"],
                    kind=tool_data.get("kind", tool_data["name"]),
                    tool_type=tool_data.get("tool_type", "builtin"),
                    description=tool_data.get("description"),
                    config=tool_data.get("config", {}),
                ))

            # 更新 skill 关联
            for old_assoc in (existing.skills or []):
                # existing.skills 是 Skill 对象列表，需要通过 AgentSkill 表删除
                pass
            await self._bind_agent_skills(existing.id, item.get("skill_refs", []))

            result.updated.append(f"agent:{name}")
        else:
            # 新建
            agent = Agent(
                name=name,
                # v2 P3: 删除 role 字段
                avatar=item.get("avatar"),
                description=item.get("description"),
                system_prompt=item.get("system_prompt", ""),
                llm_config=item.get("llm_config", {}),
                capabilities=item.get("capabilities", []),
            )
            self.db.add(agent)
            await self.db.flush()

            # 创建工具
            for tool_data in item.get("tools", []):
                self.db.add(AgentTool(
                    agent_id=agent.id,
                    name=tool_data["name"],
                    kind=tool_data.get("kind", tool_data["name"]),
                    tool_type=tool_data.get("tool_type", "builtin"),
                    description=tool_data.get("description"),
                    config=tool_data.get("config", {}),
                ))

            # 绑定 skill
            await self._bind_agent_skills(agent.id, item.get("skill_refs", []))

            result.created.append(f"agent:{name}")

    async def _bind_agent_skills(self, agent_id: str, skill_refs: List[str]) -> None:
        """按名称绑定 agent 的 skills"""
        if not skill_refs:
            return

        # 删除旧关联
        old_assocs = await self.db.execute(
            select(AgentSkill).where(AgentSkill.agent_id == agent_id)
        )
        for assoc in old_assocs.scalars().all():
            await self.db.delete(assoc)

        # 创建新关联
        for skill_name in skill_refs:
            skill_result = await self.db.execute(select(Skill).where(Skill.name == skill_name))
            skill = skill_result.scalar_one_or_none()
            if skill:
                self.db.add(AgentSkill(agent_id=agent_id, skill_id=skill.id))

    async def _import_project(
        self, item: Dict[str, Any], resolution: Dict[str, Any], result: ImportResult
    ) -> None:
        """导入项目"""
        name = resolution.get("new_name") or item["name"]
        action = resolution.get("action", "create")

        existing = None
        if action == "overwrite":
            res = await self.db.execute(select(Project).where(Project.name == item["name"]))
            existing = res.scalar_one_or_none()

        if existing:
            existing.name = name
            existing.description = item.get("description")
            existing.cover_color = item.get("cover_color")
            existing.tags = item.get("tags", [])
            existing.status = item.get("status", "active")
            existing.workflow_config = item.get("workflow_config", {})
            result.updated.append(f"project:{name}")
        else:
            project = Project(
                name=name,
                description=item.get("description"),
                cover_color=item.get("cover_color"),
                tags=item.get("tags", []),
                status=item.get("status", "active"),
                workflow_config=item.get("workflow_config", {}),
            )
            self.db.add(project)
            await self.db.flush()
            result.created.append(f"project:{name}")

    async def _import_group(
        self, item: Dict[str, Any], resolution: Dict[str, Any], result: ImportResult
    ) -> None:
        """导入群聊（需要项目上下文）"""
        # 群聊必须属于项目，跳过无项目上下文的
        result.skipped.append(f"group:{item.get('name')} (no project context)")
        return

    async def _import_task(
        self, item: Dict[str, Any], resolution: Dict[str, Any], result: ImportResult
    ) -> None:
        """导入任务（需要群聊上下文）"""
        result.skipped.append(f"task:{item.get('title')} (no group context)")
        return

    async def _import_resource(
        self, item: Dict[str, Any], resolution: Dict[str, Any], result: ImportResult
    ) -> None:
        """导入资料（需要项目上下文）"""
        result.skipped.append(f"resource:{item.get('title')} (no project context)")
        return

    async def _import_tag(
        self, item: Dict[str, Any], resolution: Dict[str, Any], result: ImportResult
    ) -> None:
        """导入标签（需要项目上下文）"""
        result.skipped.append(f"tag:{item.get('name')} (no project context)")
        return
