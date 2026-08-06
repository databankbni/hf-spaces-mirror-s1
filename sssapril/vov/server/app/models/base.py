"""
基础模型模块

提供所有数据库模型的基类，包含通用字段和方法。
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def generate_uuid() -> str:
    """生成UUID字符串"""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """获取UTC当前时间"""
    return datetime.now(timezone.utc)


class BaseModel(Base):
    """
    基础模型抽象类

    所有业务模型继承此类，自动获得以下字段：
    - id: UUID主键
    - created_at: 创建时间
    - updated_at: 更新时间
    - deleted_at: 软删除时间（可选）

    Attributes:
        __abstract__: 标记为抽象类，不创建表
    """

    __abstract__ = True

    # 主键ID（UUID）
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
        comment="主键ID"
    )

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )

    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
        comment="更新时间"
    )

    # 软删除时间
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="软删除时间"
    )

    def to_dict(self) -> dict[str, Any]:
        """
        将模型转换为字典

        Returns:
            dict: 模型字段字典
        """
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }

    def soft_delete(self) -> None:
        """
        软删除

        设置deleted_at为当前时间，不实际删除记录
        """
        self.deleted_at = utc_now()

    @property
    def is_deleted(self) -> bool:
        """
        是否已删除

        Returns:
            bool: 如果已软删除返回True
        """
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.id})>"
