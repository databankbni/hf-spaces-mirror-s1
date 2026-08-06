"""
OpenAI-compatible async adapter.
"""

import ast
import asyncio
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Union

from .base import BaseLLM, ChatMessage, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OpenAIAdapter(BaseLLM):
    def __init__(
        self,
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        fallback_models = kwargs.pop("fallback_models", None)
        self.request_timeout = kwargs.pop("request_timeout", 180.0)
        # chunk-level timeout: 单次 chunk 读取超时. 检测 "LLM API 接受请求但持续不发新 chunk" 的挂起.
        # 默认 60s (agnes-2.0-flash TTFT 7-40s, 留足余量; 真挂起 60s 内能检测到).
        self.chunk_timeout = kwargs.pop("chunk_timeout", 60.0)
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        self.api_key = api_key
        self.base_url = base_url
        self.organization = organization
        self.fallback_models = [
            item for item in (fallback_models or []) if isinstance(item, str) and item
        ]
        self._client = None

    def _sanitize_request_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(params)
        cleaned.pop("request_timeout", None)
        cleaned.pop("timeout", None)
        return cleaned

    def _get_client(self):
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "OpenAI adapter requires the 'openai' package. "
                "Install it with: pip install agentflow[openai]"
            ) from e

        if self._client is None:
            client_kwargs: Dict[str, Any] = {}
            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            if self.organization:
                client_kwargs["organization"] = self.organization
            if self.request_timeout:
                client_kwargs["timeout"] = self.request_timeout
            self._client = AsyncOpenAI(**client_kwargs)
        return self._client

    def close(self):
        if self._client is not None:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._client.close())
                else:
                    asyncio.run(self._client.close())
            except Exception:
                pass
            self._client = None

    @staticmethod
    def _invalid_response_error(status: Any, message: Any) -> RuntimeError:
        status_text = str(status) if status is not None else ""
        message_text = str(message) if message is not None else ""
        normalized_message = message_text.lower()
        if status_text == "439" or "api token has expired" in normalized_message:
            return RuntimeError("模型服务 API Token 已过期，请更新 `.env` 中的 `API_KEY`。")

        detail_parts = []
        if status is not None:
            detail_parts.append(f"status={status}")
        if message:
            detail_parts.append(f"message={message}")
        if detail_parts:
            return RuntimeError(
                "OpenAI-compatible API returned an invalid completion response: "
                + ", ".join(detail_parts)
            )
        return RuntimeError("OpenAI-compatible API returned no completion choices.")

    @staticmethod
    def _raise_for_invalid_response(response: Any) -> None:
        choices = getattr(response, "choices", None)
        if choices:
            return

        status = getattr(response, "status", None)
        message = getattr(response, "msg", None) or getattr(response, "message", None)
        raise OpenAIAdapter._invalid_response_error(status, message)

    @staticmethod
    def _coerce_tool_arguments(arguments_text: str) -> Union[str, Dict[str, Any]]:
        stripped = arguments_text.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        try:
            parsed = ast.literal_eval(stripped)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass
        return stripped

    @staticmethod
    def _normalize_text_tool_name(raw_name: str) -> str:
        stripped = raw_name.strip()
        match = re.match(r"^([A-Za-z0-9_.-]+?)(?::\d+)?$", stripped)
        return match.group(1) if match else stripped

    @classmethod
    def _tool_call_from_mapping(
        cls,
        payload: Dict[str, Any],
        *,
        default_id: str,
    ) -> Optional[ToolCall]:
        raw_name = payload.get("tool_name") or payload.get("tool") or payload.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return None

        arguments = payload.get("arguments")
        if arguments is None:
            arguments = payload.get("parameters")
        if arguments is None:
            arguments = payload.get("args")
        if isinstance(arguments, str):
            arguments = cls._coerce_tool_arguments(arguments)
        if arguments is None:
            arguments = {}

        call_id = payload.get("tool_call_id") or payload.get("id") or default_id
        return ToolCall(
            id=str(call_id),
            name=cls._normalize_text_tool_name(raw_name),
            arguments=arguments,
        )

    @classmethod
    def _extract_block_arguments(cls, block_content: str) -> Dict[str, Any]:
        """Extract arguments dict from a tool call block's content."""
        args_match = re.search(
            r'(?:args|arguments|parameters)\s*[:=]>?\s*(\{.*\}|\[.*\])',
            block_content,
            re.DOTALL,
        )
        if not args_match:
            return {}

        args_text = args_match.group(1)

        # Try JSON
        try:
            return json.loads(args_text)
        except json.JSONDecodeError:
            pass

        # Try normalizing => to : and parse as JSON
        normalized = args_text.replace("=>", ":")
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            pass

        # Try ast.literal_eval
        try:
            parsed = ast.literal_eval(args_text)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass

        # Try CLI-style parsing (--key value)
        cli_args = re.findall(r'--([\w-]+)\s+(".*?"|\S+)', args_text)
        if cli_args:
            result: Dict[str, Any] = {}
            for key, value in cli_args:
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                result[key] = value
            return result

        return {}

    @classmethod
    def _parse_tool_call_block(cls, block_content: str, default_id: str = "text-tool-call-1") -> Optional[ToolCall]:
        """Parse a [TOOL_CALL]...[/TOOL_CALL] block into a ToolCall."""
        # Try JSON first
        try:
            parsed = json.loads(block_content)
            if isinstance(parsed, dict):
                return cls._tool_call_from_mapping(parsed, default_id=default_id)
        except json.JSONDecodeError:
            pass

        # Try normalizing => to : and parse as JSON
        normalized = block_content.replace("=>", ":")
        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                return cls._tool_call_from_mapping(parsed, default_id=default_id)
        except json.JSONDecodeError:
            pass

        # Extract tool name using regex
        name_match = re.search(
            r'(?:tool|name|function)\s*[:=]>?\s*["\']?([A-Za-z0-9_.-]+)["\']?',
            block_content,
        )
        if not name_match:
            return None

        tool_name = cls._normalize_text_tool_name(name_match.group(1))
        arguments = cls._extract_block_arguments(block_content)

        return ToolCall(id=default_id, name=tool_name, arguments=arguments)

    @classmethod
    def _extract_text_tool_calls(cls, content: str) -> Optional[List[ToolCall]]:
        stripped_content = content.strip()
        if not stripped_content:
            return None

        # 1. Try to parse entire content as JSON
        try:
            parsed = json.loads(stripped_content)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            tool_call = cls._tool_call_from_mapping(parsed, default_id="text-tool-call-1")
            if tool_call is not None:
                return [tool_call]
        elif isinstance(parsed, list):
            tool_calls_from_list: List[ToolCall] = []
            for index, item in enumerate(parsed):
                if not isinstance(item, dict):
                    continue
                tool_call = cls._tool_call_from_mapping(item, default_id=f"text-tool-call-{index + 1}")
                if tool_call is not None:
                    tool_calls_from_list.append(tool_call)
            if tool_calls_from_list:
                return tool_calls_from_list

        tool_calls: List[ToolCall] = []

        # 2. Extract [TOOL_CALL] blocks with tolerant closing-tag matching
        from .tool_call_extractor import extract_tool_call_blocks
        tolerant_blocks = extract_tool_call_blocks(stripped_content)
        if tolerant_blocks:
            for index, block_content in enumerate(tolerant_blocks):
                tool_call = cls._parse_tool_call_block(block_content, default_id=f"text-tool-call-{index + 1}")
                if tool_call is not None:
                    tool_calls.append(tool_call)
            if tool_calls:
                return tool_calls

        # 2b. Fallback: strict regex for [TOOL_CALL]...[/TOOL_CALL]
        block_pattern = re.compile(r"\[TOOL_CALL\]\s*(.*?)\s*\[/TOOL_CALL\]", re.DOTALL | re.IGNORECASE)
        for index, match in enumerate(block_pattern.finditer(stripped_content)):
            block_content = match.group(1).strip()
            tool_call = cls._parse_tool_call_block(block_content, default_id=f"text-tool-call-{index + 1}")
            if tool_call is not None:
                tool_calls.append(tool_call)
        if tool_calls:
            return tool_calls

        # 3. Match [Tool Call] name arguments=... pattern (agentflow internal format)
        pattern = re.compile(r"^\[Tool Call\]\s+([A-Za-z0-9_.-]+)(?::\d+)?(?:\s+arguments=|\s+)(.+)$")
        for index, raw_line in enumerate(stripped_content.splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match is None:
                continue
            tool_calls.append(
                ToolCall(
                    id=f"text-tool-call-{index + 1}",
                    name=cls._normalize_text_tool_name(match.group(1)),
                    arguments=cls._coerce_tool_arguments(match.group(2)),
                )
            )
        return tool_calls or None

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        message = str(exc)
        return "status=449" in message or "status=429" in message or "rate limit" in message.lower()

    async def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> LLMResponse:
        client = self._get_client()
        params = self._sanitize_request_params(self._merge_kwargs(**kwargs))
        params["messages"] = self._convert_messages(messages)
        if tools:
            params["tools"] = tools

        response = None
        last_error: Optional[Exception] = None
        candidate_models = [self.model, *[item for item in self.fallback_models if item != self.model]]
        for attempt in range(3):
            active_model = candidate_models[min(attempt, len(candidate_models) - 1)]
            try:
                response = await client.chat.completions.create(**{**params, "model": active_model})
                self._raise_for_invalid_response(response)
                break
            except Exception as exc:
                last_error = exc
                if attempt >= 2 or not self._is_retryable_error(exc):
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))

        if response is None:
            raise last_error or RuntimeError("OpenAI-compatible API returned no completion response.")

        choice = response.choices[0]
        message = choice.message

        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        tool_calls = None
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in message.tool_calls
            ]

        if tool_calls is None and isinstance(message.content, str):
            tool_calls = self._extract_text_tool_calls(message.content)

        return LLMResponse(
            content=message.content or "",
            finish_reason="tool_calls" if tool_calls else (choice.finish_reason or "unknown"),
            usage=usage,
            model=response.model,
            tool_calls=tool_calls,
        )

    async def chat_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> LLMResponse:
        client = self._get_client()
        params = self._sanitize_request_params(self._merge_kwargs(**kwargs))
        params["messages"] = self._convert_messages(messages)
        params["stream"] = True
        if tools:
            params["tools"] = tools

        stream = None
        last_error: Optional[Exception] = None
        candidate_models = [self.model, *[item for item in self.fallback_models if item != self.model]]
        for attempt in range(3):
            active_model = candidate_models[min(attempt, len(candidate_models) - 1)]
            try:
                t_req = time.time()
                logger.info(
                    f"[chat_stream] POSTing to LLM model={active_model} msgs={len(messages)} "
                    f"tools={len(tools) if tools else 0} attempt={attempt+1}"
                )
                stream = await client.chat.completions.create(**{**params, "model": active_model})
                logger.info(f"[chat_stream] LLM stream opened in {time.time()-t_req:.2f}s")
                if hasattr(stream, "choices") and not hasattr(stream, "__aiter__"):
                    self._raise_for_invalid_response(stream)
                break
            except Exception as exc:
                last_error = exc
                if attempt >= 2 or not self._is_retryable_error(exc):
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))

        if stream is None:
            raise last_error or RuntimeError("OpenAI-compatible API returned no streaming response.")

        full_content = ""
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
        has_tool_calls = False
        first_chunk_t: Optional[float] = None
        chunk_count = 0
        # reasoning (thinking) 状态跟踪
        # ollama qwen3/deepseek-r1 等模型通过 delta.reasoning 返回思考内容 (非 delta.content)
        # agentflow 将其包装为 <think>...</think> 标签, 让前端以 think 块渲染
        in_reasoning = False
        reasoning_chunks = 0

        # chunk-level timeout: 检测 LLM API 接受请求但持续不发新 chunk 的挂起.
        # 不用 async for 是因为它没有 per-chunk 超时机制, LLM 挂起时会永远阻塞.
        # 用 asyncio.wait_for 包 __anext__ 让单次 chunk 读取有超时,
        # 超时抛 RuntimeError 向上冒泡, 触发 _run_stream_decoupled 的 except 分支
        # 发 error + done 事件, 前端 isStreaming 正常清掉.
        while True:
            try:
                chunk = await asyncio.wait_for(stream.__anext__(), timeout=self.chunk_timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"LLM stream chunk timeout: no chunk received in {self.chunk_timeout}s "
                    f"(model={active_model}, chunks_so_far={chunk_count}, "
                    f"t_since_req={time.time()-t_req:.2f}s)"
                )
            if first_chunk_t is None:
                first_chunk_t = time.time()
                logger.info(f"[chat_stream] first chunk arrived {time.time()-t_req:.2f}s after request")
            chunk_count += 1
            if not chunk.choices or not chunk.choices[0].delta:
                continue

            delta = chunk.choices[0].delta

            # 读取 reasoning 字段 (ollama 用 delta.reasoning, deepseek 用 delta.reasoning_content)
            # openai SDK 可能将非标准字段存于 model_extra, 需多处查找
            reasoning_text = (
                getattr(delta, "reasoning", None)
                or getattr(delta, "reasoning_content", None)
                or (delta.model_extra.get("reasoning") if hasattr(delta, "model_extra") and delta.model_extra else None)
                or (delta.model_extra.get("reasoning_content") if hasattr(delta, "model_extra") and delta.model_extra else None)
            )
            if reasoning_text:
                if not in_reasoning:
                    in_reasoning = True
                    if on_token:
                        on_token("<think>")
                reasoning_chunks += 1
                if on_token:
                    on_token(reasoning_text)

            if delta.tool_calls:
                # 从 reasoning 切换到 tool_calls, 先关闭 think 标签
                if in_reasoning:
                    in_reasoning = False
                    if on_token:
                        on_token("</think>")
                has_tool_calls = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_buffer[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_buffer[idx]["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_buffer[idx]["arguments"] += tc.function.arguments
            elif delta.content:
                # 从 reasoning 切换到 content, 先关闭 think 标签
                if in_reasoning:
                    in_reasoning = False
                    if on_token:
                        on_token("</think>")
                full_content += delta.content
                if on_token:
                    on_token(delta.content)

        # 流结束: 如果还在 reasoning 模式 (模型只输出 thinking 无正文), 关闭 think 标签
        if in_reasoning and on_token:
            on_token("</think>")

        logger.info(
            f"[chat_stream] stream finished: chunks={chunk_count} "
            f"content_len={len(full_content)} reasoning_chunks={reasoning_chunks} "
            f"tool_calls={len(tool_calls_buffer) if has_tool_calls else 0} "
            f"duration={time.time()-t_req:.2f}s"
        )

        tool_calls_list = None
        if has_tool_calls and tool_calls_buffer:
            tool_calls_list = []
            for idx in sorted(tool_calls_buffer.keys()):
                data = tool_calls_buffer[idx]
                tool_calls_list.append(
                    ToolCall(
                        id=data["id"],
                        name=data["name"],
                        arguments=data["arguments"],
                    )
                )

        if not has_tool_calls and full_content:
            tool_calls_list = self._extract_text_tool_calls(full_content)
            if tool_calls_list:
                has_tool_calls = True

        if not has_tool_calls and not full_content.strip():
            logger.warning(
                f"[chat_stream] LLM returned EMPTY content (no tool_calls, content='') on model={active_model}, "
                f"messages_count={len(messages)}, last_msg_role={messages[-1].role if messages else 'none'}, "
                f"last_msg_content_preview={repr(messages[-1].content)[:200] if messages else 'none'}"
            )
            for fallback_try in range(2):
                logger.warning(f"[chat_stream] fallback_try={fallback_try}, calling non-stream chat...")
                fallback_response = await self.chat(messages, tools=tools, **kwargs)
                logger.warning(
                    f"[chat_stream] fallback result: has_tool_calls={fallback_response.has_tool_calls()}, "
                    f"content_len={len(fallback_response.content)}, content_preview={repr(fallback_response.content)[:200]}, "
                    f"finish_reason={fallback_response.finish_reason}"
                )
                if fallback_response.has_tool_calls():
                    return fallback_response
                if fallback_response.content.strip():
                    if on_token:
                        on_token(fallback_response.content)
                    return fallback_response
                if fallback_try == 0:
                    await asyncio.sleep(2.0)
                    continue
            logger.error(
                f"[chat_stream] LLM returned EMPTY even after 2 fallback retries. "
                f"messages_count={len(messages)}, last_user_msg={repr(messages[-1].content)[:300] if messages else 'none'}"
            )
            raise RuntimeError("OpenAI-compatible API returned an empty completion response.")

        return LLMResponse(
            content=full_content,
            finish_reason="tool_calls" if has_tool_calls else "stop",
            tool_calls=tool_calls_list,
        )

    @property
    def client(self) -> Any:
        return self._client
