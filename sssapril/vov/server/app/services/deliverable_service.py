"""
交付物Service模块

提供交付物(Deliverable)的业务逻辑。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deliverable import Deliverable, DeliverableVersion
from app.repositories.deliverable_repo import DeliverableRepository, DeliverableVersionRepository
from .base import BaseService


class DeliverableService(BaseService[Deliverable, DeliverableRepository]):
    """
    交付物Service

    提供交付物的业务逻辑，包括版本管理。
    """

    def __init__(self, db: AsyncSession):
        repo = DeliverableRepository(db)
        super().__init__(repo, db)
        self.version_repo = DeliverableVersionRepository(db)

    async def get_by_group(self, group_id: str) -> List[Deliverable]:
        """
        获取群聊的交付物列表

        Args:
            group_id: 群聊ID

        Returns:
            List[Deliverable]: 交付物列表
        """
        return await self.repo.get_by_group(group_id)

    async def get_by_project(self, project_id: str) -> List[Deliverable]:
        """
        获取项目的交付物列表（scope=project）

        Args:
            project_id: 项目ID

        Returns:
            List[Deliverable]: 交付物列表
        """
        return await self.repo.get_by_project(project_id)

    async def get_detail(self, id: str) -> Optional[Deliverable]:
        """
        获取交付物详情（包含版本历史）

        Args:
            id: 交付物ID

        Returns:
            Optional[Deliverable]: 交付物详情
        """
        return await self.repo.get_with_versions(id)

    async def create_deliverable(self, data: Dict[str, Any]) -> Deliverable:
        """
        创建交付物

        Args:
            data: 交付物数据

        Returns:
            Deliverable: 创建的交付物
        """
        # 设置默认值
        if "version" not in data:
            data["version"] = 1
        if "scope" not in data:
            data["scope"] = "group"
        if "content_type" not in data:
            data["content_type"] = "markdown"
        if "tags" not in data:
            data["tags"] = []
        if "participant_ids" not in data:
            data["participant_ids"] = []

        # 创建交付物
        deliverable = await self.repo.create(data)

        # 保存初始版本
        await self.version_repo.create({
            "deliverable_id": deliverable.id,
            "version": 1,
            "content": data["content"],
            "change_summary": "Initial version",
            "created_by": data.get("author_id"),
        })

        return deliverable

    async def update_content(self, id: str, content: str, change_summary: str = None, created_by: str = None) -> Optional[Deliverable]:
        """
        更新交付物内容并创建新版本

        Args:
            id: 交付物ID
            content: 新内容
            change_summary: 变更说明
            created_by: 修改者

        Returns:
            Optional[Deliverable]: 更新后的交付物
        """
        deliverable = await self.repo.get_with_versions(id)
        if not deliverable:
            return None

        # 递增版本号
        new_version = deliverable.version + 1

        # 更新交付物
        updated = await self.repo.update(id, {
            "content": content,
            "version": new_version,
        })

        # 保存版本历史
        await self.version_repo.create({
            "deliverable_id": id,
            "version": new_version,
            "content": content,
            "change_summary": change_summary,
            "created_by": created_by,
        })

        return updated

    async def get_versions(self, deliverable_id: str) -> List[DeliverableVersion]:
        """
        获取交付物的版本列表

        Args:
            deliverable_id: 交付物ID

        Returns:
            List[DeliverableVersion]: 版本列表
        """
        return await self.version_repo.get_by_deliverable(deliverable_id)

    async def get_version(self, deliverable_id: str, version: int) -> Optional[DeliverableVersion]:
        """
        获取特定版本

        Args:
            deliverable_id: 交付物ID
            version: 版本号

        Returns:
            Optional[DeliverableVersion]: 版本记录
        """
        return await self.version_repo.get_version(deliverable_id, version)

    async def delete_deliverable(self, id: str) -> bool:
        """
        删除交付物

        Args:
            id: 交付物ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)
