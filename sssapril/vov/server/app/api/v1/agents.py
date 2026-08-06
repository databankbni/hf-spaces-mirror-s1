"""
Agent API路由模块

提供Agent相关的REST API端点。
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.agent_service import AgentService, ProjectAgentService
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentDetailResponse,
    ProjectAgentCreate,
    ProjectAgentResponse,
)
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse

router = APIRouter(tags=["agents"])


# 全局Agent端点
@router.get("/agents", response_model=ApiResponse[PaginatedResponse[AgentResponse]])
async def list_agents(
    active_only: bool = Query(False, description="仅返回启用的Agent"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取Agent列表

    返回所有全局Agent。
    """
    service = AgentService(db)
    if active_only:
        agents = await service.get_all_active()
    else:
        agents = await service.get_all()
    return ApiResponse(data=PaginatedResponse(items=agents, total=len(agents), skip=0, limit=100))


@router.post("/agents", response_model=ApiResponse[AgentResponse], status_code=201)
async def create_agent(
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建Agent

    创建新Agent，可包含工具和技能。
    """
    service = AgentService(db)
    agent = await service.create_agent(data.model_dump())
    return ApiResponse(data=agent)


@router.get("/agents/{agent_id}", response_model=ApiResponse[AgentDetailResponse])
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取Agent详情

    返回Agent的详细信息，包含工具和技能。
    """
    service = AgentService(db)
    agent = await service.get_detail(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return ApiResponse(data=agent)


@router.put("/agents/{agent_id}", response_model=ApiResponse[AgentResponse])
async def update_agent(
    agent_id: str,
    data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新Agent

    更新Agent信息，可更新工具和技能。
    """
    service = AgentService(db)
    agent = await service.update_agent(agent_id, data.model_dump(exclude_unset=True))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return ApiResponse(data=agent)


@router.delete("/agents/{agent_id}", response_model=ApiResponse[StatusResponse])
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除Agent

    删除指定Agent（软删除）。
    """
    service = AgentService(db)
    success = await service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return ApiResponse(data=StatusResponse(success=True, message="Agent deleted"))


# 项目Agent端点
@router.get("/projects/{project_id}/agents", response_model=ApiResponse[PaginatedResponse[ProjectAgentResponse]])
async def list_project_agents(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的Agent列表

    返回项目中所有Agent。
    """
    service = ProjectAgentService(db)
    agents = await service.get_by_project(project_id)
    return ApiResponse(data=PaginatedResponse(items=agents, total=len(agents), skip=0, limit=100))


@router.post("/projects/{project_id}/agents", response_model=ApiResponse[ProjectAgentResponse], status_code=201)
async def add_agent_to_project(
    project_id: str,
    data: ProjectAgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    添加Agent到项目

    将全局Agent添加到项目中。
    """
    service = ProjectAgentService(db)
    project_agent = await service.add_to_project(
        project_id,
        data.agent_id,
        data.override_config,
    )
    return ApiResponse(data=project_agent)


@router.delete("/projects/{project_id}/agents/{agent_id}", response_model=ApiResponse[StatusResponse])
async def remove_agent_from_project(
    project_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    从项目移除Agent

    从项目中移除指定Agent。
    """
    service = ProjectAgentService(db)
    success = await service.remove_from_project(project_id, agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project agent not found")
    return ApiResponse(data=StatusResponse(success=True, message="Agent removed from project"))
