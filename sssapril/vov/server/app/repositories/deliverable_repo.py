"""
交付物Repository模块

提供交付物(Deliverable)和交付物版本(DeliverableVersion)的数据访问操作。
"""

from typing import Optional, List
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.deliverable import Deliverable, DeliverableVersion
from .base import BaseRepository


class DeliverableRepository(BaseRepository[Deliverable]):
    """
    交付物Repository

    提供交付物的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Deliverable, db)

    async def get_by_group(self, group_id: str) -> List[Deliverable]:
        """
        获取群聊的交付物列表

        Args:
            group_id: 群聊ID

        Returns:
            List[Deliverable]: 交付物列表
        """
        query = (
            select(Deliverable)
            .where(and_(
                Deliverable.group_id == group_id,
                Deliverable.deleted_at.is_(None)
            ))
            .options(selectinload(Deliverable.versions))
            .order_by(Deliverable.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_project(self, project_id: str) -> List[Deliverable]:
        """
        获取项目的交付物列表（scope=project）

        Args:
            project_id: 项目ID

        Returns:
            List[Deliverable]: 交付物列表
        """
        from app.models.group import Group
        query = (
            select(Deliverable)
            .join(Group, Group.id == Deliverable.group_id)
            .where(and_(
                Group.project_id == project_id,
                Deliverable.scope == "project",
                Deliverable.deleted_at.is_(None)
            ))
            .options(selectinload(Deliverable.versions))
            .order_by(Deliverable.created_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_versions(self, id: str) -> Optional[Deliverable]:
        """
        获取交付物详情（包含版本历史）

        Args:
            id: 交付物ID

        Returns:
            Optional[Deliverable]: 交付物详情
        """
        query = (
            select(Deliverable)
            .where(and_(Deliverable.id == id, Deliverable.deleted_at.is_(None)))
            .options(selectinload(Deliverable.versions))
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class DeliverableVersionRepository(BaseRepository[DeliverableVersion]):
    """
    交付物版本Repository

    提供交付物版本的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(DeliverableVersion, db)

    async def get_by_deliverable(self, deliverable_id: str) -> List[DeliverableVersion]:
        """
        获取交付物的版本列表

        Args:
            deliverable_id: 交付物ID

        Returns:
            List[DeliverableVersion]: 版本列表，按版本号倒序
        """
        query = (
            select(DeliverableVersion)
            .where(DeliverableVersion.deliverable_id == deliverable_id)
            .order_by(DeliverableVersion.version.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_version(self, deliverable_id: str, version: int) -> Optional[DeliverableVersion]:
        """
        获取特定版本

        Args:
            deliverable_id: 交付物ID
            version: 版本号

        Returns:
            Optional[DeliverableVersion]: 版本记录
        """
        query = select(DeliverableVersion).where(and_(
            DeliverableVersion.deliverable_id == deliverable_id,
            DeliverableVersion.version == version
        ))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_max_version(self, deliverable_id: str) -> int:
        """
        获取最大版本号

        Args:
            deliverable_id: 交付物ID

        Returns:
            int: 最大版本号
        """
        from sqlalchemy import func
        query = (
            select(func.max(DeliverableVersion.version))
            .where(DeliverableVersion.deliverable_id == deliverable_id)
        )
        result = await self.db.execute(query)
        return result.scalar() or 0
