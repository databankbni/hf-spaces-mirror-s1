"""
标签Schema模块

定义标签(Tag)相关的Pydantic schemas。
"""

from typing import Optional
from pydantic import BaseModel, Field

from .common import TimestampMixin


class TagBase(BaseModel):
    """标签基础Schema"""
    name: str = Field(..., min_length=1, max_length=100, description="标签名称")
    description: Optional[str] = Field(None, description="标签说明")
    suggested_template: Optional[str] = Field(None, description="建议的格式/模板")
    color: Optional[str] = Field(None, max_length=50, description="标签颜色")


class TagCreate(TagBase):
    """创建标签请求"""
    pass


class TagUpdate(BaseModel):
    """更新标签请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="标签名称")
    description: Optional[str] = Field(None, description="标签说明")
    suggested_template: Optional[str] = Field(None, description="建议的格式/模板")
    color: Optional[str] = Field(None, max_length=50, description="标签颜色")


class TagResponse(TagBase, TimestampMixin):
    """标签响应"""
    id: str = Field(..., description="标签ID")
    project_id: str = Field(..., description="项目ID")

    class Config:
        from_attributes = True
