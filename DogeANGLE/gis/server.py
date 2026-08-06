"""
GIS-Review 百炼RAG专业课复习系统 — 薄后端代理
代理 DashScope App API，隐藏 API key
"""
import os
import json
import hashlib
import threading
import logging
from pathlib import Path

# 从 .env 文件加载环境变量
try:
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
except Exception:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import httpx

# ── 配置 ──────────────────────────────────────────────────
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
APP_ID = os.environ.get("DASHSCOPE_APP_ID", "fd3cdf976ffc4dffabaeb5ba4543308a")
API_URL = f"https://dashscope.aliyuncs.com/api/v1/apps/{APP_ID}/completion"
CACHE_FILE = Path(__file__).parent / "answer_cache.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gis-review")

if not API_KEY:
    logger.warning("DASHSCOPE_API_KEY 未设置！")

app = FastAPI(title="GIS-Review", version="0.3.0")

# ── 持久化缓存 ────────────────────────────────────────────
_cache: dict[str, str] = {}
_cache_lock = threading.Lock()

def _load_cache():
    global _cache
    if CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            logger.info(f"缓存已加载: {len(_cache)} 条")
        except Exception as e:
            logger.error(f"缓存加载失败: {e}")
            _cache = {}
    else:
        _cache = {}

def _save_cache():
    try:
        CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.error(f"缓存写入失败: {e}")

def _cache_key(messages: list[dict]) -> str:
    """取最后一条用户消息的 MD5"""
    for m in reversed(messages):
        if m.get("role") == "user":
            return hashlib.md5(m["content"].encode()).hexdigest()
    return hashlib.md5(json.dumps(messages).encode()).hexdigest()

_load_cache()


# ── 模型 ──────────────────────────────────────────────────
class ChatRequest(BaseModel):
    messages: list[dict]
    skip_cache: bool = False


class ChatResponse(BaseModel):
    answer: str
    cached: bool = False
    cache_size: int = 0
    error: str | None = None


# ── API ───────────────────────────────────────────────────
@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="服务端未配置 API key")

    key = _cache_key(req.messages)

    if not req.skip_cache:
        with _cache_lock:
            if key in _cache:
                logger.info(f"缓存命中: {key[:12]}...")
                return ChatResponse(answer=_cache[key], cached=True, cache_size=len(_cache))

    logger.info(f"调用百炼 API，消息数: {len(req.messages)}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"input": {"messages": req.messages}, "stream": False},
            )

        if resp.status_code != 200:
            logger.error(f"百炼 API 错误: {resp.status_code}")
            raise HTTPException(status_code=502, detail=f"百炼 API 返回 {resp.status_code}")

        data = resp.json()
        answer = data.get("output", {}).get("text", "（未获取到回答）")

        with _cache_lock:
            _cache[key] = answer
            _save_cache()
        logger.info(f"已缓存 (共 {len(_cache)} 条)，答案长度: {len(answer)}")

        return ChatResponse(answer=answer, cached=False, cache_size=len(_cache))

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="百炼 API 请求超时")
    except Exception as e:
        logger.error(f"请求异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cache")
async def cache_info():
    return {"total": len(_cache), "keys": list(_cache.keys())[:20]}


@app.delete("/api/cache")
async def clear_cache():
    global _cache
    with _cache_lock:
        count = len(_cache)
        _cache = {}
    _save_cache()
    logger.info(f"缓存已清除 ({count} 条)")
    return {"cleared": count}


@app.get("/api/health")
async def health():
    return {"status": "ok" if API_KEY else "no_api_key", "cache": len(_cache)}


# ── 跨端数据同步 ──────────────────────────────────────────
SYNC_DIR = Path(__file__).parent / "user_data"

class SyncUpload(BaseModel):
    user_id: str
    data: dict  # 所有要同步的 localStorage keys

def _safe_sync_path(user_id: str) -> Path:
    """防止路径遍历攻击"""
    safe = user_id.replace("..", "").replace("/", "").replace("\\", "")
    if not safe or len(safe) > 50:
        raise HTTPException(status_code=400, detail="无效的用户ID")
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    return SYNC_DIR / f"{safe}.json"

@app.post("/api/sync/upload")
async def sync_upload(req: SyncUpload):
    """上传数据：POST { user_id, data: {...localStorage keys...} }"""
    try:
        path = _safe_sync_path(req.user_id)
        path.write_text(json.dumps(req.data, ensure_ascii=False), encoding="utf-8")
        logger.info(f"同步上传: {req.user_id} ({len(req.data)} keys, {len(json.dumps(req.data))} bytes)")
        return {"status": "ok", "size": len(json.dumps(req.data))}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sync/download")
async def sync_download(user_id: str):
    """下载数据：GET /api/sync/download?user_id=xxx"""
    try:
        path = _safe_sync_path(user_id)
        if not path.exists():
            return {"status": "not_found", "data": {}}
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info(f"同步下载: {user_id} ({len(data)} keys)")
        return {"status": "ok", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步下载失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=7860)
