"""
资源模型模块

定义资源(Resource)相关的数据库模型。

资源是项目或群聊的参考资料，可以是用户手动添加或Agent生成。
"""

from typing import Optional
from sqlalchemy import String, Text, JSON, Boolean, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Resource(BaseModel):
    """
    资源模型

    资料是项目/群聊的参考材料，支持Markdown格式。

    Attributes:
        project_id: 所属项目ID
        group_id: 所属群聊ID（NULL表示全局资源）
        title: 标题
        content: 内容（Markdown格式）
        content_type: 内容类型
        type: 资源类型（note/reference/guideline/rule/custom）
        tags: 标签列表
        is_required: 是否必读
        created_by: 创建者（user 或 agent_id）

    Relationships:
        project: 所属项目
        group: 所属群聊（可选）
    """

    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint(
            "type IN ('note', 'reference', 'guideline', 'rule', 'custom', 'map')",
            name="resources_type_check"
        ),
        {"comment": "资源表"}
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID"
    )

    group_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属群聊ID，NULL表示全局资源"
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="资源标题"
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="资源内容（Markdown格式）"
    )

    content_type: Mapped[str] = mapped_column(
        String(20),
        default="markdown",
        nullable=False,
        comment="内容类型"
    )

    type: Mapped[str] = mapped_column(
        String(50),
        default="note",
        nullable=False,
        comment="资源类型: note/reference/guideline/rule/custom"
    )

    tags: Mapped[list] = mapped_column(
        JSON,
        default=list,
        comment="标签列表"
    )

    is_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否必读"
    )

    created_by: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="创建者: user 或 agent_id"
    )

    task_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="产出该资源的任务ID（用于追溯到具体群聊/任务）"
    )

    # ★ v2 P1: 文件夹支持
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="父资源ID（实现文件夹树形结构），NULL表示根级"
    )

    is_folder: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="是否为文件夹（文件夹的content为空，用于组织树形结构）"
    )

    # 关系
    project = relationship("Project", back_populates="resources")
    group = relationship("Group", back_populates="resources")
    parent = relationship(
        "Resource",
        remote_side="Resource.id",
        backref="children",
        lazy="selectin"
    )
