"""
统一导出导入 API

提供资源的统一导出/导入接口，支持：
- 列出可导出资源（skills/agents/projects）
- 选择性导出为 ZIP
- 上传 ZIP 预览（含冲突检测）
- 按冲突解决方案导入
"""

import io

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.unified_export import UnifiedExportService
from app.services.unified_import import UnifiedImportService
from app.schemas.common import ApiResponse

router = APIRouter(tags=["unified-export-import"])


# ── 导出相关 ──


@router.get("/export/skills", response_model=ApiResponse[list])
async def list_exportable_skills(db: AsyncSession = Depends(get_db)):
    """列出所有可导出的 skill"""
    service = UnifiedExportService(db)
    skills = await service.list_skills()
    return ApiResponse(data=skills)


@router.get("/export/agents", response_model=ApiResponse[list])
async def list_exportable_agents(db: AsyncSession = Depends(get_db)):
    """列出所有可导出的 agent"""
    service = UnifiedExportService(db)
    agents = await service.list_agents()
    return ApiResponse(data=agents)


@router.get("/export/projects", response_model=ApiResponse[list])
async def list_exportable_projects(db: AsyncSession = Depends(get_db)):
    """列出所有可导出的项目"""
    service = UnifiedExportService(db)
    projects = await service.list_projects()
    return ApiResponse(data=projects)


@router.post("/export/download")
async def export_download(
    items: list = Body(..., description="导出项列表 [{type, id}, ...]"),
    db: AsyncSession = Depends(get_db),
):
    """导出选中资源为 ZIP 下载"""
    service = UnifiedExportService(db)

    try:
        zip_bytes = await service.export(items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=vov_export.zip"
        },
    )


# ── 导入相关 ──


@router.post("/import/preview", response_model=ApiResponse[dict])
async def import_preview(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 ZIP 预览导入内容（含冲突检测）"""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP file")

    content = await file.read()
    service = UnifiedImportService(db)

    try:
        preview = service.preview(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=preview.to_dict())


@router.post("/import/execute", response_model=ApiResponse[dict])
async def import_execute(
    file: UploadFile = File(...),
    resolutions: str = Body(default="[]", description="JSON 格式的冲突解决方案"),
    db: AsyncSession = Depends(get_db),
):
    """执行导入（带冲突解决方案）"""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP file")

    import json
    try:
        resolutions_list = json.loads(resolutions)
    except json.JSONDecodeError:
        resolutions_list = []

    content = await file.read()
    service = UnifiedImportService(db)

    try:
        result = await service.execute(content, resolutions_list)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(data=result.to_dict())
