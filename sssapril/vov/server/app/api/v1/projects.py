"""
项目API路由模块

提供项目相关的REST API端点。
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.project_service import ProjectService
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListItem,
)
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ApiResponse[PaginatedResponse[ProjectListItem]])
async def list_projects(
    status: Optional[str] = Query(None, description="状态筛选"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目列表

    返回所有项目，包含统计信息（群聊数量、Agent数量）。
    """
    service = ProjectService(db)
    filters = {}
    if status:
        filters["status"] = status
    items = await service.get_list(filters)
    return ApiResponse(data=PaginatedResponse(items=items, total=len(items), skip=0, limit=100))


@router.post("", response_model=ApiResponse[ProjectResponse], status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建项目

    创建新项目并返回项目详情。
    """
    service = ProjectService(db)
    project = await service.create_project(data.model_dump())
    return ApiResponse(data=project)


@router.get("/{project_id}", response_model=ApiResponse[ProjectResponse])
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目详情

    返回指定项目的详细信息。
    """
    service = ProjectService(db)
    project = await service.get_detail(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ApiResponse(data=project)


@router.put("/{project_id}", response_model=ApiResponse[ProjectResponse])
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新项目

    更新指定项目的信息。
    """
    service = ProjectService(db)
    project = await service.update_project(project_id, data.model_dump(exclude_unset=True))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ApiResponse(data=project)


@router.delete("/{project_id}", response_model=ApiResponse[StatusResponse])
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除项目

    删除指定项目（软删除）。
    """
    service = ProjectService(db)
    success = await service.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return ApiResponse(data=StatusResponse(success=True, message="Project deleted"))
