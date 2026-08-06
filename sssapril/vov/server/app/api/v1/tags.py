"""
标签API路由模块

提供标签相关的REST API端点。
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.tag_service import TagService
from app.schemas.tag import (
    TagCreate,
    TagUpdate,
    TagResponse,
)
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse

router = APIRouter(tags=["tags"])


# 项目标签端点
@router.get("/projects/{project_id}/tags", response_model=ApiResponse[PaginatedResponse[TagResponse]])
async def list_tags(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的标签列表

    返回项目中所有标签。
    """
    service = TagService(db)
    tags = await service.get_by_project(project_id)
    return ApiResponse(data=PaginatedResponse(items=tags, total=len(tags), skip=0, limit=100))


@router.post("/projects/{project_id}/tags", response_model=ApiResponse[TagResponse], status_code=201)
async def create_tag(
    project_id: str,
    data: TagCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建标签

    在项目中创建新标签。
    """
    service = TagService(db)
    try:
        tag = await service.create_tag(project_id, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data=tag)


# 标签CRUD端点
@router.get("/tags/{tag_id}", response_model=ApiResponse[TagResponse])
async def get_tag(
    tag_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取标签详情

    返回标签的详细信息。
    """
    service = TagService(db)
    tag = await service.get_by_id(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return ApiResponse(data=tag)


@router.put("/tags/{tag_id}", response_model=ApiResponse[TagResponse])
async def update_tag(
    tag_id: str,
    data: TagUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新标签

    更新标签信息。
    """
    service = TagService(db)
    tag = await service.update_tag(tag_id, data.model_dump(exclude_unset=True))
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return ApiResponse(data=tag)


@router.delete("/tags/{tag_id}", response_model=ApiResponse[StatusResponse])
async def delete_tag(
    tag_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除标签

    删除指定标签（软删除）。
    """
    service = TagService(db)
    success = await service.delete_tag(tag_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tag not found")
    return ApiResponse(data=StatusResponse(success=True, message="Tag deleted"))
