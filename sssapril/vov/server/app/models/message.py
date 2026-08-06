"""
消息模型模块

定义消息(Message)相关的数据库模型。
"""

from sqlalchemy import String, Text, JSON, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Message(BaseModel):
    """
    消息模型

    记录群聊讨论中的每条消息。

    Attributes:
        chain_id: 所属讨论链ID
        sender_id: 发送者ID（agent_id 或 'user' 或 'system'）
        sender_type: 发送者类型（agent/user/system）
        sender_name: 发送者显示名称
        content: 消息内容
        content_type: 内容类型（text/markdown/json）
        metadata: 元数据

    Relationships:
        chain: 所属讨论链
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "sender_type IN ('agent', 'user', 'system')",
            name="messages_sender_type_check"
        ),
        {"comment": "消息表"}
    )

    chain_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chains.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属讨论链ID"
    )

    sender_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="发送者ID: agent_id 或 'user' 或 'system'"
    )

    sender_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="发送者类型: agent/user/system"
    )

    sender_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="发送者显示名称"
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="消息内容"
    )

    content_type: Mapped[str] = mapped_column(
        String(20),
        default="text",
        nullable=False,
        comment="内容类型: text/markdown/json"
    )

    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        comment="元数据"
    )

    # 关系
    chain: Mapped["Chain"] = relationship(
        "Chain",
        foreign_keys=[chain_id]
    )
