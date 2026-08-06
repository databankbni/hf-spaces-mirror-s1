"""
交付物模型模块

定义交付物(Deliverable)和交付物版本(DeliverableVersion)相关的数据库模型。
"""

from typing import Optional, List
from sqlalchemy import String, Text, JSON, Integer, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Deliverable(BaseModel):
    """
    交付物模型

    交付物是任务的产出，以Markdown格式存储。

    Attributes:
        chain_id: 关联的讨论链ID
        group_id: 所属群聊ID
        task_id: 关联的任务ID
        title: 标题
        content: 内容（Markdown格式）
        content_type: 内容类型
        type: 交付物类型（标签）
        tags: 额外标签
        author_id: 主导Agent ID
        participant_ids: 参与Agent ID列表
        metadata_json: 元数据
        version: 版本号
        scope: 作用域（group/project）

    Relationships:
        chain: 关联的讨论链
        group: 所属群聊
        task: 关联的任务
        versions: 版本历史
    """

    __tablename__ = "deliverables"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('group', 'project')",
            name="deliverables_scope_check"
        ),
        {"comment": "交付物表"}
    )

    chain_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("chains.id"),
        nullable=True,
        index=True,
        comment="关联的讨论链ID"
    )

    group_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("groups.id"),
        nullable=False,
        index=True,
        comment="所属群聊ID"
    )

    task_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("tasks.id"),
        nullable=True,
        index=True,
        comment="关联的任务ID"
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="交付物标题"
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="交付物内容（Markdown格式）"
    )

    content_type: Mapped[str] = mapped_column(
        String(20),
        default="markdown",
        nullable=False,
        comment="内容类型"
    )

    type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="交付物类型（标签）"
    )

    tags: Mapped[list] = mapped_column(
        JSON,
        default=list,
        comment="额外标签"
    )

    author_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="主导Agent ID"
    )

    participant_ids: Mapped[list] = mapped_column(
        JSON,
        default=list,
        comment="参与Agent ID列表"
    )

    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        comment="元数据"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="版本号"
    )

    scope: Mapped[str] = mapped_column(
        String(20),
        default="group",
        nullable=False,
        comment="作用域: group/project"
    )

    # 关系
    chain = relationship("Chain")
    group = relationship("Group", back_populates="deliverables")
    task = relationship("Task", back_populates="deliverable")
    versions: Mapped[List["DeliverableVersion"]] = relationship(
        "DeliverableVersion",
        back_populates="deliverable",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="DeliverableVersion.version.desc()"
    )


class DeliverableVersion(BaseModel):
    """
    交付物版本模型

    记录交付物的历史版本，支持版本对比。

    Attributes:
        deliverable_id: 交付物ID
        version: 版本号
        content: 该版本的内容
        change_summary: 变更说明
        created_by: 修改者
    """

    __tablename__ = "deliverable_versions"
    __table_args__ = (
        UniqueConstraint("deliverable_id", "version", name="deliverable_versions_unique"),
        {"comment": "交付物版本表"}
    )

    deliverable_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("deliverables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="交付物ID"
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="版本号"
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="该版本的内容"
    )

    change_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="变更说明"
    )

    created_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="修改者"
    )

    # 关系
    deliverable: Mapped["Deliverable"] = relationship(
        "Deliverable",
        back_populates="versions"
    )
