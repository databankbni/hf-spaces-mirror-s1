"""
项目Service模块

提供项目(Project)的业务逻辑。
"""

import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project
from app.models.agent import Agent, AgentTool, ProjectAgent
from app.repositories.project_repo import ProjectRepository
from app.repositories.agent_repo import SkillRepository
from .base import BaseService

logger = logging.getLogger(__name__)

# v2 P2: 默认项目总控 agent 模板路径。
# 空白项目（POST /projects）创建后, 自动用此模板建出 project-level coordinator agent,
# 用户进项目就有'项目总控·编舟'可聊, 帮用户编排 pipeline。
# 模板项目（POST /templates/apply）自带 coordinator, 不走此路径。
DEFAULT_COORDINATOR_TEMPLATE_PATH = (
    Path(__file__).parent.parent / "default_presets" / "agent_templates" / "coordinator.json"
)


class ProjectService(BaseService[Project, ProjectRepository]):
    """
    项目Service

    提供项目相关的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = ProjectRepository(db)
        super().__init__(repo, db)

    async def get_list(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        获取项目列表（包含统计信息）

        Args:
            filters: 筛选条件

        Returns:
            List[Dict]: 项目列表
        """
        return await self.repo.get_list_with_stats(filters)

    async def get_detail(self, id: str) -> Optional[Project]:
        """
        获取项目详情

        Args:
            id: 项目ID

        Returns:
            Optional[Project]: 项目详情
        """
        return await self.repo.get_with_details(id)

    async def create_project(self, data: Dict[str, Any]) -> Project:
        """
        创建项目

        Args:
            data: 项目数据

        Returns:
            Project: 创建的项目

        v2 P2: 空白项目自动建出 project-level coordinator agent。
        - 加载默认 coordinator agent 模板（app/default_presets/agent_templates/coordinator.json）
        - 按 name upsert global Agent + tools（幂等）
        - 创建 ProjectAgent 关联
        - 与 project 在同一事务中提交（get_db 依赖负责 commit）
        """
        # 设置默认值
        if "status" not in data:
            data["status"] = "active"
        if "workflow_config" not in data:
            data["workflow_config"] = {}

        project = await self.repo.create(data)
        await self.db.flush()

        # v2 P2: 自动建出 project-level coordinator agent
        # 设计意图: 空白项目用户进来第一个就看到编舟, 可以聊着收需求构造 pipeline
        try:
            await self._ensure_project_coordinator(project)
        except Exception as e:
            # 兜底: coordinator bootstrap 失败不应阻断项目创建
            # 用户仍可在项目里手动创建 coordinator
            logger.warning(
                "[create_project] _ensure_project_coordinator failed for project=%s: %s",
                project.id, e,
            )

        return project

    async def update_project(self, id: str, data: Dict[str, Any]) -> Optional[Project]:
        """
        更新项目

        Args:
            id: 项目ID
            data: 更新数据

        Returns:
            Optional[Project]: 更新后的项目
        """
        return await self.repo.update(id, data)

    async def delete_project(self, id: str) -> bool:
        """
        删除项目

        Args:
            id: 项目ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)

    # ── v2 P2: 默认 coordinator 引导 ──

    async def _ensure_project_coordinator(self, project: Project) -> Optional[ProjectAgent]:
        """
        空白项目自动建出 project-level coordinator agent (项目总控·编舟)。

        行为:
        1. 加载 default coordinator 模板（coordinator.json）
        2. 按 name upsert global Agent（同名复用, 不同则更新 prompt/tools/skills）
        3. 重建 AgentTool 绑定（删旧 + 加新）
        4. 按 skill_refs 绑定/创建 Skill, 再建 AgentSkill 关联
        5. 建 ProjectAgent 关联
        6. 返回 ProjectAgent

        与 project 同一事务（db 由调用方管理 commit）。
        """
        template = self._load_default_coordinator_template()
        if not template:
            logger.warning("[_ensure_project_coordinator] template not found, skip")
            return None

        agent_data = template.get("agent", {})
        agent_name = agent_data.get("name")
        if not agent_name:
            logger.warning("[_ensure_project_coordinator] template missing 'agent.name', skip")
            return None

        # 1. 复用/创建 global Agent
        agent = await self._upsert_coordinator_agent(agent_data)

        # 2. 检查 ProjectAgent 是否已存在（幂等: 同项目 + 同 agent 不重复建）
        existing_pa = (await self.db.execute(
            select(ProjectAgent).where(
                ProjectAgent.project_id == project.id,
                ProjectAgent.agent_id == agent.id,
            )
        )).scalar_one_or_none()
        if existing_pa:
            logger.info(
                "[_ensure_project_coordinator] project=%s already has agent %s, skip",
                project.id, agent.name,
            )
            return existing_pa

        # 3. 建 ProjectAgent
        pa = ProjectAgent(
            project_id=project.id,
            agent_id=agent.id,
            override_config={},
        )
        self.db.add(pa)
        await self.db.flush()
        logger.info(
            "[_ensure_project_coordinator] created ProjectAgent: project=%s agent=%s (id=%s)",
            project.id, agent.name, pa.id,
        )
        return pa

    def _load_default_coordinator_template(self) -> Optional[Dict[str, Any]]:
        """加载默认 coordinator agent 模板 JSON"""
        if not DEFAULT_COORDINATOR_TEMPLATE_PATH.exists():
            return None
        try:
            with open(DEFAULT_COORDINATOR_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(
                "[_load_default_coordinator_template] failed to load %s: %s",
                DEFAULT_COORDINATOR_TEMPLATE_PATH, e,
            )
            return None

    async def _upsert_coordinator_agent(self, agent_data: Dict[str, Any]) -> Agent:
        """
        按 name 复用/创建 Agent, 同步 tools 和 skill 绑定。

        同步策略（与 template_service._upsert_agents 对齐）:
        - role / avatar / description / system_prompt / llm_config / capabilities / force_tool_choice: 覆盖
        - tools: 删旧 + 加新（保证和模板一致）
        - skills: 按 skill_refs 名字解析 id（已有则复用, 没有则创建空 skill）, 建 AgentSkill 关联
        """
        name = agent_data["name"]

        # 1. 查现有
        res = await self.db.execute(
            select(Agent)
            .options(selectinload(Agent.tools), selectinload(Agent.skills))
            .where(Agent.name == name)
        )
        existing = res.scalar_one_or_none()

        if existing:
            # v2 P3: 删除 role 字段, 只覆盖余下字段
            existing.avatar = agent_data.get("avatar", existing.avatar)
            existing.description = agent_data.get("description", existing.description)
            existing.system_prompt = agent_data.get("system_prompt", existing.system_prompt)
            existing.llm_config = agent_data.get("llm_config", existing.llm_config or {})
            existing.capabilities = agent_data.get("capabilities", existing.capabilities or [])
            existing.force_tool_choice = bool(
                agent_data.get("force_tool_choice", existing.force_tool_choice)
            )
            agent = existing
        else:
            agent = Agent(
                name=name,
                # v2 P3: 删除 role 字段
                avatar=agent_data.get("avatar"),
                description=agent_data.get("description"),
                system_prompt=agent_data.get("system_prompt", ""),
                llm_config=agent_data.get("llm_config", {}),
                capabilities=agent_data.get("capabilities", []),
                force_tool_choice=bool(agent_data.get("force_tool_choice", False)),
            )
            self.db.add(agent)
            await self.db.flush()

        # 2. 重建 tools
        # v2 P2: 用 bulk delete 而不是 iterate-delete, 避免 identity map 在 commit 后
        # 状态混乱 (之前会出 'expected 29, 0 matched' SAWarning + UNIQUE 撞约束)
        from sqlalchemy import delete as sa_delete
        await self.db.execute(
            sa_delete(AgentTool).where(AgentTool.agent_id == agent.id)
        )
        await self.db.flush()
        for tool_data in agent_data.get("tools", []):
            self.db.add(AgentTool(
                agent_id=agent.id,
                name=tool_data["name"],
                kind=tool_data.get("kind", tool_data["name"]),
                tool_type=tool_data.get("tool_type", "builtin"),
                description=tool_data.get("description"),
                config=tool_data.get("config", {}),
            ))
        await self.db.flush()

        # 3. 同步 skill_refs (resolve by name; auto-create if missing)
        await self._sync_agent_skill_refs(agent, agent_data.get("skill_refs", []))

        return agent

    async def _sync_agent_skill_refs(self, agent: Agent, skill_refs: List[str]) -> None:
        """
        按名字解析 skill_refs, 给 agent 建 AgentSkill 关联。
        - 已有的 active skill: 复用
        - 软删除的 skill: 恢复并复用
        - 完全不存在: 自动创建一个 minimal skill（skill_type=prompt, content='', description='auto-created by coordinator bootstrap'）
          — 这样 coordinator agent 永远有声明的 skill_refs 都能解析, 不会因缺 skill 而报 'skill not found'
        """
        from app.models.agent import Skill, AgentSkill
        from sqlalchemy import delete as sa_delete

        skill_repo = SkillRepository(self.db)

        # 删旧绑定 (bulk, 同上避免 identity map 状态问题)
        await self.db.execute(
            sa_delete(AgentSkill).where(AgentSkill.agent_id == agent.id)
        )
        await self.db.flush()

        for skill_name in skill_refs or []:
            # 1. 查 active skill
            skill = await skill_repo.get_by_name(skill_name)
            if not skill:
                # 2. 查是否被软删除（同名 skill 由于 unique 约束可能只是软删了）
                res = await self.db.execute(
                    select(Skill).where(Skill.name == skill_name)
                )
                skill = res.scalar_one_or_none()
                if skill:
                    # 软删除的 skill：恢复它
                    skill.deleted_at = None
                else:
                    # 3. 完全不存在：建一个 minimal skill
                    skill = Skill(
                        name=skill_name,
                        description="auto-created by coordinator bootstrap",
                        skill_type="prompt",
                        content="",
                        config={},
                        files={},
                    )
                    self.db.add(skill)
                await self.db.flush()
            # 4. 建 AgentSkill 关联
            self.db.add(AgentSkill(agent_id=agent.id, skill_id=skill.id))
        await self.db.flush()

