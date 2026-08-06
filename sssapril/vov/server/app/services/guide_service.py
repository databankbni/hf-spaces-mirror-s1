"""
引导Service模块

提供引导 project 的自动创建和管理逻辑。

设计意图:
- 每用户一个引导 project (is_guide=True), 作为引导 agent 的工作容器
- 引导 project 不在「我的项目」列表展示
- 引导 agent 通过系统级工具跨 project 操作真实项目
- 首次使用时 (或前端检测无引导 project) 通过 ensure_guide_state 自动创建

不继承 BaseService: 引导 project 涉及多表 (Project + Agent + Group) 联动创建,
用独立 service 更清晰, 不强制套单一 repo 模式。
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.agent import Agent, ProjectAgent
from app.models.group import Group, GroupMember
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)

# L0 引导 agent 模板路径
GUIDE_L0_TEMPLATE_PATH = (
    Path(__file__).parent.parent / "default_presets" / "agent_templates" / "guide_l0.json"
)

# 引导 project / group 固定名称 (用于幂等识别)
GUIDE_PROJECT_NAME = "引导·需求收集"
GUIDE_GROUP_NAME = "引导对话"

# L1: 项目内引导相关常量
# coordinator agent 名称（与 coordinator.json 中 agent.name 一致）
COORDINATOR_AGENT_NAME = "项目总控·编舟"
# 项目引导群名称（coordinator 与用户对话的群聊）
PROJECT_GUIDE_GROUP_NAME = "项目引导"


class GuideService:
    """
    引导Service

    提供引导 project 的自动创建和管理。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.project_service = ProjectService(db)

    # ── 对外接口 ──

    async def ensure_guide_state(self) -> Dict[str, Any]:
        """
        幂等创建引导 project + agent + group, 返回状态 dict。

        首次调用: 创建全部
        后续调用: 复用现有, 补建缺失的 agent/group (容错)
        """
        project, agent, pa, group = await self._ensure_guide_project()
        return {
            "project_id": project.id,
            "agent_id": agent.id,
            "project_agent_id": pa.id,
            "group_id": group.id,
            "agent_name": agent.name,
            "agent_avatar": agent.avatar,
            "group_name": group.name,
        }

    async def get_guide_state(self) -> Optional[Dict[str, Any]]:
        """
        查询引导状态 (只查不建)。

        返回 None 表示未初始化。
        """
        guide_project = await self._get_guide_project()
        if not guide_project:
            return None

        # 查 agent 和 group (不补建, 只读)
        res_pa = await self.db.execute(
            select(ProjectAgent)
            .where(ProjectAgent.project_id == guide_project.id)
            .limit(1)
        )
        pa = res_pa.scalar_one_or_none()
        if not pa:
            return None

        res_group = await self.db.execute(
            select(Group)
            .where(Group.project_id == guide_project.id)
            .limit(1)
        )
        group = res_group.scalar_one_or_none()
        if not group:
            return None

        return {
            "project_id": guide_project.id,
            "agent_id": pa.agent_id,
            "project_agent_id": pa.id,
            "group_id": group.id,
            "agent_name": pa.agent.name if pa.agent else "",
            "agent_avatar": pa.agent.avatar if pa.agent else None,
            "group_name": group.name,
        }

    # ── 内部实现 ──

    async def _ensure_guide_project(self) -> Tuple[Project, Agent, ProjectAgent, Group]:
        """幂等创建引导 project + agent + group, 返回四元组"""
        # 1. 查现有引导 project
        guide_project = await self._get_guide_project()

        if guide_project:
            # 幂等: 引导 project 已存在, 补建缺失的 agent/group
            guide_agent, guide_pa = await self._ensure_guide_agent(guide_project)
            guide_group = await self._ensure_guide_group(guide_project, guide_pa)
            logger.info(
                "[ensure_guide_project] reuse existing: project=%s agent=%s group=%s",
                guide_project.id, guide_agent.id, guide_group.id,
            )
            return guide_project, guide_agent, guide_pa, guide_group

        # 2. 首次创建: 建 project
        guide_project = await self._create_guide_project()

        # 3. 建 agent + ProjectAgent 关联
        guide_agent, guide_pa = await self._ensure_guide_agent(guide_project)

        # 4. 建 group + 加 lead member
        guide_group = await self._ensure_guide_group(guide_project, guide_pa)

        logger.info(
            "[ensure_guide_project] created: project=%s agent=%s group=%s",
            guide_project.id, guide_agent.id, guide_group.id,
        )
        return guide_project, guide_agent, guide_pa, guide_group

    async def _get_guide_project(self) -> Optional[Project]:
        """查 is_guide=True 的 project (期望至多一个)"""
        res = await self.db.execute(
            select(Project).where(Project.is_guide == True).limit(1)  # noqa: E712
        )
        return res.scalar_one_or_none()

    async def _create_guide_project(self) -> Project:
        """创建引导 project"""
        project = Project(
            name=GUIDE_PROJECT_NAME,
            description="引导 agent 工作容器。用户首页召唤的引导 agent 住在这里, 通过系统级工具帮用户建项目。",
            status="active",
            workflow_config={},
            is_guide=True,
        )
        self.db.add(project)
        await self.db.flush()
        return project

    async def _ensure_guide_agent(self, project: Project) -> Tuple[Agent, ProjectAgent]:
        """
        幂等创建引导 agent + ProjectAgent 关联。

        复用 project_service._upsert_coordinator_agent 的通用 agent upsert 逻辑:
        - 按 name 复用/创建 Agent
        - 重建 tools 和 skill 绑定 (保证和模板一致)
        - 建 ProjectAgent 关联 (幂等: 同 project + 同 agent 不重复建)

        注: _upsert_coordinator_agent 方法名带 coordinator 是历史命名,
            实际是通用的 "从 template upsert agent" 逻辑, 引导 agent 同样适用。
        """
        template = self._load_guide_l0_template()
        if not template:
            raise RuntimeError(
                f"[ensure_guide_agent] guide_l0.json template not found at {GUIDE_L0_TEMPLATE_PATH}"
            )

        agent_data = template.get("agent", {})
        agent_name = agent_data.get("name")
        if not agent_name:
            raise RuntimeError("[ensure_guide_agent] template missing 'agent.name'")

        # 1. upsert Agent (复用 project_service 的通用 upsert 逻辑)
        agent = await self.project_service._upsert_coordinator_agent(agent_data)

        # 2. 检查 ProjectAgent 是否已存在 (幂等)
        existing_pa = (await self.db.execute(
            select(ProjectAgent).where(
                ProjectAgent.project_id == project.id,
                ProjectAgent.agent_id == agent.id,
            )
        )).scalar_one_or_none()
        if existing_pa:
            return agent, existing_pa

        # 3. 建 ProjectAgent
        pa = ProjectAgent(
            project_id=project.id,
            agent_id=agent.id,
            override_config={},
        )
        self.db.add(pa)
        await self.db.flush()
        return agent, pa

    async def _ensure_guide_group(
        self, project: Project, guide_pa: ProjectAgent
    ) -> Group:
        """
        幂等创建引导 group + 加 lead member。

        - 按 project_id + name=GUIDE_GROUP_NAME 查现有
        - 有: 补 lead_agent_id 和 member (容错老数据)
        - 无: 创建 + 加 lead member
        """
        # 1. 查现有
        res = await self.db.execute(
            select(Group).where(
                Group.project_id == project.id,
                Group.name == GUIDE_GROUP_NAME,
            ).limit(1)
        )
        existing_group = res.scalar_one_or_none()

        if existing_group:
            # 补 lead_agent_id (老数据可能没设)
            if not existing_group.lead_agent_id:
                existing_group.lead_agent_id = guide_pa.id
                await self.db.flush()
            # 补 member
            await self._ensure_group_member(existing_group.id, guide_pa.id, "lead")
            return existing_group

        # 2. 创建 group
        group = Group(
            project_id=project.id,
            lead_agent_id=guide_pa.id,
            name=GUIDE_GROUP_NAME,
            description="引导 agent 与用户的对话群聊。用户在首页召唤的对话框背后就是这个群。",
            status="active",
            order_index=0,
            autonomy_level="manual",
            auto_advance=False,
            workflow_config={},
        )
        self.db.add(group)
        await self.db.flush()

        # 3. 加 lead member
        await self._ensure_group_member(group.id, guide_pa.id, "lead")

        return group

    async def _ensure_group_member(
        self, group_id: str, project_agent_id: str, role: str = "participant"
    ) -> GroupMember:
        """幂等添加群成员"""
        existing = (await self.db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.project_agent_id == project_agent_id,
            )
        )).scalar_one_or_none()
        if existing:
            return existing

        member = GroupMember(
            group_id=group_id,
            project_agent_id=project_agent_id,
            role=role,
        )
        self.db.add(member)
        await self.db.flush()
        return member

    def _load_guide_l0_template(self) -> Optional[Dict[str, Any]]:
        """加载 L0 引导 agent 模板"""
        if not GUIDE_L0_TEMPLATE_PATH.exists():
            return None
        try:
            with open(GUIDE_L0_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(
                "[load_guide_l0_template] failed to load %s: %s",
                GUIDE_L0_TEMPLATE_PATH, e,
            )
            return None

    # ── L1: 项目内引导（coordinator + 项目引导群） ──

    async def ensure_project_guide_state(self, project_id: str) -> Dict[str, Any]:
        """
        L1: 幂等确保项目有 coordinator + 项目引导群, 返回状态 dict。

        逻辑:
        1. 查项目 (project_id), 不存在则抛错
        2. 查项目的 coordinator ProjectAgent (按 agent.name = COORDINATOR_AGENT_NAME)
           - 没有则调 project_service._ensure_project_coordinator 补建
        3. 查 coordinator 所在的群聊 (GroupMember.project_agent_id = coordinator_pa.id)
           - 有: 返回第一个 (模板项目通常已有群聊)
           - 没有: 建「项目引导群」+ 加 coordinator 为 lead (空白项目场景)
        4. 返回 {project_id, agent_id, project_agent_id, group_id, agent_name, agent_avatar, group_name}

        与 L0 的区别:
        - L0: 在引导 project (is_guide=True) 里工作, 跨 project 操作
        - L1: 在真实项目里工作, coordinator 是项目内 agent, 群聊是项目内群聊
        """
        # 1. 查项目
        project = await self.db.get(Project, project_id)
        if not project:
            raise ValueError(f"[ensure_project_guide_state] project not found: {project_id}")

        # 2. 确保 coordinator ProjectAgent 存在
        coordinator_pa = await self._ensure_project_coordinator_pa(project)

        # 3. 确保 coordinator 在一个群聊里
        group = await self._ensure_project_guide_group(project, coordinator_pa)

        # 取 agent 信息用于返回
        agent = coordinator_pa.agent
        return {
            "project_id": project.id,
            "agent_id": agent.id,
            "project_agent_id": coordinator_pa.id,
            "group_id": group.id,
            "agent_name": agent.name,
            "agent_avatar": agent.avatar,
            "group_name": group.name,
        }

    async def _ensure_project_coordinator_pa(self, project: Project) -> ProjectAgent:
        """
        确保项目有 coordinator ProjectAgent。

        - 查现有: ProjectAgent.project_id = project.id AND Agent.name = COORDINATOR_AGENT_NAME
        - 没有则调 project_service._ensure_project_coordinator 补建
        """
        # 查现有 coordinator ProjectAgent
        res = await self.db.execute(
            select(ProjectAgent)
            .join(Agent, ProjectAgent.agent_id == Agent.id)
            .where(
                ProjectAgent.project_id == project.id,
                Agent.name == COORDINATOR_AGENT_NAME,
            )
            .limit(1)
        )
        pa = res.scalar_one_or_none()
        if pa:
            return pa

        # 补建 (复用 project_service 的逻辑, 会加载 coordinator.json 模板)
        pa = await self.project_service._ensure_project_coordinator(project)
        if not pa:
            raise RuntimeError(
                f"[ensure_project_coordinator_pa] failed to ensure coordinator for project={project.id}"
            )
        return pa

    async def _ensure_project_guide_group(
        self, project: Project, coordinator_pa: ProjectAgent
    ) -> Group:
        """
        确保 coordinator 在一个群聊里。

        - 查 coordinator 已在的群聊 (GroupMember.project_agent_id = coordinator_pa.id)
        - 有: 返回第一个 (模板项目通常已有)
        - 没有: 建「项目引导群」+ 加 coordinator 为 lead (空白项目场景)
        """
        # 1. 查 coordinator 已在的群聊
        res = await self.db.execute(
            select(Group)
            .join(GroupMember, Group.id == GroupMember.group_id)
            .where(GroupMember.project_agent_id == coordinator_pa.id)
            .where(Group.project_id == project.id)
            .limit(1)
        )
        existing_group = res.scalar_one_or_none()
        if existing_group:
            return existing_group

        # 2. 没有群聊, 建「项目引导群」
        group = Group(
            project_id=project.id,
            lead_agent_id=coordinator_pa.id,
            name=PROJECT_GUIDE_GROUP_NAME,
            description="项目引导群。coordinator 与用户在这里对话, 帮用户建群聊、分方向、规划 pipeline。",
            status="active",
            order_index=0,
            autonomy_level="manual",
            auto_advance=False,
            workflow_config={},
        )
        self.db.add(group)
        await self.db.flush()

        # 3. 加 coordinator 为 lead member
        await self._ensure_group_member(group.id, coordinator_pa.id, "lead")

        logger.info(
            "[ensure_project_guide_group] created group=%s for project=%s, coordinator_pa=%s",
            group.id, project.id, coordinator_pa.id,
        )
        return group
