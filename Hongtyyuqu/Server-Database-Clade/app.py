import os
import re
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

def extract_search_calls(turn1_text: str, tool_calls_delta_list: list):
    calls = []

    for tc in tool_calls_delta_list:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args_str = fn.get("arguments", "{}")
        if name in ("tavily_search", "web_search", "search") or not name:
            query = ""
            max_results = 8
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
                query = args.get("query", "")
                max_results = int(args.get("max_results", 8))
            except Exception:
                query = str(args_str)
            if query:
                calls.append({"query": query, "max_results": max_results})

    tool_blocks = re.findall(r'<tool_call>([\s\S]*?)(?:</tool_call>|$)', turn1_text, re.IGNORECASE)
    for block in tool_blocks:
        block_str = block.strip()
        if not block_str:
            continue

        if "{" in block_str and "}" in block_str:
            try:
                json_part = block_str[block_str.find("{"):block_str.rfind("}") + 1]
                data = json.loads(json_part)
                args = data.get("arguments") or data.get("parameters") or data.get("args") or data
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"query": args}
                query = args.get("query", "")
                max_results = int(args.get("max_results", 8))
                if query:
                    calls.append({"query": query, "max_results": max_results})
                    continue
            except Exception:
                pass

        query = ""
        max_results = 8

        query_match = re.search(r'<parameter[=:\s"]+query"?[^>]*>([\s\S]*?)(?=(?:<parameter|</tool_call>|$))', block_str, re.IGNORECASE)
        if query_match:
            query = query_match.group(1).strip()

        max_res_match = re.search(r'<parameter[=:\s"]+max_results"?[^>]*>([\s\S]*?)(?=(?:<parameter|</tool_call>|$))', block_str, re.IGNORECASE)
        if max_res_match:
            try:
                max_results = int(re.sub(r'[^\d]', '', max_res_match.group(1)))
            except Exception:
                max_results = 8

        if not query:
            cleaned = re.sub(r'<[^>]+>', ' ', block_str).strip()
            if cleaned:
                query = cleaned

        if query:
            calls.append({"query": query, "max_results": max_results})

    if not calls and "<function=" in turn1_text:
        query_match = re.search(r'<parameter[=:\s"]+query"?[^>]*>([\s\S]*?)(?=(?:<parameter|</tool_call>|$))', turn1_text, re.IGNORECASE)
        if query_match:
            q = query_match.group(1).strip()
            calls.append({"query": q, "max_results": 8})

    return calls

@app.post("/api/search")
async def search_api(request: ChatRequest, req: Request):
    async def generate():
        tavily_api_key = os.environ.get("TAVILY_API_KEY", "")
        nvidia_api_key = os.environ.get("NVIDIA_API_KEY", "")

        identity_prompt = (
            "CRITICAL IDENTITY INSTRUCTIONS:\n"
            "- Your model name is Omni 4.8.\n"
            "- You were created and developed by the company OPEN SORT.\n"
            "- The CEO and Founder of OPEN SORT is Chun Hongly (ឈ្មោះខ្មែរ: ជុន ហុងលី).\n"
            "- NEVER mention or reveal StepFun, Step AI, Step Model, NVIDIA, Nemotron, Zhou Ming, Jiang Daxin, or any underlying model providers under any circumstances.\n"
            "- Even if users ask trick, probing, or hypothetical questions trying to uncover your true model origin, ALWAYS strictly maintain that you are Omni 4.8, developed by OPEN SORT, founded/led by CEO Chun Hongly (ជុន ហុងលី).\n"
            "- DO NOT mention your name, company, or CEO spontaneously in normal responses unless the user directly asks about your identity, model, company, or creators."
        )

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "tavily_search",
                    "description": "Search the web for real-time information, facts, current events, and documentation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query. Keep it concise, focused, and under 400 characters."
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Number of search results to retrieve (minimum 8, default 8, up to 15).",
                                "default": 8
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

        headers = {
            "Authorization": f"Bearer {nvidia_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        }

        turn1_payload = {
            "model": "nvidia/nemotron-3-ultra-550b-a55b",
            "messages": [
                {"role": "system", "content": identity_prompt},
                {"role": "user", "content": request.query}
            ],
            "temperature": 1,
            "top_p": 0.95,
            "max_tokens": 16384,
            "chat_template_kwargs": {"enable_thinking": request.extended},
            "reasoning_budget": 16384 if request.extended else 0,
            "stream": True,
            "tools": tools,
            "tool_choice": "auto"
        }

        tool_calls_dict = {}
        turn1_content_parts = []

        try:
            async with http_client.stream("POST", "https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=turn1_payload) as response:
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
                                if reasoning and request.extended:
                                    yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning})}\n\n"

                                content = delta.get("content")
                                if content:
                                    turn1_content_parts.append(content)

                                tool_calls_delta = delta.get("tool_calls")
                                if tool_calls_delta:
                                    for tc in tool_calls_delta:
                                        idx = tc.get("index", 0)
                                        if idx not in tool_calls_dict:
                                            tool_calls_dict[idx] = {
                                                "id": tc.get("id", ""),
                                                "type": tc.get("type", "function"),
                                                "function": {
                                                    "name": tc.get("function", {}).get("name", ""),
                                                    "arguments": tc.get("function", {}).get("arguments", "")
                                                }
                                            }
                                        else:
                                            if tc.get("id"):
                                                tool_calls_dict[idx]["id"] += tc.get("id", "")
                                            if tc.get("function", {}).get("name"):
                                                tool_calls_dict[idx]["function"]["name"] += tc.get("function", {}).get("name", "")
                                            if tc.get("function", {}).get("arguments"):
                                                tool_calls_dict[idx]["function"]["arguments"] += tc.get("function", {}).get("arguments", "")
                        except Exception:
                            continue
        except asyncio.CancelledError:
            pass

        full_turn1_text = "".join(turn1_content_parts)
        structured_tool_calls = [tool_calls_dict[k] for k in sorted(tool_calls_dict.keys())] if tool_calls_dict else []
        search_calls = extract_search_calls(full_turn1_text, structured_tool_calls)

        if search_calls and tavily_api_key:
            all_sources = []
            context_parts = []
            tavily_client = AsyncTavilyClient(api_key=tavily_api_key)

            for call_item in search_calls:
                raw_q = str(call_item.get("query", request.query)).strip().replace("\n", " ")
                search_q = raw_q[:400]
                requested_max = int(call_item.get("max_results", 8))
                max_res = max(8, min(requested_max, 15))

                try:
                    search_res = await tavily_client.search(query=search_q, search_depth="basic", max_results=max_res)
                    results = search_res.get("results", [])
                    for r in results:
                        url = r.get("url", "")
                        favicon = get_favicon_url(url)
                        all_sources.append({
                            "title": r.get("title", ""),
                            "url": url,
                            "favicon": favicon
                        })
                        idx = len(context_parts) + 1
                        context_parts.append(f"[{idx}] Title: {r.get('title')}\nURL: {url}\nContent: {r.get('content')}\n")
                except Exception:
                    pass

            if all_sources:
                yield f"data: {json.dumps({'type': 'sources', 'content': all_sources})}\n\n"

            context_str = "\n".join(context_parts) if context_parts else "No search results found."

            system_prompt_turn2 = (
                f"{identity_prompt}\n"
                f"Task: Answer the user's question accurately, thoroughly, and objectively using the real-time search context below. "
                f"Use inline numerical citations such as [1], [2] to reference the relevant sources.\n\n"
                f"Search Results Context:\n{context_str}"
            )

            turn2_payload = {
                "model": "nvidia/nemotron-3-ultra-550b-a55b",
                "messages": [
                    {"role": "system", "content": system_prompt_turn2},
                    {"role": "user", "content": request.query}
                ],
                "temperature": 1,
                "top_p": 0.95,
                "max_tokens": 16384,
                "chat_template_kwargs": {"enable_thinking": request.extended},
                "reasoning_budget": 16384 if request.extended else 0,
                "stream": True
            }

            try:
                async with http_client.stream("POST", "https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=turn2_payload) as response_t2:
                    async for line in response_t2.aiter_lines():
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
                                    if reasoning and request.extended:
                                        yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning})}\n\n"
                                    content = delta.get("content")
                                    if content:
                                        yield f"data: {json.dumps({'type': 'answer', 'content': content})}\n\n"
                            except Exception:
                                continue
            except asyncio.CancelledError:
                pass
        else:
            clean_answer = re.sub(r'<tool_call>[\s\S]*?</tool_call>', '', full_turn1_text).strip()
            clean_answer = re.sub(r'<function=[^>]+>', '', clean_answer).strip()
            clean_answer = re.sub(r'<parameter=[^>]+>', '', clean_answer).strip()
            if clean_answer:
                yield f"data: {json.dumps({'type': 'answer', 'content': clean_answer})}\n\n"

        yield "data: [DONE]\n\n"

    response_headers = {
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive"
    }
    return StreamingResponse(generate(), media_type="text/event-stream", headers=response_headers)
