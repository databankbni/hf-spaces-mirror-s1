"""
core/agent.py
──────────────
查询重写（Multi-Query）+ DeepSeek Tool Calling 主循环。

流式架构：
  每一轮 LLM 调用都使用 stream=True 并携带 tools。
  流式过程中：
    - reasoning_content delta 聚合后 emit 为 thinking 事件
    - content delta 实时 emit 为 token 事件（前端渲染为最终答案气泡）
    - tool_calls delta 按 index 聚合 function.name 和 arguments 分片
  流结束后根据 finish_reason 分派：
    - tool_calls：emit token_flush 让前端把已推送的 token 转为思考气泡，
                  然后解析参数执行工具，追加 tool message，进入下一轮
    - 其他（stop/length/...）：token 已在流中推送完毕，直接返回答案

SSE 事件约定：
  token        {text: str}                  # 答案 token，前端追加进 streamBubble
  thinking     {text: str}                  # 本轮思维链，前端追加进思考区
  thinking_flush {}                         # 本轮思维链结束，下一轮新建思考块
  token_flush  {}                            # 前端把当前 streamBubble 转为 thinking-text
  tool_start   {tool: str, query: str}      # 工具开始执行
  tool_done    {tool: str, found: bool, count: int}  # 工具执行结果
  answer       {sources: list[dict]}         # 最终 sources（token 在此之前已推送完毕）
  error        {message: str}

verbose 模式：打印每轮 finish_reason 和工具调用。
debug  模式：在 verbose 基础上额外打印每轮发给 LLM 的完整请求体。
"""

from __future__ import annotations

import json
import sys
from typing import Iterator, Optional

from openai import OpenAI

from core.prompts import get_system_prompt, QUERY_REWRITE_PROMPT


def get_platform_settings(api_url: str, model_name: str, thinking: bool) -> dict:
    """
    根据 API 平台和思考模式设置，返回 extra_body 参数。
    从 LLM_Prompt_Formatter.get_platform_settings 提取为模块级函数，
    供 Agent 模式和普通模式共用。
    """
    extra_body = {}

    def _is_claude_46_plus(name):
        n = name.lower()
        return ('claude-sonnet-4-6' in n or 'claude-opus-4-6' in n
                or 'sonnet-4.6' in n or 'opus-4.6' in n)

    if 'openrouter' in api_url:
        if thinking:
            extra_body = {"reasoning": {"enabled": True, "exclude": False}}
        else:
            extra_body = {"reasoning": {"enabled": False, "effort": "minimal"}}

    elif 'googleapis' in api_url:
        if not thinking:
            if '3' in model_name or '2.5-pro' in model_name:
                print(f"[Agent]: googleapis平台的{model_name}模型无法彻底关闭思考功能。已将思考模式设置为low。")
                extra_body = {"reasoning_effort": "low"}
            else:
                extra_body = {"reasoning_effort": "none"}

    elif 'xiaomimimo' in api_url or 'moonshot' in api_url or 'deepseek' in api_url:
        if thinking:
            extra_body = {"thinking": {"type": "enabled"}}
        else:
            extra_body = {"thinking": {"type": "disabled"}}

    elif 'anthropic.com' in api_url:
        if thinking:
            if _is_claude_46_plus(model_name):
                extra_body = {"thinking": {"type": "adaptive"}}
            else:
                extra_body = {"thinking": {"type": "enabled", "budget_tokens": 8000}}

    elif 'vercel' in api_url:
        if thinking:
            extra_body = {"reasoning": {"enabled": True, "max_tokens": 8000}}
        else:
            extra_body = {"reasoning": {"effort": "none"}}

    else:
        print(f"[Agent]: 思考模式开关暂不支持您使用的API平台。")

    return extra_body


_IMMERSION_INJECTION = """

【角色沉浸要求】在你的思考过程（<think>标签内）中，请遵守以下规则：
1. 请以角色第一人称进行内心独白，用括号包裹内心活动，例如"（心想：……）"或"(内心OS：……)"
2. 用第一人称描写角色的内心感受，例如"我心想""我觉得""我暗自"等
3. 思考内容应沉浸在角色中，通过内心独白分析剧情和规划回复

<system_rule> 请务必使用用户提问的语言进行思考，推理，并回答用户的问题 </system_rule>"""
from core.tools import (
    get_tools,
    execute_rag_search,
    execute_fetch_context,
    execute_web_search,
    limit_tool_result_for_history,
)

MAX_ROUNDS = 10


def _serialize_message(msg) -> dict:
    if isinstance(msg, dict):
        return msg
    result = {"role": msg.role, "content": msg.content}
    reasoning_content = getattr(msg, "reasoning_content", None)
    if reasoning_content is not None:
        result["reasoning_content"] = reasoning_content
    if getattr(msg, "tool_calls", None):
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return result


def _dump_request(messages: list, tools: list | None, extra: dict | None = None):
    payload: dict = {"messages": [_serialize_message(m) for m in messages]}
    if tools:
        payload["tools"] = tools
    if extra:
        payload.update(extra)
    print("\n[DEBUG] ── LLM 请求体 ──────────────────────────────────", file=sys.stderr)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    print("[DEBUG] ───────────────────────────────────────────────\n", file=sys.stderr)


class Agent:
    def __init__(
        self,
        retriever,
        deepseek_api_key: str,
        tavily_api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        verbose: bool = False,
        debug: bool = False,
    ):
        self.retriever = retriever
        self.model = model
        self.verbose = verbose
        self.debug = debug
        self.base_url = base_url

        self.llm = OpenAI(api_key=deepseek_api_key, base_url=base_url)

        self.tavily = None
        if tavily_api_key:
            from tavily import TavilyClient
            self.tavily = TavilyClient(api_key=tavily_api_key)

    def _log(self, msg: str):
        if self.verbose or self.debug:
            print(f"[Agent] {msg}", file=sys.stderr)

    def _emit(self, event_type: str, payload: dict, on_event=None):
        if callable(on_event):
            on_event(event_type, payload)

    # ── 查询重写 ───────────────────────────────────────────────────────

    def rewrite_query(self, question: str, thinking: bool = False) -> list[str]:
        prompt = QUERY_REWRITE_PROMPT.format(question=question)
        req_messages = [{"role": "user", "content": prompt}]

        if self.debug:
            _dump_request(req_messages, None, {"note": "query_rewrite", "temperature": 0.3})

        try:
            resp = self.llm.chat.completions.create(
                model=self.model,
                messages=req_messages,
                temperature=0.3,
                max_tokens=200,
                extra_body=get_platform_settings(self.base_url, self.model, thinking)
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.strip("```json").strip("```").strip()
            variants = json.loads(raw)
            if isinstance(variants, list):
                result = [str(v) for v in variants if v]
                self._log(f"查询重写: {result}")
                return result
        except Exception as e:
            self._log(f"查询重写失败（已跳过）: {e}")
        return []

    # ── Tool 执行 ──────────────────────────────────────────────────────

    def _execute_tool(
        self,
        name: str,
        args: dict,
        rewrite_queries: list[str],
        web_search: bool = True,
    ) -> str:
        if name == "rag_search":
            return execute_rag_search(
                query=args["query"],
                retriever=self.retriever,
                rewrite_queries=rewrite_queries,
            )
        elif name == "fetch_context":
            return execute_fetch_context(
                url=args["url"],
                chunk_index=int(args["chunk_index"]),
                retriever=self.retriever,
            )
        elif name == "web_search":
            if not web_search:
                return json.dumps(
                    {"found": False, "error": "联网搜索已关闭"},
                    ensure_ascii=False,
                )
            if self.tavily is None:
                return json.dumps(
                    {"found": False, "error": "web_search 未配置 Tavily API Key"},
                    ensure_ascii=False,
                )
            return execute_web_search(args["query"], self.tavily)
        else:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    # ── 流式单轮调用 ──────────────────────────────────────────────────

    def _stream_round(
        self,
        messages: list,
        on_event=None,
        cancel_check=None,
        thinking: bool = False,
        web_search: bool = True,
    ) -> tuple[str, str, str, list[dict], object | None]:
        """
        发起一次带 tools 的流式请求，在流中聚合 reasoning_content、content 和 tool_calls。

        content delta 实时 emit 为 token 事件；
        tool_calls delta 按 index 聚合 function.name 和 arguments 分片。

        返回：(finish_reason, reasoning_content, content, tool_calls, usage)
          tool_calls 为 list[dict]，每项形如：
            {"id": str, "type": "function",
             "function": {"name": str, "arguments": str}}
        """
        if callable(cancel_check):
            cancel_check()

        tools = get_tools(web_search)
        if self.debug:
            _dump_request(messages, tools, {"temperature": 0.7, "stream": True})

        stream = self.llm.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.7,
            max_tokens=10240,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=get_platform_settings(self.base_url, self.model, thinking)
        )

        reasoning_chunks: list[str] = []
        content_chunks: list[str] = []
        tool_calls_acc: dict[int, dict] = {}  # index -> {id, type, function: {name, arguments}}
        finish_reason: str = ""
        prefix_printed = False
        usage = None

        for chunk in stream:
            if callable(cancel_check):
                try:
                    cancel_check()
                except Exception:
                    close_stream = getattr(stream, "close", None)
                    if callable(close_stream):
                        close_stream()
                    raise
            if not chunk.choices:
                if chunk.usage:
                    usage = chunk.usage
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            # 思维链增量必须与 content 分开收集；工具调用后的请求还要原样回传。
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta is None:
                reasoning_delta = getattr(delta, "reasoning", None)
            if reasoning_delta:
                reasoning_text = reasoning_delta if isinstance(reasoning_delta, str) else str(reasoning_delta)
                reasoning_chunks.append(reasoning_text)
                self._emit("thinking", {"text": reasoning_text}, on_event)

            # content 增量
            if delta.content:
                if not prefix_printed:
                    print("\n秋月：", end="", flush=True)
                    prefix_printed = True
                content_chunks.append(delta.content)
                print(delta.content, end="", flush=True)
                self._emit("token", {"text": delta.content}, on_event)

            # tool_calls 增量：按 index 聚合
            if getattr(delta, "tool_calls", None):
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    slot = tool_calls_acc[idx]
                    if tc_delta.id:
                        slot["id"] = tc_delta.id
                    if tc_delta.type:
                        slot["type"] = tc_delta.type
                    fn_delta = getattr(tc_delta, "function", None)
                    if fn_delta is not None:
                        if fn_delta.name:
                            slot["function"]["name"] += fn_delta.name
                        if fn_delta.arguments:
                            slot["function"]["arguments"] += fn_delta.arguments

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            # 从流的最后一个 chunk 中提取 usage（需要 stream_options={"include_usage": True}）
            if getattr(chunk, "usage", None):
                usage = chunk.usage

        reasoning_content = "".join(reasoning_chunks)
        if reasoning_content:
            self._emit("thinking_flush", {}, on_event)
        content = "".join(content_chunks)
        tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
        return finish_reason, reasoning_content, content, tool_calls, usage

    # ── 主问答循环 ─────────────────────────────────────────────────────

    def chat(
        self,
        question: str | list,
        history: list[dict] | None = None,
        on_event=None,
        cancel_check=None,
        thinking: bool = False,
        web_search: bool = True,
        trace: bool = False,
    ) -> dict:
        """
        输入用户问题和对话历史，返回：
        {
            "answer":  "回答文本",
            "sources": [{"title": ..., "url": ...}, ...]
        }
        question 为 str（纯文本）或 list（OpenAI 多模态 content 数组）。
        """
        if callable(cancel_check):
            cancel_check()

        # 预处理：区分纯文本和多模态
        is_multimodal = isinstance(question, list)
        text_question = question if not is_multimodal else " ".join(
            p.get("text", "") for p in question if isinstance(p, dict) and p.get("type") == "text"
        )

        # 1. 查询重写（仅首轮执行，后续轮次直接用原问题检索）
        is_first_turn = not history
        if is_first_turn:
            rewrite_queries = self.rewrite_query(text_question, thinking=thinking)
        else:
            rewrite_queries = []
        if callable(cancel_check):
            cancel_check()

        # 2. 构建初始 messages
        messages = [{"role": "system", "content": get_system_prompt(web_search=web_search)}]
        if history:
            messages.extend(history)
        if is_multimodal:
            # 多模态：直接使用 content 数组，沉浸注入作为额外 text part 追加
            user_content = list(question)
            if is_first_turn:
                user_content.append({"type": "text", "text": _IMMERSION_INJECTION})
        else:
            # 纯文本：保持原有 XML 包装
            user_content = f"<user_message>\n{question}\n</user_message>"
            if is_first_turn:
                user_content += _IMMERSION_INJECTION

        messages.append({"role": "user", "content": user_content})

        def append_message(message: dict):
            """追加上下文，并在彩蛋模式下同步这一条真实 Agent 消息。"""
            messages.append(message)
            if trace:
                self._emit("trace_message", {"message": message}, on_event)

        if trace:
            self._emit("trace_reset", {"messages": messages}, on_event)

        sources: list[dict] = []
        rounds = 0
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0}

        # 3. 流式 Tool Calling 主循环
        while rounds < MAX_ROUNDS:
            # 每轮流式调用：content delta 实时 emit 为 token，
            # tool_calls delta 聚合等流结束后处理。
            # 若 finish_reason=tool_calls，本轮 token 实为思考文本，
            # 通过 token_flush 事件通知前端转换样式。

            finish_reason, reasoning_content, content, tool_calls, usage = self._stream_round(
                messages,
                on_event=on_event,
                cancel_check=cancel_check,
                thinking=thinking,
                web_search=web_search,
            )

            if usage:
                total_usage["prompt_tokens"] += usage.prompt_tokens
                total_usage["completion_tokens"] += usage.completion_tokens
                self._emit("usage", {
                    "prompt_tokens": total_usage["prompt_tokens"],
                    "completion_tokens": total_usage["completion_tokens"],
                }, on_event)

            self._log(f"round={rounds}, finish_reason={finish_reason}, "
                      f"reasoning_len={len(reasoning_content)}, "
                      f"content_len={len(content)}, tool_calls={len(tool_calls)}")

            if finish_reason == "tool_calls" and tool_calls:
                # 追加 assistant 消息（含 tool_calls）到上下文
                append_message({
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning_content,
                    "tool_calls": tool_calls,
                })

                # 通知前端：本轮已流式推送的 token 实为思考文本，
                # 需将 streamBubble 收尾并转换为 thinking-text 样式。
                # content 非空时才有必要 flush；为空时跳过避免产生空思考气泡。
                if content.strip():
                    self._emit("token_flush", {}, on_event)

                # 执行每个工具
                for tc in tool_calls:
                    if callable(cancel_check):
                        cancel_check()
                    name = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError as e:
                        self._log(f"工具参数解析失败: {name}, {raw_args}, {e}")
                        args = {}

                    self._log(f"调用工具: {name}({args})")

                    query_str = args.get("query", "")
                    if name == "rag_search":
                        print(f"  > 检索博客知识库：{query_str}", flush=True)
                        self._emit("tool_start", {"tool": "rag_search", "query": query_str, "args": args}, on_event)
                    elif name == "fetch_context":
                        ctx_url = args.get("url", "")
                        ctx_idx = args.get("chunk_index", "")
                        print(f"  > 获取上下文：{ctx_url} chunk={ctx_idx}", flush=True)
                        self._emit("tool_start", {"tool": "fetch_context", "query": ctx_url, "args": args}, on_event)
                    elif name == "web_search":
                        print(f"  > 搜索互联网：{query_str}", flush=True)
                        self._emit("tool_start", {"tool": "web_search", "query": query_str, "args": args}, on_event)
                    else:
                        print(f"  > 调用工具：{name}", flush=True)
                        self._emit("tool_start", {"tool": name, "query": query_str, "args": args}, on_event)

                    result = limit_tool_result_for_history(
                        self._execute_tool(name, args, rewrite_queries, web_search=web_search)
                    )
                    if callable(cancel_check):
                        cancel_check()

                    try:
                        data = json.loads(result)
                        hit = int(data.get("result_count", len(data.get("results", []))))
                        if data.get("found"):
                            print(f"    找到 {hit} 条相关内容", flush=True)
                            self._emit("tool_done", {"tool": name, "found": True, "count": hit, "result": result}, on_event)
                        else:
                            print(f"    未找到相关内容", flush=True)
                            self._emit("tool_done", {"tool": name, "found": False, "count": 0, "result": result}, on_event)
                    except Exception:
                        self._emit("tool_done", {"tool": name, "found": False, "count": 0, "result": result}, on_event)

                    append_message({
                        "role":         "tool",
                        "tool_call_id": tc["id"],
                        "content":      result,
                    })

                    # 收集 sources
                    try:
                        data = json.loads(result)
                        for r in data.get("results", []):
                            if r.get("url") and r.get("title"):
                                src = {"title": r["title"], "url": r["url"]}
                                if src not in sources:
                                    sources.append(src)
                    except Exception:
                        pass

                rounds += 1
                continue

            # finish_reason 非 tool_calls：content 已作为 token 推送完毕，直接返回
            print()  # 换行收尾
            append_message({
                "role": "assistant",
                "content": content,
                "reasoning_content": reasoning_content,
            })
            return {"answer": content, "sources": sources, "messages": messages[1:]}

        # 超出最大轮次：追加强制作答指令，再发起一轮流式
        self._log("达到最大轮次，强制作答")
        append_message({
            "role":    "user",
            "content": "请根据已收集到的信息直接作答，禁止再调用任何工具。",
        })
        finish_reason, reasoning_content, content, tool_calls, usage = self._stream_round(
            messages,
            on_event=on_event,
            cancel_check=cancel_check,
            thinking=thinking,
            web_search=web_search,
        )
        if usage:
            total_usage["prompt_tokens"] += usage.prompt_tokens
            total_usage["completion_tokens"] += usage.completion_tokens
            self._emit("usage", {
                "prompt_tokens": total_usage["prompt_tokens"],
                "completion_tokens": total_usage["completion_tokens"],
            }, on_event)
        print()
        append_message({
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning_content,
        })
        return {"answer": content, "sources": sources, "messages": messages[1:]}
