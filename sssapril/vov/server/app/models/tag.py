"""
标签模型模块

定义项目标签(Tag)相关的数据库模型。

标签是项目级的，用于分类交付物和资源。
"""

from typing import Optional
from sqlalchemy import String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Tag(BaseModel):
    """
    项目标签模型

    每个项目独立管理自己的标签体系，用于分类交付物和资源。

    Attributes:
        project_id: 所属项目ID
        name: 标签名称
        description: 标签说明
        suggested_template: 建议的格式/模板
        color: 标签颜色

    Relationships:
        project: 所属项目
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="tags_unique"),
        {"comment": "项目标签表"}
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID"
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="标签名称"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="标签说明"
    )

    suggested_template: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="建议的格式/模板"
    )

    color: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="标签颜色"
    )

    # 关系
    # project = relationship("Project")
