"""
订阅 Schema
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.services.subscription_engine import (
    TRIGGER_AS_MESSAGE,
    VALID_ACTIONS,
    VALID_EVENT_TYPES,
    VALID_SUBSCRIBER_TYPES,
)


class SubscriptionCreate(BaseModel):
    """创建订阅"""
    subscriber_type: str = Field(
        ..., description="订阅者类型", example="group",
    )
    subscriber_id: str = Field(
        ..., description="订阅者 ID（群 ID 或 agent ID）",
    )
    event_type: str = Field(
        ..., description="事件类型", example="group_status_changed",
    )
    filter: Optional[Dict[str, Any]] = Field(
        None, description="事件过滤条件（JSON object）",
        example={"group_id": "G4", "new_status": "completed"},
    )
    action: str = Field(
        TRIGGER_AS_MESSAGE,
        description="触发动作",
    )
    message_template: Optional[str] = Field(
        None, max_length=2000,
        description="消息模板，支持 {field} 占位符",
        example="G{group_id} 已 {new_status}，请基于其产出开始工作",
    )
    one_shot: bool = Field(
        False, description="是否一次性（触发后自动禁用）",
    )


class SubscriptionUpdate(BaseModel):
    """更新订阅"""
    filter: Optional[Dict[str, Any]] = None
    action: Optional[str] = None
    message_template: Optional[str] = Field(None, max_length=2000)
    enabled: Optional[bool] = None
    one_shot: Optional[bool] = None


class SubscriptionResponse(BaseModel):
    """订阅详情"""
    id: str
    project_id: str
    subscriber_type: str
    subscriber_id: str
    event_type: str
    filter: Optional[Dict[str, Any]] = None
    action: str
    message_template: Optional[str] = None
    enabled: bool
    one_shot: bool
    triggered_count: int
    last_triggered_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SubscriptionListResponse(BaseModel):
    """订阅列表"""
    items: List[SubscriptionResponse]
    total: int
