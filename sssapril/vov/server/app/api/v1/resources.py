"""
资源API路由模块

提供资源相关的REST API端点。
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.resource_service import ResourceService
from app.schemas.resource import (
    ResourceCreate,
    ResourceUpdate,
    ResourceResponse,
)
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse

router = APIRouter(tags=["resources"])


# 项目全局资源端点
@router.get("/projects/{project_id}/resources", response_model=ApiResponse[PaginatedResponse[ResourceResponse]])
async def list_project_resources(
    project_id: str,
    resource_type: Optional[str] = Query(None, description="资源类型筛选"),
    is_required: Optional[bool] = Query(None, description="是否必读筛选"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的全局资源列表

    返回项目中所有全局资源（非群聊专属）。
    """
    service = ResourceService(db)
    resources = await service.get_by_project(project_id, resource_type, is_required)
    return ApiResponse(data=PaginatedResponse(items=resources, total=len(resources), skip=0, limit=100))


@router.get("/projects/{project_id}/resources/required", response_model=ApiResponse[PaginatedResponse[ResourceResponse]])
async def list_required_resources(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的必读资源

    返回项目中所有标记为必读的资源。
    """
    service = ResourceService(db)
    resources = await service.get_required_by_project(project_id)
    return ApiResponse(data=PaginatedResponse(items=resources, total=len(resources), skip=0, limit=100))


# 群聊资源端点
@router.get("/groups/{group_id}/resources", response_model=ApiResponse[PaginatedResponse[ResourceResponse]])
async def list_group_resources(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取群聊的资源列表

    返回群聊专属的资源。
    """
    service = ResourceService(db)
    resources = await service.get_by_group(group_id)
    return ApiResponse(data=PaginatedResponse(items=resources, total=len(resources), skip=0, limit=100))


# 资源CRUD端点
@router.post("/resources", response_model=ApiResponse[ResourceResponse], status_code=201)
async def create_resource(
    data: ResourceCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建资源

    创建新资源。
    """
    service = ResourceService(db)
    resource = await service.create_resource(data.model_dump())
    return ApiResponse(data=resource)


@router.get("/resources/{resource_id}", response_model=ApiResponse[ResourceResponse])
async def get_resource(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取资源详情

    返回资源的详细信息。
    """
    service = ResourceService(db)
    resource = await service.get_by_id(resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return ApiResponse(data=resource)


@router.put("/resources/{resource_id}", response_model=ApiResponse[ResourceResponse])
async def update_resource(
    resource_id: str,
    data: ResourceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新资源

    更新资源信息。
    """
    service = ResourceService(db)
    resource = await service.update_resource(resource_id, data.model_dump(exclude_unset=True))
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return ApiResponse(data=resource)


@router.delete("/resources/{resource_id}", response_model=ApiResponse[StatusResponse])
async def delete_resource(
    resource_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除资源

    删除指定资源（软删除）。
    """
    service = ResourceService(db)
    success = await service.delete_resource(resource_id)
    if not success:
        raise HTTPException(status_code=404, detail="Resource not found")
    return ApiResponse(data=StatusResponse(success=True, message="Resource deleted"))
