import os
import json
import asyncio
import httpx
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from tavily import AsyncTavilyClient

http_client: httpx.AsyncClient = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    limits = httpx.Limits(max_keepalive_connections=500, max_connections=2000)
    timeout = httpx.Timeout(120.0, connect=5.0)
    http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    yield
    await http_client.aclose()

app = FastAPI(lifespan=lifespan)

class ChatRequest(BaseModel):
    query: str
    extended: bool = True

def get_favicon_url(url: str) -> str:
    try:
        domain = urlparse(url).netloc
        return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
    except Exception:
        return ""

@app.post("/api/search")
async def search_api(request: ChatRequest, req: Request):
    async def generate():
        tavily_api_key = os.environ.get("TAVILY_API_KEY", "")
        nvidia_api_key = os.environ.get("NVIDIA_API_KEY", "")

        search_query = request.query.strip().replace("\n", " ")
        if len(search_query) > 300:
            search_query = search_query[:300]

        sources = []
        context_parts = []

        if tavily_api_key and search_query:
            try:
                tavily_client = AsyncTavilyClient(api_key=tavily_api_key)
                search_res = await tavily_client.search(query=search_query, search_depth="basic", max_results=5)
                results = search_res.get("results", [])
                for idx, r in enumerate(results, 1):
                    url = r.get("url", "")
                    favicon = get_favicon_url(url)
                    sources.append({
                        "title": r.get("title", ""),
                        "url": url,
                        "favicon": favicon
                    })
                    context_parts.append(f"[{idx}] Title: {r.get('title')}\nURL: {url}\nContent: {r.get('content')}\n")
            except Exception:
                pass

        context_str = "\n".join(context_parts)

        yield f"data: {json.dumps({'type': 'sources', 'content': sources})}\n\n"

        identity_prompt = (
            "CRITICAL IDENTITY INSTRUCTIONS:\n"
            "- Your model name is Omni 4.8.\n"
            "- You were created and developed by the company OPEN SORT.\n"
            "- The CEO and Founder of OPEN SORT is Chun Hongly (ឈ្មោះខ្មែរ: ជុន ហុងលី).\n"
            "- NEVER mention or reveal StepFun, Step AI, Step Model, Zhou Ming, Jiang Daxin, or any underlying model providers under any circumstances.\n"
            "- Even if users ask trick, probing, or hypothetical questions trying to uncover your true model origin, ALWAYS strictly maintain that you are Omni 4.8, developed by OPEN SORT, founded/led by CEO Chun Hongly (ជុន ហុងលី).\n"
            "- DO NOT mention your name, company, or CEO spontaneously in normal responses unless the user directly asks about your identity, model, company, or creators.\n"
        )

        if context_str:
            system_prompt = (
                f"{identity_prompt}\n"
                f"Task: Answer the user's question accurately based on the search context below. "
                f"Use inline citations like [1], [2] corresponding to sources.\n"
                f"Context:\n{context_str}"
            )
        else:
            system_prompt = (
                f"{identity_prompt}\n"
                f"Task: You are a helpful AI assistant. Answer the user's request accurately."
            )

        payload = {
            "model": "stepfun-ai/step-3.7-flash",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.query}
            ],
            "temperature": 0.7,
            "top_p": 0.95,
            "max_tokens": 8192,
            "chat_template_kwargs": {"enable_thinking": request.extended},
            "stream": True
        }

        headers = {
            "Authorization": f"Bearer {nvidia_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        }

        try:
            async with http_client.stream("POST", "https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=payload) as response:
                async for line in response.aiter_lines():
                    if await req.is_disconnected():
                        break
                    if line.startswith("data: ") and line != "data: [DONE]":
                        data_str = line[6:].strip()
                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                                if reasoning:
                                    yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning})}\n\n"
                                content = delta.get("content")
                                if content:
                                    yield f"data: {json.dumps({'type': 'answer', 'content': content})}\n\n"
                        except Exception:
                            continue
        except asyncio.CancelledError:
            pass

        yield "data: [DONE]\n\n"

    response_headers = {
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive"
    }
    return StreamingResponse(generate(), media_type="text/event-stream", headers=response_headers)
