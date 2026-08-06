"""
API v1模块

定义v1版本的API路由。
"""

from fastapi import APIRouter

from .projects import router as projects_router
from .agents import router as agents_router
from .groups import router as groups_router
from .tasks import router as tasks_router
from .chains import router as chains_router
from .deliverables import router as deliverables_router
from .resources import router as resources_router
from .tags import router as tags_router
from .memories import router as memories_router
from .skills import router as skills_router
from .websocket import router as websocket_router
from .export_import import router as export_import_router
from .unified_export_import import router as unified_export_import_router
from .tools import router as tools_router
from .settings import router as settings_router
from .templates import router as templates_router
from .guide import router as guide_router
from .subscriptions import router as subscriptions_router

router = APIRouter()

# 注册子路由
router.include_router(projects_router)
router.include_router(agents_router)
router.include_router(skills_router)
router.include_router(groups_router)
router.include_router(tasks_router)
router.include_router(chains_router)
router.include_router(deliverables_router)
router.include_router(resources_router)
router.include_router(tags_router)
router.include_router(memories_router)
router.include_router(websocket_router)
router.include_router(export_import_router)
router.include_router(unified_export_import_router)
router.include_router(tools_router)
router.include_router(settings_router)
router.include_router(templates_router)
router.include_router(guide_router)
router.include_router(subscriptions_router)
