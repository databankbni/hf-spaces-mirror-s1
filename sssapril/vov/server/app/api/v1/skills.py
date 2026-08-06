"""
技能 API 路由模块

提供独立技能的 CRUD 端点。
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.agent_service import SkillService
from app.schemas.agent import SkillCreate, SkillUpdate, SkillResponse
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse

router = APIRouter(tags=["skills"])


@router.get("/skills", response_model=ApiResponse[PaginatedResponse[SkillResponse]])
async def list_skills(
    db: AsyncSession = Depends(get_db),
):
    """获取所有技能列表"""
    service = SkillService(db)
    skills = await service.get_all_active()
    return ApiResponse(data=PaginatedResponse(items=skills, total=len(skills), skip=0, limit=100))


@router.post("/skills", response_model=ApiResponse[SkillResponse], status_code=201)
async def create_skill(
    data: SkillCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建新技能"""
    service = SkillService(db)
    skill = await service.create(data.model_dump())
    return ApiResponse(data=skill)


@router.get("/skills/{skill_id}", response_model=ApiResponse[SkillResponse])
async def get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取技能详情"""
    service = SkillService(db)
    skill = await service.get_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return ApiResponse(data=skill)


@router.put("/skills/{skill_id}", response_model=ApiResponse[SkillResponse])
async def update_skill(
    skill_id: str,
    data: SkillUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新技能"""
    service = SkillService(db)
    skill = await service.update(skill_id, data.model_dump(exclude_unset=True))
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return ApiResponse(data=skill)


@router.delete("/skills/{skill_id}", response_model=ApiResponse[StatusResponse])
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除技能"""
    service = SkillService(db)
    success = await service.delete(skill_id)
    if not success:
        raise HTTPException(status_code=404, detail="Skill not found")
    return ApiResponse(data=StatusResponse(success=True, message="Skill deleted"))
