"""
系统设置 API

提供 LLM 配置的读写、测试连接、系统状态查询。
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# ── 配置缓存 ─────────────────────────────────────────────────

_CONFIG_CACHE_TTL = 60  # 秒
_config_cache: dict[str, tuple[Optional[str], float]] = {}


def _invalidate_config_cache(key: Optional[str] = None) -> None:
    """清除配置缓存。key=None 清除全部。"""
    if key:
        _config_cache.pop(key, None)
    else:
        _config_cache.clear()


# ── 辅助函数 ──────────────────────────────────────────────────


async def get_config(session: AsyncSession, key: str) -> Optional[str]:
    """从数据库读取配置值（带 60s 内存缓存）"""
    now = time.time()
    if key in _config_cache:
        value, ts = _config_cache[key]
        if now - ts < _CONFIG_CACHE_TTL:
            return value

    result = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == key)
    )
    row = result.scalar_one_or_none()
    _config_cache[key] = (row, now)
    return row


async def set_config(session: AsyncSession, key: str, value: str) -> None:
    """写入或更新配置值"""
    result = await session.execute(
        select(SystemConfig).where(SystemConfig.key == key)
    )
    config = result.scalar_one_or_none()
    if config:
        config.value = value
    else:
        config = SystemConfig(key=key, value=value)
        session.add(config)
    await session.flush()
    _invalidate_config_cache(key)


def mask_api_key(key: Optional[str]) -> str:
    """脱敏显示 API Key"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:6]}...{key[-4:]}"


def classify_llm_error(exc: Exception) -> str:
    """将 LLM 异常转为中文提示"""
    err_str = str(exc).lower()
    err_type = type(exc).__name__

    if "401" in err_str or "unauthorized" in err_str or "invalid api key" in err_str:
        return "API Key 无效或已过期，请检查并更新"
    if "403" in err_str or "forbidden" in err_str:
        return "API 访问被拒绝，请检查 API Key 权限"
    if "429" in err_str or "rate limit" in err_str:
        return "请求频率超限，请稍后重试"
    if "500" in err_str or "502" in err_str or "503" in err_str:
        return "LLM 服务暂时不可用，请稍后重试"
    if "timeout" in err_str or "timed out" in err_str:
        return "连接超时，请检查网络或 Base URL"
    if "connection" in err_str or "connect" in err_str:
        return "无法连接到 LLM 服务，请检查网络和 Base URL 配置"
    if "not found" in err_str or "404" in err_str:
        return "模型不存在，请检查模型名称"
    if "authentication" in err_str or err_type == "AuthenticationError":
        return "API Key 无效，请在设置中检查并更新"

    return f"连接失败: {str(exc)[:200]}"


# ── 请求/响应模型 ─────────────────────────────────────────────


class LLMSettingsResponse(BaseModel):
    api_key_masked: str
    api_key_set: bool
    base_url: Optional[str] = None
    default_model: Optional[str] = None


class LLMSettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None


class LLMTestRequest(BaseModel):
    api_key: str
    base_url: Optional[str] = None


class LLMTestResponse(BaseModel):
    success: bool
    message: str
    models: list[str] = []


class SystemStatusResponse(BaseModel):
    llm_configured: bool
    db_driver: str
    app_version: str


# ── 端点 ──────────────────────────────────────────────────────


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(session: AsyncSession = Depends(get_db_session)):
    """系统状态（首次引导用）"""
    api_key = await get_config(session, "llm.api_key")
    if not api_key:
        api_key = settings.get_llm_api_key()

    return SystemStatusResponse(
        llm_configured=bool(api_key),
        db_driver="sqlite",
        app_version=settings.APP_VERSION,
    )


@router.get("/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(session: AsyncSession = Depends(get_db_session)):
    """获取 LLM 配置（API Key 脱敏返回）"""
    # 优先读 DB，fallback 到环境变量
    api_key = await get_config(session, "llm.api_key") or settings.get_llm_api_key()
    base_url = await get_config(session, "llm.base_url") or settings.get_llm_api_base()
    model = await get_config(session, "llm.default_model") or settings.DEFAULT_LLM_MODEL

    return LLMSettingsResponse(
        api_key_masked=mask_api_key(api_key),
        api_key_set=bool(api_key),
        base_url=base_url,
        default_model=model,
    )


@router.put("/llm")
async def update_llm_settings(
    body: LLMSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """更新 LLM 配置"""
    if body.api_key is not None:
        await set_config(session, "llm.api_key", body.api_key)
    if body.base_url is not None:
        await set_config(session, "llm.base_url", body.base_url)
    if body.default_model is not None:
        await set_config(session, "llm.default_model", body.default_model)

    return {"ok": True, "message": "配置已保存"}


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(body: LLMTestRequest):
    """测试 LLM 连通性"""
    try:
        from openai import AsyncOpenAI

        client_kwargs = {"api_key": body.api_key}
        if body.base_url:
            client_kwargs["base_url"] = body.base_url

        client = AsyncOpenAI(**client_kwargs)
        models_resp = await client.models.list()
        model_ids = sorted([m.id for m in models_resp.data[:30]])

        return LLMTestResponse(
            success=True,
            message=f"连接成功，发现 {len(models_resp.data)} 个模型",
            models=model_ids,
        )
    except Exception as e:
        logger.warning("LLM connection test failed: %s", e)
        return LLMTestResponse(
            success=False,
            message=classify_llm_error(e),
        )


@router.get("/llm/models")
async def list_llm_models(session: AsyncSession = Depends(get_db_session)):
    """获取可用模型列表"""
    api_key = await get_config(session, "llm.api_key") or settings.get_llm_api_key()
    base_url = await get_config(session, "llm.base_url") or settings.get_llm_api_base()

    if not api_key:
        return {"models": [], "message": "未配置 API Key"}

    try:
        from openai import AsyncOpenAI

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = AsyncOpenAI(**client_kwargs)
        models_resp = await client.models.list()
        model_ids = sorted([m.id for m in models_resp.data])

        return {"models": model_ids, "count": len(model_ids)}
    except Exception as e:
        logger.warning("Failed to list models: %s", e)
        return {"models": [], "message": classify_llm_error(e)}
