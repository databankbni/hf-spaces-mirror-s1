"""
资源Repository模块

提供资源(Resource)和标签(Tag)的数据访问操作。
"""

from typing import Optional, List
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import Resource
from app.models.tag import Tag
from .base import BaseRepository


class ResourceRepository(BaseRepository[Resource]):
    """
    资源Repository

    提供资源的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Resource, db)

    async def get_by_project(self, project_id: str, resource_type: Optional[str] = None, is_required: Optional[bool] = None) -> List[Resource]:
        """
        获取项目的全局资源列表

        Args:
            project_id: 项目ID
            resource_type: 资源类型筛选
            is_required: 是否必读筛选

        Returns:
            List[Resource]: 资源列表
        """
        query = (
            select(Resource)
            .where(and_(
                Resource.project_id == project_id,
                Resource.group_id.is_(None),  # 全局资源
                Resource.deleted_at.is_(None)
            ))
        )

        if resource_type:
            query = query.where(Resource.type == resource_type)
        if is_required is not None:
            query = query.where(Resource.is_required == is_required)

        query = query.order_by(Resource.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_group(self, group_id: str) -> List[Resource]:
        """
        获取群聊的资源列表

        Args:
            group_id: 群聊ID

        Returns:
            List[Resource]: 资源列表
        """
        query = (
            select(Resource)
            .where(and_(
                Resource.group_id == group_id,
                Resource.deleted_at.is_(None)
            ))
            .order_by(Resource.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_required_by_project(self, project_id: str) -> List[Resource]:
        """
        获取项目的必读资源

        Args:
            project_id: 项目ID

        Returns:
            List[Resource]: 必读资源列表
        """
        query = (
            select(Resource)
            .where(and_(
                Resource.project_id == project_id,
                Resource.is_required == True,
                Resource.deleted_at.is_(None)
            ))
            .order_by(Resource.created_at)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())


class TagRepository(BaseRepository[Tag]):
    """
    标签Repository

    提供标签的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Tag, db)

    async def get_by_project(self, project_id: str) -> List[Tag]:
        """
        获取项目的标签列表

        Args:
            project_id: 项目ID

        Returns:
            List[Tag]: 标签列表
        """
        query = (
            select(Tag)
            .where(Tag.project_id == project_id)
            .order_by(Tag.name)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_name(self, project_id: str, name: str) -> Optional[Tag]:
        """
        根据名称获取标签

        Args:
            project_id: 项目ID
            name: 标签名称

        Returns:
            Optional[Tag]: 标签记录
        """
        query = select(Tag).where(and_(
            Tag.project_id == project_id,
            Tag.name == name
        ))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
