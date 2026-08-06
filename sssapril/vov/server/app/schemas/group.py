"""
群聊Schema模块

定义群聊(Group)相关的Pydantic schemas。
"""

from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin
from .agent import AgentDetailResponse, ProjectAgentResponse
from .task import TaskResponse
from .resource import ResourceResponse
from .deliverable import DeliverableResponse


class GroupBase(BaseModel):
    """群聊基础Schema"""
    name: str = Field(..., min_length=1, max_length=255, description="群聊名称")
    description: Optional[str] = Field(None, description="群聊描述")
    lead_agent_id: Optional[str] = Field(None, description="主导Agent ID")
    status: str = Field("pending", description="状态: pending/active/completed")
    order_index: int = Field(0, description="排序索引")
    autonomy_level: str = Field("semi_auto", description="自主级别: full_auto/semi_auto/manual")
    auto_advance: bool = Field(False, description="任务完成后自动推进")
    bypass_deliverable_required: bool = Field(False, description="true: 跳过 update_task_status(done) 的 deliverable 存在性检查")
    watchdog_enabled: bool = Field(True, description="true: 空闲 watchdog 监控本群; false: 跳过")


class GroupCreate(GroupBase):
    """创建群聊请求"""
    member_agent_ids: List[str] = Field(default_factory=list, description="成员Agent ID列表")


class GroupUpdate(BaseModel):
    """更新群聊请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="群聊名称")
    description: Optional[str] = Field(None, description="群聊描述")
    lead_agent_id: Optional[str] = Field(None, description="主导Agent ID")
    status: Optional[str] = Field(None, description="状态")
    order_index: Optional[int] = Field(None, description="排序索引")
    autonomy_level: Optional[str] = Field(None, description="自主级别")
    auto_advance: Optional[bool] = Field(None, description="任务完成后自动推进")
    bypass_deliverable_required: Optional[bool] = Field(None, description="true: 跳过 done 的 deliverable 检查")


class GroupMemberBase(BaseModel):
    """群聊成员基础Schema"""
    project_agent_id: str = Field(..., description="项目Agent ID")
    role: str = Field("participant", description="角色: admin/participant/observer")


class GroupMemberCreate(GroupMemberBase):
    """添加群聊成员请求"""
    pass


class GroupMemberResponse(GroupMemberBase):
    """群聊成员响应"""
    id: str = Field(..., description="成员ID")
    group_id: str = Field(..., description="群聊ID")
    agent: Optional[AgentDetailResponse] = Field(None, description="关联的Agent信息")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True


class GroupResponse(GroupBase, TimestampMixin):
    """群聊响应"""
    id: str = Field(..., description="群聊ID")
    project_id: str = Field(..., description="项目ID")
    lead_agent: Optional[ProjectAgentResponse] = Field(None, description="主导Agent信息")
    members: List[GroupMemberResponse] = Field(default_factory=list, description="成员列表")
    tasks: List[TaskResponse] = Field(default_factory=list, description="任务列表")
    resources: List[ResourceResponse] = Field(default_factory=list, description="资源列表")
    deliverables: List[DeliverableResponse] = Field(default_factory=list, description="交付物列表")

    class Config:
        from_attributes = True


class GroupListItem(BaseModel):
    """群聊列表项"""
    id: str = Field(..., description="群聊ID")
    project_id: str = Field(..., description="项目ID")
    name: str = Field(..., description="群聊名称")
    description: Optional[str] = Field(None, description="群聊描述")
    status: str = Field(..., description="状态")
    order_index: int = Field(..., description="排序索引")
    autonomy_level: str = Field(..., description="自主级别")
    task_count: int = Field(0, description="任务数量")
    done_task_count: int = Field(0, description="已完成任务数")
    member_count: int = Field(0, description="成员数量")
    message_count: int = Field(0, description="消息数量")
    deliverable_count: int = Field(0, description="交付物数量")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True


class ReorderGroupsRequest(BaseModel):
    """重新排序群聊请求"""
    ordered_ids: List[str] = Field(..., description="排序后的群聊ID列表")
