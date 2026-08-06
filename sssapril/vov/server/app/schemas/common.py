"""
通用Schema模块

定义通用的Pydantic schemas。
"""

from typing import Optional, List, Any, Generic, TypeVar
from datetime import datetime
from pydantic import BaseModel, Field

# 泛型类型变量
DataT = TypeVar("DataT")


class PaginationParams(BaseModel):
    """分页参数"""
    skip: int = Field(0, ge=0, description="跳过数量")
    limit: int = Field(100, ge=1, le=1000, description="限制数量")


class PaginatedResponse(BaseModel, Generic[DataT]):
    """分页响应"""
    items: List[DataT] = Field(..., description="数据列表")
    total: int = Field(..., description="总数")
    skip: int = Field(..., description="跳过数量")
    limit: int = Field(..., description="限制数量")


class ApiResponse(BaseModel, Generic[DataT]):
    """通用API响应"""
    success: bool = Field(True, description="是否成功")
    data: Optional[DataT] = Field(None, description="数据")
    message: Optional[str] = Field(None, description="消息")


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(False, description="是否成功")
    error: str = Field(..., description="错误信息")
    detail: Optional[Any] = Field(None, description="错误详情")


class IDResponse(BaseModel):
    """ID响应"""
    id: str = Field(..., description="记录ID")


class StatusResponse(BaseModel):
    """状态响应"""
    success: bool = Field(..., description="是否成功")
    message: Optional[str] = Field(None, description="消息")


class TimestampMixin(BaseModel):
    """时间戳混入"""
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
