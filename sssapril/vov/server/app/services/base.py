"""
基础Service模块

提供通用的业务逻辑层基类。
"""

from typing import TypeVar, Generic, Type, Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.models.base import BaseModel

# 泛型类型变量
ModelType = TypeVar("ModelType", bound=BaseModel)
RepoType = TypeVar("RepoType", bound=BaseRepository)


class BaseService(Generic[ModelType, RepoType]):
    """
    基础Service类

    提供通用的业务逻辑，所有Service继承此类。

    Type Parameters:
        ModelType: SQLAlchemy模型类型
        RepoType: Repository类型

    Attributes:
        repo: Repository实例
        db: 数据库会话
    """

    def __init__(self, repo: RepoType, db: AsyncSession):
        """
        初始化Service

        Args:
            repo: Repository实例
            db: 数据库会话
        """
        self.repo = repo
        self.db = db

    async def get_by_id(self, id: str) -> Optional[ModelType]:
        """
        根据ID获取记录

        Args:
            id: 记录ID

        Returns:
            Optional[ModelType]: 记录
        """
        return await self.repo.get_by_id(id)

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None
    ) -> List[ModelType]:
        """
        获取记录列表

        Args:
            skip: 跳过数量
            limit: 限制数量
            filters: 筛选条件
            order_by: 排序字段

        Returns:
            List[ModelType]: 记录列表
        """
        return await self.repo.get_all(skip, limit, filters, order_by)

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        统计记录数量

        Args:
            filters: 筛选条件

        Returns:
            int: 记录数量
        """
        return await self.repo.count(filters)

    async def create(self, data: Dict[str, Any]) -> ModelType:
        """
        创建记录

        Args:
            data: 记录数据

        Returns:
            ModelType: 创建的记录
        """
        return await self.repo.create(data)

    async def update(self, id: str, data: Dict[str, Any]) -> Optional[ModelType]:
        """
        更新记录

        Args:
            id: 记录ID
            data: 更新数据

        Returns:
            Optional[ModelType]: 更新后的记录
        """
        return await self.repo.update(id, data)

    async def delete(self, id: str) -> bool:
        """
        删除记录

        Args:
            id: 记录ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)

    async def exists(self, id: str) -> bool:
        """
        检查记录是否存在

        Args:
            id: 记录ID

        Returns:
            bool: 是否存在
        """
        return await self.repo.exists(id)
