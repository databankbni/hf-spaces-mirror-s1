"""
资源Schema模块

定义资源(Resource)相关的Pydantic schemas。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


class ResourceBase(BaseModel):
    """资源基础Schema"""
    title: str = Field(..., min_length=1, max_length=255, description="资源标题")
    content: str = Field(..., description="资源内容（Markdown格式）")
    content_type: str = Field("markdown", description="内容类型")
    type: str = Field("note", description="资源类型: note/reference/guideline/rule/custom/map")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    is_required: bool = Field(False, description="是否必读")
    created_by: str = Field("user", description="创建者: user 或 agent_id")


class ResourceCreate(ResourceBase):
    """创建资源请求"""
    project_id: str = Field(..., description="所属项目ID")
    group_id: Optional[str] = Field(None, description="所属群聊ID，NULL表示全局资源")


class ResourceUpdate(BaseModel):
    """更新资源请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=255, description="资源标题")
    content: Optional[str] = Field(None, description="资源内容")
    type: Optional[str] = Field(None, description="资源类型")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    is_required: Optional[bool] = Field(None, description="是否必读")


class ResourceResponse(ResourceBase, TimestampMixin):
    """资源响应"""
    id: str = Field(..., description="资源ID")
    project_id: str = Field(..., description="项目ID")
    group_id: Optional[str] = Field(None, description="群聊ID")
    task_id: Optional[str] = Field(None, description="关联任务ID")
    parent_id: Optional[str] = Field(None, description="父资源ID（文件夹）")
    is_folder: bool = Field(False, description="是否为文件夹")

    class Config:
        from_attributes = True
