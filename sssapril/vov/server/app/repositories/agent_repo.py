"""
Agent Repository模块

提供Agent相关的数据访问操作。
"""

from typing import Optional, List
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent, AgentTool, AgentSkill, Skill, ProjectAgent
from app.models.memory import Memory
from .base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    """
    全局Agent Repository

    提供Agent的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Agent, db)

    async def get_with_tools_and_skills(self, id: str) -> Optional[Agent]:
        """
        获取Agent详情（包含工具和技能）

        Args:
            id: Agent ID

        Returns:
            Optional[Agent]: Agent详情
        """
        query = (
            select(Agent)
            .where(and_(Agent.id == id, Agent.deleted_at.is_(None)))
            .options(
                selectinload(Agent.tools),
                selectinload(Agent.skills),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_all_active(self) -> List[Agent]:
        """
        获取所有启用的Agent

        Returns:
            List[Agent]: Agent列表
        """
        query = (
            select(Agent)
            .where(and_(
                Agent.is_active == True,
                Agent.deleted_at.is_(None)
            ))
            .options(
                selectinload(Agent.tools),
                selectinload(Agent.skills),
            )
            .order_by(Agent.name)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())


class ProjectAgentRepository(BaseRepository[ProjectAgent]):
    """
    项目Agent Repository

    提供项目Agent的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(ProjectAgent, db)

    async def get_by_project(self, project_id: str) -> List[ProjectAgent]:
        """
        获取项目的Agent列表

        Args:
            project_id: 项目ID

        Returns:
            List[ProjectAgent]: 项目Agent列表
        """
        query = (
            select(ProjectAgent)
            .where(ProjectAgent.project_id == project_id)
            .options(
                selectinload(ProjectAgent.agent),
                selectinload(ProjectAgent.agent).selectinload(Agent.tools),
                selectinload(ProjectAgent.agent).selectinload(Agent.skills),
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_project_and_agent(self, project_id: str, agent_id: str) -> Optional[ProjectAgent]:
        """
        根据项目和Agent获取记录

        Args:
            project_id: 项目ID
            agent_id: Agent ID

        Returns:
            Optional[ProjectAgent]: 项目Agent记录
        """
        query = (
            select(ProjectAgent)
            .where(and_(
                ProjectAgent.project_id == project_id,
                ProjectAgent.agent_id == agent_id
            ))
            .options(
                selectinload(ProjectAgent.agent),
                selectinload(ProjectAgent.agent).selectinload(Agent.tools),
                selectinload(ProjectAgent.agent).selectinload(Agent.skills),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class AgentToolRepository(BaseRepository[AgentTool]):
    """Agent工具Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(AgentTool, db)

    async def get_by_agent(self, agent_id: str) -> List[AgentTool]:
        """获取Agent的工具列表"""
        query = select(AgentTool).where(AgentTool.agent_id == agent_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def delete_by_agent(self, agent_id: str) -> None:
        """删除Agent的所有工具"""
        tools = await self.get_by_agent(agent_id)
        for tool in tools:
            await self.db.delete(tool)
        await self.db.flush()


class SkillRepository(BaseRepository[Skill]):
    """独立技能Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(Skill, db)

    async def get_all_active(self) -> List[Skill]:
        """获取所有技能"""
        query = (
            select(Skill)
            .where(Skill.deleted_at.is_(None))
            .order_by(Skill.name)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> Optional[Skill]:
        """根据名称获取技能"""
        query = select(Skill).where(and_(Skill.name == name, Skill.deleted_at.is_(None)))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class AgentSkillRepository:
    """Agent-技能关联Repository（junction 表操作）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_skills_by_agent(self, agent_id: str) -> List[Skill]:
        """获取Agent绑定的所有技能"""
        query = (
            select(Skill)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .where(and_(AgentSkill.agent_id == agent_id, Skill.deleted_at.is_(None)))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def link(self, agent_id: str, skill_id: str) -> AgentSkill:
        """绑定技能到Agent"""
        link = AgentSkill(agent_id=agent_id, skill_id=skill_id)
        self.db.add(link)
        await self.db.flush()
        return link

    async def unlink(self, agent_id: str, skill_id: str) -> bool:
        """解绑Agent的某个技能"""
        query = select(AgentSkill).where(and_(
            AgentSkill.agent_id == agent_id,
            AgentSkill.skill_id == skill_id,
        ))
        result = await self.db.execute(query)
        link = result.scalar_one_or_none()
        if link:
            await self.db.delete(link)
            await self.db.flush()
            return True
        return False

    async def unlink_all(self, agent_id: str) -> None:
        """解绑Agent的所有技能"""
        query = select(AgentSkill).where(AgentSkill.agent_id == agent_id)
        result = await self.db.execute(query)
        for link in result.scalars().all():
            await self.db.delete(link)
        await self.db.flush()

    async def set_skills(self, agent_id: str, skill_ids: List[str]) -> None:
        """设置Agent的技能列表（替换模式）"""
        await self.unlink_all(agent_id)
        for skill_id in skill_ids:
            await self.link(agent_id, skill_id)


class MemoryRepository(BaseRepository[Memory]):
    """
    Agent记忆Repository

    提供Agent个人笔记的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Memory, db)

    async def get_by_agent_and_project(
        self,
        agent_id: str,
        project_id: str,
        slug: Optional[str] = None,
    ) -> Optional[Memory]:
        """
        获取Agent在项目中的笔记

        Args:
            agent_id: Agent ID
            project_id: 项目ID
            slug: 分类标识（None 时返回 slug='default' 的笔记，保持向后兼容）

        Returns:
            Optional[Memory]: 笔记记录
        """
        effective_slug = slug or "default"
        query = select(Memory).where(and_(
            Memory.agent_id == agent_id,
            Memory.project_id == project_id,
            Memory.slug == effective_slug,
            Memory.deleted_at.is_(None)
        ))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_by_agent_and_project(
        self,
        agent_id: str,
        project_id: str,
    ) -> List[Memory]:
        """
        列出 Agent 在项目下的所有笔记（按 slug）

        Returns:
            List[Memory]: 笔记列表，按 updated_at 倒序
        """
        query = (
            select(Memory)
            .where(and_(
                Memory.agent_id == agent_id,
                Memory.project_id == project_id,
                Memory.deleted_at.is_(None)
            ))
            .order_by(Memory.updated_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_project(self, project_id: str) -> List[Memory]:
        """
        获取项目的所有Agent笔记

        Args:
            project_id: 项目ID

        Returns:
            List[Memory]: 笔记列表
        """
        query = (
            select(Memory)
            .where(and_(
                Memory.project_id == project_id,
                Memory.deleted_at.is_(None)
            ))
            .options(selectinload(Memory.agent))
            .order_by(Memory.updated_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
