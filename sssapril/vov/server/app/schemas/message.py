"""
消息Schema模块

定义消息(Message)相关的Pydantic schemas。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


class MessageBase(BaseModel):
    """消息基础Schema"""
    chain_id: str = Field(..., description="讨论链ID")
    content: str = Field(..., description="消息内容")
    content_type: str = Field("text", description="内容类型: text/markdown/json/file")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class MessageCreate(BaseModel):
    """创建消息请求"""
    content: str = Field(..., description="消息内容")
    content_type: str = Field("text", description="内容类型")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class MessageResponse(BaseModel):
    """消息响应"""
    id: str = Field(..., description="消息ID")
    chain_id: str = Field(..., description="讨论链ID")
    sender_id: Optional[str] = Field(None, description="发送者ID")
    sender_type: str = Field(..., description="发送者类型: user/agent/system")
    sender_name: Optional[str] = Field(None, description="发送者名称")
    content: str = Field(..., description="消息内容")
    content_type: str = Field(..., description="内容类型")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "MessageResponse":
        """从ORM对象验证，处理 metadata_json -> metadata 映射"""
        if hasattr(obj, 'metadata_json'):
            # ORM 对象：手动提取字段
            data = {
                "id": obj.id,
                "chain_id": obj.chain_id,
                "sender_id": obj.sender_id,
                "sender_type": obj.sender_type,
                "sender_name": obj.sender_name,
                "content": obj.content,
                "content_type": obj.content_type,
                "metadata": obj.metadata_json or {},
                "created_at": obj.created_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


class MessageListResponse(BaseModel):
    """消息列表响应"""
    items: List[MessageResponse] = Field(..., description="消息列表")
    total: int = Field(..., description="总数")
    has_more: bool = Field(False, description="是否有更多")


# WebSocket消息schemas
class WsClientMessage(BaseModel):
    """WebSocket客户端消息"""
    type: str = Field(..., description="消息类型: send/action/typing/stop")
    payload: Dict[str, Any] = Field(..., description="消息负载")


class WsServerMessage(BaseModel):
    """WebSocket服务端消息"""
    type: str = Field(..., description="消息类型")
    payload: Dict[str, Any] = Field(..., description="消息负载")


class AgentTypingPayload(BaseModel):
    """Agent正在输入的负载"""
    agent_id: str = Field(..., description="Agent ID")
    agent_name: str = Field(..., description="Agent名称")


class SystemMessagePayload(BaseModel):
    """系统消息负载"""
    event: str = Field(..., description="事件类型")
    data: Dict[str, Any] = Field(default_factory=dict, description="事件数据")
