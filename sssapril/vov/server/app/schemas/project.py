"""
项目Schema模块

定义项目(Project)相关的Pydantic schemas。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


class ProjectBase(BaseModel):
    """项目基础Schema"""
    name: str = Field(..., min_length=1, max_length=255, description="项目名称")
    description: Optional[str] = Field(None, description="项目描述")
    cover_color: Optional[str] = Field(None, max_length=50, description="封面颜色")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    status: str = Field("active", description="状态: active/archived")
    workflow_config: Dict[str, Any] = Field(default_factory=dict, description="工作流配置")


class ProjectCreate(ProjectBase):
    """创建项目请求"""
    pass


class ProjectUpdate(BaseModel):
    """更新项目请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="项目名称")
    description: Optional[str] = Field(None, description="项目描述")
    cover_color: Optional[str] = Field(None, max_length=50, description="封面颜色")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    status: Optional[str] = Field(None, description="状态: active/archived")
    workflow_config: Optional[Dict[str, Any]] = Field(None, description="工作流配置")


class ProjectResponse(ProjectBase, TimestampMixin):
    """项目响应"""
    id: str = Field(..., description="项目ID")

    class Config:
        from_attributes = True


class ProjectListItem(BaseModel):
    """项目列表项"""
    id: str = Field(..., description="项目ID")
    name: str = Field(..., description="项目名称")
    description: Optional[str] = Field(None, description="项目描述")
    cover_color: Optional[str] = Field(None, description="封面颜色")
    status: str = Field(..., description="状态")
    group_count: int = Field(0, description="群聊数量")
    agent_count: int = Field(0, description="Agent数量")
    is_guide: bool = Field(False, description="是否为引导 project")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    class Config:
        from_attributes = True
