"""
标签Service模块

提供标签(Tag)的业务逻辑。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag
from app.repositories.resource_repo import TagRepository
from .base import BaseService


class TagService(BaseService[Tag, TagRepository]):
    """
    标签Service

    提供标签的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = TagRepository(db)
        super().__init__(repo, db)

    async def get_by_project(self, project_id: str) -> List[Tag]:
        """
        获取项目的标签列表

        Args:
            project_id: 项目ID

        Returns:
            List[Tag]: 标签列表
        """
        return await self.repo.get_by_project(project_id)

    async def create_tag(self, project_id: str, data: Dict[str, Any]) -> Tag:
        """
        创建标签

        Args:
            project_id: 项目ID
            data: 标签数据

        Returns:
            Tag: 创建的标签

        Raises:
            ValueError: 标签名已存在时抛出
        """
        # 检查名称唯一性
        existing = await self.repo.get_by_name(project_id, data["name"])
        if existing:
            raise ValueError(f"Tag '{data['name']}' already exists in this project")

        data["project_id"] = project_id
        return await self.repo.create(data)

    async def update_tag(self, id: str, data: Dict[str, Any]) -> Optional[Tag]:
        """
        更新标签

        Args:
            id: 标签ID
            data: 更新数据

        Returns:
            Optional[Tag]: 更新后的标签
        """
        return await self.repo.update(id, data)

    async def delete_tag(self, id: str) -> bool:
        """
        删除标签

        Args:
            id: 标签ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)
