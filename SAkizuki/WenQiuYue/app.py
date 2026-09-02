"""
app.py
-------
合并入口：问秋月博客问答 + Prompt 炼金术打标签，共用一个 HF Space。

路由：
  GET  /                  → landing.html（导航页）
  GET  /blog              → index_blog.html（问秋月）
  GET  /prompt            → index_prompt.html（打标签）
  POST /blog/chat         → 问秋月 SSE 流
  GET  /blog/health       → 问秋月健康检查
  POST /prompt/chat       → 打标签 SSE 流
  POST /prompt/title      → 生成对话标题（下载用）
  GET  /prompt/health     → 打标签健康检查
  GET  /balance           → DeepSeek 余额查询（相对于 30 元的百分比）

BGE-M3 / ChromaDB 在第一次请求 /blog/chat 时延迟初始化，
避免只用打标签功能时加载 2GB 模型。

本地启动：
  uvicorn app:app --host 0.0.0.0 --port 7860 --reload
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import html
import json
import os
import sys
import time
import traceback
import yaml
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# ── 配置加载 ───────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    cfg_path = _ROOT / "pipeline_config.yaml"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _render_landing_page() -> str:
    """读取公告配置并渲染首页 HTML。"""
    config_path = _ROOT / "config" / "announcements.yaml"
    template_path = _ROOT / "landing.html"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            announcement = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"无法读取公告配置 {config_path}: {exc}") from exc

    if not isinstance(announcement, dict):
        raise RuntimeError(f"公告配置 {config_path} 的顶层必须是对象")

    title = announcement.get("title")
    icon = announcement.get("icon", "")
    items = announcement.get("items")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError(f"公告配置 {config_path} 中的 title 必须是非空字符串")
    if not isinstance(icon, str):
        raise RuntimeError(f"公告配置 {config_path} 中的 icon 必须是字符串")
    if not isinstance(items, list) or not items:
        raise RuntimeError(f"公告配置 {config_path} 中的 items 必须是非空列表")

    rendered_items = []
    for index, item in enumerate(items, start=1):
        item_html = item.get("html") if isinstance(item, dict) else None
        if not isinstance(item_html, str) or not item_html.strip():
            raise RuntimeError(
                f"公告配置 {config_path} 中第 {index} 条公告的 html 必须是非空字符串"
            )
        rendered_items.append(
            "      <div class=\"announce-item\">\n"
            "        <span class=\"announce-dot\"></span>\n"
            f"        <span>{item_html.strip()}</span>\n"
            "      </div>"
        )

    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"无法读取首页模板 {template_path}: {exc}") from exc

    placeholders = {
        "{{ANNOUNCEMENT_ICON}}": html.escape(icon.strip()),
        "{{ANNOUNCEMENT_TITLE}}": html.escape(title.strip()),
        "{{ANNOUNCEMENT_ITEMS}}": "\n".join(rendered_items),
        "{{DEEPSEEK_MODEL}}": html.escape(model.strip()),
    }
    for placeholder, value in placeholders.items():
        if placeholder not in template:
            raise RuntimeError(f"首页模板缺少公告占位符：{placeholder}")
        template = template.replace(placeholder, value)
    return template

cfg = _load_cfg()
deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
base_url     = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model        = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash-vision-exp")
tavily_key   = os.environ.get("TAVILY_API_KEY") or None

prompt_agent_debug = os.environ.get("PROMPT_AGENT_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

# ── 全局 Token 消耗计数器（持久化到 HF Bucket） ────────────────────
import threading

_TOKEN_BASELINE = 510_513_557  # 项目上线以来累计消耗的 token 数
_TOKEN_FILE = Path("/data/.token_count")  # HF Storage Bucket 挂载路径
_token_lock = threading.Lock()  # 保护 _total_tokens_used 的读-改-写

def _load_token_count() -> int:
    """从 HF Bucket 加载累计新增 token 数。"""
    print(f"[token] 检查挂载路径: {_TOKEN_FILE}  存在={_TOKEN_FILE.exists()}", file=sys.stderr, flush=True)
    print(f"[token] /data 目录内容: {list(Path('/data').iterdir()) if Path('/data').exists() else '不存在'}", file=sys.stderr, flush=True)
    try:
        if _TOKEN_FILE.exists():
            val = int(_TOKEN_FILE.read_text(encoding="utf-8").strip())
            print(f"[token] 从 Bucket 加载: {val}", file=sys.stderr, flush=True)
            return val
    except Exception as e:
        print(f"[token] 加载计数文件失败: {e}", file=sys.stderr, flush=True)
    return 0

def _save_token_count(count: int):
    """将累计新增 token 数写入 HF Bucket。"""
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(str(count), encoding="utf-8")
        print(f"[token] 已保存到 Bucket: {count}  (文件={_TOKEN_FILE})", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[token] 保存计数文件失败: {e}", file=sys.stderr, flush=True)

def _add_tokens(n: int):
    """线程安全地累加 token 并持久化。"""
    global _total_tokens_used
    with _token_lock:
        _total_tokens_used += n
        _save_token_count(_total_tokens_used)

_total_tokens_used = _load_token_count()
print(f"[token] 启动时累计 token: {_TOKEN_BASELINE + _total_tokens_used}  (基准={_TOKEN_BASELINE}, 新增={_total_tokens_used})", file=sys.stderr, flush=True)

if not deepseek_key:
    raise RuntimeError("DeepSeek API Key 未配置。请设置环境变量 DEEPSEEK_API_KEY。")

# ── 打标签 Agent（启动时初始化） ─────────────────────────────────────

from prompt_agent.agent import Agent as PromptAgent
from prompt_agent.tools import check_mcp_health

prompt_agent = PromptAgent(
    deepseek_api_key=deepseek_key,
    base_url=base_url,
    model=model,
    tavily_api_key=tavily_key,
    debug=prompt_agent_debug,
)

# ── 博客 Agent（启动时初始化，加载 BGE-M3 和 BM25 索引） ─────────────

from core.retriever import Retriever
from core.agent import Agent as BlogAgent

_retriever = Retriever(
    chroma_dir=_ROOT / cfg.get("chroma_dir", ".chroma"),
    model_path=cfg.get("model_path", "BAAI/bge-m3"),
    collection_name=cfg.get("collection_name", "akizuki_blog"),
    score_threshold=0.4,
    max_seq_length=cfg.get("embedding", {}).get("max_seq_length", 512),
)

blog_agent = BlogAgent(
    retriever=_retriever,
    deepseek_api_key=deepseek_key,
    base_url=base_url,
    model=model,
    tavily_api_key=tavily_key,
)


# ── FastAPI ────────────────────────────────────────────────────────────

app = FastAPI(title="秋月空间")


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    images: list[str] = []  # base64 图片列表（支持 data: 前缀或纯 base64）
    thinking: bool = False
    web_search: bool = True
    trace: bool = False


_BEIJING_TZ = timezone(timedelta(hours=8))


def _is_system_thinking_peak(now: datetime | None = None) -> bool:
    """判断当前北京时间是否处于系统 API 的深度思考限制时段。"""
    current = datetime.now(_BEIJING_TZ) if now is None else now
    if current.tzinfo is None:
        current = current.replace(tzinfo=_BEIJING_TZ)
    else:
        current = current.astimezone(_BEIJING_TZ)
    minutes = current.hour * 60 + current.minute
    return 9 * 60 <= minutes < 12 * 60 or 14 * 60 <= minutes < 18 * 60


def _apply_thinking_policy(
    thinking: bool,
    using_user_api: bool,
    now: datetime | None = None,
) -> bool:
    """系统 API 高峰时段强制关闭深度思考，自定义 API 不受限制。"""
    return bool(thinking) and (using_user_api or not _is_system_thinking_peak(now))


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _extract_user_api(request: Request) -> dict | None:
    """从请求 headers 中提取用户自定义 API 配置。"""
    api_key = request.headers.get("X-User-API-Key")
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "base_url": request.headers.get("X-User-Base-URL", "https://api.deepseek.com"),
        "model": request.headers.get("X-User-Model", "deepseek-chat"),
    }


def _format_message_with_images(message: str, images: list[str]):
    """将纯文本消息和 base64 图片列表组装为 OpenAI 多模态 content 数组。"""
    if not images:
        return message
    parts = [{"type": "text", "text": message}]
    for img_b64 in images:
        # 支持带 data: 前缀和纯 base64
        url = img_b64 if img_b64.startswith("data:") else f"data:image/jpeg;base64,{img_b64}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def _make_stream(agent_fn, user_model=None):
    """
    通用 SSE 流工厂。
    agent_fn: 接受 (message, history, on_event) 参数的同步函数。
    user_model: 用户自定义 API 的模型名称，非 None 时在 SSE 中通知前端。
    """
    async def stream_response(req: ChatRequest):
        if not req.message.strip() and not req.images:
            raise HTTPException(status_code=400, detail="message 不能为空")

        # 有图片时将消息格式化为多模态 content 数组
        message = _format_message_with_images(req.message, req.images or [])

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        cancel_event = threading.Event()

        class GenerationCancelled(Exception):
            pass

        def cancel_check():
            if cancel_event.is_set():
                raise GenerationCancelled()

        # 如果使用用户自定义 API，通知前端模型信息
        if user_model:
            await queue.put({"type": "user_model", "model": user_model})

        def on_event(event_type: str, payload: dict):
            cancel_check()
            if event_type == "usage":
                tokens = payload.get("prompt_tokens", 0) + payload.get("completion_tokens", 0)
                _add_tokens(tokens)
                print(f"[token] 本轮消耗 {tokens} tokens", file=sys.stderr, flush=True)
                return  # usage 事件不推送给前端
            if event_type not in {"token", "thinking", "trace_reset", "trace_message"}:
                print(f"[SSE] {event_type}: {payload}", file=sys.stderr, flush=True)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": event_type, **payload})

        async def run_agent():
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: agent_fn(
                        message,
                        history=req.history or None,
                        on_event=on_event,
                        cancel_check=cancel_check,
                        thinking=req.thinking,
                        web_search=req.web_search,
                        trace=req.trace,
                    ),
                )
                cancel_check()
                await queue.put({"type": "answer", "sources": result.get("sources", [])})
                # 发送完整 messages 供前端保存为下一轮 history
                if "messages" in result:
                    await queue.put({"type": "messages", "messages": result["messages"]})
            except GenerationCancelled:
                print("[SSE] generation cancelled", file=sys.stderr, flush=True)
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                await queue.put({"type": "error", "message": str(e)})
            finally:
                await queue.put(None)

        async def stream():
            task = asyncio.create_task(run_agent())
            try:
                while True:
                    item = await asyncio.wait_for(queue.get(), timeout=120)
                    if item is None:
                        break
                    yield _sse(item)
            except asyncio.TimeoutError:
                print("[SSE] timeout", file=sys.stderr, flush=True)
                yield _sse({"type": "error", "message": "响应超时，请重试"})
            finally:
                cancel_event.set()
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return stream_response


# ── 路由：导航页 ──────────────────────────────────────────────────────

@app.get("/")
async def landing():
    return HTMLResponse(
        _render_landing_page(),
        headers={"Cache-Control": "no-cache"},
    )


# ── 路由：问秋月 ──────────────────────────────────────────────────────

@app.get("/blog")
async def blog_index():
    return FileResponse(_ROOT / "index_blog.html")


@app.get("/conversation-storage.js")
async def conversation_storage_script():
    return FileResponse(_ROOT / "conversation_storage.js", media_type="application/javascript")


@app.post("/blog/chat")
async def blog_chat(req: ChatRequest, request: Request):
    user_api = _extract_user_api(request)
    req.thinking = _apply_thinking_policy(req.thinking, user_api is not None)

    if user_api:
        temp_agent = BlogAgent(
            retriever=_retriever,
            deepseek_api_key=user_api["api_key"],
            base_url=user_api["base_url"],
            model=user_api["model"],
            tavily_api_key=tavily_key,
        )
        return await _make_stream(temp_agent.chat, user_model=user_api["model"])(req)

    balance = await _fetch_balance_cny()
    if balance is not None and balance < _BALANCE_THRESHOLD:
        async def _exhausted():
            yield _sse({"type": "token", "text": "本月Token已经用完了喵......\n\n你可以点击页面右上角的齿轮按钮，填入自己的 API Key，即可继续使用~"})
            yield _sse({"type": "answer", "sources": []})
            yield _sse({"type": "done"})
        return StreamingResponse(_exhausted(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await _make_stream(blog_agent.chat)(req)


@app.get("/blog/health")
async def blog_health():
    try:
        return {"status": "ok", "doc_count": _retriever.content_col.count()}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── 路由：Prompt 炼金术 ───────────────────────────────────────────────

@app.get("/prompt")
async def prompt_index():
    return FileResponse(_ROOT / "index_prompt.html")


@app.post("/prompt/chat")
async def prompt_chat(req: ChatRequest, request: Request):
    user_api = _extract_user_api(request)
    req.thinking = _apply_thinking_policy(req.thinking, user_api is not None)

    if user_api:
        temp_agent = PromptAgent(
            deepseek_api_key=user_api["api_key"],
            base_url=user_api["base_url"],
            model=user_api["model"],
            tavily_api_key=tavily_key,
            debug=prompt_agent_debug,
        )
        return await _make_stream(temp_agent.chat, user_model=user_api["model"])(req)

    balance = await _fetch_balance_cny()
    if balance is not None and balance < _BALANCE_THRESHOLD:
        msg = ("本月大模型体验配额已耗尽\n"
               "你可以点击页面右上角的齿轮按钮，填入自己的 API Key，即可继续使用~\n"
               "或接入自己的Agent终端：https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline#mcp-%E6%8E%A5%E5%8F%A3")
        async def _exhausted():
            yield _sse({"type": "token", "text": msg})
            yield _sse({"type": "answer", "sources": []})
            yield _sse({"type": "done"})
        return StreamingResponse(_exhausted(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await _make_stream(prompt_agent.chat)(req)


class TitleRequest(BaseModel):
    history: list[dict] = []
    thinking: bool = False


@app.post("/prompt/title")
async def prompt_title(req: TitleRequest, request: Request):
    if not req.history:
        return {"title": "对话"}

    user_api = _extract_user_api(request)
    req.thinking = _apply_thinking_policy(req.thinking, user_api is not None)

    if user_api:
        temp_agent = PromptAgent(
            deepseek_api_key=user_api["api_key"],
            base_url=user_api["base_url"],
            model=user_api["model"],
            debug=prompt_agent_debug,
        )
        try:
            title, usage = await asyncio.get_running_loop().run_in_executor(
                None, lambda: temp_agent.generate_title(req.history, thinking=req.thinking)
            )
            if usage:
                _add_tokens(usage.prompt_tokens + usage.completion_tokens)
            return {"title": title}
        except Exception:
            return {"title": "对话"}

    balance = await _fetch_balance_cny()
    if balance is not None and balance < _BALANCE_THRESHOLD:
        return {"title": "对话"}
    try:
        title, usage = await asyncio.get_running_loop().run_in_executor(
            None, lambda: prompt_agent.generate_title(req.history, thinking=req.thinking)
        )
        if usage:
            _add_tokens(usage.prompt_tokens + usage.completion_tokens)
        print(f"[title] 生成标题: {title!r}", file=sys.stderr, flush=True)
        return {"title": title}
    except Exception as e:
        print(f"[title] 生成标题异常: {e}", file=sys.stderr, flush=True)
        return {"title": "对话"}


@app.get("/prompt/health")
async def prompt_health():
    result = check_mcp_health()
    hf_ok = result["hf"]["ok"]
    ms_ok = result["ms"]["ok"]
    if hf_ok:
        return {
            "status": "ok",
            "active": "hf",
            "latency_ms": result["hf"].get("latency_ms"),
            "hf": result["hf"],
            "ms": result["ms"],
        }
    if ms_ok:
        return {
            "status": "fallback",
            "active": "ms",
            "latency_ms": result["ms"].get("latency_ms"),
            "hf": result["hf"],
            "ms": result["ms"],
        }
    return {
        "status": "error",
        "active": None,
        "hf": result["hf"],
        "ms": result["ms"],
    }


# ── 余额查询 ───────────────────────────────────────────────────────────

_BALANCE_TARGET = 30.0  # 目标余额（元），作为 100%
_BALANCE_THRESHOLD = 0.5  # 余额低于此值时拦截请求
_BALANCE_CACHE_TTL = 60  # 余额缓存秒数

_balance_cache: dict = {"value": None, "ts": 0.0}


async def _fetch_balance_cny() -> float | None:
    """查询 DeepSeek 账户余额，返回 CNY 金额（带 60s 缓存）。失败时返回 None。"""
    now = time.time()
    if now - _balance_cache["ts"] < _BALANCE_CACHE_TTL:
        return _balance_cache["value"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url}/user/balance",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {deepseek_key}",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        for info in data.get("balance_infos", []):
            if info.get("currency") == "CNY":
                val = float(info.get("total_balance", "0"))
                _balance_cache["value"] = val
                _balance_cache["ts"] = now
                return val
    except Exception as e:
        print(f"[balance] 查询余额失败: {e}", file=sys.stderr, flush=True)
    return _balance_cache["value"]  # 查询失败时返回旧缓存值


@app.get("/tokens")
async def get_tokens():
    """返回程序累计消耗的总 token 数（输入+输出合并计算）。"""
    total = _TOKEN_BASELINE + _total_tokens_used
    return {"total_tokens": total}


@app.get("/balance")
async def get_balance():
    """查询 DeepSeek API 账户余额，返回相对于目标金额的百分比。"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url}/user/balance",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {deepseek_key}",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # 提取 CNY 余额
        total_balance = 0.0
        for info in data.get("balance_infos", []):
            if info.get("currency") == "CNY":
                total_balance = float(info.get("total_balance", "0"))
                break

        percentage = min(round((total_balance / _BALANCE_TARGET) * 100, 1), 100.0)
        percentage = max(percentage, 0.0)

        return {
            "percentage": percentage,
            "is_available": data.get("is_available", False),
        }
    except Exception as e:
        print(f"[balance] 查询余额失败: {e}", file=sys.stderr, flush=True)
        return {
            "percentage": 0.0,
            "is_available": False,
            "error": str(e),
        }


# ── 用户 API 校验 ─────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


@app.post("/api/validate")
async def validate_user_api(req: ValidateRequest):
    """验证用户提供的 API Key 是否有效。"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=req.api_key, base_url=req.base_url)
        resp = client.chat.completions.create(
            model=req.model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return {"valid": True}
    except Exception as e:
        error_msg = str(e)
        if req.api_key in error_msg:
            error_msg = error_msg.replace(req.api_key, "***")
        return {"valid": False, "error": error_msg}


# ── HF Space 探活接口 ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
