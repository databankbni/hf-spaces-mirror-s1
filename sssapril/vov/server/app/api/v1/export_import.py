"""
导出导入API模块

提供项目导出导入的REST API端点。
"""

import io

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.export_service import ExportService
from app.services.import_service import ImportService
from app.schemas.common import ApiResponse

router = APIRouter(tags=["export-import"])


@router.get("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    导出项目

    将项目导出为ZIP文件下载。

    Args:
        project_id: 项目ID

    Returns:
        StreamingResponse: ZIP文件流
    """
    service = ExportService(db)

    try:
        zip_bytes = await service.export_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 返回文件流
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=project_{project_id}.zip"
        },
    )


@router.post("/projects/{project_id}/export/preview", response_model=ApiResponse[dict])
async def preview_project_export(
    project_id: str,
    selection: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
):
    """预览项目资产包导出内容。"""
    service = ExportService(db)

    try:
        preview = await service.preview_project(project_id, selection)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ApiResponse(data=preview)


@router.post("/projects/{project_id}/export/bundle")
async def export_project_bundle(
    project_id: str,
    selection: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
):
    """按选择配置导出项目资产包。"""
    service = ExportService(db)

    try:
        zip_bytes = await service.export_project_bundle(project_id, selection)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=project_bundle_{project_id}.zip"
        },
    )


@router.post("/projects/import", response_model=ApiResponse[dict])
async def import_project(
    file: UploadFile = File(...),
    name_suffix: str = " (imported)",
    db: AsyncSession = Depends(get_db),
):
    """
    导入项目

    从ZIP文件导入项目。

    Args:
        file: ZIP文件
        name_suffix: 项目名称后缀

    Returns:
        ApiResponse: 导入结果
    """
    # 验证文件类型
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP file")

    # 读取文件内容
    content = await file.read()

    service = ImportService(db)

    try:
        project = await service.import_project(content, name_suffix)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApiResponse(
        data={
            "id": project.id,
            "name": project.name,
            "message": "Project imported successfully",
        }
    )
