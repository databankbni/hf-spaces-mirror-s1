"""
基础Repository模块

提供通用的数据访问层基类，封装CRUD操作。
"""

from typing import TypeVar, Generic, Type, Optional, List, Dict, Any
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.models.base import BaseModel

# 泛型类型变量
ModelType = TypeVar("ModelType", bound=BaseModel)


class BaseRepository(Generic[ModelType]):
    """
    基础Repository类

    提供通用的CRUD操作，所有Repository继承此类。

    Type Parameters:
        ModelType: SQLAlchemy模型类型

    Attributes:
        model: SQLAlchemy模型类
        db: 数据库会话
    """

    def __init__(self, model: Type[ModelType], db: AsyncSession):
        """
        初始化Repository

        Args:
            model: SQLAlchemy模型类
            db: 数据库会话
        """
        self.model = model
        self.db = db

    async def get_by_id(self, id: str) -> Optional[ModelType]:
        """
        根据ID获取记录

        Args:
            id: 记录ID

        Returns:
            Optional[ModelType]: 找到的记录，不存在返回None
        """
        query = select(self.model).where(
            and_(
                self.model.id == id,
                self.model.deleted_at.is_(None)
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

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
        query = select(self.model).where(self.model.deleted_at.is_(None))

        # 应用筛选条件
        if filters:
            for key, value in filters.items():
                if value is not None and hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        # 应用排序
        if order_by:
            if order_by.startswith("-"):
                query = query.order_by(getattr(self.model, order_by[1:]).desc())
            else:
                query = query.order_by(getattr(self.model, order_by))
        else:
            query = query.order_by(self.model.created_at.desc())

        # 应用分页
        query = query.offset(skip).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        统计记录数量

        Args:
            filters: 筛选条件

        Returns:
            int: 记录数量
        """
        query = select(func.count()).select_from(self.model).where(
            self.model.deleted_at.is_(None)
        )

        if filters:
            for key, value in filters.items():
                if value is not None and hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def create(self, data: Dict[str, Any]) -> ModelType:
        """
        创建记录

        Args:
            data: 记录数据

        Returns:
            ModelType: 创建的记录
        """
        instance = self.model(**data)
        self.db.add(instance)
        await self.db.flush()
        await self.db.refresh(instance)
        return instance

    async def update(self, id: str, data: Dict[str, Any]) -> Optional[ModelType]:
        """
        更新记录

        Args:
            id: 记录ID
            data: 更新数据

        Returns:
            Optional[ModelType]: 更新后的记录，不存在返回None
        """
        instance = await self.get_by_id(id)
        if not instance:
            return None

        for key, value in data.items():
            if hasattr(instance, key):
                setattr(instance, key, value)

        await self.db.flush()
        await self.db.refresh(instance)
        return instance

    async def delete(self, id: str) -> bool:
        """
        删除记录（软删除）

        Args:
            id: 记录ID

        Returns:
            bool: 是否删除成功
        """
        instance = await self.get_by_id(id)
        if not instance:
            return False

        instance.soft_delete()
        await self.db.flush()
        return True

    async def hard_delete(self, id: str) -> bool:
        """
        硬删除记录

        Args:
            id: 记录ID

        Returns:
            bool: 是否删除成功
        """
        instance = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        instance = instance.scalar_one_or_none()
        if not instance:
            return False

        await self.db.delete(instance)
        await self.db.flush()
        return True

    async def exists(self, id: str) -> bool:
        """
        检查记录是否存在

        Args:
            id: 记录ID

        Returns:
            bool: 是否存在
        """
        query = select(func.count()).select_from(self.model).where(
            and_(
                self.model.id == id,
                self.model.deleted_at.is_(None)
            )
        )
        result = await self.db.execute(query)
        return (result.scalar() or 0) > 0
