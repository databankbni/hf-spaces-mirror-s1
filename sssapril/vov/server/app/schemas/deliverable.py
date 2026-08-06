"""
交付物Schema模块

定义交付物(Deliverable)相关的Pydantic schemas。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


class DeliverableBase(BaseModel):
    """交付物基础Schema"""
    title: str = Field(..., min_length=1, max_length=255, description="交付物标题")
    content: str = Field(..., description="交付物内容（Markdown格式）")
    content_type: str = Field("markdown", description="内容类型")
    type: Optional[str] = Field(None, max_length=50, description="交付物类型（标签）")
    tags: List[str] = Field(default_factory=list, description="额外标签")
    author_id: Optional[str] = Field(None, description="主导Agent ID")
    participant_ids: List[str] = Field(default_factory=list, description="参与Agent ID列表")
    metadata_json: Dict[str, Any] = Field(default_factory=dict, description="元数据")
    scope: str = Field("group", description="作用域: group/project")


class DeliverableCreate(DeliverableBase):
    """创建交付物请求"""
    chain_id: Optional[str] = Field(None, description="关联的讨论链ID")
    group_id: str = Field(..., description="所属群聊ID")
    task_id: Optional[str] = Field(None, description="关联的任务ID")


class DeliverableUpdate(BaseModel):
    """更新交付物请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=255, description="交付物标题")
    content: Optional[str] = Field(None, description="交付物内容")
    type: Optional[str] = Field(None, max_length=50, description="交付物类型")
    tags: Optional[List[str]] = Field(None, description="额外标签")
    scope: Optional[str] = Field(None, description="作用域")


class DeliverableUpdateContent(BaseModel):
    """更新交付物内容请求"""
    content: str = Field(..., description="新内容")
    change_summary: Optional[str] = Field(None, description="变更说明")
    created_by: Optional[str] = Field(None, description="修改者")


class DeliverableResponse(DeliverableBase, TimestampMixin):
    """交付物响应"""
    id: str = Field(..., description="交付物ID")
    chain_id: Optional[str] = Field(None, description="讨论链ID")
    group_id: str = Field(..., description="群聊ID")
    task_id: Optional[str] = Field(None, description="任务ID")
    version: int = Field(1, description="版本号")

    class Config:
        from_attributes = True


class DeliverableVersionResponse(BaseModel):
    """交付物版本响应"""
    id: str = Field(..., description="版本ID")
    deliverable_id: str = Field(..., description="交付物ID")
    version: int = Field(..., description="版本号")
    content: str = Field(..., description="版本内容")
    change_summary: Optional[str] = Field(None, description="变更说明")
    created_by: Optional[str] = Field(None, description="修改者")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True


class DeliverableDiffItem(BaseModel):
    """交付物差异项"""
    type: str = Field(..., description="差异类型: add/remove/unchanged")
    content: str = Field(..., description="内容")
    line_number: Optional[int] = Field(None, description="行号")


class DeliverableDiff(BaseModel):
    """交付物差异"""
    version_a: int = Field(..., description="版本A")
    version_b: int = Field(..., description="版本B")
    items: List[DeliverableDiffItem] = Field(..., description="差异项列表")
