"""
Agent Service模块

提供Agent相关的业务逻辑。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, ProjectAgent, AgentTool, AgentSkill, Skill
from app.models.memory import Memory
from app.repositories.agent_repo import (
    AgentRepository,
    ProjectAgentRepository,
    AgentToolRepository,
    AgentSkillRepository,
    SkillRepository,
    MemoryRepository,
)
from .base import BaseService


class AgentService(BaseService[Agent, AgentRepository]):
    """
    全局Agent Service

    提供Agent的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = AgentRepository(db)
        super().__init__(repo, db)
        self.tool_repo = AgentToolRepository(db)
        self.skill_link_repo = AgentSkillRepository(db)

    async def get_detail(self, id: str) -> Optional[Agent]:
        """
        获取Agent详情（包含工具和技能）

        Args:
            id: Agent ID

        Returns:
            Optional[Agent]: Agent详情
        """
        return await self.repo.get_with_tools_and_skills(id)

    async def get_all_active(self) -> List[Agent]:
        """
        获取所有启用的Agent

        Returns:
            List[Agent]: Agent列表
        """
        return await self.repo.get_all_active()

    async def create_agent(self, data: Dict[str, Any]) -> Agent:
        """
        创建Agent

        Args:
            data: Agent数据，可包含tools列表和skill_ids列表

        Returns:
            Agent: 创建的Agent
        """
        # 提取工具和技能 ID
        tools_data = data.pop("tools", [])
        skill_ids = data.pop("skill_ids", [])

        # 设置默认值
        if "is_active" not in data:
            data["is_active"] = True
        if "llm_config" not in data:
            data["llm_config"] = {}
        if "capabilities" not in data:
            data["capabilities"] = []

        # 创建Agent
        agent = await self.repo.create(data)

        # 创建工具
        for tool_data in tools_data:
            tool_data["agent_id"] = agent.id
            await self.tool_repo.create(tool_data)

        # 绑定技能
        if skill_ids:
            await self.skill_link_repo.set_skills(agent.id, skill_ids)

        return agent

    async def update_agent(self, id: str, data: Dict[str, Any]) -> Optional[Agent]:
        """
        更新Agent

        Args:
            id: Agent ID
            data: 更新数据

        Returns:
            Optional[Agent]: 更新后的Agent
        """
        # 提取工具和技能 ID
        tools_data = data.pop("tools", None)
        skill_ids = data.pop("skill_ids", None)

        # 更新Agent基本信息
        agent = await self.repo.update(id, data)
        if not agent:
            return None

        # 更新工具
        if tools_data is not None:
            await self.tool_repo.delete_by_agent(id)
            for tool_data in tools_data:
                tool_data["agent_id"] = id
                await self.tool_repo.create(tool_data)

        # 更新技能绑定
        if skill_ids is not None:
            await self.skill_link_repo.set_skills(id, skill_ids)

        return agent

    async def delete_agent(self, id: str) -> bool:
        """
        删除Agent

        Args:
            id: Agent ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)


class ProjectAgentService(BaseService[ProjectAgent, ProjectAgentRepository]):
    """
    项目Agent Service

    提供项目Agent的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = ProjectAgentRepository(db)
        super().__init__(repo, db)

    async def get_by_project(self, project_id: str) -> List[ProjectAgent]:
        """
        获取项目的Agent列表

        Args:
            project_id: 项目ID

        Returns:
            List[ProjectAgent]: 项目Agent列表
        """
        return await self.repo.get_by_project(project_id)

    async def add_to_project(self, project_id: str, agent_id: str, override_config: Dict = None) -> ProjectAgent:
        """
        添加Agent到项目

        Args:
            project_id: 项目ID
            agent_id: Agent ID
            override_config: 覆盖配置

        Returns:
            ProjectAgent: 项目Agent记录
        """
        project_agent = await self.repo.create({
            "project_id": project_id,
            "agent_id": agent_id,
            "override_config": override_config or {},
        })
        # Reload with agent relationship
        return await self.repo.get_by_project_and_agent(project_id, agent_id)

    async def remove_from_project(self, project_id: str, agent_id: str) -> bool:
        """
        从项目移除Agent

        Args:
            project_id: 项目ID
            agent_id: Agent ID

        Returns:
            bool: 是否移除成功
        """
        project_agent = await self.repo.get_by_project_and_agent(project_id, agent_id)
        if not project_agent:
            return False
        return await self.repo.hard_delete(project_agent.id)


class SkillService(BaseService[Skill, SkillRepository]):
    """
    独立技能 Service

    提供技能的独立 CRUD 操作。
    """

    def __init__(self, db: AsyncSession):
        repo = SkillRepository(db)
        super().__init__(repo, db)

    async def get_all_active(self) -> List[Skill]:
        """获取所有技能"""
        return await self.repo.get_all_active()

    async def get_by_name(self, name: str) -> Optional[Skill]:
        """根据名称获取技能"""
        return await self.repo.get_by_name(name)


class MemoryService(BaseService[Memory, MemoryRepository]):
    """
    Agent记忆Service

    提供Agent个人笔记的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = MemoryRepository(db)
        super().__init__(repo, db)

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
            slug: 分类标识（None 时返回 slug='default' 的笔记）

        Returns:
            Optional[Memory]: 笔记记录
        """
        return await self.repo.get_by_agent_and_project(agent_id, project_id, slug)

    async def list_by_agent_and_project(
        self,
        agent_id: str,
        project_id: str,
    ) -> List[Memory]:
        """列出 Agent 在项目下的所有笔记（按 slug 分类）"""
        return await self.repo.list_by_agent_and_project(agent_id, project_id)

    async def get_by_project(self, project_id: str) -> List[Memory]:
        """
        获取项目的所有Agent笔记

        Args:
            project_id: 项目ID

        Returns:
            List[Memory]: 笔记列表
        """
        return await self.repo.get_by_project(project_id)

    async def upsert(
        self,
        agent_id: str,
        project_id: str,
        content: str,
        tags: List[str] = None,
        slug: str = "default",
        mode: str = "replace",
        find: str = None,
        replace_with: str = None,
        section_heading: str = None,
    ) -> Memory:
        """
        创建或更新笔记（按 slug 分类）

        如果 (agent_id, project_id, slug) 的笔记不存在则创建，存在则按 mode 更新。

        Args:
            agent_id: Agent ID
            project_id: 项目ID
            content: 笔记内容
            tags: 标签列表
            slug: 分类标识
            mode: 更新模式
                - "replace": 全量替换 content（默认，兼容旧用法）
                - "append": 追加到已有内容末尾（用 \\n\\n 分隔）
                - "replace_globally": 全文查找替换，需配合 find + replace_with
                - "rewrite_section": 按 Markdown 标题锚点替换整个 section，需配合 section_heading
            find: mode="replace_globally" 时要查找的字符串
            replace_with: mode="replace_globally" 时替换为的字符串
            section_heading: mode="rewrite_section" 时要替换的 ## 标题（不含 ## 前缀）

        Returns:
            Memory: 笔记记录
        """
        existing = await self.repo.get_by_agent_and_project(agent_id, project_id, slug)

        if existing:
            new_content = self._apply_mode(existing.content or "", content, mode, find, replace_with, section_heading)
            update_data = {"content": new_content}
            if tags is not None:
                update_data["tags"] = tags
            return await self.repo.update(existing.id, update_data)
        else:
            return await self.repo.create({
                "agent_id": agent_id,
                "project_id": project_id,
                "slug": slug,
                "content": content,
                "tags": tags or [],
            })

    @staticmethod
    def _apply_mode(
        old_content: str,
        new_content: str,
        mode: str,
        find: str = None,
        replace_with: str = None,
        section_heading: str = None,
    ) -> str:
        """根据 mode 对已有内容应用不同的更新策略"""
        if mode == "append":
            if old_content:
                return old_content + "\n\n" + new_content
            return new_content

        if mode == "replace_globally":
            if not find:
                raise ValueError("mode='replace_globally' requires 'find' parameter")
            replace_with = replace_with or ""
            count = old_content.count(find)
            if count == 0:
                raise ValueError(f"find string not found in existing content")
            return old_content.replace(find, replace_with)

        if mode == "rewrite_section":
            if not section_heading:
                raise ValueError("mode='rewrite_section' requires 'section_heading' parameter")
            import re
            heading_escaped = re.escape(section_heading)
            # 匹配 ## heading 到下一个 ## 或文档末尾
            pattern = rf"(##\s+{heading_escaped}\s*\n)(.*?)(?=\n##\s|\Z)"
            match = re.search(pattern, old_content, re.DOTALL)
            if not match:
                # 如果找不到该 section，追加到末尾
                return old_content + f"\n\n## {section_heading}\n{new_content}"
            # 替换 section 内容，保留标题
            replacement = match.group(1) + new_content
            return old_content[:match.start()] + replacement + old_content[match.end():]

        # mode == "replace" (默认)
        return new_content
