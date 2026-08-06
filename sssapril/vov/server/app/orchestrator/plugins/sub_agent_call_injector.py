"""
P0 修复 (Bug 3): sub-agent 调用 "No user query found in messages" bug

根因分析:
  agentflow 的 agent 通过 register_call_target(other_flow_agent) 把其他 agent 当作"工具"暴露。
  当主 agent 的 LLM 调用 other_flow_agent 时, 生成 CALL packet, content = {
    "tool_name": "<sub-agent name>",
    "arguments": {"request": "<user query>"},
    "tool_call_id": "call_abc"
  }
  CALL packet 进入 sub-agent flow_agent 的 input → _process:
    1. CallbackPlugin.pre_process: 创建新的 sub_chain_id, 在 _chain_heads[sub_chain_id] 标记 is_call=True
       (确保 sub-agent 的响应通过 CallbackPlugin.post_process 转回 RESPONSE 给主 agent)
    2. core_process: _build_messages(packet) 查询 MemoryPlugin.get_chain_history(sub_chain_id)
       → 新 sub-chain 没有任何历史 → messages 只有 [system_prompt]
    3. llm.chat(messages=[system]) → LLM API 报 "No user query found in messages" (400)

修复方案:
  在 _register_group_agents 给 sub-agent 加一个 SubAgentCallInjector plugin,
  在 CallbackPlugin.pre_process 之后、MemoryPlugin.pre_process 之前运行:
    - 检测进入 sub-agent 的 CALL packet
    - 提取 arguments.request (或 arguments.query/message) 作为 user query
    - 用 create_child 转换 packet 为 NORMAL user packet
      - 保持原 packet.id (CallbackPlugin._call_heads 用 id 索引, 不能变)
      - 保持原 chain_id (新 sub_chain_id, 保留 is_call=True 标记)
      - content = request 字符串
      - type = NORMAL
      - metadata.sender_type = "user"
      - metadata.sender_name = "用户"
    - 保留 metadata.requester, tool_call_id, tool_name (供 CallbackPlugin.post_process 用)

  之后 LLM 看到 [system, user: "<request>"] → 正常响应 NORMAL → CallbackPlugin.post_process
  转 RESPONSE 并通过 requester 回流到主 agent 的主链。

设计原则:
  - 不改 agentflow 框架, 仅在 server 层加 plugin
  - 不影响 sub-agent 的 chain 历史 (sub-chain 仍由 CallbackPlugin 隔离)
  - 不影响 sub-agent 调工具的能力 (如果 sub-agent 自己要调主 agent 走另一条路径,
    那个 CALL 是 sub-agent 自己的 LLM 生成的, 不会经过这个 plugin — 因为 sub-agent
    的 LLM 不会把自己当工具调自己, 而调用主 agent 走的是子链外层正常路径)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from agentflow.packet import InfoPacket, PacketType
from agentflow.plugin import Plugin

logger = logging.getLogger(__name__)


class SubAgentCallInjector(Plugin):
    """
    sub-agent 调用注入器 — 把"主 agent 把 sub-agent 当工具调用"的 CALL packet
    转换成 NORMAL user packet, 让 sub-agent 的 LLM 有 user query 上下文。

    仅在 pre_process 阶段生效, 顺序:
      CallbackPlugin.pre_process (创建 sub-chain, 标记 is_call=True)
        → SubAgentCallInjector.pre_process (把 CALL 转 NORMAL, 注入 user query)
          → MemoryPlugin.pre_process (把 NORMAL user packet 保存到 sub-chain)
    """

    # arguments 里可能放 user query 的字段名, 按优先级尝试
    _QUERY_KEYS = ("request", "query", "message", "text", "prompt", "input")

    def __init__(self, name: Optional[str] = None):
        super().__init__(name or "SubAgentCallInjector")

    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        # 只处理 CALL packet
        if packet.type != PacketType.CALL:
            return packet

        # 提取 arguments
        content = packet.content
        if not isinstance(content, dict):
            return packet

        arguments = content.get("arguments")
        if not isinstance(arguments, dict):
            # arguments 可能是 string (模型有时不严格按 schema 传 dict)
            if isinstance(arguments, str) and arguments.strip():
                user_query = arguments.strip()
            else:
                logger.debug(
                    "[SubAgentCallInjector] CALL packet has no extractable arguments: %s",
                    type(arguments).__name__,
                )
                return packet
        else:
            user_query = self._extract_user_query(arguments)
            if not user_query:
                logger.warning(
                    "[SubAgentCallInjector] CALL packet arguments has no recognizable "
                    "user query field (tried: %s), args=%s",
                    self._QUERY_KEYS, list(arguments.keys()),
                )
                return packet

        # 保留原 packet 的 id (CallbackPlugin._call_heads 用 id 索引) 和 chain_id
        original_id = packet.id
        original_chain_id = packet.chain_id
        parent_id = packet.parent_id
        original_metadata = dict(packet.metadata)  # 解冻后拷贝

        # 用 create_child 构造新的 NORMAL user packet
        #   sender_id 改为 "user" — _packet_to_message 看 sender_type=user 渲染为 user role
        #   保留原 id — CallbackPlugin.post_process 用 _call_heads[id] 查 chain_info
        #   保留原 chain_id — 仍是 sub_chain_id, is_call=True 标记保持
        new_packet = packet.create_child(
            sender_id="user",
            content=user_query,
            packet_type=PacketType.NORMAL,
            id=original_id,
            inherit_metadata=False,
        )
        # 继承关键 metadata (requester, tool_call_id, tool_name, batch_id 等)
        for key, value in original_metadata.items():
            try:
                new_packet.add_metadata(key, value)
            except KeyError:
                # metadata 已存在 (display_content 等) → 用 set_metadata 覆盖
                new_packet.set_metadata(key, value)
        # 标记这是 user query 注入, 便于调试
        new_packet.set_metadata("sender_type", "user")
        new_packet.set_metadata("sender_name", "用户")
        new_packet.set_metadata("injected_from_call", True)

        logger.info(
            "[SubAgentCallInjector] CALL→NORMAL conversion: chain=%s request_preview=%s",
            original_chain_id[:8], repr(user_query)[:80],
        )
        return new_packet

    def _extract_user_query(self, arguments: Dict[str, Any]) -> Optional[str]:
        """从 arguments dict 里提取 user query 字符串"""
        for key in self._QUERY_KEYS:
            if key in arguments:
                value = arguments[key]
                if isinstance(value, str) and value.strip():
                    return value.strip()
                # 兼容 LLM 把整个 request 对象传成 dict/str 的情况
                if value is not None:
                    return str(value)
        return None
