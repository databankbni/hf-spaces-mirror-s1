"""
FastAPI应用入口

配置和启动FastAPI应用，包括中间件、路由、事件处理等。
"""

import sys

# Windows 环境下确保 stdout/stderr 使用 UTF-8 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.database import init_db, close_db


def _get_static_dir() -> Path:
    """获取前端静态文件目录"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包模式：数据文件在 _internal/ 下
        exe_dir = Path(sys.executable).parent
        # PyInstaller onefile 模式用 sys._MEIPASS，onedir 模式用 _internal
        internal = exe_dir / "_internal"
        if internal.exists():
            return internal / "static"
        return Path(getattr(sys, '_MEIPASS', exe_dir)) / "static"
    else:
        # 开发模式：client/dist/
        return Path(__file__).resolve().parent.parent.parent / "client" / "dist"

# 配置日志：确保 app 和 agentflow 模块的 INFO 日志能输出
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
    ],
)
# 降低第三方库日志级别
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用生命周期管理

    在应用启动时初始化数据库，关闭时释放资源。

    Args:
        app: FastAPI应用实例

    Yields:
        None
    """
    # 启动时
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # 保存主事件循环引用，供 agentflow 子线程中的 run_async 使用
    import asyncio
    from agentflow.async_bridge import set_main_loop
    set_main_loop(asyncio.get_running_loop())

    # 自动建表
    await init_db()
    logger.info("Database initialized: sqlite")

    # 首次运行初始化
    from app.core.startup import init_llm_config, init_default_skills, init_default_agents
    from app.core.database import async_session_factory
    await init_default_skills(async_session_factory)  # 默认 Skills
    print("====== INIT_SKILLS DONE ======", flush=True)
    await init_default_agents(async_session_factory)   # 默认 Agents
    print("====== INIT_AGENTS DONE ======", flush=True)
    await init_llm_config(async_session_factory)       # LLM 配置
    print("====== INIT_LLM_CONFIG DONE ======", flush=True)

    # v2 P2: 注册 EventDispatcher（事件 → [系统通知] → 新 session）
    # 纯基础设施接入，不跑业务流程。
    # 谁订阅 / 订阅什么 / 收到后做什么 = agent 自己决定。
    from app.orchestrator.event_dispatcher import EventDispatcher
    from app.orchestrator.agent_executor import AgentExecutor
    from app.orchestrator.session_lifecycle import SessionLifecycleGate, set_session_gate
    # 共享 session gate: 让 chat API / EventDispatcher / MessageDispatcher 各自创建的
    # AgentExecutor 都走同一个 gate, 实现同 (agent_id, group_id) 串行化 + 群级串行锁.
    # 注册为模块级单例, 使 ChatService 等未显式传 gate 的 executor 也能共享.
    shared_gate = SessionLifecycleGate()
    set_session_gate(shared_gate)
    executor = AgentExecutor(async_session_factory, session_gate=shared_gate)

    # 订阅机制 v1: 创建 SubscriptionTrigger + SubscriberDispatcher
    # - chat_service 用于把消息注入到群/agent（复用现有 send_message_stream）
    # - subscription_trigger 注入到 EventDispatcher，与 event_bus 内存订阅并存
    from app.services.chat_service import ChatService
    from app.services.subscriber_dispatcher import SubscriberDispatcher
    from app.services.subscription_trigger import SubscriptionTrigger
    from app.orchestrator.websocket_manager import ws_manager as websocket_manager
    _chat_service = ChatService(async_session_factory)
    _subscriber_dispatcher = SubscriberDispatcher(chat_service=_chat_service)
    _subscription_trigger = SubscriptionTrigger(
        session_factory=async_session_factory,
        dispatcher=_subscriber_dispatcher,
        ws_broadcast=websocket_manager.broadcast,
    )

    app.state.event_dispatcher = EventDispatcher(
        agent_executor=executor,
        session_factory=async_session_factory,
        session_gate=shared_gate,
        subscription_trigger=_subscription_trigger,
    )
    app.state.event_dispatcher.register()
    # P0 修复: 启动空闲 watchdog, 防止 lead 静默停摆 (e.g. 灵感孵化群 3h+ 无活动)
    app.state.event_dispatcher.start_idle_watchdog()
    logger.info("[EventDispatcher] registered on event_bus")
    print("====== LIFESPAN READY ======", flush=True)

    yield

    # 关闭时
    logger.info("Shutting down %s", settings.APP_NAME)
    if hasattr(app.state, "event_dispatcher") and app.state.event_dispatcher is not None:
        app.state.event_dispatcher.unregister()
        logger.info("[EventDispatcher] unregistered")
    set_main_loop(None)
    await close_db()


def create_app() -> FastAPI:
    """
    创建FastAPI应用实例

    配置应用的所有组件：
    - 中间件（CORS等）
    - 路由
    - 异常处理
    - 生命周期事件

    Returns:
        FastAPI: 配置好的应用实例
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="多Agent群聊协作创作平台",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 配置CORS（桌面打包模式下同源，不需要CORS）
    if not getattr(sys, 'frozen', False):
        cors_origins = settings.get_cors_origins()
        # "*" 与 allow_credentials=True 不兼容，需特殊处理
        allow_all = cors_origins == ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"] if allow_all else cors_origins,
            allow_credentials=not allow_all,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 注册路由
    register_routes(app)

    # 注册异常处理
    register_exception_handlers(app)

    return app


def register_routes(app: FastAPI) -> None:
    """
    注册API路由

    将各模块的路由注册到应用中。

    Args:
        app: FastAPI应用实例
    """
    # 健康检查
    @app.get("/health")
    async def health_check():
        try:
            from app.core.database import async_session_factory
            from sqlalchemy import text
            async with async_session_factory() as db:
                await db.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "connected"}
        except Exception as e:
            return {"status": "unhealthy", "database": "error", "detail": str(e)}

    # 注册v1 API路由
    from app.api import v1_router
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    # 静态文件服务（前端 build 产物）
    # 必须在所有 API 路由之后注册，避免拦截 API 请求
    static_dir = _get_static_dir()
    if static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            from fastapi.staticfiles import StaticFiles
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """SPA catch-all：静态文件返回文件，其他返回 index.html"""
            file_path = static_dir / full_path
            if full_path and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(static_dir / "index.html"))
    else:
        logger.info("Static dir not found: %s (frontend not built)", static_dir)


def register_exception_handlers(app: FastAPI) -> None:
    """
    注册全局异常处理

    统一处理应用中的异常，返回标准格式的错误响应。
    所有异常响应都包含CORS头，避免浏览器报CORS错误。

    Args:
        app: FastAPI应用实例
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from fastapi.exceptions import RequestValidationError

    def cors_json_response(request: Request, status_code: int, content: dict) -> JSONResponse:
        """返回带CORS头的JSON响应"""
        origin = request.headers.get("origin", "*")
        response = JSONResponse(status_code=status_code, content=content)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局异常处理器 - 捕获所有未处理的异常"""
        return cors_json_response(request, 500, {
            "code": 500,
            "message": "Internal server error",
            "detail": str(exc) if settings.DEBUG else None,
        })

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP异常处理器"""
        return cors_json_response(request, exc.status_code, {
            "code": exc.status_code,
            "message": exc.detail,
            "detail": None,
        })

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """请求验证异常处理器"""
        return cors_json_response(request, 422, {
            "code": 422,
            "message": "Validation error",
            "detail": str(exc.errors()),
        })

    # OPTIONS预检请求处理
    @app.options("/{path:path}")
    async def options_handler(request: Request, path: str):
        """处理CORS预检请求"""
        origin = request.headers.get("origin", "*")
        response = JSONResponse(content={"message": "OK"})
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Max-Age"] = "3600"
        return response


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn

    # 端口由部署平台通过环境变量注入（HF=7860, Render=10000, 本地默认 8002）
    # uvicorn 直接读 PORT env var（通过 Dockerfile CMD 显式传 --port）
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8002,  # 实际值由部署启动命令覆盖
        reload=settings.DEBUG,
    )
