"""
项目Repository模块

提供项目(Project)的数据访问操作。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project
from app.models.group import Group
from app.models.agent import ProjectAgent
from app.models.task import Task
from .base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """
    项目Repository

    提供项目相关的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Project, db)

    async def get_with_details(self, id: str) -> Optional[Project]:
        """
        获取项目详情（包含关联数据）

        Args:
            id: 项目ID

        Returns:
            Optional[Project]: 项目详情，包含groups、agents、resources
        """
        query = (
            select(Project)
            .where(and_(Project.id == id, Project.deleted_at.is_(None)))
            .options(
                selectinload(Project.groups),
                selectinload(Project.project_agents),
                selectinload(Project.resources),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_list_with_stats(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        获取项目列表（包含统计信息）

        Args:
            filters: 筛选条件

        Returns:
            List[Dict]: 项目列表，包含统计信息
        """
        # Subquery for group count
        group_count_sq = (
            select(func.count(Group.id))
            .where(and_(Group.project_id == Project.id, Group.deleted_at.is_(None)))
            .correlate(Project)
            .scalar_subquery()
        )
        # Subquery for agent count
        agent_count_sq = (
            select(func.count(ProjectAgent.id))
            .where(and_(ProjectAgent.project_id == Project.id, ProjectAgent.deleted_at.is_(None)))
            .correlate(Project)
            .scalar_subquery()
        )

        query = (
            select(
                Project,
                group_count_sq.label("group_count"),
                agent_count_sq.label("agent_count"),
            )
            .where(Project.deleted_at.is_(None))
            .order_by(Project.updated_at.desc())
        )

        if filters:
            if "status" in filters and filters["status"]:
                query = query.where(Project.status == filters["status"])

        result = await self.db.execute(query)
        rows = result.all()

        projects = []
        for row in rows:
            project = row[0]
            projects.append({
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "cover_color": project.cover_color,
                "tags": project.tags,
                "status": project.status,
                "group_count": row[1],
                "agent_count": row[2],
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "updated_at": project.updated_at.isoformat() if project.updated_at else None,
                "is_guide": project.is_guide,
            })

        return projects
