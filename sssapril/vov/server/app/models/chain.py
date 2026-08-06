"""
链模型模块

定义链(Chain)相关的数据库模型。

链是树形结构的核心节点：
- 群链(group): 群的根节点，含群初始描述
- 任务链(task): 一个任务的主对话链
- 回复链(reply): @agent触发的回复子链
- 工具链(tool): 工具调用子链

每条链只关心子链的结果，不关心子链的内部过程。
"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy import String, Text, JSON, Integer, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Chain(BaseModel):
    """
    链模型

    链是树形结构的核心节点，支持嵌套子链。

    Attributes:
        parent_chain_id: 父链ID（群链为None）
        chain_type: 链类型（group/task/reply/tool）
        group_id: 所属群聊ID
        task_id: 关联任务ID（task链才有）
        agent_id: 执行Agent ID（reply/tool链才有）
        status: 链状态（active/completed/failed）
        head_packet_id: 链头包ID（触发原因/请求）
        tail_packet_id: 链尾包ID（最终结果/回复）
        description: 描述（群链存群初始描述）
        packet_count: 包数量（冗余缓存）
        sub_chain_count: 子链数量（冗余缓存）
    """

    __tablename__ = "chains"
    __table_args__ = (
        CheckConstraint(
            "chain_type IN ('group', 'task', 'reply', 'tool')",
            name="chains_chain_type_check"
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'paused', 'completed', 'archived', 'failed')",
            name="chains_status_check"
        ),
        {"comment": "链表"}
    )

    parent_chain_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("chains.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="父链ID（群链为None）"
    )

    chain_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="链类型: group/task/reply/tool"
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
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联任务ID（task链才有）"
    )

    agent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        index=True,
        comment="执行Agent ID（reply/tool链才有）"
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
        comment="链状态: active(当前活跃)/paused(被任务接管挂起)/completed(已交接)/archived(任务折叠归档)/failed"
    )

    head_packet_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        comment="链头包ID（触发原因/请求）"
    )

    tail_packet_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        comment="链尾包ID（最终结果/回复）"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="描述（群链存群初始描述）"
    )

    packet_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="包数量（冗余缓存）"
    )

    sub_chain_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="子链数量（冗余缓存）"
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成时间"
    )

    # 交接相关（保留兼容，仅task链使用）
    rollover_from_chain_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        comment="交接来源链ID（本链由哪个链交接而来）"
    )

    rollover_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="交接时的总结内容（作为本链的链头上下文）"
    )

    # 关系
    parent_chain: Mapped[Optional["Chain"]] = relationship(
        "Chain",
        remote_side="Chain.id",
        foreign_keys=[parent_chain_id],
        back_populates="sub_chains"
    )
    sub_chains: Mapped[List["Chain"]] = relationship(
        "Chain",
        back_populates="parent_chain",
        lazy="selectin",
        order_by="Chain.created_at"
    )
    task: Mapped[Optional["Task"]] = relationship(
        "Task",
        back_populates="chain"
    )
    packets: Mapped[List["Packet"]] = relationship(
        "Packet",
        foreign_keys="[Packet.chain_id]",
        back_populates="chain",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="Packet.created_at"
    )


class Packet(BaseModel):
    """
    包模型

    包是链内的节点，按链表结构组织（prev_packet_id）。
    每个包可以触发一条子链（sub_chain_id）。

    Attributes:
        chain_id: 所属链ID
        prev_packet_id: 链内前一个包ID
        packet_type: 包类型
        sender_type: 发送者类型
        sender_id: 发送者ID
        sender_name: 发送者显示名
        content: 内容
        content_type: 内容类型
        sub_chain_id: 本包触发的子链ID
        metadata: 扩展信息
    """

    __tablename__ = "packets"
    __table_args__ = (
        CheckConstraint(
            "packet_type IN ('user_input', 'agent_text', 'think', 'tool_call', 'tool_result', 'error', 'system')",
            name="packets_packet_type_check"
        ),
        CheckConstraint(
            "sender_type IN ('user', 'agent', 'system', 'tool')",
            name="packets_sender_type_check"
        ),
        {"comment": "包表"}
    )

    chain_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chains.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属链ID"
    )

    prev_packet_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        comment="链内前一个包ID（链表结构）"
    )

    packet_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="包类型: user_input/agent_text/think/tool_call/tool_result/error/system"
    )

    sender_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="发送者类型: user/agent/system/tool"
    )

    sender_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="发送者ID"
    )

    sender_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="发送者显示名称"
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="内容"
    )

    content_type: Mapped[str] = mapped_column(
        String(20),
        default="text",
        nullable=False,
        comment="内容类型: text/markdown/json"
    )

    sub_chain_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("chains.id", ondelete="SET NULL"),
        nullable=True,
        comment="本包触发的子链ID"
    )

    metadata_json: Mapped[dict] = mapped_column(
        "metadata",
        JSON,
        default=dict,
        comment="扩展信息（render_spec, tool_name, tool_args等）"
    )

    # 关系
    chain: Mapped["Chain"] = relationship(
        "Chain",
        foreign_keys=[chain_id],
        back_populates="packets"
    )
    sub_chain: Mapped[Optional["Chain"]] = relationship(
        "Chain",
        foreign_keys=[sub_chain_id],
        backref="trigger_packet"
    )
