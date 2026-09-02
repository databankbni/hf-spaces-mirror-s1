"""
prompt_agent/agent.py
----------------------
画面描述重写（Multi-Query）+ DeepSeek Tool Calling 主循环。

与问秋月 agent.py 的差异：
  - 无 Retriever / Tavily 依赖，工具调用直接 HTTP 请求 DanbooruSearch API
  - 工具集替换为 search_tags / get_related_tags / get_anima_format
  - _execute_tool 分派逻辑对应新工具
  - tool_done 的 count 来自 tags 列表长度（而非 results）
  - sources 字段不再收集，始终返回空列表（本项目无来源引用需求）
  - 查询重写目标改为画面要素分解短语

流式架构、SSE 事件约定、token_flush 机制与问秋月完全一致，不重复说明。

SSE 事件约定：
  token        {text: str}
  thinking     {text: str}
  thinking_flush {}
  token_flush  {}
  tool_start   {tool: str, query: str}
  tool_done    {tool: str, found: bool, count: int}
  answer       {sources: []}
  error        {message: str}
"""

from __future__ import annotations

import json
import re
import sys
from typing import Optional

from openai import OpenAI

from prompt_agent.prompts import get_system_prompt, QUERY_REWRITE_PROMPT
from core.tools import execute_web_search, limit_tool_result_for_history

# ── 防重复搜索常量 ────────────────────────────────────────────────
# 信息增量停滞检测：某轮搜索新增的「未见过」标签少于此阈值，记为一次停滞轮
_STAGNATION_MIN_NEW = 3
# 连续停滞轮次达到此值时，提前结束 Agent 探索并强制收尾输出
_STAGNATION_LIMIT = 2
# 单次工具返回中「新标签占比」低于此值时，向模型回灌"该方向已充分覆盖"的提示
_LOW_NOVELTY_RATIO = 0.34
# 搜索结果前 K 名若命中用户已提供标签，判定为「重搜已覆盖概念」并回灌提示
_PROVIDED_TOPK = 3

# ── 用户已提供标签的确定性抽取（移植自 ComfyUI-NewBie-LLM-Formatter） ──

_PROVIDED_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_().:'+\-]*$")


def _normalize_tag(tag: str) -> str:
    """归一化标签用于比较：小写、去转义括号、空格→下划线。"""
    t = (tag or "").strip().lower()
    t = t.replace("\\(", "(").replace("\\)", ")")
    t = t.replace(" ", "_")
    return t


def _extract_provided_tags(text: str) -> list[str]:
    """从用户原始输入中确定性地抽取已提供的 Danbooru 标签。

    按逗号/顿号/换行切分，凡是「无空格的全小写 token」即视为用户已提供标签。
    自然语言（中文、含空格的英文短句）不会被误抽。返回保序去重的标签列表。
    """
    provided = []
    seen = set()
    for chunk in re.split(r"[,\n，、]", text):
        tok = chunk.strip()
        if not tok or len(tok) < 2 or " " in tok:
            continue
        if _PROVIDED_TAG_RE.match(tok.lower()):
            key = _normalize_tag(tok)
            if key and key not in seen:
                seen.add(key)
                provided.append(tok)
    return provided


def _extract_tag_names(result_str: str) -> set[str]:
    """从工具返回的 JSON 中提取标签名集合，用于信息增量统计。"""
    try:
        data = json.loads(result_str)
    except Exception:
        return set()
    prompt = data.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return {t.strip() for t in prompt.split(",") if t.strip()}
    return {
        (t.get("tag") or "").strip()
        for t in data.get("results", [])
        if (t.get("tag") or "").strip()
    }


def _extract_tag_list(result_str: str) -> list[str]:
    """保序提取标签列表。prompt 字段按匹配强度降序，供前 K 名判据使用。"""
    try:
        data = json.loads(result_str)
    except Exception:
        return []
    prompt = data.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return [t.strip() for t in prompt.split(",") if t.strip()]
    return [
        (t.get("tag") or "").strip()
        for t in data.get("results", [])
        if (t.get("tag") or "").strip()
    ]


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
from prompt_agent.tools import (
    TOOLS,
    execute_search_tags,
    execute_get_related_tags,
    execute_get_artist_recommendations,
    execute_get_artist_profile,
    execute_get_anima_format,
    execute_get_newbie_format,
)


_WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "补充角色服饰、发色、作品、相关背景等公开知识。"
            "仅用于背景知识，严禁把搜索结果当作 Danbooru 标签或标签来源。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "需要补充背景知识的搜索关键词"},
            },
            "required": ["query"],
        },
    },
}


def _get_tools(include_web_search: bool = True) -> list[dict]:
    """返回 Prompt Agent 当前请求可用的 MCP 工具和可选 Tavily 工具。"""
    tools = [tool for tool in TOOLS if tool["function"].get("name") != "web_search"]
    if include_web_search:
        tools.append(_WEB_SEARCH_TOOL)
    return tools

MAX_ROUNDS = 10

_TITLE_PROMPT = """请用不超过10个字概括这段对话的主题，作为文件标题。
只输出标题本身，不要引号、标点或任何解释。

对话内容：
{conversation}"""

_IMMERSION_INJECTION = """
<system_rule> 请务必使用用户提问的语言进行思考，推理，并回答用户的问题 </system_rule>"""


_TITLE_META_RE = re.compile(
    r"^(?:the user (?:wants|asks|is asking|would like)|"
    r"the conversation (?:is|asks|concerns)|this conversation|"
    r"user (?:wants|asks)|we need|i need|i should|"
    r"用户(?:想要|希望|询问|要求)|我需要|这段对话|标题应该)",
    re.IGNORECASE,
)


def _title_content_text(content, first_text_part: bool = False) -> str:
    """从纯文本或 OpenAI 多模态 content 中提取标题所需的可见文本。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    texts = [
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
    ]
    if first_text_part:
        return texts[0] if texts else ""
    return "\n".join(texts)


def _title_history_text(message: dict) -> str:
    """只保留标题生成需要的用户/助手可见文本，排除图片和内部注入。"""
    role = message.get("role")
    if role not in {"user", "assistant"}:
        return ""

    content = message.get("content")
    text = _title_content_text(
        content,
        first_text_part=role == "user" and isinstance(content, list),
    )
    if role == "user":
        match = re.search(r"<user_message>\s*([\s\S]*?)\s*</user_message>", text)
        if match:
            text = match.group(1)
        for marker in ("【画面要素分解参考", "【用户已提供标签", "【角色沉浸要求】", "<system_rule>"):
            text = text.split(marker, 1)[0]
        text = re.sub(r"\s*请生成(?:SDXL|Anima|NewBie)格式的提示词\s*$", "", text)

    return re.sub(r"\s+", " ", text).strip()[:200]


def _fallback_title(history: list[dict]) -> str:
    """标题模型输出不可用时，用首条用户可见文本生成稳定的本地标题。"""
    for message in history:
        if message.get("role") != "user":
            continue
        text = _title_history_text(message)
        if text:
            return text[:20]
    return "对话"


def _normalize_generated_title(raw_title: str, fallback: str) -> str:
    """清理标题输出，并拒绝把模型的元分析/思考句当作标题。"""
    lines = [line.strip() for line in str(raw_title or "").splitlines() if line.strip()]
    if not lines:
        return fallback

    title = lines[-1]
    title = re.sub(r"^(?:标题|主题)\s*[:：]\s*", "", title)
    title = title.strip(" `#*\"'“”‘’「」『』")
    title = re.sub(r"[。.!！?？]+$", "", title).strip()
    if not title or _TITLE_META_RE.match(title):
        return fallback
    return title[:20]


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
        deepseek_api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        tavily_api_key: Optional[str] = None,
        verbose: bool = False,
        debug: bool = False,
    ):
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

    # ── 对话标题生成 ───────────────────────────────────────────────────

    def generate_title(self, history: list[dict], thinking: bool = False) -> tuple[str, dict | None]:
        """根据对话历史生成一个简短标题（~10字）。返回 (title, usage)。"""
        recent = history[-20:] if len(history) > 20 else history
        parts = []
        for msg in recent:
            role_name = msg.get("role")
            if role_name not in {"user", "assistant"}:
                continue
            role = "用户" if role_name == "user" else "助手"
            text = _title_history_text(msg)
            if text:
                parts.append(f"{role}：{text}")
        conversation = "\n".join(parts)
        fallback = _fallback_title(history)
        if not conversation:
            print("[title] conversation 为空，history 长度:", len(history), file=sys.stderr, flush=True)
            return fallback, None

        try:
            resp = self.llm.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": _TITLE_PROMPT.format(conversation=conversation)}],
                temperature=0.3,
                max_tokens=30,
                # 标题是短文本辅助任务，固定关闭思考，避免 reasoning/元分析污染标题。
                extra_body=get_platform_settings(self.base_url, self.model, False),
            )
            title = _normalize_generated_title(resp.choices[0].message.content, fallback)
            usage = resp.usage
            print(f"[title] LLM 返回: {title!r}", file=sys.stderr, flush=True)
            return title, usage
        except Exception as e:
            print(f"[title] LLM 调用异常: {e}", file=sys.stderr, flush=True)
            return fallback, None

    # ── 画面描述重写 ───────────────────────────────────────────────────

    def rewrite_query(self, question: str, thinking: bool = False) -> list[str]:
        """将用户的完整画面描述分解为适合独立检索的要素短语列表。"""
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
                extra_body=get_platform_settings(self.base_url, self.model, thinking),
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.strip("```json").strip("```").strip()
            variants = json.loads(raw)
            if isinstance(variants, list):
                result = [str(v) for v in variants if v]
                self._log(f"画面要素重写: {result}")
                return result
        except Exception as e:
            self._log(f"查询重写失败（已跳过）: {e}")
        return []

    # ── Tool 执行 ──────────────────────────────────────────────────────

    def _execute_tool(self, name: str, args: dict, web_search: bool = True) -> str:
        if name == "search_tags":
            return execute_search_tags(
                query=str(args.get("query", "")),
                search_mode=str(args.get("search_mode", "full_scene")),
                show_nsfw=bool(args.get("show_nsfw", True)),
                include_wiki=bool(args.get("include_wiki", False)),
                category=str(args.get("category", "all")),
            )
        elif name == "get_related_tags":
            tags = args.get("tags", [])
            if isinstance(tags, str):
                # LLM 偶尔会把数组序列化为字符串，容错处理
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
            return execute_get_related_tags(
                tags=tags,
                limit=int(args.get("limit", 30)),
                show_nsfw=bool(args.get("show_nsfw", True)),
                include_wiki=bool(args.get("include_wiki", False)),
            )
        elif name == "get_artist_recommendations":
            tags = args.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
            return execute_get_artist_recommendations(
                tags=tags,
                limit=int(args.get("limit", 30)),
                min_cooc=int(args.get("min_cooc", 3)),
                show_nsfw=bool(args.get("show_nsfw", True)),
            )
        elif name == "get_artist_profile":
            return execute_get_artist_profile(
                artist_name=str(args.get("artist_name", "")),
                top_n=int(args.get("top_n", 20)),
                show_nsfw=bool(args.get("show_nsfw", True)),
            )
        elif name == "get_anima_format":
            return execute_get_anima_format()
        elif name == "get_newbie_format":
            return execute_get_newbie_format()
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
            return execute_web_search(str(args.get("query", "")), self.tavily)
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
        返回：(finish_reason, reasoning_content, content, tool_calls, usage)
        """
        if callable(cancel_check):
            cancel_check()

        tools = _get_tools(web_search)
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
            extra_body=get_platform_settings(self.base_url, self.model, thinking),
        )

        reasoning_chunks: list[str] = []
        content_chunks: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
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

            if delta.content:
                if not prefix_printed:
                    print("\n秋枫：", end="", flush=True)
                    prefix_printed = True
                content_chunks.append(delta.content)
                print(delta.content, end="", flush=True)
                self._emit("token", {"text": delta.content}, on_event)

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
        输入用户画面描述和对话历史，返回：
        {
            "answer":  "回答文本（含结构化 prompt）",
            "sources": []   # 本项目无来源引用，始终为空列表
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

        # 1. 构建初始 messages：system + 完整历史 + 当前用户消息
        messages = [{"role": "system", "content": get_system_prompt(web_search=web_search)}]
        if history:
            messages.extend(history)

        is_first_turn = not history
        if is_multimodal:
            # 多模态：直接使用 content 数组，重写结果和沉浸注入作为额外 text part 追加
            user_content = list(question)
            if is_first_turn and len(text_question) > 10:
                rewrite_queries = self.rewrite_query(text_question, thinking=thinking)
                if rewrite_queries:
                    user_content.append({"type": "text", "text": (
                        f"\n\n【画面要素分解参考（仅供内部规划，不对用户显示）】\n"
                        + "\n".join(f"- {q}" for q in rewrite_queries)
                    )})
            if is_first_turn:
                user_content.append({"type": "text", "text": _IMMERSION_INJECTION})
        else:
            # 纯文本：保持原有 XML 包装
            user_content = f"<user_message>\n{question}\n</user_message>\n\n **务必调用工具搜索，以获得准确回答** "
            if is_first_turn:
                if len(question) > 10:
                    rewrite_queries = self.rewrite_query(question, thinking=thinking)
                    if rewrite_queries:
                        user_content += (
                            f"\n\n【画面要素分解参考（仅供内部规划，不对用户显示）】\n"
                            + "\n".join(f"- {q}" for q in rewrite_queries)
                        )
                user_content += _IMMERSION_INJECTION

        if callable(cancel_check):
            cancel_check()

        # 用户已提供标签：确定性抽取（正则）+ 查询重写的 [已有] 标记
        provided_list = _extract_provided_tags(text_question)
        provided_norm = {_normalize_tag(t) for t in provided_list}
        if provided_list:
            self._log(f"确定性抽取到用户已提供标签 {len(provided_list)} 个，将禁止重复检索")
            if is_multimodal:
                # 多模态：追加 text part
                user_content.append({"type": "text", "text": (
                    "\n\n【用户已提供标签（直接信任，禁止检索）】\n"
                    + ", ".join(provided_list)
                    + "\n以上标签已由用户提供，直接使用，禁止检索这些标签或其变体。"
                )})
            else:
                user_content += (
                    "\n\n【用户已提供标签（直接信任，禁止检索）】\n"
                    + ", ".join(provided_list)
                    + "\n以上标签已由用户提供，直接使用，禁止检索这些标签或其变体。"
                )

        messages.append({"role": "user", "content": user_content})

        def append_message(message: dict):
            """追加上下文，并在彩蛋模式下同步这一条真实 Agent 消息。"""
            messages.append(message)
            if trace:
                self._emit("trace_message", {"message": message}, on_event)

        if trace:
            self._emit("trace_reset", {"messages": messages}, on_event)

        rounds = 0
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        duplicate_tracker: dict[str, int] = {}
        seen_tags: set[str] = set()      # 累计已见过的标签，用于信息增量统计
        stagnant_rounds = 0              # 连续低信息增量轮次计数
        stagnated = False                # 因停滞而提前结束的标志

        # 3. 流式 Tool Calling 主循环
        while rounds < MAX_ROUNDS:
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

            self._log(
                f"round={rounds}, finish_reason={finish_reason}, "
                f"reasoning_len={len(reasoning_content)}, "
                f"content_len={len(content)}, tool_calls={len(tool_calls)}"
            )

            if finish_reason == "tool_calls" and tool_calls:
                # 预先解析参数并过滤重复调用
                parsed = []
                skipped = []
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    raw_args = tc["function"]["arguments"]
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError as e:
                        self._log(f"工具参数解析失败: {name}, {raw_args}, {e}")
                        args = {}
                    # 守卫：search_tags 查询命中用户已提供标签 → 不执行，回灌"已提供"提示
                    if name == "search_tags" and provided_norm:
                        qn = _normalize_tag(str(args.get("query", "")))
                        if qn and qn in provided_norm:
                            self._log(f"搜索查询「{args.get('query', '')}」命中用户已提供标签，跳过执行")
                            skipped.append((tc, json.dumps(
                                {"skipped": "user_provided",
                                 "note": "该标签用户已提供，禁止重复搜索，直接使用用户提供的版本即可。"},
                                ensure_ascii=False)))
                            continue
                    # 守卫：完全相同的工具调用超过 3 次 → 跳过
                    call_key = name + ":" + json.dumps(args, sort_keys=True)
                    count = duplicate_tracker.get(call_key, 0) + 1
                    duplicate_tracker[call_key] = count
                    if count > 3:
                        self._log(f"检测到重复调用 {name}（第{count}次），跳过执行")
                        skipped.append((tc, json.dumps({"skipped": "duplicate"}, ensure_ascii=False)))
                        continue
                    parsed.append((tc, name, args))

                if not parsed:
                    # 所有 tool_calls 均为重复：仍需添加 assistant+tool 消息，
                    # 否则上一轮遗留的 tool_calls 无对应 response 会导致 API 400
                    append_message({
                        "role": "assistant",
                        "content": content,
                        "reasoning_content": reasoning_content,
                        "tool_calls": tool_calls,
                    })
                    for tc in tool_calls:
                        append_message({"role": "tool", "tool_call_id": tc["id"],
                                        "content": json.dumps({"skipped": "duplicate"}, ensure_ascii=False)})
                    self._log("所有 tool_calls 均为重复调用，强制退出循环")
                    break

                append_message({
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning_content,
                    "tool_calls": tool_calls,
                })

                if content.strip():
                    self._emit("token_flush", {}, on_event)

                round_returned: set[str] = set()  # 本轮所有搜索/关联返回的标签

                for tc, name, args in parsed:
                    if callable(cancel_check):
                        cancel_check()
                    self._log(f"调用工具: {name}({args})")

                    # tool_start 事件：附带查询内容、参数和完整请求体，供前端展示
                    if name == "search_tags":
                        query_str = args.get("query", "")
                        print(f"  > 搜索标签：{query_str}", flush=True)
                        self._emit("tool_start", {
                            "tool": "search_tags",
                            "query": query_str,
                            "args": args,
                            "params": {
                                "search_mode": str(args.get("search_mode", "full_scene")),
                                "category": str(args.get("category", "all")),
                                "nsfw": bool(args.get("show_nsfw", False)),
                                "wiki": bool(args.get("include_wiki", False)),
                            },
                        }, on_event)
                    elif name == "get_related_tags":
                        tags = args.get("tags", [])
                        if isinstance(tags, str):
                            try:
                                tags = json.loads(tags)
                            except Exception:
                                tags = [t.strip() for t in tags.split(",") if t.strip()]
                        tags_preview = ", ".join(tags[:5])
                        print(f"  > 关联推荐：{tags_preview}", flush=True)
                        self._emit("tool_start", {
                            "tool": "get_related_tags",
                            "query": tags_preview,
                            "args": args,
                            "params": {
                                "tags_count": len(tags),
                                "limit": int(args.get("limit", 30)),
                                "wiki": bool(args.get("include_wiki", False)),
                            },
                        }, on_event)
                    elif name == "get_artist_recommendations":
                        tags = args.get("tags", [])
                        if isinstance(tags, str):
                            try:
                                tags = json.loads(tags)
                            except Exception:
                                tags = [t.strip() for t in tags.split(",") if t.strip()]
                        tags_preview = ", ".join(tags[:5])
                        print(f"  > 画师推荐：{tags_preview}", flush=True)
                        self._emit("tool_start", {
                            "tool": "get_artist_recommendations",
                            "query": tags_preview,
                            "args": args,
                            "params": {
                                "tags_count": len(tags),
                                "limit": int(args.get("limit", 30)),
                            },
                        }, on_event)
                    elif name == "get_artist_profile":
                        artist_name = str(args.get("artist_name", ""))
                        print(f"  > 画师画像：{artist_name}", flush=True)
                        self._emit("tool_start", {
                            "tool": "get_artist_profile",
                            "query": artist_name,
                            "args": args,
                            "params": {
                                "top_n": int(args.get("top_n", 20)),
                                "nsfw": bool(args.get("show_nsfw", True)),
                            },
                        }, on_event)
                    elif name == "get_anima_format":
                        print(f"  > 获取 Anima 提示词格式规范", flush=True)
                        self._emit("tool_start", {
                            "tool": "get_anima_format",
                            "query": "Anima 格式规范",
                            "args": args,
                            "params": {},
                        }, on_event)
                    elif name == "get_newbie_format":
                        print(f"  > 获取 NewBie 提示词格式规范", flush=True)
                        self._emit("tool_start", {
                            "tool": "get_newbie_format",
                            "query": "NewBie 格式规范",
                            "args": args,
                            "params": {},
                        }, on_event)
                    elif name == "web_search":
                        query_str = str(args.get("query", ""))
                        print(f"  > 补充互联网知识：{query_str}", flush=True)
                        self._emit("tool_start", {
                            "tool": "web_search",
                            "query": query_str,
                            "args": args,
                            "params": {},
                        }, on_event)
                    else:
                        print(f"  > 调用工具：{name}", flush=True)
                        self._emit("tool_start", {"tool": name, "query": "", "args": args, "params": {}}, on_event)

                    result = limit_tool_result_for_history(
                        self._execute_tool(name, args, web_search=web_search)
                    )
                    if callable(cancel_check):
                        cancel_check()

                    # tool_done 事件
                    if name in ("get_anima_format", "get_newbie_format"):
                        label = "Anima" if name == "get_anima_format" else "NewBie"
                        print(f"    {label} 格式规范已获取", flush=True)
                        self._emit("tool_done", {"tool": name, "found": True, "count": 1, "result": result}, on_event)
                    else:
                        # 泛化结果提取：兼容 search_tags({tags:...}) 和 get_related_tags({results:...}) 两种格式
                        try:
                            data = json.loads(result)
                            if isinstance(data, dict) and data.get("truncated"):
                                found = bool(data.get("found", False))
                                hit = int(data.get("result_count", 0))
                            elif isinstance(data, dict):
                                items = data.get("results", data.get("tags", data.get("top_tags", [])))
                                if "error" in data and not items:
                                    found, hit = False, 0
                                else:
                                    hit = len(items) if isinstance(items, list) else 0
                                    found = hit > 0
                            elif isinstance(data, list):
                                found, hit = len(data) > 0, len(data)
                            else:
                                found, hit = False, 0

                            if found:
                                print(f"    找到 {hit} 个结果", flush=True)
                                self._emit("tool_done", {"tool": name, "found": True, "count": hit, "result": result}, on_event)
                            else:
                                print(f"    未找到结果", flush=True)
                                self._emit("tool_done", {"tool": name, "found": False, "count": 0, "result": result}, on_event)
                        except Exception:
                            self._emit("tool_done", {"tool": name, "found": False, "count": 0, "result": result}, on_event)

                    # ── 信息增量统计与防重复回灌 ──
                    if name in ("search_tags", "get_related_tags"):
                        returned_list = _extract_tag_list(result)
                        returned = set(returned_list)
                        if returned:
                            # 已覆盖概念重搜检测：结果前 K 名命中用户已提供标签
                            if provided_norm:
                                top_hit = [
                                    t for t in returned_list[:_PROVIDED_TOPK]
                                    if _normalize_tag(t) in provided_norm
                                ]
                                if top_hit:
                                    result = result + (
                                        f"\n\n[系统提示] 本次结果中排名最靠前的标签 "
                                        f"{', '.join(top_hit)} 属于用户已提供标签，"
                                        f"说明你正在搜索用户已覆盖的概念。用户已提供的标签禁止重复检索，"
                                        f"请勿再搜索该概念，转向尚未覆盖的维度或直接输出。"
                                    )
                            # 新标签占比过低：回灌停滞信号给模型
                            new_in_call = returned - seen_tags - round_returned
                            round_returned |= returned
                            if len(new_in_call) / len(returned) < _LOW_NOVELTY_RATIO:
                                result = result + (
                                    f"\n\n[系统提示] 本次返回 {len(returned)} 个标签，"
                                    f"其中仅 {len(new_in_call)} 个为新标签，其余均已在先前轮次出现。"
                                    f"该主题/维度已充分覆盖，请勿换措辞重复搜索同一主题，"
                                    f"转向尚未覆盖的维度，或直接输出最终结果。"
                                )

                    result = limit_tool_result_for_history(result)
                    append_message({
                        "role":         "tool",
                        "tool_call_id": tc["id"],
                        "content":      result,
                    })

                # 被跳过的调用（重复 / 命中已提供标签）：写入占位 response，保证一一对应
                for tc, skip_content in skipped:
                    append_message({"role": "tool", "tool_call_id": tc["id"],
                                    "content": skip_content})

                # 信息增量停滞检测：连续多轮搜索几乎无新标签 → 提前收尾
                round_new = len(round_returned - seen_tags)
                round_had_search = len(round_returned) > 0
                seen_tags |= round_returned
                if round_had_search and round_new < _STAGNATION_MIN_NEW:
                    stagnant_rounds += 1
                    self._log(
                        f"低信息增量轮次（本轮新增 {round_new} 个标签），"
                        f"停滞计数 {stagnant_rounds}/{_STAGNATION_LIMIT}"
                    )
                else:
                    stagnant_rounds = 0

                rounds += 1

                if stagnant_rounds >= _STAGNATION_LIMIT:
                    self._log("连续低信息增量，提前结束探索，进入收尾输出")
                    stagnated = True
                    break

                continue

            print()
            # 将最终回答追加到 messages 后再返回，保证 history 完整
            append_message({
                "role": "assistant",
                "content": content,
                "reasoning_content": reasoning_content,
            })
            return {"answer": content, "sources": [], "messages": messages[1:]}

        # 因信息增量停滞而提前跳出：强制收尾输出
        if stagnated:
            self._log("因信息增量停滞提前结束，强制作答")
            append_message({
                "role":    "user",
                "content": "请根据已收集到的标签信息直接输出最终结果，禁止再调用任何工具。",
            })
            finish_reason, reasoning_content, content, _, usage = self._stream_round(
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
            return {"answer": content, "sources": [], "messages": messages[1:]}

        # 超出最大轮次，强制作答
        self._log("达到最大轮次，强制作答")
        append_message({
            "role":    "user",
            "content": "请根据已收集到的标签信息直接输出最终结果，禁止再调用任何工具。",
        })
        finish_reason, reasoning_content, content, _, usage = self._stream_round(
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
        return {"answer": content, "sources": [], "messages": messages[1:]}
