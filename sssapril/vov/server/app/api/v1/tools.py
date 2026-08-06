"""
工具目录 API

从 agentflow 的 tool_catalog 模块动态获取工具目录数据，
前端工具库页面从此 API 加载，保持单一数据源。
"""

from fastapi import APIRouter

from agentflow.tool_catalog import get_tool_catalog, get_category_labels

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/catalog")
async def list_tool_catalog():
    """获取所有内置工具的目录信息"""
    return {
        "success": True,
        "data": {
            "tools": get_tool_catalog(),
            "categories": get_category_labels(),
        },
    }
