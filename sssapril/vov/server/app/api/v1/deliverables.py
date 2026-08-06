"""
交付物API路由模块

提供交付物相关的REST API端点。
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.deliverable_service import DeliverableService
from app.schemas.deliverable import (
    DeliverableCreate,
    DeliverableUpdate,
    DeliverableUpdateContent,
    DeliverableResponse,
    DeliverableVersionResponse,
    DeliverableDiff,
    DeliverableDiffItem,
)
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse

router = APIRouter(tags=["deliverables"])


# 群聊交付物端点
@router.get("/groups/{group_id}/deliverables", response_model=ApiResponse[PaginatedResponse[DeliverableResponse]])
async def list_group_deliverables(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取群聊的交付物列表

    返回群聊中所有交付物。
    """
    service = DeliverableService(db)
    deliverables = await service.get_by_group(group_id)
    return ApiResponse(data=PaginatedResponse(items=deliverables, total=len(deliverables), skip=0, limit=100))


# 项目交付物端点
@router.get("/projects/{project_id}/deliverables", response_model=ApiResponse[PaginatedResponse[DeliverableResponse]])
async def list_project_deliverables(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的交付物列表

    返回项目中所有scope=project的交付物。
    """
    service = DeliverableService(db)
    deliverables = await service.get_by_project(project_id)
    return ApiResponse(data=PaginatedResponse(items=deliverables, total=len(deliverables), skip=0, limit=100))


# 交付物CRUD端点
@router.post("/deliverables", response_model=ApiResponse[DeliverableResponse], status_code=201)
async def create_deliverable(
    data: DeliverableCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建交付物

    创建新交付物。
    """
    service = DeliverableService(db)
    deliverable = await service.create_deliverable(data.model_dump())
    return ApiResponse(data=deliverable)


@router.get("/deliverables/{deliverable_id}", response_model=ApiResponse[DeliverableResponse])
async def get_deliverable(
    deliverable_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取交付物详情

    返回交付物的详细信息，包含版本历史。
    """
    service = DeliverableService(db)
    deliverable = await service.get_detail(deliverable_id)
    if not deliverable:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    return ApiResponse(data=deliverable)


@router.put("/deliverables/{deliverable_id}", response_model=ApiResponse[DeliverableResponse])
async def update_deliverable(
    deliverable_id: str,
    data: DeliverableUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新交付物

    更新交付物基本信息。
    """
    service = DeliverableService(db)
    deliverable = await service.update(deliverable_id, data.model_dump(exclude_unset=True))
    if not deliverable:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    return ApiResponse(data=deliverable)


@router.patch("/deliverables/{deliverable_id}/content", response_model=ApiResponse[DeliverableResponse])
async def update_deliverable_content(
    deliverable_id: str,
    data: DeliverableUpdateContent,
    db: AsyncSession = Depends(get_db),
):
    """
    更新交付物内容

    更新交付物内容并创建新版本。
    """
    service = DeliverableService(db)
    deliverable = await service.update_content(
        deliverable_id,
        data.content,
        data.change_summary,
        data.created_by,
    )
    if not deliverable:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    return ApiResponse(data=deliverable)


@router.delete("/deliverables/{deliverable_id}", response_model=ApiResponse[StatusResponse])
async def delete_deliverable(
    deliverable_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除交付物

    删除指定交付物（软删除）。
    """
    service = DeliverableService(db)
    success = await service.delete_deliverable(deliverable_id)
    if not success:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    return ApiResponse(data=StatusResponse(success=True, message="Deliverable deleted"))


# 版本端点
@router.get("/deliverables/{deliverable_id}/versions", response_model=ApiResponse[PaginatedResponse[DeliverableVersionResponse]])
async def list_versions(
    deliverable_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取交付物的版本列表

    返回交付物的所有历史版本。
    """
    service = DeliverableService(db)
    versions = await service.get_versions(deliverable_id)
    return ApiResponse(data=PaginatedResponse(items=versions, total=len(versions), skip=0, limit=100))


@router.get("/deliverables/{deliverable_id}/versions/{version}", response_model=ApiResponse[DeliverableVersionResponse])
async def get_version(
    deliverable_id: str,
    version: int,
    db: AsyncSession = Depends(get_db),
):
    """
    获取特定版本

    返回交付物的指定版本。
    """
    service = DeliverableService(db)
    ver = await service.get_version(deliverable_id, version)
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    return ApiResponse(data=ver)


@router.get("/deliverables/{deliverable_id}/diff", response_model=ApiResponse[DeliverableDiff])
async def get_diff(
    deliverable_id: str,
    version_a: int = Query(..., description="版本A"),
    version_b: int = Query(..., description="版本B"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取版本差异

    比较两个版本的差异。
    """
    service = DeliverableService(db)

    # 获取两个版本
    ver_a = await service.get_version(deliverable_id, version_a)
    ver_b = await service.get_version(deliverable_id, version_b)

    if not ver_a or not ver_b:
        raise HTTPException(status_code=404, detail="Version not found")

    # 简单的行级差异比较
    lines_a = ver_a.content.splitlines(keepends=True)
    lines_b = ver_b.content.splitlines(keepends=True)

    items = []
    max_len = max(len(lines_a), len(lines_b))

    for i in range(max_len):
        line_a = lines_a[i] if i < len(lines_a) else ""
        line_b = lines_b[i] if i < len(lines_b) else ""

        if line_a == line_b:
            items.append(DeliverableDiffItem(
                type="unchanged",
                content=line_a.rstrip("\n"),
                line_number=i + 1,
            ))
        else:
            if line_a:
                items.append(DeliverableDiffItem(
                    type="remove",
                    content=line_a.rstrip("\n"),
                    line_number=i + 1,
                ))
            if line_b:
                items.append(DeliverableDiffItem(
                    type="add",
                    content=line_b.rstrip("\n"),
                    line_number=i + 1,
                ))

    return ApiResponse(data=DeliverableDiff(
        version_a=version_a,
        version_b=version_b,
        items=items,
    ))
