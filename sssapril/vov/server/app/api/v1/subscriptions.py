"""
订阅 API 路由

提供订阅 CRUD 端点。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse, ErrorResponse
from app.schemas.subscription import (
    SubscriptionCreate,
    SubscriptionUpdate,
    SubscriptionResponse,
    SubscriptionListResponse,
)
from app.services.subscription_service import SubscriptionService

router = APIRouter(tags=["subscriptions"])


@router.post(
    "/projects/{project_id}/subscriptions",
    response_model=ApiResponse[SubscriptionResponse],
    responses={400: {"model": ErrorResponse}},
)
async def create_subscription(
    project_id: str,
    body: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建订阅"""
    service = SubscriptionService(db)
    result = await service.create_subscription(
        project_id=project_id,
        config=body.model_dump(),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "unknown"))
    return ApiResponse(data=SubscriptionResponse(**result["data"]))


@router.get(
    "/projects/{project_id}/subscriptions",
    response_model=ApiResponse[SubscriptionListResponse],
)
async def list_subscriptions(
    project_id: str,
    subscriber_type: Optional[str] = Query(None),
    subscriber_id: Optional[str] = Query(None),
    enabled_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """列出项目下的订阅"""
    service = SubscriptionService(db)
    result = await service.list_subscriptions(
        project_id=project_id,
        subscriber_type=subscriber_type,
        subscriber_id=subscriber_id,
        enabled_only=enabled_only,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    items = [SubscriptionResponse(**d) for d in result["data"]]
    return ApiResponse(data=SubscriptionListResponse(
        items=items, total=len(items),
    ))


@router.get(
    "/subscriptions/{sub_id}",
    response_model=ApiResponse[SubscriptionResponse],
)
async def get_subscription(
    sub_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取单个订阅"""
    service = SubscriptionService(db)
    result = await service.get_subscription(sub_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return ApiResponse(data=SubscriptionResponse(**result["data"]))


@router.patch(
    "/subscriptions/{sub_id}",
    response_model=ApiResponse[SubscriptionResponse],
)
async def update_subscription(
    sub_id: str,
    body: SubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新订阅"""
    service = SubscriptionService(db)
    result = await service.update_subscription(
        sub_id, body.model_dump(exclude_unset=True),
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return ApiResponse(data=SubscriptionResponse(**result["data"]))


@router.delete(
    "/subscriptions/{sub_id}",
    response_model=ApiResponse,
)
async def delete_subscription(
    sub_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除订阅（软删除）"""
    service = SubscriptionService(db)
    result = await service.delete_subscription(sub_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return ApiResponse(message="deleted")
