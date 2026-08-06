"""
订阅模型

通用事件订阅：群/agent 可以订阅系统事件，事件触发时执行预定义动作。
与现有 event_bus 的 agent-side 订阅并存（不替代），但提供：
- DB 持久化
- 复杂 filter（递归字段匹配）
- 多种 action（trigger_as_message / task / notification）
- 模板消息渲染
- 一次性/持续订阅
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class Subscription(BaseModel):
    """
    通用事件订阅

    Attributes:
        project_id: 所属项目
        subscriber_type: 订阅者类型（group/agent）
        subscriber_id: 订阅者 ID（群 ID 或 agent ID）
        event_type: 事件类型（task_status_changed/resource_created/resource_updated/group_status_changed/chain_*）
        filter: 事件过滤条件（JSON object，递归字段比较）
        action: 触发动作（trigger_as_message / trigger_as_task / trigger_as_notification）
        message_template: 消息模板（支持 {field} 占位符）
        enabled: 是否启用
        one_shot: 是否一次性（触发后自动禁用）
        triggered_count: 触发次数统计
        last_triggered_at: 上次触发时间
    """

    __tablename__ = "subscriptions"

    project_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True,
        comment="所属项目 ID",
    )
    subscriber_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="订阅者类型: group / agent",
    )
    subscriber_id: Mapped[str] = mapped_column(
        String(36), nullable=False,
        comment="订阅者 ID（群 ID 或 agent ID）",
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="事件类型",
    )
    # SQLite 没有原生 JSON 类型；用 JSON 抽象（SQLAlchemy 会转成 TEXT）
    filter: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="事件过滤条件（JSON object，递归字段比较）",
    )
    action: Mapped[str] = mapped_column(
        String(30), nullable=False, default="trigger_as_message",
        comment="触发动作: trigger_as_message / trigger_as_task / trigger_as_notification",
    )
    message_template: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True,
        comment="消息模板（支持 {field} 占位符）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1",
        comment="是否启用",
    )
    one_shot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0",
        comment="是否一次性（触发后自动禁用）",
    )
    triggered_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="触发次数统计",
    )
    last_triggered_at: Mapped[Optional[Any]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="上次触发时间",
    )

    __table_args__ = (
        Index("ix_subscriptions_subscriber", "subscriber_type", "subscriber_id"),
        Index("ix_subscriptions_project_event", "project_id", "event_type"),
        Index("ix_subscriptions_enabled", "enabled"),
    )

    def __repr__(self) -> str:
        return (
            f"<Subscription(id={self.id[:8]}, "
            f"{self.subscriber_type}={self.subscriber_id[:8]}, "
            f"event={self.event_type}, enabled={self.enabled})>"
        )

    def to_dict(self) -> dict:
        """转为字典（用于 API 返回）"""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "subscriber_type": self.subscriber_type,
            "subscriber_id": self.subscriber_id,
            "event_type": self.event_type,
            "filter": self.filter,
            "action": self.action,
            "message_template": self.message_template,
            "enabled": self.enabled,
            "one_shot": self.one_shot,
            "triggered_count": self.triggered_count,
            "last_triggered_at": self.last_triggered_at.isoformat() if self.last_triggered_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
