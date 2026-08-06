"""
记忆模型模块

定义Agent个人笔记(Memory)相关的数据库模型。

Agent个人笔记是Agent在项目中的知识积累，跨群聊共用。
一个 Agent 在同一个项目下可以有多条笔记（按 slug 分类），
由 Agent 自身通过 self-memory skill 管理。
"""

from sqlalchemy import String, Text, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Memory(BaseModel):
    """
    Agent个人笔记模型

    记录Agent在项目中的个人知识积累，跨群聊共用。
    通过 slug 字段分类（例如：decisions / watchouts / state_snapshot），
    由 Agent 自行决定写入什么、如何分类。

    Attributes:
        agent_id: Agent ID
        project_id: 项目ID
        slug: 分类标识（Agent 自定义）
        content: 笔记内容（Markdown格式）
        content_type: 内容类型
        tags: 标签列表

    Relationships:
        agent: 关联的Agent
        project: 所属项目
    """

    __tablename__ = "memories"
    __table_args__ = (
        # 同一 Agent 在同一项目下，slug 唯一
        UniqueConstraint("agent_id", "project_id", "slug", name="memories_unique"),
        {"comment": "Agent个人笔记表"}
    )

    agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Agent ID"
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目ID"
    )

    slug: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="default",
        index=True,
        comment="分类标识，由 Agent 自行定义（self-memory skill 模板）"
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="笔记内容（Markdown格式）"
    )

    content_type: Mapped[str] = mapped_column(
        String(20),
        default="markdown",
        nullable=False,
        comment="内容类型"
    )

    tags: Mapped[list] = mapped_column(
        JSON,
        default=list,
        comment="标签列表"
    )

    # 关系
    agent: Mapped["Agent"] = relationship(
        "Agent",
        lazy="selectin"
    )
    # project = relationship("Project")
