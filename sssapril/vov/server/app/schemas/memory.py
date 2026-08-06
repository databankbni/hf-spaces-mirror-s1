"""
记忆Schema模块

定义Agent记忆(Memory)相关的Pydantic schemas。
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


class MemoryBase(BaseModel):
    """记忆基础Schema"""
    content: str = Field(..., description="笔记内容")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    slug: str = Field(default="default", description="分类标识（Agent 自定义）")


class MemoryCreate(MemoryBase):
    """创建记忆请求"""
    agent_id: str = Field(..., description="Agent ID")
    project_id: str = Field(..., description="项目ID")


class MemoryUpdate(BaseModel):
    """更新记忆请求"""
    content: Optional[str] = Field(None, description="笔记内容")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    slug: Optional[str] = Field(None, description="分类标识")


class MemoryUpsert(BaseModel):
    """创建或更新记忆请求（按 slug 分类）"""
    content: str = Field(..., description="笔记内容")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    slug: str = Field(default="default", description="分类标识")


class MemoryResponse(MemoryBase, TimestampMixin):
    """记忆响应"""
    id: str = Field(..., description="记忆ID")
    agent_id: str = Field(..., description="Agent ID")
    project_id: str = Field(..., description="项目ID")
    agent_name: Optional[str] = Field(None, description="Agent名称")

    class Config:
        from_attributes = True
