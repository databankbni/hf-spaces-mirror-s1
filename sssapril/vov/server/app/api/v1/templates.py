"""
项目模板 API 路由模块

提供项目模板的列表、详情、应用端点。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse
from app.services.template_service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])


# ── 请求体 ──


class ApplyTemplateRequest(BaseModel):
    template_id: str = Field(..., description="模板 ID")
    project_name: str = Field(..., min_length=1, max_length=255, description="项目名称")
    project_description: Optional[str] = Field(None, description="项目描述（覆盖模板默认）")
    cover_color: Optional[str] = Field(None, description="封面颜色（覆盖模板默认）")
    project_tags: Optional[List[str]] = Field(None, description="项目标签（覆盖模板默认）")


# ── 端点 ──


@router.get("", response_model=ApiResponse[List[Dict[str, Any]]])
async def list_templates(db: AsyncSession = Depends(get_db)):
    """列出所有可用项目模板（仅元信息与预览统计）"""
    service = TemplateService(db)
    templates = await service.list_templates()
    return ApiResponse(data=[t.to_dict() for t in templates])


@router.get("/{template_id}", response_model=ApiResponse[Dict[str, Any]])
async def get_template(template_id: str, db: AsyncSession = Depends(get_db)):
    """获取模板详情（含 skills/agents/groups/resources 完整内容）"""
    service = TemplateService(db)
    template = await service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"模板 '{template_id}' 不存在")
    return ApiResponse(data=template.to_dict())


@router.post("/apply", response_model=ApiResponse[Dict[str, Any]])
async def apply_template(
    payload: ApplyTemplateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    应用模板创建项目。

    会一次性创建：项目、Skills（按名称去重）、Agents（按名称去重）、
    ProjectAgent 关联、Groups（带 GroupMember）、Tasks（带 TaskAssignee）、
    项目级 Resources。整个流程在单事务中完成，失败回滚。
    """
    service = TemplateService(db)
    try:
        result = await service.apply_template(
            template_id=payload.template_id,
            project_name=payload.project_name,
            project_description=payload.project_description,
            cover_color=payload.cover_color,
            project_tags=payload.project_tags,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(data=result.to_dict())
