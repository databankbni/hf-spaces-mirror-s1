from typing import Optional, List, Union, Any, Tuple, Dict
from datetime import datetime
import asyncio
import logging
import threading
import time
import copy
import json

from ._execution import ProcessorExecutors
from .async_bridge import run_async as _bridge_run_async, AsyncBridgeError
from .content_protocol import strip_hidden_trace_blocks, strip_tool_call_markers
from .processor import Processor, PostProcessFunc
from .packet import InfoPacket, PacketType
from .id_generator import IDGenerator
from .llm.base import BaseLLM, ChatMessage, MessageRole, LLMResponse
from .plugins.callback_plugin import CallbackPlugin
from .plugins.memory_plugin import MemoryPlugin
from .plugins.allmodel_plugin import AllModelPlugin
from .plugins.context_rollover_plugin import ContextRolloverPlugin
from .plugins.reasoning_filter_plugin import ReasoningFilterPlugin
from .plugins.skill_plugin import SkillPlugin
from .specs import AgentSpec, BuiltinProcessorConfig, LLMConfig, PluginConfig, build_llm_from_config


class Agent(Processor):
    """Agent：调用 LLM 并支持工具调用的 Processor

    ════════════════════════════════════════════════════════════════
    架构设计：工具调用流程（异步消息收发模式，非同步阻塞）
    ════════════════════════════════════════════════════════════════

    1. 用户消息进入 Agent → _process → stream_process → LLM 第一次调用
    2. LLM 返回工具调用 → stream_process 构建 CALL 包返回
    3. _process 将 CALL 包通过 _output_to_list 发给工具 Processor
       - _output_to_list 用 target.input(call_packet) 异步发送，不等待
       - CALL 包同时转发到 _to_list 下游（StreamCollector 用于流式显示）
    4. 工具 Processor 异步执行，通过 CallbackPlugin 将 RESPONSE 包
       发回 Agent 的 input()（回流机制，通过 requester 元数据标识）
    5. Agent 的 _process 收到 RESPONSE/ERROR 包 → 走正常流程
       - ToolEventPlugin（pre_process）：转发给 StreamCollector，前端实时展示
       - AllModelPlugin（pre_process）：并行工具调用时聚合所有 RESPONSE
       - MemoryPlugin（pre_process）：自动存入链历史
       - core_process：构建包含工具结果的对话历史，调 LLM 生成下一轮回复
       - LLM 再返回工具调用 → 重复步骤 3-5（agentic loop）
       - LLM 返回最终回复 → 输出到下游管线 → StreamCollector 显示
    ════════════════════════════════════════════════════════════════

    关键组件：
    - _to_list：正常数据处理管线（记录、存储、下游处理）
    - _stream_to_list：流式显示分支（StreamCollector），仅展示中间状态
    - CallbackPlugin：回流插件，工具 Processor 通过 register_call_target 注册，
      工具执行完后将 RESPONSE 发回 requester（Agent）
    - MemoryPlugin：记忆插件，自动存入链历史，供 _build_messages 构建对话上下文
    - AllModelPlugin：并行批处理插件，等所有 RESPONSE 到齐后再调 LLM
    - ToolEventPlugin：监控插件，转发 RESPONSE 给 StreamCollector 用于前端展示

    注意：_output_to_list 对 CALL 包必须用 target.input() 异步发送，
    不能用 target.core_process() 同步等待，否则会绕过 CallbackPlugin 回流机制。
    """

    def __init__(
        self,
        name: str,
        llm: Optional[BaseLLM] = None,
        llm_config: Optional[Union[LLMConfig, Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        stream_mode: bool = False,
        description: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        force_tool_choice_on_first_turn: bool = False,
    ):
        super().__init__(name)
        self.llm = llm
        self.llm_config = llm_config if isinstance(llm_config, LLMConfig) else LLMConfig.from_dict(llm_config)
        self.system_prompt = system_prompt
        self.stream_mode = stream_mode
        self.description = description
        self._schema = schema
        self.force_tool_choice_on_first_turn = force_tool_choice_on_first_turn
        self._call_targets: List[Processor] = []
        self._pending_calls: dict = {}
        self._stream_to_list: List['Processor'] = []

        self.add_post_process(self._route_call_packet)

    def to(self, processors: Union['Processor', List['Processor']], stream: bool = False, allow_loop: bool = False) -> 'Agent':
        """添加下游处理器，同时支持普通和流式输出"""
        if isinstance(processors, Processor):
            processors = [processors]
        for p in processors:
            if not allow_loop:
                self._check_circular_call(p)
            self._to_list.append(p)
            self._stream_to_list.append(p)
        return self

    def register_call_target(self, processor: 'Processor') -> 'Agent':
        if any(existing.name == processor.name for existing in self._call_targets):
            return self

        self._call_targets.append(processor)

        callback_plugins = processor.get_plugins(CallbackPlugin)
        if callback_plugins:
            callback_plugins[0].set_callback_target(self)
        else:
            callback_plugin = CallbackPlugin()
            callback_plugin.set_callback_target(self)
            processor.add_plugin(callback_plugin)

        return self

    def _run_async(self, coro):
        """
        运行异步协程

        通过统一的异步桥接机制执行，支持超时和错误分类。
        """
        try:
            return _bridge_run_async(coro, timeout=self._timeout, context=f"Agent.{self.name}")
        except AsyncBridgeError:
            raise

    def _run_with_retries(self, func):
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return func()
            except Exception as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    raise
        raise last_error or RuntimeError("Agent execution failed.")

    def _route_call_packet(self, packet: InfoPacket, output_list: List['Processor']) -> Tuple[InfoPacket, List['Processor']]:
        """路由CALL包到对应的工具Processor

        检查包内容中的tool_name或tool，找到匹配的call_target并添加到output_list。
        如果工具不在当前Agent的可用工具列表中，返回ERROR包。
        """
        if packet.type == PacketType.CALL:
            content = packet.content
            if isinstance(content, dict):
                # 支持 tool_name 或 tool 键
                tool_name = content.get('tool_name') or content.get('tool')
                if tool_name:
                    target = next((p for p in self._call_targets if p.name == tool_name), None)
                    if target is not None:
                        # CALL 包默认只路由到目标处理器，不泄漏到普通下游节点
                        output_list = [target]
                    else:
                        # 工具不在当前Agent的可用列表中，返回权限错误
                        error_packet = packet.create_child(
                            sender_id=self.sender_id,
                            content=f"[Tool Error] {tool_name} error=Permission denied: tool '{tool_name}' is not available for this agent. Available tools: {', '.join(t.name for t in self._call_targets)}",
                            packet_type=PacketType.ERROR,
                            inherit_metadata=False,
                        )
                        error_packet.add_metadata("tool_name", tool_name)
                        error_packet.add_metadata("tool_call_id", content.get("tool_call_id", ""))
                        return error_packet, output_list
        return packet, output_list

    def _output_to_list(self, packet: InfoPacket, target_list: List['Processor']) -> None:
        """重写输出方法：CALL 包通过 target.input() 异步发送给工具 Processor

        异步收发模式：
        - CALL 包通过 target.input() 发给工具 Processor（异步执行）
        - 工具执行完后，CallbackPlugin 将 RESPONSE 包发回 Agent 的 input()
        - CALL 包同时转发到 _to_list 下游（StreamCollector 用于流式显示）
        - 工具不在当前Agent的可用列表中时，不走 CALL 包逻辑，直接走普通输出
        """
        if packet.type == PacketType.CALL and len(target_list) == 1:
            target = target_list[0]
            # 先将 CALL 包转发给下游（StreamCollector 等），用于流式显示
            for proc in self._to_list:
                if proc is not target:
                    proc.input(packet)
            # 异步发送给工具 Processor，不等待结果
            # 工具执行完后通过 CallbackPlugin 回流 RESPONSE 到 Agent 的 input()
            target.input(packet)
        else:
            super()._output_to_list(packet, target_list)

    def _process(self, packet: InfoPacket) -> None:
        try:
            for func in self._pre_processes:
                packet = func(packet)
                if packet.type == PacketType.INTERRUPT:
                    return packet

            if self.stream_mode:
                if asyncio.iscoroutinefunction(self.stream_process):
                    result = self._run_with_retries(lambda: self._run_async(self.stream_process(packet)))
                else:
                    result = self._run_with_retries(
                        lambda: ProcessorExecutors.run_sync(lambda: self.stream_process(packet), timeout=self._timeout)
                    )
            else:
                if asyncio.iscoroutinefunction(self.core_process):
                    result = self._run_with_retries(lambda: self._run_async(self.core_process(packet)))
                else:
                    result = self._run_with_retries(
                        lambda: ProcessorExecutors.run_sync(lambda: self.core_process(packet), timeout=self._timeout)
                    )

            # core_process/stream_process可能返回单个包或多个包（工具调用场景）
            packets_to_process: List[InfoPacket] = []
            if result is not None:
                if isinstance(result, InfoPacket):
                    packets_to_process = [result]
                elif isinstance(result, list) and all(isinstance(r, InfoPacket) for r in result):
                    packets_to_process = result
                else:
                    packets_to_process = [packet]
            else:
                packets_to_process = [packet]

            # 对每个包，创建独立的output_list_copy，通过post_process处理
            processed_outputs: List[Tuple[InfoPacket, List['Processor']]] = []
            for pkt in packets_to_process:
                output_list_copy = copy.copy(self._to_list)
                current_packet = pkt

                for func in self._post_processes:
                    current_packet, output_list_copy = func(current_packet, output_list_copy)
                    if current_packet.type == PacketType.INTERRUPT:
                        return current_packet

                processed_outputs.append((current_packet, output_list_copy))

            for current_packet, output_list_copy in processed_outputs:
                self._output_to_list(current_packet, output_list_copy)
        except Exception as e:
            error_packet = self._create_error_packet(packet, str(e))
            try:
                output_list_copy = copy.copy(self._to_list)
                current_packet = error_packet
                for func in self._post_processes:
                    current_packet, output_list_copy = func(current_packet, output_list_copy)
                    if current_packet.type == PacketType.INTERRUPT:
                        return current_packet
                self._output_to_list(current_packet, output_list_copy)
            except Exception:
                self._output(error_packet)

    def _get_available_schemas(self) -> Optional[List[Dict[str, Any]]]:
        """
        获取可用的 tool schema 列表

        从 _call_targets 中提取每个 target 的 schema

        Returns:
            schema 字典列表，如果没有可用 schema 则返回 None
        """
        schemas = []
        seen_tool_names = set()
        for target in self._call_targets:
            schema = target.get_schema()
            if schema:
                function = schema.get("function", {}) if isinstance(schema, dict) else {}
                tool_name = function.get("name")
                if tool_name and tool_name in seen_tool_names:
                    continue
                if tool_name:
                    seen_tool_names.add(tool_name)
                schemas.append(schema)
        return schemas if schemas else None

    def _get_memory_plugin(self) -> Optional[MemoryPlugin]:
        plugins = self.get_plugins(MemoryPlugin)
        return plugins[0] if plugins else None

    def _get_allmodel_plugin(self) -> Optional[AllModelPlugin]:
        plugins = self.get_plugins(AllModelPlugin)
        return plugins[0] if plugins else None

    def _get_tool_call_limit_plugin(self) -> Optional['ToolCallLimitPlugin']:
        """获取工具调用次数上限插件（如果已注册）。

        用于在 stream_process / core_process 开头检查是否达到硬上限，
        避免在 LLM 永不产 content 的场景下无限循环。
        """
        from .plugins.tool_call_limit_plugin import ToolCallLimitPlugin
        plugins = self.get_plugins(ToolCallLimitPlugin)
        return plugins[0] if plugins else None

    def _build_call_packets(self, packet: InfoPacket, response: LLMResponse) -> List[InfoPacket]:
        batch_id = None
        if len(response.tool_calls or []) > 1:
            allmodel_plugin = self._get_allmodel_plugin()
            if allmodel_plugin is not None:
                batch_id = allmodel_plugin.create_batch_id()

        call_packets = []
        seen_calls = set()  # 去重：相同 tool_name + arguments 只执行一次
        for tool_call in response.tool_calls or []:
            # 去重：相同工具名 + 相同参数的调用只保留第一个
            call_key = (tool_call.name, json.dumps(tool_call.get_arguments_dict(), sort_keys=True, ensure_ascii=False))
            if call_key in seen_calls:
                continue
            seen_calls.add(call_key)

            call_packet = self._create_packet(
                content={
                    "tool_name": tool_call.name,
                    "arguments": tool_call.get_arguments_dict(),
                    "tool_call_id": tool_call.id
                },
                packet_type=PacketType.CALL,
                parent_id=packet.id,
                chain_id=packet.chain_id
            )
            for key, value in packet.metadata.items():
                if key in {
                    "requester",
                    "tool_name",
                    "tool_call_id",
                    "batch_id",
                    "batch_origin_id",
                    "force_tool_choice_required",
                    "preferred_tool_name",
                }:
                    continue
                call_packet.add_metadata(key, value)
            call_packet.add_metadata("requester", self.sender_id)
            call_packet.add_metadata("tool_name", tool_call.name)
            call_packet.add_metadata("tool_call_id", tool_call.id)
            if batch_id is not None:
                call_packet.add_metadata("batch_id", batch_id)
                call_packet.add_metadata("batch_origin_id", packet.id)
            call_packets.append(call_packet)

        return call_packets

    async def core_process(self, packet: InfoPacket) -> Union[InfoPacket, List[InfoPacket]]:
        if self.llm is None:
            raise RuntimeError("LLM not configured for this agent")

        # ToolCallLimitPlugin 硬上限检查：累计工具调用次数达到 max_threshold 时
        # 强制走 NORMAL 分支终止循环，避免 LLM 永不产 content 导致死循环。
        # 软提醒 (warn_threshold) 由 build_system_message 注入，不需要这里处理。
        tool_call_limit_plugin = self._get_tool_call_limit_plugin()
        if tool_call_limit_plugin is not None and tool_call_limit_plugin.should_force_terminate(packet):
            total = tool_call_limit_plugin.get_total_count(packet.chain_id or "")
            logging.getLogger(__name__).warning(
                "[core_process] sender=%s chain=%s reached max_tool_calls=%d, forcing termination",
                (self.sender_id or self.name or "?")[:12],
                (packet.chain_id or "?")[:8],
                total,
            )
            return self._create_packet(
                content=(
                    f"[ToolCallLimit] 已达到工具调用次数上限 {tool_call_limit_plugin.max_threshold}，"
                    f"等待用户决策是否继续。"
                ),
                packet_type=PacketType.NORMAL,
                parent_id=packet.id,
                chain_id=packet.chain_id
            )

        messages = self._build_messages(packet)

        # 获取可用工具 schema
        tools = self._get_available_schemas()

        chat_kwargs: Dict[str, Any] = {}
        tool_choice = self._resolve_tool_choice(packet, tools)
        if tool_choice is not None:
            chat_kwargs["tool_choice"] = tool_choice

        # 诊断: 记录本轮 LLM 调用前的 tool 列表大小 + messages 数 (判断 LLM 是不是没看到工具)
        _logger = logging.getLogger(__name__)
        sender = self.sender_id or self.name or "?"
        _logger.info(
            "[core_process] sender=%s messages=%d tools=%d tool_choice=%s",
            sender[:12], len(messages), len(tools or []), tool_choice,
        )

        _t_llm = time.perf_counter()
        response = await self.llm.chat(messages, tools=tools, **chat_kwargs)
        _logger.info(
            "[perf] core_process sender=%s llm.chat %.3fs (model=%s)",
            sender[:12], time.perf_counter() - _t_llm, getattr(response, 'model', '?'),
        )

        # 诊断: LLM 响应后记录调了哪些工具, finish_reason
        try:
            resp_tool_calls = response.tool_calls or []
            _logger.info(
                "[core_process] sender=%s finish_reason=%s tool_calls=%d names=%s content_preview=%s",
                sender[:12],
                getattr(response, 'finish_reason', '?'),
                len(resp_tool_calls),
                [tc.name for tc in resp_tool_calls],
                (response.content or "")[:120],
            )
        except Exception as _diag_exc:
            pass

        # 检查是否有工具调用
        if response.has_tool_calls():
            text_content = (response.content or "").strip()
            # Strip tool call markers from text so they don't appear in the response
            text_content = strip_tool_call_markers(text_content)
            has_text = bool(text_content) and text_content != ""

            call_packets = self._build_call_packets(packet, response)

            if has_text:
                text_packet = self._create_packet(
                    content=text_content,
                    packet_type=PacketType.NORMAL,
                    parent_id=packet.id,
                    chain_id=packet.chain_id,
                )
                text_packet.add_metadata("requester", self.sender_id)
                text_packet.add_metadata("has_pending_tool_calls", True)
                return [text_packet, *call_packets]

            return call_packets

        # 普通响应
        response_packet = self._create_packet(
            content=response.content,
            packet_type=PacketType.NORMAL,
            parent_id=packet.id,
            chain_id=packet.chain_id
        )

        return response_packet

    async def stream_process(self, packet: InfoPacket) -> Union[InfoPacket, List[InfoPacket]]:
        if self.llm is None:
            raise RuntimeError("LLM not configured for this agent")

        # ToolCallLimitPlugin 硬上限检查：累计工具调用次数达到 max_threshold 时
        # 强制走 NORMAL 分支终止循环，避免 LLM 永不产 content 导致死循环。
        # 软提醒 (warn_threshold) 由 build_system_message 注入，不需要这里处理。
        tool_call_limit_plugin = self._get_tool_call_limit_plugin()
        if tool_call_limit_plugin is not None and tool_call_limit_plugin.should_force_terminate(packet):
            total = tool_call_limit_plugin.get_total_count(packet.chain_id or "")
            logging.getLogger(__name__).warning(
                "[stream_process] sender=%s chain=%s reached max_tool_calls=%d, forcing termination",
                (self.sender_id or self.name or "?")[:12],
                (packet.chain_id or "?")[:8],
                total,
            )
            return self._create_packet(
                content=(
                    f"[ToolCallLimit] 已达到工具调用次数上限 {tool_call_limit_plugin.max_threshold}，"
                    f"等待用户决策是否继续。"
                ),
                packet_type=PacketType.NORMAL,
                parent_id=packet.id,
                chain_id=packet.chain_id
            )

        messages = self._build_messages(packet)
        tools = self._get_available_schemas()
        chat_kwargs: Dict[str, Any] = {}
        tool_choice = self._resolve_tool_choice(packet, tools)
        if tool_choice is not None:
            chat_kwargs["tool_choice"] = tool_choice

        # 用 list 容器让 on_token 闭包能修改（首 token TTFT 一次性记录）
        _t_stream_start: List[float] = [0.0]
        _ttft_recorded: List[bool] = [False]

        def on_token(token: str) -> None:
            if not _ttft_recorded[0]:
                _ttft_recorded[0] = True
                logging.getLogger(__name__).info(
                    "[perf] stream_process sender=%s TTFT %.3fs (model=%s)",
                    (self.sender_id or self.name or "?")[:12],
                    time.perf_counter() - _t_stream_start[0],
                    getattr(self.llm, 'model', '?'),
                )
            stream_packet = self._create_packet(
                content=token,
                packet_type=PacketType.STREAM,
                parent_id=packet.id,
                chain_id=packet.chain_id
            )
            self._output(stream_packet, stream=True)

        _t_stream_start[0] = time.perf_counter()
        _t_stream_total = time.perf_counter()
        response = await self.llm.chat_stream(messages, tools=tools, on_token=on_token, **chat_kwargs)
        logging.getLogger(__name__).info(
            "[perf] stream_process sender=%s chat_stream total %.3fs finish_reason=%s",
            (self.sender_id or self.name or "?")[:12],
            time.perf_counter() - _t_stream_total,
            getattr(response, 'finish_reason', '?'),
        )

        if response.has_tool_calls():
            text_content = (response.content or "").strip()
            # Strip tool call markers from text so they don't appear in the response
            text_content = strip_tool_call_markers(text_content)
            has_text = bool(text_content) and text_content != ""

            call_packets = self._build_call_packets(packet, response)

            # 推送工具调用位置标记到流, 让前端能按原始时序穿插渲染工具调用.
            # 背景: tool_calls 只累积到 metadata, content 里没位置信息,
            #   前端只能把工具调用统一放到消息末尾, 丢失了"何时调用"的时序.
            # 方案: 每个 call_packet 对应一个 <tool_call_pos /> 标记,
            #   前端按标记出现顺序从 metadata.tool_calls 消费详情.
            # 多轮调用 (tool → result → 再 stream_process) 时, 所有标记都会
            # 被 StreamPushPlugin 累积到同一个 _latest_content, 时序天然正确.
            for _ in call_packets:
                on_token('\n<tool_call_pos />\n')

            if has_text:
                text_packet = self._create_packet(
                    content=text_content,
                    packet_type=PacketType.NORMAL,
                    parent_id=packet.id,
                    chain_id=packet.chain_id,
                )
                text_packet.add_metadata("requester", self.sender_id)
                text_packet.add_metadata("has_pending_tool_calls", True)
                return [text_packet, *call_packets]

            return call_packets

        normal_packet = self._create_packet(
            content=response.content,
            packet_type=PacketType.NORMAL,
            parent_id=packet.id,
            chain_id=packet.chain_id
        )
        return normal_packet

    def _build_messages(self, packet: InfoPacket) -> List[ChatMessage]:
        messages = []

        if self.system_prompt and self.system_prompt.strip():
            messages.append(ChatMessage(role=MessageRole.SYSTEM, content=self.system_prompt))

        for plugin in self.get_plugins():
            system_message = plugin.build_system_message(packet)
            if isinstance(system_message, str) and system_message.strip():
                messages.append(ChatMessage(role=MessageRole.SYSTEM, content=system_message.strip()))

        for history_packet in self._get_chain_packets_for_messages(packet):
            message = self._packet_to_message(history_packet)
            if self._should_include_message(message):
                messages.append(message)

        return messages

    def _should_include_message(self, message: Optional[ChatMessage]) -> bool:
        if message is None:
            return False
        content = message.content if isinstance(message.content, str) else str(message.content)
        return bool(content.strip())

    def _should_force_tool_choice(
        self,
        packet: InfoPacket,
        tools: Optional[List[Dict[str, Any]]],
    ) -> bool:
        if not tools:
            return False
        if bool(packet.get_metadata("force_tool_choice_required")):
            return True
        if not self.force_tool_choice_on_first_turn:
            return False
        if packet.type == PacketType.CALL and self._is_call_packet_for_current_agent(packet):
            return True
        if packet.type == PacketType.NORMAL and packet.sender_id != self.sender_id and not self._is_all_result_packet(packet):
            return True
        return False

    def _supports_tool_choice(self) -> bool:
        """检查当前 LLM 是否支持 tool_choice 参数。

        DeepSeek reasoning 系列模型（deepseek-reasoner、deepseek-r1、deepseek-v4-flash 等）
        不支持 tool_choice，必须返回 "auto" 或 "none"。
        """
        if self.llm is None:
            return True
        model = (self.llm.model or "").lower()
        if model.startswith("deepseek-"):
            return model in ("deepseek-chat", "deepseek-v3", "deepseek-v3-0324")
        return True

    def _resolve_tool_choice(
        self,
        packet: InfoPacket,
        tools: Optional[List[Dict[str, Any]]],
    ) -> Any:
        if not tools:
            return None

        if not self._supports_tool_choice():
            return "auto"

        preferred_tool_name = str(packet.get_metadata("preferred_tool_name") or "").strip()
        if preferred_tool_name:
            available_tool_names = {
                str(function.get("name") or "").strip()
                for tool in tools
                if isinstance(tool, dict)
                for function in [tool.get("function")]
                if isinstance(function, dict)
            }
            if preferred_tool_name in available_tool_names:
                return {"type": "function", "function": {"name": preferred_tool_name}}

        if self._should_force_tool_choice(packet, tools):
            return "required"
        return None

    def _get_chain_packets_for_messages(self, packet: InfoPacket) -> List[InfoPacket]:
        memory_plugin = self._get_memory_plugin()
        chain_packets: List[InfoPacket] = []

        if memory_plugin is not None:
            chain_packets = memory_plugin.get_chain_history(packet.chain_id)

        visible_packets = [p for p in chain_packets if p.type != PacketType.STREAM]
        visible_packets.sort(key=lambda p: p.timestamp)

        packet_ids = [p.id for p in visible_packets]
        if packet.id in packet_ids:
            visible_packets = visible_packets[:packet_ids.index(packet.id) + 1]
        else:
            visible_packets.append(packet)
            visible_packets.sort(key=lambda p: p.timestamp)

        deduplicated_packets: List[InfoPacket] = []
        seen_ids = set()
        for current_packet in visible_packets:
            if current_packet.id in seen_ids:
                continue
            seen_ids.add(current_packet.id)
            deduplicated_packets.append(current_packet)

        if memory_plugin is not None and memory_plugin.max_history > 0:
            if len(deduplicated_packets) > memory_plugin.max_history:
                first_message = deduplicated_packets[0]
                tail = deduplicated_packets[-(memory_plugin.max_history - 1):]
                deduplicated_packets = [first_message] + tail

        return deduplicated_packets

    def _packet_to_message(self, packet: InfoPacket) -> Optional[ChatMessage]:
        if packet.type == PacketType.STREAM:
            return None

        if packet.get_metadata("rollover_handoff"):
            return None

        if packet.get_metadata("rollover_summary"):
            previous_chain = packet.get_metadata("rollover_from_chain") or "previous"
            return ChatMessage(
                role=MessageRole.SYSTEM,
                content=f"[Previous Chain Summary from {previous_chain}]\n{self._stringify_content(packet.content)}",
            )

        if packet.type == PacketType.CALL:
            if self._is_call_packet_for_current_agent(packet):
                # 别的 agent 调我 → 保持 USER role（等同于收到一条消息）
                return self._sanitize_message_content(
                    packet,
                    ChatMessage(
                        role=MessageRole.USER,
                        content=self._format_incoming_agent_call_message(packet),
                    ),
                )
            # 我调工具 → OpenAI 原生 tool_calls 格式
            return self._build_native_tool_call_message(packet)

        if packet.type == PacketType.RESPONSE:
            # 工具返回结果 → OpenAI 原生 tool role
            return self._build_native_tool_result_message(packet)

        if packet.type == PacketType.ERROR:
            # 工具执行出错 → tool role（OpenAI 标准：错误也用 tool role）
            return self._build_native_tool_error_message(packet)

        if packet.type == PacketType.INTERRUPT:
            return None

        if self._is_all_result_packet(packet):
            return self._sanitize_message_content(
                packet,
                ChatMessage(
                    role=MessageRole.USER,
                    content=self._format_all_results_message(packet),
                ),
            )

        role = MessageRole.ASSISTANT if packet.sender_id == self.sender_id else MessageRole.USER
        rendered = self._apply_history_filters(packet, self._stringify_content(packet.content))
        # 群聊场景: 非自己的发言, 在 content 前缀拼 [sender_name]: 让 LLM 区分发言者
        # (ChatMessage.name 字段部分模型忽略, content 前缀跨模型更可靠)
        # sender_name 由 agent_executor._seed_history_from_db 写入 packet.metadata
        if role == MessageRole.USER:
            sender_name = packet.get_metadata("sender_name") or ""
            if sender_name and sender_name != "user":
                prefix = f"[{sender_name}]: "
                if not rendered.startswith(prefix):
                    rendered = prefix + rendered
        return self._sanitize_message_content(packet, ChatMessage(role=role, content=rendered))

    def _apply_history_filters(self, packet: InfoPacket, rendered_text: str) -> str:
        filtered = rendered_text
        for plugin in self.get_plugins(ReasoningFilterPlugin):
            filtered = plugin.sanitize_packet_content(packet, filtered)
        return filtered

    def _sanitize_message_content(self, packet: InfoPacket, message: ChatMessage) -> ChatMessage:
        content = message.content
        if content is not None:
            content = content if isinstance(content, str) else str(content)
            if packet.sender_id != "user":
                content = strip_hidden_trace_blocks(content)
        return ChatMessage(
            role=message.role,
            content=content,
            name=message.name,
            tool_call_id=message.tool_call_id,
            tool_calls=message.tool_calls,
        )

    def _sanitize_hidden_trace_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return strip_hidden_trace_blocks(value)
        if isinstance(value, list):
            return [self._sanitize_hidden_trace_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._sanitize_hidden_trace_value(item) for key, item in value.items()}
        return value

    def _build_native_tool_call_message(self, packet: InfoPacket) -> ChatMessage:
        """将 CALL packet 转为 OpenAI 原生 assistant + tool_calls 格式
        
        替代旧的 [Tool Call] xxx arguments={...} 纯文本格式。
        LLM 历史中不再出现可被模仿的文本标记。
        """
        content = packet.content if isinstance(packet.content, dict) else {}
        tool_name = content.get("tool_name") or packet.get_metadata("tool_name") or "unknown_tool"
        tool_call_id = content.get("tool_call_id") or packet.get_metadata("tool_call_id") or f"call_{packet.id[:8]}"
        arguments = self._sanitize_hidden_trace_value(content.get("arguments", {}))
        arguments_str = json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, dict) else str(arguments)
        
        return self._sanitize_message_content(
            packet,
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=[{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": arguments_str,
                    },
                }],
            ),
        )

    def _build_native_tool_result_message(self, packet: InfoPacket) -> ChatMessage:
        """将 RESPONSE packet 转为 OpenAI 原生 tool role 格式
        
        替代旧的 [Tool Result] xxx result={...} 纯文本格式。
        """
        tool_name = packet.get_metadata("tool_name") or "unknown_tool"
        tool_call_id = packet.get_metadata("tool_call_id")
        result = self._sanitize_hidden_trace_value(packet.content)
        result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
        
        return self._sanitize_message_content(
            packet,
            ChatMessage(
                role=MessageRole.TOOL,
                content=result_str,
                tool_call_id=tool_call_id,
            ),
        )

    def _build_native_tool_error_message(self, packet: InfoPacket) -> ChatMessage:
        """将 ERROR packet 转为 OpenAI 原生 tool role 格式（含错误信息）
        
        替代旧的 [Tool Error] xxx error={...} 纯文本格式。
        """
        tool_call_id = packet.get_metadata("tool_call_id")
        error = self._sanitize_hidden_trace_value(packet.content)
        error_str = str(error) if not isinstance(error, (dict, list)) else json.dumps(error, ensure_ascii=False)
        
        return self._sanitize_message_content(
            packet,
            ChatMessage(
                role=MessageRole.TOOL,
                content=f"[ERROR] {error_str}",
                tool_call_id=tool_call_id,
            ),
        )

    def _is_call_packet_for_current_agent(self, packet: InfoPacket) -> bool:
        if packet.sender_id == self.sender_id:
            return False

        content = packet.content if isinstance(packet.content, dict) else {}
        tool_name = content.get("tool_name") or packet.get_metadata("tool_name")
        return tool_name == self.name

    def _format_incoming_agent_call_message(self, packet: InfoPacket) -> str:
        content = packet.content if isinstance(packet.content, dict) else {}
        arguments = self._sanitize_hidden_trace_value(content.get("arguments"))

        if isinstance(arguments, dict):
            if set(arguments.keys()) == {"request"} and isinstance(arguments["request"], str):
                return arguments["request"]
            return self._stringify_content(arguments)

        return self._stringify_content(self._sanitize_hidden_trace_value(content))

    def _is_all_result_packet(self, packet: InfoPacket) -> bool:
        return (
            packet.get_metadata("aggregate") == "all"
            or (
                isinstance(packet.content, dict)
                and packet.content.get("mode") == "all"
                and isinstance(packet.content.get("results"), list)
            )
        )

    def _format_all_results_message(self, packet: InfoPacket) -> str:
        content = packet.content if isinstance(packet.content, dict) else {}
        results = content.get("results", [])
        lines = ["[Parallel Tool Results]"]

        for index, result in enumerate(results, start=1):
            tool_name = result.get("tool_name") or f"tool_{index}"
            arguments = self._stringify_content(self._sanitize_hidden_trace_value(result.get("arguments")))
            value = self._stringify_content(self._sanitize_hidden_trace_value(result.get("result")))
            status = result.get("status", "success")
            lines.append(f"{index}. {tool_name} status={status} arguments={arguments} result={value}")

        return "\n".join(lines)

    def _stringify_content(self, content: Any) -> str:
        if isinstance(content, bytes):
            return content.decode('utf-8', errors='replace')
        if isinstance(content, (dict, list)):
            return json.dumps(content, ensure_ascii=False, sort_keys=True)
        return str(content)

    def get_schema(self) -> Optional[Dict[str, Any]]:
        if self._schema is not None:
            return self._schema

        if self.description is None:
            return None

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "request": {
                            "type": "string",
                            "description": "The task or request for this agent.",
                        }
                    },
                    "required": ["request"],
                },
            },
        }

    def set_llm(self, llm: BaseLLM) -> 'Agent':
        self.llm = llm
        return self

    def set_llm_config(self, llm_config: Union[LLMConfig, Dict[str, Any]]) -> 'Agent':
        self.llm_config = llm_config if isinstance(llm_config, LLMConfig) else LLMConfig.from_dict(llm_config)
        return self

    def set_system_prompt(self, prompt: str) -> 'Agent':
        self.system_prompt = prompt
        return self

    def set_stream_mode(self, enabled: bool = True) -> 'Agent':
        self.stream_mode = enabled
        return self

    def set_description(self, description: str) -> 'Agent':
        self.description = description
        return self

    def set_schema(self, schema: Dict[str, Any]) -> 'Agent':
        self._schema = schema
        return self

    def to_spec(
        self,
        builtin_tools: Optional[List[Union[BuiltinProcessorConfig, Dict[str, Any]]]] = None,
        tool_names: Optional[List[str]] = None,
    ) -> AgentSpec:
        plugin_specs: List[PluginConfig] = []
        for plugin in self.get_plugins():
            if isinstance(plugin, MemoryPlugin):
                plugin_specs.append(PluginConfig(kind="memory", config={"max_history": plugin.max_history}))
            elif isinstance(plugin, AllModelPlugin):
                plugin_specs.append(PluginConfig(kind="allmodel", config={"timeout": plugin.timeout}))
            elif isinstance(plugin, ContextRolloverPlugin):
                plugin_specs.append(
                    PluginConfig(
                        kind="context_rollover",
                        config={
                            "max_history_chars": plugin.max_history_chars,
                            "trigger_ratio": plugin.trigger_ratio,
                            "summary_prompt": plugin.summary_prompt,
                            "rollover_metadata_key": plugin.rollover_metadata_key,
                            "history_query_mode": plugin.history_query_mode,
                            "read_only_previous_chain": plugin.read_only_previous_chain,
                        },
                    )
                )
            elif isinstance(plugin, ReasoningFilterPlugin):
                plugin_specs.append(
                    PluginConfig(
                        kind="reasoning_filter",
                        config={
                            "reasoning_markers": [list(item) for item in plugin.reasoning_markers],
                            "preserve_final_answer": plugin.preserve_final_answer,
                        },
                    )
                )
            elif isinstance(plugin, SkillPlugin):
                plugin_specs.append(
                    PluginConfig(
                        kind="skill",
                        config={
                            "skill_roots": list(plugin.skill_roots),
                            "skill_names": list(plugin.skill_names),
                            "auto_select": plugin.auto_select,
                            "max_skills": plugin.max_skills,
                            "max_skill_chars": plugin.max_skill_chars,
                        },
                    )
                )

        normalized_builtin_tools = []
        source_builtin_tools = builtin_tools
        if source_builtin_tools is None:
            source_builtin_tools = []
            for target in self._call_targets:
                if hasattr(target, "to_config"):
                    source_builtin_tools.append(target.to_config())

        for tool in source_builtin_tools:
            normalized_builtin_tools.append(
                tool if isinstance(tool, BuiltinProcessorConfig) else BuiltinProcessorConfig.from_dict(tool)
            )

        return AgentSpec(
            name=self.name,
            description=self.description,
            system_prompt=self.system_prompt,
            stream_mode=self.stream_mode,
            force_tool_choice_on_first_turn=self.force_tool_choice_on_first_turn,
            llm_config=self.llm_config,
            plugins=plugin_specs,
            builtin_tools=normalized_builtin_tools,
            tool_names=tool_names or [target.name for target in self._call_targets],
        )

    @classmethod
    def from_spec(
        cls,
        spec: Union[AgentSpec, Dict[str, Any]],
        workspace: Optional['Workspace'] = None,
        default_llm_config: Optional[Union[LLMConfig, Dict[str, Any]]] = None,
        register_builtin_tools: bool = True,
    ) -> 'Agent':
        from .builtin_processors import create_builtin_processor
        from .workspace import Workspace

        agent_spec = spec if isinstance(spec, AgentSpec) else AgentSpec.from_dict(spec)
        effective_llm_config = agent_spec.llm_config or (
            default_llm_config if isinstance(default_llm_config, LLMConfig) else LLMConfig.from_dict(default_llm_config)
        )
        llm = build_llm_from_config(effective_llm_config) if effective_llm_config is not None else None

        agent = cls(
            name=agent_spec.name,
            llm=llm,
            llm_config=effective_llm_config,
            system_prompt=agent_spec.system_prompt,
            stream_mode=agent_spec.stream_mode,
            description=agent_spec.description,
            force_tool_choice_on_first_turn=agent_spec.force_tool_choice_on_first_turn,
        )

        for plugin_config in agent_spec.plugins:
            if plugin_config.kind == "memory":
                agent.add_plugin(MemoryPlugin(max_history=plugin_config.config.get("max_history", 10)))
            elif plugin_config.kind == "allmodel":
                agent.add_plugin(AllModelPlugin(timeout=plugin_config.config.get("timeout", 30.0)))
            elif plugin_config.kind == "context_rollover":
                agent.add_plugin(
                    ContextRolloverPlugin(
                        max_history_chars=plugin_config.config.get("max_history_chars", 12000),
                        trigger_ratio=plugin_config.config.get("trigger_ratio", 0.7),
                        summary_prompt=plugin_config.config.get(
                            "summary_prompt",
                            "Please summarize the current chain state for the next chain.",
                        ),
                        rollover_metadata_key=plugin_config.config.get("rollover_metadata_key", "rollover_from_chain"),
                        history_query_mode=plugin_config.config.get("history_query_mode", "chain-switch"),
                        read_only_previous_chain=plugin_config.config.get("read_only_previous_chain", True),
                    )
                )
            elif plugin_config.kind == "reasoning_filter":
                markers = plugin_config.config.get("reasoning_markers", [("思考", "回答")])
                agent.add_plugin(ReasoningFilterPlugin(
                    reasoning_markers=[tuple(m) for m in markers],
                    preserve_final_answer=plugin_config.config.get("preserve_final_answer", True),
                ))
            elif plugin_config.kind == "skill":
                agent.add_plugin(SkillPlugin(
                    skill_roots=plugin_config.config.get("skill_roots", []),
                    skill_names=plugin_config.config.get("skill_names", []),
                    auto_select=plugin_config.config.get("auto_select", True),
                    max_skills=plugin_config.config.get("max_skills", 3),
                    max_skill_chars=plugin_config.config.get("max_skill_chars", 12000),
                ))

        if register_builtin_tools and agent_spec.builtin_tools and workspace is not None:
            for tool_config in agent_spec.builtin_tools:
                try:
                    processor = create_builtin_processor(tool_config, workspace=workspace)
                    agent.register_call_target(processor)
                except (ValueError, KeyError) as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Skipping builtin tool %s in from_spec: %s", tool_config.kind, exc
                    )

        return agent