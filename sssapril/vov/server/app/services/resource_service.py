"""
资源Service模块

提供资源(Resource)的业务逻辑。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import Resource
from app.repositories.resource_repo import ResourceRepository
from .base import BaseService


class ResourceService(BaseService[Resource, ResourceRepository]):
    """
    资源Service

    提供资源的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = ResourceRepository(db)
        super().__init__(repo, db)

    async def get_by_project(
        self,
        project_id: str,
        resource_type: Optional[str] = None,
        is_required: Optional[bool] = None
    ) -> List[Resource]:
        """
        获取项目的全局资源列表

        Args:
            project_id: 项目ID
            resource_type: 资源类型筛选
            is_required: 是否必读筛选

        Returns:
            List[Resource]: 资源列表
        """
        return await self.repo.get_by_project(project_id, resource_type, is_required)

    async def get_by_group(self, group_id: str) -> List[Resource]:
        """
        获取群聊的资源列表

        Args:
            group_id: 群聊ID

        Returns:
            List[Resource]: 资源列表
        """
        return await self.repo.get_by_group(group_id)

    async def get_required_by_project(self, project_id: str) -> List[Resource]:
        """
        获取项目的必读资源

        Args:
            project_id: 项目ID

        Returns:
            List[Resource]: 必读资源列表
        """
        return await self.repo.get_required_by_project(project_id)

    async def create_resource(self, data: Dict[str, Any]) -> Resource:
        """
        创建资源

        Args:
            data: 资源数据

        Returns:
            Resource: 创建的资源
        """
        # 设置默认值
        if "content_type" not in data:
            data["content_type"] = "markdown"
        if "type" not in data:
            data["type"] = "note"
        if "tags" not in data:
            data["tags"] = []
        if "is_required" not in data:
            data["is_required"] = False

        return await self.repo.create(data)

    async def update_resource(self, id: str, data: Dict[str, Any]) -> Optional[Resource]:
        """
        更新资源

        Args:
            id: 资源ID
            data: 更新数据

        Returns:
            Optional[Resource]: 更新后的资源
        """
        return await self.repo.update(id, data)

    async def delete_resource(self, id: str) -> bool:
        """
        删除资源

        Args:
            id: 资源ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)
