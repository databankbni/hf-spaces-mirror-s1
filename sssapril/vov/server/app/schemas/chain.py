"""
链Schema模块

定义链(Chain)相关的Pydantic schemas。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


class ChainBase(BaseModel):
    """链基础Schema"""
    parent_chain_id: Optional[str] = Field(None, description="父链ID")
    chain_type: str = Field("task", description="链类型: group/task/reply/tool")
    group_id: str = Field(..., description="所属群聊ID")
    task_id: Optional[str] = Field(None, description="关联任务ID")
    agent_id: Optional[str] = Field(None, description="执行Agent ID")
    status: str = Field("active", description="状态: active/completed/failed")
    description: Optional[str] = Field(None, description="描述")


class ChainCreate(ChainBase):
    """创建链请求"""
    pass


class ChainUpdate(BaseModel):
    """更新链请求"""
    status: Optional[str] = Field(None, description="状态")
    description: Optional[str] = Field(None, description="描述")


class ChainResponse(ChainBase, TimestampMixin):
    """链响应"""
    id: str = Field(..., description="链ID")
    head_packet_id: Optional[str] = Field(None, description="链头包ID")
    tail_packet_id: Optional[str] = Field(None, description="链尾包ID")
    packet_count: int = Field(0, description="包数量")
    sub_chain_count: int = Field(0, description="子链数量")
    completed_at: Optional[datetime] = Field(None, description="完成时间")

    class Config:
        from_attributes = True


class ChainDetailResponse(ChainResponse):
    """链详情响应（包含包列表）"""
    packets: List[Dict[str, Any]] = Field(default_factory=list, description="包列表")


class ChainActionRequest(BaseModel):
    """链操作请求"""
    action: str = Field(..., description="操作: pause/resume/complete/cancel")
    reason: Optional[str] = Field(None, description="操作原因")


class PacketCreate(BaseModel):
    """创建包请求"""
    content: str = Field(..., description="内容")
    content_type: str = Field("text", description="内容类型")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
