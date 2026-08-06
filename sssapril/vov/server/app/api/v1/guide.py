"""
引导API路由模块

提供引导 project 的初始化和查询接口。

前端在用户进入首页时调 POST /api/v1/guide/ensure 幂等初始化引导 agent,
然后拿 group_id 接入 useChatStream 进行对话。

L1: 进入项目页时调 POST /api/v1/guide/ensure_project?project_id=xxx
确保项目有 coordinator + 项目引导群, 拿 group_id 接入 useChatStream。
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.guide_service import GuideService
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/guide", tags=["guide"])


class GuideStateResponse(BaseModel):
    """引导状态响应"""
    project_id: str = Field(..., description="引导 project ID")
    agent_id: str = Field(..., description="引导 agent ID (全局)")
    project_agent_id: str = Field(..., description="引导 ProjectAgent ID")
    group_id: str = Field(..., description="引导 group ID (对话容器, 接 useChatStream)")
    agent_name: str = Field(..., description="引导 agent 名称")
    agent_avatar: Optional[str] = Field(None, description="引导 agent 头像")
    group_name: str = Field(..., description="引导 group 名称")


@router.post("/ensure", response_model=ApiResponse[GuideStateResponse])
async def ensure_guide(
    db: AsyncSession = Depends(get_db),
):
    """
    L0: 幂等初始化引导 project。

    首次调用: 创建引导 project + agent + group
    后续调用: 返回现有引导状态 (不重复创建, 但会补建缺失的 agent/group)

    前端在用户进入首页时调用此接口, 确保引导 agent 就绪。
    返回的 group_id 用于接入 useChatStream 进行对话。
    """
    service = GuideService(db)
    state = await service.ensure_guide_state()
    return ApiResponse(data=state)


@router.get("/state", response_model=ApiResponse[GuideStateResponse])
async def get_guide_state(
    db: AsyncSession = Depends(get_db),
):
    """
    L0: 查询引导状态 (只查不建)。

    返回 data=None 表示未初始化, 前端可调 POST /guide/ensure 初始化。
    """
    service = GuideService(db)
    state = await service.get_guide_state()
    return ApiResponse(data=state)


@router.post("/ensure_project", response_model=ApiResponse[GuideStateResponse])
async def ensure_project_guide(
    project_id: str = Query(..., description="项目 ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    L1: 幂等确保项目有 coordinator + 项目引导群。

    逻辑:
    - 查项目的 coordinator ProjectAgent (项目总控·编舟), 没有则补建
    - 查 coordinator 所在的群聊, 没有则建「项目引导群」+ 加 coordinator 为 lead
    - 返回 group_id 用于接入 useChatStream

    前端在用户进入项目页 (/project/:id) 时调用此接口。
    """
    service = GuideService(db)
    try:
        state = await service.ensure_project_guide_state(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data=state)
