"""
记忆API路由模块

提供Agent记忆相关的REST API端点。
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.agent_service import MemoryService
from app.schemas.memory import (
    MemoryUpsert,
    MemoryResponse,
)
from app.schemas.common import ApiResponse, PaginatedResponse

router = APIRouter(tags=["memories"])


# 项目记忆端点
@router.get("/projects/{project_id}/memories", response_model=ApiResponse[PaginatedResponse[MemoryResponse]])
async def list_memories(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的Agent记忆列表

    返回项目中所有Agent的所有 slug 笔记。
    """
    service = MemoryService(db)
    memories = await service.get_by_project(project_id)
    return ApiResponse(data=PaginatedResponse(items=memories, total=len(memories), skip=0, limit=100))


# Agent 记忆列表（按 slug）
@router.get("/agents/{agent_id}/projects/{project_id}/memories", response_model=ApiResponse[list[MemoryResponse]])
async def list_agent_memories(
    agent_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出 Agent 在项目下的所有笔记（按 slug 分类）"""
    service = MemoryService(db)
    memories = await service.list_by_agent_and_project(agent_id, project_id)
    return ApiResponse(data=memories)


# Agent 记忆单条（按 slug）
@router.get("/agents/{agent_id}/projects/{project_id}/memory", response_model=ApiResponse[MemoryResponse])
async def get_memory(
    agent_id: str,
    project_id: str,
    slug: str = Query(default="default", description="分类标识"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取Agent在项目中的特定 slug 笔记
    """
    service = MemoryService(db)
    memory = await service.get_by_agent_and_project(agent_id, project_id, slug)
    if not memory:
        raise HTTPException(status_code=404, detail=f"Memory not found for slug='{slug}'")
    return ApiResponse(data=memory)


@router.put("/agents/{agent_id}/projects/{project_id}/memory", response_model=ApiResponse[MemoryResponse])
async def upsert_memory(
    agent_id: str,
    project_id: str,
    data: MemoryUpsert,
    db: AsyncSession = Depends(get_db),
):
    """
    创建或更新Agent笔记（按 slug 分类）

    如果 (agent_id, project_id, slug) 的笔记不存在则创建，存在则更新。
    """
    service = MemoryService(db)
    memory = await service.upsert(
        agent_id,
        project_id,
        data.content,
        data.tags,
        data.slug,
    )
    return ApiResponse(data=memory)
