"""
Agent执行器模块

负责将数据库中的Agent配置转换为agentflow的FlowAgent，并执行Agent处理流程。
支持同步执行和流式执行两种模式。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, AsyncGenerator

logger = logging.getLogger(__name__)


def _perf(label: str, start: float) -> None:
    """统一耗时日志（[perf] 前缀，便于 grep 排查慢点）"""
    logger.info("[perf] %s %.3fs", label, time.perf_counter() - start)

# v2 P2: 任务状态变更通知已全部走 EventDispatcher (经 event_bus).
# AgentExecutor 不再持有 awake 钩子字段, 不再维护 _awake_task_cb / _awake_lead_task_cb.
# 保留此文件其他职责（执行 / 流式 / 工具注册 / 深度限制）不变.

# 匹配 <think...>...</think...> 标签
# 开标签：<think 后面只能跟空白和 >，不允许包含 <（防止跨标签匹配）
# 闭标签：</think 后面只能跟空白和 >
_THINK_RE = re.compile(r"<think\s*>[\s\S]*?</think\s*>", re.IGNORECASE)
# 匹配未闭合的 <think...> 标签（流式输出中可能先到开标签）
_THINK_OPEN_RE = re.compile(r"<think\s*>", re.IGNORECASE)


def _strip_think_tags(text: str) -> str:
    """移除 think 标签及其内容，保留正文。注意真实的think模块没有反斜杠转义，防止ai读取和本身的think模块混淆。"""
    if not text:
        return text
    # 先移除完整的 <think...>...</think*>
    result = _THINK_RE.sub("", text)
    # 再移除未闭合的 <think...>（流式输出中间状态）
    result = _THINK_OPEN_RE.sub("", result)
    # 清理多余空行
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _extract_inject_meta(packet) -> tuple[Optional[str], Optional[str]]:
    """从工具 RESPONSE 包中提取 page_inject 的 inject_js / inject_description。

    page_inject 工具把代码放在返回 dict 里（content 为该 dict 的 JSON 字符串），
    也可能通过 packet.metadata 显式声明。无论哪种形式都兼容。

    Returns:
        (inject_js, inject_description) — 任一字段缺失时为 None
    """
    inject_js = packet.get_metadata("inject_js")
    inject_description = packet.get_metadata("inject_description")

    # 从 packet.content 解析（page_inject 工具返回 dict 的 JSON 序列化）
    content = packet.content
    parsed: Optional[Dict[str, Any]] = None
    if isinstance(content, dict):
        parsed = content
    elif isinstance(content, str) and content:
        # 仅在看起来像 JSON 对象时才尝试解析
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(content)
            except (ValueError, TypeError):
                parsed = None

    if isinstance(parsed, dict):
        if not inject_js and isinstance(parsed.get("inject_js"), str):
            inject_js = parsed["inject_js"]
        if not inject_description and isinstance(parsed.get("description"), str):
            inject_description = parsed["description"]

    return inject_js, inject_description

from agentflow.agent import Agent as FlowAgent
from agentflow.workspace import Workspace
from agentflow.plugins.memory_plugin import MemoryPlugin
from agentflow.plugins.allmodel_plugin import AllModelPlugin
from agentflow.plugins.tool_event_plugin import ToolEventPlugin
from agentflow.plugins.tool_call_limit_plugin import ToolCallLimitPlugin
from agentflow.packet import InfoPacket, PacketType
from agentflow.processor import Processor
from agentflow.plugin import Plugin
from agentflow.builtin_processors import create_builtin_processor
from agentflow.specs import LLMConfig, build_llm_from_config
from app.orchestrator.tool_adapter import ServerToolAdapter
from app.orchestrator.plugins.sub_agent_call_injector import SubAgentCallInjector
from app.orchestrator.session_lifecycle import is_serial_group
from app.models.agent import Agent, ProjectAgent
from app.models.group import Group, GroupMember
from app.models.task import Task
from app.models.chain import Chain
from sqlalchemy import select

# Agent间调用最大深度（防止LLM层面无限递归）
MAX_AGENT_CALL_DEPTH = 3


def _get_memory_db_path(chain_id: str) -> str:
    """获取持久化记忆数据库路径"""
    from app.core.config import _default_data_dir
    data_dir = _default_data_dir()
    return str(data_dir / f"memory_{chain_id}.db")


def cleanup_memory_db(chain_id: str) -> bool:
    """删除指定链的持久化记忆数据库文件"""
    import os
    db_path = _get_memory_db_path(chain_id)
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            logger.info("Cleaned up memory db for chain %s", chain_id)
            return True
        except OSError as e:
            logger.warning("Failed to clean up memory db for chain %s: %s", chain_id, e)
            return False
    return False


def _build_llm(agent: Agent, global_config: Optional[Dict[str, str]] = None) -> Any:
    """根据Agent配置构建LLM实例

    Args:
        agent: Agent 数据库记录
        global_config: 从 DB 加载的全局 LLM 配置（api_key, base_url, default_model）
    """
    from app.core.config import settings

    # 始终从 agent.llm_config 复制（不修改原对象），缺失字段由全局兜底
    llm_config_dict: Dict[str, Any] = dict(agent.llm_config or {})

    # 优先级：agent.llm_config.model > DB 全局 default_model > settings.DEFAULT_LLM_MODEL
    if "model" not in llm_config_dict:
        llm_config_dict["model"] = (
            (global_config or {}).get("default_model")
            or settings.DEFAULT_LLM_MODEL
        )

    # 优先级：agent.llm_config.api_key > DB 全局 api_key > 环境变量
    if "api_key" not in llm_config_dict:
        llm_config_dict["api_key"] = (
            (global_config or {}).get("api_key")
            or settings.get_llm_api_key()
            or ""
        )
    # 优先级：agent.llm_config.base_url > DB 全局 base_url > 环境变量
    if "base_url" not in llm_config_dict:
        base_url = (global_config or {}).get("base_url") or settings.get_llm_api_base()
        if base_url:
            llm_config_dict["base_url"] = base_url

    llm_config = LLMConfig.from_dict(llm_config_dict)
    if llm_config is None:
        raise ValueError("Failed to build LLM config from agent settings")
    return build_llm_from_config(llm_config)


async def _load_global_llm_config(session_factory) -> Dict[str, str]:
    """从数据库加载全局 LLM 配置（过滤 None 值）

    单次批量查询 llm.* 配置项, 替代之前 3 次独立 SELECT。
    注: 不复用 get_config 的 60s 缓存, 因为这里是批量查询更高效, 且每次 _prepare 都会调用。
    """
    from app.models.system_config import SystemConfig
    try:
        async with session_factory() as session:
            result_rows = await session.execute(
                select(SystemConfig.key, SystemConfig.value).where(
                    SystemConfig.key.in_(["llm.api_key", "llm.base_url", "llm.default_model"])
                )
            )
            result: Dict[str, str] = {}
            for key, value in result_rows.all():
                if value:
                    short_key = key.split(".", 1)[1]  # "llm.api_key" -> "api_key"
                    result[short_key] = value
            return result
    except Exception:
        return {}


def _seed_history_from_db(
    memory_plugin: MemoryPlugin,
    flow_agent: FlowAgent,
    llm_context: Dict[str, Any],
    chain_id: str,
) -> None:
    """将 DB 历史消息增量同步到 MemoryPlugin

    每次调用都从主 DB 加载最新消息，增量合并到 MemoryPlugin（避免双重历史源导致上下文丢失）。
    使用 (sender_type, sender_name, content[:200]) 作为去重 key，防止重复注入。

    使用 raw_history（包含 packet_type + metadata）创建正确类型的 InfoPacket：
    - call → PacketType.CALL（MemoryPlugin._packet_to_message 会转为原生 tool_calls）
    - response → PacketType.RESPONSE（转为原生 tool role）
    - error → PacketType.ERROR（转为原生 tool role + error）
    - normal → PacketType.NORMAL（保持原样）

    这确保了 agent 重新 dispatch 时，MemoryPlugin 中的工具调用历史是结构完整的，
    _build_messages 能正确构建包含 tool_calls 的对话上下文。
    """
    import hashlib

    # 优先使用 raw_history（含 packet_type + metadata），fallback 到 messages（旧格式）
    raw_history = llm_context.get("raw_history", [])
    if not raw_history:
        # fallback: 旧格式 messages（仅 role+content）
        db_history = llm_context.get("messages", [])
        if not db_history:
            return
        raw_history = [{"sender_type": "user" if m["role"] == "user" else "agent",
                        "sender_name": m.get("sender_name", ""),
                        "content": m["content"],
                        "packet_type": "normal",
                        "metadata": {}} for m in db_history]

    # 收集 MemoryPlugin 中已有的消息签名（用于去重）
    existing = memory_plugin.get_chain_history(chain_id)
    existing_sigs: set = set()
    for p in existing:
        if p.type == PacketType.STREAM:
            continue
        sender_type = p.get_metadata("sender_type") or "unknown"
        sender_name = p.get_metadata("sender_name") or ""
        content = (p.content or "") if isinstance(p.content, str) else str(p.content or "")
        sig = hashlib.md5(f"{sender_type}|{sender_name}|{content[:200]}".encode()).hexdigest()
        existing_sigs.add(sig)

    # 收集当前 Agent 可用的工具名集合
    available_tools = {t.name for t in flow_agent._call_targets} if flow_agent._call_targets else set()

    for msg in raw_history:
        pkt_type = msg.get("packet_type", "normal")
        metadata = msg.get("metadata") or {}
        sender_type = msg.get("sender_type", "agent")
        content = msg.get("content", "")

        # 跳过 system event packet（v2 P2+: EventDispatcher 写到主群的系统通知）
        #   为什么跳过: _seed_history_from_db 会把 packet 注入到 MemoryPlugin, 后续
        #   MemoryPlugin._packet_to_message 会按 sender_id 判定 role. 如果不区分
        #   system sender, system packet 的 sender_id 会被设为 flow_agent.sender_id,
        #   _packet_to_message 看到 sender_id == self.sender_id 就把 content 渲染成
        #   assistant role (= agent 上一轮说的话), LLM 复述 [系统通知] 内容到主群.
        #   修复策略: 跳过 system packet, 不让它污染 LLM history. trigger_msg 已通过
        #   user_message 注入到 LLM (line 600: user_message=trigger_msg), LLM 仍然知道
        #   事件发生, 只是不会再误以为"自己上一轮说过 [系统通知]".
        if sender_type == "system":
            continue

        # 跳过空内容（但 call 类型的 content 可能是 dict，不算空）
        if pkt_type != "call":
            if not content or (isinstance(content, str) and not content.strip()):
                continue

        # 过滤：call 类型的工具不在当前 Agent 可用列表中则跳过
        if pkt_type == "call" and available_tools:
            if isinstance(content, dict):
                tool_name = content.get("tool_name") or metadata.get("tool_name") or ""
            else:
                tool_name = metadata.get("tool_name") or ""
            if tool_name and tool_name not in available_tools:
                continue

        # 去重：检查是否已存在相同签名
        content_str = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True)
        sender_name = msg.get("sender_name") or ("用户" if sender_type == "user" else flow_agent.name)
        sig = hashlib.md5(f"{sender_type}|{sender_name}|{content_str[:200]}".encode()).hexdigest()
        if sig in existing_sigs:
            continue
        existing_sigs.add(sig)

        sender_id = "user" if sender_type == "user" else flow_agent.sender_id

        # 根据 packet_type 创建正确类型的 InfoPacket
        if pkt_type == "call":
            packet_type = PacketType.CALL
        elif pkt_type == "response":
            packet_type = PacketType.RESPONSE
        elif pkt_type == "error":
            packet_type = PacketType.ERROR
        else:
            packet_type = PacketType.NORMAL

        packet = InfoPacket(
            id=f"seed_{uuid.uuid4().hex[:12]}",
            sender_id=sender_id,
            parent_id=None,
            chain_id=chain_id,
            content=content,
            type=packet_type,
            timestamp=datetime.now(),
        )
        packet.add_metadata("sender_type", sender_type)
        packet.add_metadata("sender_name", sender_name)
        # 保留原始 metadata（tool_call_id, tool_name, tool_calls 等）
        for key, value in metadata.items():
            if key not in ("sender_type", "sender_name"):
                packet.add_metadata(key, value)
        memory_plugin.manager.save(packet)

        # 如果 agent_text 包含 tool_calls，为每个工具调用创建 CALL + RESPONSE 包
        # 这样 MemoryPlugin._packet_to_message 能正确转为原生 tool_calls 格式
        if pkt_type not in ("call", "response", "error") and sender_type == "agent":
            tool_calls = metadata.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    tc_name = tc.get("tool_name") or tc.get("name") or "unknown"
                    tc_id = tc.get("tool_call_id") or f"seed_call_{uuid.uuid4().hex[:8]}"
                    tc_args = tc.get("arguments") or tc.get("args") or {}

                    # 创建 CALL 包
                    call_packet = InfoPacket(
                        id=f"seed_call_{uuid.uuid4().hex[:12]}",
                        sender_id=sender_id,
                        parent_id=packet.id,
                        chain_id=chain_id,
                        content={"tool_name": tc_name, "arguments": tc_args, "tool_call_id": tc_id},
                        type=PacketType.CALL,
                        timestamp=datetime.now(),
                    )
                    call_packet.add_metadata("sender_type", "agent")
                    call_packet.add_metadata("sender_name", sender_name)
                    call_packet.add_metadata("tool_name", tc_name)
                    call_packet.add_metadata("tool_call_id", tc_id)
                    call_packet.add_metadata("requester", sender_id)
                    memory_plugin.manager.save(call_packet)

                    # 创建 RESPONSE 包（如果有结果）
                    tc_result = tc.get("result")
                    if tc_result is not None:
                        resp_packet = InfoPacket(
                            id=f"seed_resp_{uuid.uuid4().hex[:12]}",
                            sender_id=sender_id,
                            parent_id=call_packet.id,
                            chain_id=chain_id,
                            content=tc_result if isinstance(tc_result, str) else json.dumps(tc_result, ensure_ascii=False),
                            type=PacketType.RESPONSE,
                            timestamp=datetime.now(),
                        )
                        resp_packet.add_metadata("sender_type", "agent")
                        resp_packet.add_metadata("sender_name", sender_name)
                        resp_packet.add_metadata("tool_name", tc_name)
                        resp_packet.add_metadata("tool_call_id", tc_id)
                        memory_plugin.manager.save(resp_packet)


def _build_context_and_agent(
    agent: Agent,
    llm_context: Dict[str, Any],
    chain_id: str,
    session_factory,
    global_config: Optional[Dict[str, str]] = None,
    group: Optional["Group"] = None,
):
    """创建 agentflow Agent + Workspace，注入记忆和工具"""
    flow_llm = _build_llm(agent, global_config)

    # v2 P2: 是否强制首轮 LLM 调用工具（tool_choice="required"）。
    # 由 agent 自身的 force_tool_choice 字段声明, 平台不根据 capability 文本"猜"。
    # 用途: coordinator 等必须调工具才能完成工作的角色。
    flow_agent = FlowAgent(
        name=agent.name,
        llm=flow_llm,
        system_prompt=llm_context.get("system_message", ""),
        force_tool_choice_on_first_turn=bool(getattr(agent, "force_tool_choice", False)),
    )
    # LLM 调用 + 工具执行需要足够时间 (默认 60s 对复杂 prompt 不够)
    flow_agent.set_timeout(180.0)

    # 使用持久化 SQLite 让 MemoryPlugin 跨调用保留历史
    db_path = _get_memory_db_path(chain_id)
    workspace = Workspace(f"chain_{chain_id}", db_path=db_path)
    workspace.tool_adapter = ServerToolAdapter(session_factory)
    # 注入当前 group_id（让 write_resource 等工具能自动获取 group 上下文）
    if group is not None:
        workspace.tool_adapter._current_group_id = group.id
        workspace.tool_adapter._current_project_id = group.project_id
        workspace.tool_adapter._current_agent_id = agent.id  # send_message 用作 sender 标识
        workspace.tool_adapter._current_agent_name = agent.name  # send_message 用作 sender_name
    else:
        workspace.tool_adapter._current_group_id = None
        workspace.tool_adapter._current_project_id = None
        workspace.tool_adapter._current_agent_id = None
        workspace.tool_adapter._current_agent_name = None

    # v2 P2: 任务状态变更通知改走 EventDispatcher (经 event_bus).
    # 这里不再注入 awake 钩子 - ServerToolAdapter 也不再持有这些钩子字段.
    # 任务状态变更 → event_bus.publish → EventDispatcher 查订阅者 → 写 system packet + 启动新 session.

    memory_plugin = MemoryPlugin(
        manager=workspace.info_manager,
        max_history=20,
    )
    flow_agent.add_plugin(memory_plugin)

    # AllModelPlugin: 并行工具调用批处理，等所有 RESPONSE 到齐再调 LLM
    allmodel_plugin = AllModelPlugin(timeout=30.0)
    flow_agent.add_plugin(allmodel_plugin)

    # ToolEventPlugin: 捕获 RESPONSE/ERROR 转发给下游 ResultCollector，前端实时展示工具结果
    tool_event_plugin = ToolEventPlugin()
    flow_agent.add_plugin(tool_event_plugin)

    # ToolCallLimitPlugin: 上下文管理职责，防止 LLM 反复调工具不产 content 导致死循环
    # - warn_threshold=20: 连续 tool_calls 无文本输出时注入提醒 system message 让 LLM 自我反思
    # - max_threshold=50: 累计 tool_calls 达到上限时强制走 NORMAL 分支终止循环（触发 ResultCollector.set）
    # 这避免 agentflow agentic loop 因 LLM 行为问题导致 600s 超时 + streaming=true 永不 pop
    tool_call_limit_plugin = ToolCallLimitPlugin(warn_threshold=20, max_threshold=50)
    flow_agent.add_plugin(tool_call_limit_plugin)

    # 注册工具处理器（仅注册 Agent 显式配置的工具，kind 优先取顶层 kind，fallback 到 config.kind，再 fallback 到 name）
    # 注意：必须在 _seed_history_from_db 之前注册，以便历史过滤时能获取可用工具列表
    tool_configs = llm_context.get("tools", [])
    for tool_config in tool_configs:
        kind = tool_config.get("kind") or (tool_config.get("config") or {}).get("kind") or tool_config.get("name")
        if not kind:
            continue
        try:
            # config 中移除 kind，避免展开为构造函数的意外关键字参数
            # 注意：config 可能是 None（DB 中未设置时），需要保护
            tool_config_copy = dict(tool_config.get("config") or {})
            tool_config_copy.pop("kind", None)
            processor = create_builtin_processor(
                {"kind": kind, "name": kind, "config": tool_config_copy},
                workspace=workspace,
            )
            flow_agent.register_call_target(processor)
        except (ValueError, Exception) as e:
            logger.warning("Failed to register tool '%s': %s", kind, e)

    _seed_history_from_db(memory_plugin, flow_agent, llm_context, chain_id)

    return flow_agent, workspace


def _register_group_agents(
    primary_flow_agent: FlowAgent,
    primary_agent: Agent,
    group: Optional[Group],
    chain_id: str,
    session_factory,
    global_config: Optional[Dict[str, str]] = None,
    push_plugin: Optional[StreamPushPlugin] = None,
) -> set:
    """
    将群聊中的其他Agent注册为可调用工具（@agent机制）

    @本质上是将信息传输到被@agent的input，类似工具调用但在agent级别。
    CallbackPlugin自动处理RESPONSE回流，不会触发新CALL，天然防循环。

    被调agent也可以调用群聊中的其他agent（包括主agent），
    通过_agent_call_depth metadata追踪深度，超过MAX_AGENT_CALL_DEPTH时拒绝。

    Returns:
        注册的agent名称集合（用于深度限制）
    """
    if not group or not group.members:
        return set()

    # 收集群聊中所有agent（排除主agent）
    other_agents = []
    for member in group.members:
        if not member.project_agent or not member.project_agent.agent:
            continue
        other_agent = member.project_agent.agent
        if other_agent.id != primary_agent.id:
            other_agents.append(other_agent)

    if not other_agents:
        return set()

    agent_names = {a.name for a in other_agents}
    all_agent_names = agent_names | {primary_agent.name}

    # 为每个被调agent创建FlowAgent
    other_flow_agents = {}
    for other_agent in other_agents:
        other_llm = _build_llm(other_agent, global_config)

        other_flow_agent = FlowAgent(
            name=other_agent.name,
            llm=other_llm,
            system_prompt=other_agent.system_prompt or "",
            description=other_agent.description or f"群聊成员 {other_agent.name}，可以咨询其专业领域的问题",
        )
        other_flow_agent.set_timeout(180.0)

        # 创建独立 workspace（隔离记忆）
        db_path = _get_memory_db_path(f"{chain_id}_{other_agent.id}")
        workspace = Workspace(f"chain_{chain_id}_agent_{other_agent.id}", db_path=db_path)
        workspace.tool_adapter = ServerToolAdapter(session_factory)
        # 注入 group/project 上下文（被调 agent 也能获取到原 group 信息）
        if group is not None:
            workspace.tool_adapter._current_group_id = group.id
            workspace.tool_adapter._current_project_id = group.project_id

        # 注册被调agent的工具
        workspace.tool_adapter._current_agent_id = other_agent.id  # send_message 用作 sender
        workspace.tool_adapter._current_agent_name = other_agent.name  # send_message 用作 sender_name
        for tool in other_agent.tools:
            kind = tool.kind or (tool.config.get("kind") if isinstance(tool.config, dict) else None) or tool.name
            if not kind:
                continue
            try:
                tool_config_copy = dict(tool.config) if isinstance(tool.config, dict) else {}
                tool_config_copy.pop("kind", None)
                processor = create_builtin_processor(
                    {"kind": kind, "name": kind, "config": tool_config_copy},
                    workspace=workspace,
                )
                other_flow_agent.register_call_target(processor)
            except (ValueError, Exception) as e:
                logger.warning("Failed to register tool '%s' for agent '%s': %s", kind, other_agent.name, e)

        # 挂载 StreamPushPlugin（共享实例，推送该 agent 的 packet 到 WebSocket）
        if push_plugin is not None:
            other_flow_agent.add_plugin(push_plugin)

        other_flow_agents[other_agent.name] = other_flow_agent

    # 被调agent之间互相注册为call_target（允许agent间协作）
    # 同时将主agent也注册为被调agent的call_target
    # 修复: 玩家之间不应直接互调（会触发重复 dispatch + 身份泄露）。
    # 群聊场景下, 玩家交互必须经过 lead/法官 创建任务 → update_task_status 激活。
    # 因此去掉玩家之间的互注册, 只保留 玩家 → 主agent 的注册, 以及 depth limiter。
    for name, flow_agent in other_flow_agents.items():
        # 注册主agent（主agent作为工具可被调用, 玩家有事找法官）
        flow_agent.register_call_target(primary_flow_agent)
        # 添加深度限制器
        depth_limiter = _make_agent_call_depth_limiter(all_agent_names)
        flow_agent._post_processes.insert(0, depth_limiter)

        # P0 修复 (Bug 3): 给 sub-agent 加 SubAgentCallInjector,
        # 解决 "No user query found in messages" bug。
        #
        # plugin 顺序 (pre_process 阶段):
        #   1. StreamPushPlugin (推送 token 到 WS)
        #   2. CallbackPlugin (上面 register_call_target 加的, 创建 sub-chain + 标记 is_call=True)
        #   3. SubAgentCallInjector (新加, CALL→NORMAL 注入 user query)
        #   4. MemoryPlugin (新加, 保存 NORMAL user packet 到 sub-chain)
        #
        # 必须放在 CallbackPlugin 之后: 否则 sub_chain_id + is_call=True 标记还没建,
        # 转完 NORMAL 后 post_process 找不到 chain_info, response 不会回流到主 agent。
        # 必须放在 MemoryPlugin 之前: 让 MemoryPlugin 保存的是"转换后"的 NORMAL user packet
        # (而不是原始 CALL packet), 这样 LLM 看到 [system, user] 而不是 [system, tool_call]。
        # 同时 SubAgentCallInjector 不依赖 MemoryPlugin, 只读 packet.metadata, 顺序无关。
        flow_agent.add_plugin(SubAgentCallInjector())
        # 加 MemoryPlugin 让 sub-chain 历史有持久化 (后续 sub-agent 自己再调工具时
        # MemoryPlugin 能查 chain 历史, 虽然每个 call 一个新 sub-chain 隔离但保险起见加上)
        flow_agent.add_plugin(MemoryPlugin(max_history=20))

    # 将被调agent注册为主agent的call_target
    for name, flow_agent in other_flow_agents.items():
        primary_flow_agent.register_call_target(flow_agent)
        logger.info("Registered group agent '%s' as call target for '%s'", name, primary_agent.name)

    return agent_names


def _make_agent_call_depth_limiter(agent_names: set, max_depth: int = MAX_AGENT_CALL_DEPTH):
    """
    创建agent间调用深度限制post-process

    通过packet metadata中的_agent_call_depth追踪调用深度：
    - 每次agent调用其他agent时，depth+1
    - 超过max_depth时拒绝调用，返回ERROR
    - depth通过_build_call_packets的metadata复制机制自动传播

    必须在_route_call_packet之前执行（insert到post_processes首位）。
    """
    def limit_depth(packet: InfoPacket, output_list):
        if packet.type == PacketType.CALL:
            content = packet.content if isinstance(packet.content, dict) else {}
            tool_name = content.get('tool_name') or content.get('tool')
            if tool_name in agent_names:
                current_depth = packet.get_metadata('_agent_call_depth') or 0
                if isinstance(current_depth, str):
                    current_depth = int(current_depth)
                next_depth = current_depth + 1
                if next_depth > max_depth:
                    logger.warning("Agent call depth limit reached: %d > %d for %s", next_depth, max_depth, tool_name)
                    error_packet = packet.create_child(
                        sender_id=packet.sender_id,
                        content=f"[Agent Call Error] 已达到最大调用深度({max_depth})，无法继续调用 {tool_name}。请直接给出你的回答。",
                        packet_type=PacketType.ERROR,
                    )
                    error_packet.add_metadata("tool_name", tool_name)
                    error_packet.add_metadata("tool_call_id", content.get("tool_call_id", ""))
                    # 不路由到目标agent，让ERROR回到正常下游（ResultCollector等）
                    return error_packet, output_list
                packet.set_metadata('_agent_call_depth', next_depth)
        return packet, output_list
    return limit_depth


class ResultCollector(Processor):
    """
    结果收集器：接收 Agent 的最终输出，设置 Event 通知调用方

    挂在 Agent 的下游，当收到最终的 NORMAL 包时触发完成。

    工具调用流程（由 agentflow CallbackPlugin 自动处理回流）：
    1. Agent 返回 [text_packet(NORMAL), call_packet(CALL)]
    2. text_packet 到达 ResultCollector -> 如果包含工具调用标记，仅保存，不触发完成
    3. CALL 包被路由到工具处理器执行
    4. 工具结果(RESPONSE)回流到 Agent -> Agent 再次调用 LLM
    5. Agent 生成总结(NORMAL) -> 到达 ResultCollector -> 触发完成

    关键设计：重写 input() 方法，直接处理包而不经过 agentflow 的 dispatch 线程池，
    避免三跳路径导致的死锁风险（与原 StreamCollector 同理，现由 StreamPushPlugin 替代）。
    """

    def __init__(self):
        super().__init__(name="result_collector")
        self._event = asyncio.Event()
        self._holder: Dict[str, Any] = {"content": None, "metadata": {}}
        self._tool_calls: List[Dict[str, Any]] = []
        self._has_tool_call_pending = False
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = asyncio.get_event_loop()

    def input(self, packet: InfoPacket) -> None:
        """重写 input()：直接处理包，绕过 agentflow 的 submit_process 线程池调度"""
        self._handle_packet(packet)

    def _handle_packet(self, packet: InfoPacket) -> None:
        """统一包处理逻辑"""
        if packet.type == PacketType.CALL:
            content = packet.content if isinstance(packet.content, dict) else {}
            tool_name = content.get("tool_name") or content.get("tool", "unknown")
            arguments = content.get("arguments", {})
            self._tool_calls.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "timestamp": datetime.now().isoformat(),
            })
            self._has_tool_call_pending = True
        elif packet.type == PacketType.RESPONSE:
            # 工具结果不拼入 content，仅记录到 metadata
            tool_name = packet.get_metadata("tool_name") or "unknown"
            tool_call_id = packet.get_metadata("tool_call_id")
            # 合并 metadata（而非覆盖），保留之前收集的 render_spec 等
            new_metadata = dict(packet.metadata) if packet.metadata else {}
            self._holder["metadata"] = self._holder.get("metadata") or {}
            self._holder["metadata"].update(new_metadata)
            # page_inject: 工具把脚本放在返回 dict 里，从 packet.content 解析
            resp_inject_js, resp_inject_desc = _extract_inject_meta(packet)
            # 关联到对应的 tool_call 记录
            for call in reversed(self._tool_calls):
                if tool_call_id and call.get("tool_call_id") == tool_call_id:
                    call["result"] = packet.content
                    if resp_inject_js:
                        call["inject_js"] = resp_inject_js
                        if resp_inject_desc:
                            call["inject_description"] = resp_inject_desc
                    break
                elif not tool_call_id and call.get("tool_name") == tool_name and "result" not in call:
                    call["result"] = packet.content
                    if resp_inject_js:
                        call["inject_js"] = resp_inject_js
                        if resp_inject_desc:
                            call["inject_description"] = resp_inject_desc
                    break
            if self._tool_calls:
                self._holder["metadata"]["tool_calls"] = self._tool_calls
            # RESPONSE 不触发完成，等待 Agent 总结
        elif packet.type == PacketType.NORMAL:
            content_str = str(packet.content) if packet.content else ""
            has_pending_tool_calls = bool(packet.get_metadata("has_pending_tool_calls"))

            # 中间状态（含待处理工具调用）的文本不拼入最终 content
            if not has_pending_tool_calls:
                # 保留 think 标签，由前端负责解析和渲染
                clean_content = content_str
                if clean_content:
                    if not self._holder["content"]:
                        self._holder["content"] = clean_content
                    else:
                        self._holder["content"] = str(self._holder["content"]) + "\n\n" + clean_content

            self._holder["metadata"] = dict(packet.metadata) if packet.metadata else {}
            if self._tool_calls:
                self._holder["metadata"]["tool_calls"] = self._tool_calls

            # 仅当无待处理工具调用时，才触发完成
            if not has_pending_tool_calls:
                self._loop.call_soon_threadsafe(self._event.set)
        elif packet.type == PacketType.ERROR:
            error_content = packet.content
            if isinstance(error_content, dict):
                error_msg = error_content.get("error", str(error_content))
            else:
                error_msg = str(error_content)
            # 区分工具 ERROR（有 tool_call_id）与 agent 致命 ERROR
            # 工具错误不应终止 agent：让 Agent.core_process 把错误作为
            # tool role 反馈给 LLM，由 LLM 决定重试或换工具
            # （ToolCallLimitPlugin 兜底防死循环）
            tool_call_id = packet.get_metadata("tool_call_id")
            if tool_call_id:
                # 工具错误：像 RESPONSE 一样记录结果，不触发完成
                for call in reversed(self._tool_calls):
                    if call.get("tool_call_id") == tool_call_id:
                        call["result"] = {"error": error_msg}
                        break
                if self._tool_calls:
                    self._holder["metadata"] = self._holder.get("metadata") or {}
                    self._holder["metadata"]["tool_calls"] = self._tool_calls
                # 不 _event.set，等待 Agent 总结
            else:
                # agent 致命错误（LLM 调用失败等）：终止 agent
                self._holder["content"] = f"[Agent error: {error_msg}]"
                self._holder["metadata"] = {"error": True}
                if self._tool_calls:
                    self._holder["metadata"]["tool_calls"] = self._tool_calls
                self._loop.call_soon_threadsafe(self._event.set)

    def core_process(self, packet: InfoPacket) -> None:
        """Fallback：如果包意外走了管线调度，仍然正确处理"""
        self._handle_packet(packet)

    async def wait(self, timeout: float = 180.0) -> Dict[str, Any]:
        """等待结果返回"""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            if self._tool_calls:
                return {
                    "content": self._holder["content"] or "[Timeout: Agent did not respond in time]",
                    "metadata": {**self._holder.get("metadata", {}), "tool_calls": self._tool_calls, "partial": True}
                }
            return {"content": "[Timeout: Agent did not respond in time]", "metadata": {"error": "timeout"}}
        
        return self._holder

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        """获取记录的工具调用信息"""
        return self._tool_calls


class StreamPushPlugin(Plugin):
    """
    Workspace 级别的 packet → WebSocket 推送插件。

    替代 StreamCollector：不再使用 queue + SSE 中转，
    而是直接通过 broadcast_fn 将 packet 实时推送到前端 WebSocket。

    覆盖所有 packet 类型：
    - on_stream(STREAM)   → "token" 事件（流式 token）
    - post_process(CALL)  → "tool_call" 事件（工具调用开始）
    - pre_process(RESPONSE) → "tool_result" 事件（工具返回结果）
    - pre_process(ERROR)  → "error" 事件（错误包）

    挂载方式：在 _prepare 中创建，添加到 chain 内所有 agent（共享一个实例）。
    一个 chain 共享一个实例，统一收集所有 agent 的 tool_calls 记录。
    """

    def __init__(
        self,
        group_id: str,
        chain_id: str,
        broadcast_fn: Any,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        super().__init__(name="StreamPushPlugin")
        self.group_id = str(group_id) if group_id else ""
        self.chain_id = chain_id
        self._broadcast_fn = broadcast_fn
        self._loop = loop
        self._tool_calls: List[Dict[str, Any]] = []
        # 累计 token 内容，供 cancel 时获取部分内容做 DB finalize
        self._latest_content: str = ""
        # Token 批处理: 累积 token, 每 16ms 合并成一个 token 事件推送
        # 减少 run_coroutine_threadsafe 调度次数 + json.dumps 次数 + send_text 次数
        # reasoning 模型一秒几百 token, 不批处理会导致主循环协程堆积
        self._token_buffer: List[str] = []
        self._token_buffer_lock = threading.Lock()
        self._last_token_flush_ts: float = 0.0
        self._token_flush_interval: float = 0.016  # 16ms (对齐前端 rAF)
        self._token_chain_id: Optional[str] = None
        self._token_sender_id: Optional[str] = None

    def _flush_token_buffer(self) -> None:
        """合并 buffer 中的 token 成一个事件推送. 调用方需持有 _token_buffer_lock."""
        if not self._token_buffer:
            return
        batch_content = "".join(self._token_buffer)
        self._token_buffer.clear()
        self._last_token_flush_ts = time.time()
        chain_id = self._token_chain_id or ""
        sender_id = self._token_sender_id or ""
        # 构造 message (在 lock 内构造, _push 本身不阻塞)
        message = {
            "type": "token",
            "payload": {
                "chain_id": chain_id,
                "sender_id": sender_id,
                "content": batch_content,
            },
        }
        self._push(message)

    def _push(self, message: Dict[str, Any]) -> None:
        """线程安全地推送消息到 WebSocket（从工作线程调用）。"""
        # non-token 事件前先 flush 剩余 token, 保证前端事件顺序
        if message.get("type") != "token":
            with self._token_buffer_lock:
                self._flush_token_buffer()

        msg_type = message.get("type", "?")
        if not self._broadcast_fn:
            logger.warning(f"[StreamPushPlugin._push] DROP type={msg_type}: broadcast_fn is None")
            return
        if not self._loop:
            logger.warning(f"[StreamPushPlugin._push] DROP type={msg_type}: loop is None")
            return
        if not self._loop.is_running():
            logger.warning(f"[StreamPushPlugin._push] DROP type={msg_type}: loop not running")
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._broadcast_fn(self.group_id, message),
                self._loop,
            )
            logger.debug(f"[StreamPushPlugin._push] scheduled type={msg_type} group={self.group_id[:8]}")
        except Exception as e:
            logger.warning(f"[StreamPushPlugin._push] FAILED type={msg_type}: {e}", exc_info=True)

    def on_stream(self, packet: InfoPacket) -> None:
        """STREAM 包（token）→ 累积到 buffer, 每 16ms 合并推送一次。"""
        content = packet.content if isinstance(packet.content, str) else ""
        if content:
            self._latest_content += content
        logger.debug(f"[StreamPushPlugin.on_stream] token={repr(content[:20])} chain={packet.chain_id[:8]}")

        with self._token_buffer_lock:
            self._token_buffer.append(content)
            self._token_chain_id = packet.chain_id
            self._token_sender_id = packet.sender_id
            now = time.time()
            if now - self._last_token_flush_ts >= self._token_flush_interval:
                self._flush_token_buffer()

    @property
    def latest_content(self) -> str:
        """已累计的 token 内容（供 cancel 时获取部分内容）。"""
        return self._latest_content

    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        """RESPONSE/ERROR/聚合 NORMAL 包（进入 agent 输入侧）。"""
        if packet.type == PacketType.RESPONSE:
            self._handle_response(packet)
        elif packet.type == PacketType.ERROR:
            self._handle_error(packet)
        elif packet.type == PacketType.NORMAL and packet.get_metadata("aggregate") == "all":
            # AllModelPlugin 在 batch 模式下把多个 RESPONSE 聚合成一个 NORMAL 包,
            # 原始 RESPONSE 包不会到达 StreamPushPlugin.pre_process (被 AllModelPlugin
            # 转为 INTERRUPT 或聚合 NORMAL). 不处理会导致 batch 模式下 tool_calls
            # 的 result 永远 MISSING, 下次 _seed_history_from_db 重建历史时缺失
            # RESPONSE 包, OpenAI API 收到 assistant.tool_calls 但无对应 tool 消息,
            # LLM 行为异常 (重复调用相同工具).
            self._handle_aggregated(packet)
        return packet

    def post_process(self, packet: InfoPacket, output_list: list) -> tuple:
        """CALL 包（agent 输出侧）."""
        # 流结束 (stream_process 返回) 后 flush 剩余 token
        # post_process 是 stream 结束后的第一个 hook, 此时 token 不再产生
        # 注: _push 在 non-token 事件前已自动 flush, 但 NORMAL 包场景 post_process 不调 _push,
        # 需要这里兜底; 多次调用安全 (buffer 空时 _flush_token_buffer 直接返回)
        with self._token_buffer_lock:
            self._flush_token_buffer()
        if packet.type == PacketType.CALL:
            self._handle_call(packet)
        return packet, output_list

    def _handle_call(self, packet: InfoPacket) -> None:
        """工具调用开始 → 推送 tool_call 事件。"""
        content = packet.content if isinstance(packet.content, dict) else {}
        tool_name = content.get("tool_name") or content.get("tool", "unknown")
        arguments = content.get("arguments", {})
        tool_call_id = content.get("tool_call_id") or packet.get_metadata("tool_call_id")
        call_info = {
            "tool_name": tool_name,
            "arguments": arguments,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
        }
        self._tool_calls.append(call_info)
        self._push({"type": "tool_call", "payload": call_info})

    def _handle_response(self, packet: InfoPacket) -> None:
        """工具结果 → 推送 tool_result 事件 + render_spec。"""
        tool_name = packet.get_metadata("tool_name") or "unknown"
        tool_call_id = packet.get_metadata("tool_call_id")
        render_spec = packet.get_metadata("render_spec")
        inject_js, inject_description = _extract_inject_meta(packet)

        result_info: Dict[str, Any] = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "result": packet.content,
        }
        if render_spec:
            result_info["render_spec"] = render_spec
        if inject_js:
            result_info["inject_js"] = inject_js
            if inject_description:
                result_info["inject_description"] = inject_description

        # 关联结果到 tool_calls 记录
        matched = False
        for call in reversed(self._tool_calls):
            if tool_call_id and call.get("tool_call_id") == tool_call_id:
                call["result"] = packet.content
                if render_spec:
                    call["render_spec"] = render_spec
                if inject_js:
                    call["inject_js"] = inject_js
                    if inject_description:
                        call["inject_description"] = inject_description
                matched = True
                break
            elif not tool_call_id and call.get("tool_name") == tool_name and "result" not in call:
                call["result"] = packet.content
                if render_spec:
                    call["render_spec"] = render_spec
                if inject_js:
                    call["inject_js"] = inject_js
                    if inject_description:
                        call["inject_description"] = inject_description
                matched = True
                break
        if not matched:
            logger.warning(
                "[StreamPushPlugin._handle_response] NO MATCH for tool_name=%r tool_call_id=%r _tool_calls_count=%d",
                tool_name, tool_call_id, len(self._tool_calls),
            )

        self._push({"type": "tool_result", "payload": result_info})

    def _handle_error(self, packet: InfoPacket) -> None:
        """错误包 → 推送 error 事件 + 关联到 _tool_calls。"""
        error_content = packet.content
        if isinstance(error_content, dict):
            error_msg = error_content.get("error", str(error_content))
        else:
            error_msg = str(error_content)

        # 关联 error 到 _tool_calls (修复 ERROR 包 result MISSING bug).
        # 之前 _handle_error 只推送 error 事件, 不更新 _tool_calls, 导致
        # 工具调用失败的 tool_call 记录永远没有 result, 下次重建历史时缺失
        # RESPONSE 包 (与 batch 模式同样的问题).
        tool_call_id = packet.get_metadata("tool_call_id")
        tool_name = packet.get_metadata("tool_name") or "unknown"
        for call in reversed(self._tool_calls):
            if tool_call_id and call.get("tool_call_id") == tool_call_id:
                call["result"] = f"Error: {error_msg}"
                call["error"] = True
                break
            elif not tool_call_id and call.get("tool_name") == tool_name and "result" not in call:
                call["result"] = f"Error: {error_msg}"
                call["error"] = True
                break

        self._push({
            "type": "error",
            "payload": {
                "chain_id": packet.chain_id,
                "content": error_msg,
            },
        })

    def _handle_aggregated(self, packet: InfoPacket) -> None:
        """AllModelPlugin 聚合的 NORMAL 包 → 把每个 tool 的 result 关联到 _tool_calls。

        AllModelPlugin.pre_process 在 batch 模式下拦截原始 RESPONSE 包, 聚合成
        NORMAL 包 (content.results 是 list of dict, 每个含 tool_name/tool_call_id/result).
        本方法从 content.results 提取每个 tool 的 result, 关联到 _tool_calls 对应记录.

        不修复会导致 batch 模式下 tool_calls 的 result 永远 MISSING (如并行 read_resource x2),
        下次 _seed_history_from_db 重建历史时缺失 RESPONSE 包, OpenAI API 报 400.
        """
        content = packet.content
        if not isinstance(content, dict):
            return
        results = content.get("results") or []
        for item in results:
            tool_call_id = item.get("tool_call_id")
            tool_name = item.get("tool_name") or "unknown"
            result_content = item.get("result")
            status = item.get("status", "success")

            # 关联到 _tool_calls 对应记录
            for call in reversed(self._tool_calls):
                if tool_call_id and call.get("tool_call_id") == tool_call_id:
                    call["result"] = result_content
                    if status == "error":
                        call["error"] = True
                    break
                elif not tool_call_id and call.get("tool_name") == tool_name and "result" not in call:
                    call["result"] = result_content
                    if status == "error":
                        call["error"] = True
                    break

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        """供 executor 获取工具调用记录（用于最终 metadata）。"""
        return self._tool_calls


class AgentExecutor:
    """
    Agent执行器：负责执行Agent处理流程

    支持两种模式：
    1. 同步执行：execute() - 等待完整结果返回
    2. 流式执行：execute_stream() - 逐token返回结果

    v2 P2: 不再绑"任务变 in_progress / done 时唤起 X"的回调。
    任务事件通知改走 EventDispatcher (经 event_bus) — 谁订阅就通知谁,
    通知策略由订阅者的 skill 决定, 不硬编码 lead / assignee 角色。
    """

    def __init__(self, session_factory, session_gate=None):
        """
        Args:
            session_factory: SQLAlchemy async_session_factory
            session_gate: 可选, 共享的 SessionLifecycleGate 实例. None 时使用
                          模块级单例 (由 main.py 启动时通过 set_session_gate 注册).
                          显式传入用于测试隔离.
        """
        self._session_factory = session_factory
        self._tool_calls_tracker: List[Dict[str, Any]] = []
        # 按 chain_id 索引的 StreamPushPlugin 字典 (v6 streaming bug 修复 6)
        # 原设计为单实例 _current_push_plugin, 但嵌套 execute (如法官调 send_message
        # 跨群发消息) 时内层 _prepare 会覆盖外层引用, 导致外层 finalize 读到内层
        # push_plugin 的 latest_content (内容/chain_id 都错). 改字典按 chain_id 索引,
        # 外层用 chain_id 取回自己的 push_plugin, 互不干扰.
        self._push_plugins: Dict[str, "StreamPushPlugin"] = {}
        # session gate: 跨 dispatcher/executor 共享的 session lifecycle gate.
        # 不传则取全局单例 — 保证 ChatService / EventDispatcher / MessageDispatcher
        # 各自创建的 AgentExecutor 都共享同一个 gate (含群级串行锁).
        if session_gate is None:
            from app.orchestrator.session_lifecycle import get_session_gate
            session_gate = get_session_gate()
        self._session_gate = session_gate
        self.session_gate = session_gate  # public alias for app.state access

    async def _auto_complete_task_if_needed(self, task: Optional["Task"]) -> None:
        """卡点 5 修复: task chain 的 agent 完成回复后, 如果 task 仍 in_progress
        (agent 未调 update_task_status), 自动标记为 done 并触发事件,
        避免 task 永挂导致 EventDispatcher 无法触发 lead 通知.

        场景: agnes-2.0-flash 完成调研回复但没调 update_task_status,
        task 卡在 in_progress, 后续任务无法被 v9 修复激活.

        注意: 只对 task chain 生效 (task is not None), 主群流不触发.

        卡点 5 二次修复 (v16): 之前直接调 apply_task_status_transition 跳过了
        TaskService.update_status, 导致 task.status 字段没更新 (chain 已 archived
        但 task 仍 in_progress). 正确顺序: 先 update_status 改 task.status,
        再 apply_task_status_transition 处理 chain 侧 + 发布事件.
        """
        if task is None:
            return
        try:
            from app.services.chain_handover_service import ChainHandoverService
            from app.services.task_service import TaskService
            from app.models.task import Task as TaskModel
            async with self._session_factory() as db:
                # 重新查询 task 当前状态 (agent 执行过程中可能已更新)
                current = await db.get(TaskModel, task.id)
                if current is None:
                    return
                if current.status != "in_progress":
                    # 已是 done/todo/其他状态, 不需要兜底
                    return
                # 1) 先更新 task.status (apply_task_status_transition 的前置条件)
                updated = await TaskService(db).update_status(task.id, "done")
                if updated is None:
                    logger.warning("[execute] auto-complete task %s: update_status returned None", task.id[:8])
                    return
                # 2) 处理 chain 侧 (fold task chain → archived, 主链 active)
                #    + 发布 task_status_changed 事件 + v9 修复激活下一个 todo
                handover_svc = ChainHandoverService(db)
                await handover_svc.apply_task_status_transition(updated, "done", result="")
                await db.commit()
                logger.info(
                    "[execute] task=%s auto-completed by framework (agent=%s 未调 update_task_status)",
                    task.id[:8], getattr(task, "lead_agent_id", "?")[:8] if task.lead_agent_id else "?",
                )
        except Exception as e:
            logger.exception("[execute] auto-complete task %s failed: %s", task.id[:8], e)

    def get_push_plugin(self, chain_id: str) -> Optional["StreamPushPlugin"]:
        """
        按 chain_id 取回对应的 StreamPushPlugin (v6 修复 6).

        嵌套 execute 场景下 (如法官调 send_message 跨群发消息), 外层和内层
        各有自己的 push_plugin, 用 chain_id 区分. 外层 _run_stream_decoupled
        用本方法取回自己的 push_plugin, 不会被内层覆盖.

        Returns:
            StreamPushPlugin 或 None (该 chain_id 没有挂载 push_plugin 时)
        """
        return self._push_plugins.get(chain_id)

    def _make_call_tracker_post_process(self):
        """创建一个post-process来记录CALL包和RESPONSE包的工具调用信息"""
        def track_call(packet: InfoPacket, output_list):
            if packet.type == PacketType.CALL:
                content = packet.content if isinstance(packet.content, dict) else {}
                tool_name = content.get("tool_name") or content.get("tool", "unknown")
                arguments = content.get("arguments", {})
                tool_call_id = content.get("tool_call_id") or packet.get_metadata("tool_call_id")
                self._tool_calls_tracker.append({
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "tool_call_id": tool_call_id,
                    "timestamp": datetime.now().isoformat(),
                })
            elif packet.type == PacketType.RESPONSE:
                # 工具返回结果，关联到对应的CALL记录
                tool_name = packet.get_metadata("tool_name") or "unknown"
                tool_call_id = packet.get_metadata("tool_call_id")
                result_content = packet.content
                # 从 RESPONSE 包中提取 render_spec（render_view 工具生成的数据视图配置）
                render_spec = packet.get_metadata("render_spec")
                # 提取 page_inject 工具的 inject_js（从 packet.content JSON 里）
                inject_js, inject_description = _extract_inject_meta(packet)
                # 查找对应的CALL记录并添加结果
                for call in reversed(self._tool_calls_tracker):
                    if tool_call_id and call.get("tool_call_id") == tool_call_id:
                        call["result"] = result_content
                        if render_spec:
                            call["render_spec"] = render_spec
                        if inject_js:
                            call["inject_js"] = inject_js
                            if inject_description:
                                call["inject_description"] = inject_description
                        break
                    elif not tool_call_id and call.get("tool_name") == tool_name and "result" not in call:
                        call["result"] = result_content
                        if render_spec:
                            call["render_spec"] = render_spec
                        if inject_js:
                            call["inject_js"] = inject_js
                            if inject_description:
                                call["inject_description"] = inject_description
                        break
            return packet, output_list
        return track_call

    async def _prepare(
        self,
        agent: Agent,
        project_agent: Optional[ProjectAgent] = None,
        group: Optional[Group] = None,
        task: Optional[Task] = None,
        chain: Optional[Chain] = None,
    ):
        """准备Agent执行环境"""
        from app.orchestrator.context_builder import ContextBuilder

        t_prepare_start = time.perf_counter()
        chain_id_log = chain.id[:8] if chain else "adhoc"
        logger.info(f"[_prepare] start for agent={agent.name}, chain={chain_id_log}")

        # 重置工具调用追踪器
        self._tool_calls_tracker = []

        t0 = time.perf_counter()
        async with self._session_factory() as db:
            builder = ContextBuilder(db)
            context = await builder.build(
                agent=agent,
                project_agent=project_agent,
                group=group,
                task=task,
                chain=chain,
            )
            llm_context = builder.format_for_llm(context)
        _perf(f"_prepare.chain={chain_id_log} ContextBuilder.build", t0)

        logger.info(f"[_prepare] context built, llm_context keys={list(llm_context.keys()) if llm_context else 'None'}")

        # 记录 execution_mode 变体（用于 A/B 测试分析）
        exec_mode = llm_context.get("execution_mode") or {}
        if exec_mode:
            logger.info(
                f"[_prepare] execution_mode: mode={exec_mode.get('mode')}, "
                f"variant={exec_mode.get('variant')}, label={exec_mode.get('label')}, "
                f"intensity={exec_mode.get('intensity')}, env_override={exec_mode.get('env_override') or '(none)'}"
            )

        # 从 DB 加载全局 LLM 配置（API Key 等）
        t0 = time.perf_counter()
        global_llm_config = await _load_global_llm_config(self._session_factory)
        _perf(f"_prepare.chain={chain_id_log} load_global_llm_config", t0)

        chain_id = chain.id if chain else "adhoc"
        t0 = time.perf_counter()
        flow_agent, workspace = _build_context_and_agent(
            agent, llm_context, chain_id, self._session_factory, global_llm_config, group=group
        )
        _perf(f"_prepare.chain={chain_id_log} _build_context_and_agent", t0)

        logger.info(f"[_prepare] flow_agent built: {flow_agent.name}")

        # 设置主agent的description（用于被其他agent调用时的工具schema）
        if not flow_agent.description:
            flow_agent.description = agent.description or f"群聊成员 {agent.name}"

        # 创建并挂载 StreamPushPlugin（workspace 级别，推送所有 packet 到 WebSocket）
        # 按 chain_id 存入字典 (v6 修复 6), 供 _run_stream_decoupled 用 chain_id 取回
        self._push_plugins.pop(chain_id, None)
        try:
            from app.orchestrator.websocket_manager import ws_manager
            loop = asyncio.get_running_loop()
            group_id = str(group.id) if group else ""
            push_plugin = StreamPushPlugin(
                group_id=group_id,
                chain_id=chain_id,
                broadcast_fn=ws_manager.broadcast,
                loop=loop,
            )
            flow_agent.add_plugin(push_plugin)
            self._push_plugins[chain_id] = push_plugin
            logger.info(
                f"[_prepare] StreamPushPlugin mounted group={group_id[:8]} chain={chain_id[:8]} "
                f"loop={loop} running={loop.is_running()} broadcast_fn={ws_manager.broadcast}"
            )
        except Exception:
            logger.debug("[_prepare] StreamPushPlugin mount failed", exc_info=True)

        # 注册群聊其他Agent为可调用工具（@agent机制）
        t0 = time.perf_counter()
        agent_names = _register_group_agents(
            flow_agent, agent, group, chain_id, self._session_factory, global_llm_config,
            push_plugin=push_plugin,
        )
        _perf(f"_prepare.chain={chain_id_log} _register_group_agents (count={len(agent_names)})", t0)

        logger.info(f"[_prepare] registered agents: {agent_names}")

        # 添加深度限制器（必须在_route_call_packet之前）
        if agent_names:
            depth_limiter = _make_agent_call_depth_limiter(agent_names)
            flow_agent._post_processes.insert(0, depth_limiter)

        # 添加CALL包追踪post-process
        flow_agent.add_post_process(self._make_call_tracker_post_process())

        _perf(f"_prepare.chain={chain_id_log} _prepare TOTAL", t_prepare_start)
        logger.info("[_prepare] done")
        return flow_agent, workspace, chain_id

    def _make_user_packet(self, chain_id: str, user_message: Optional[str]) -> InfoPacket:
        """构建用户消息 InfoPacket"""
        user_packet = InfoPacket(
            id=f"user_msg_{uuid.uuid4().hex[:12]}",
            sender_id="user",
            parent_id=None,
            chain_id=chain_id,
            content=user_message or "",
            type=PacketType.NORMAL,
            timestamp=datetime.now(),
        )
        user_packet.add_metadata("sender_type", "user")
        user_packet.add_metadata("sender_name", "用户")
        return user_packet

    async def execute(
        self,
        agent: Agent,
        project_agent: Optional[ProjectAgent] = None,
        group: Optional[Group] = None,
        task: Optional[Task] = None,
        chain: Optional[Chain] = None,
        user_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行 Agent（非流式）

        通过 agentflow 管线发送用户消息，等待 Agent 处理完成，
        支持多轮工具调用。MemoryPlugin 使用持久化 SQLite 保留历史。

        工具调用流程：
        1. 用户消息 → Agent → LLM → 工具调用(CALL) → 工具处理器 → RESPONSE
        2. RESPONSE → Agent → LLM总结 → 最终回复(NORMAL)

        429 限流重试：免费模型档 60s 限流容易触发。
        MemoryPlugin 持久化历史，重试时 LLM 上下文不丢。

        v2 P2+: 同 (agent_id, group_id) 同时只允许一个 active session.
                 execute() 入口 await 已有 session 完成 (chat API 启动的)，
                 出口时 register 当前 task 到 registry, 完成后 release.

        v2 P3: 群级串行锁 (serial_execution).
                 对 workflow_config.serial_execution=true 的 group, 整个 execute()
                 持有群级 asyncio.Lock, 确保同群不同 agent 也串行执行.
                 解决狼人杀"群内串行"需求: 法官激活玩家任务后, 玩家 session 等
                 法官 execute() 结束才真正开始, 避免 LLM 请求排队导致 TTFT 累积.
        v7 修复: task chain 跳过 group_lock, 避免级联阻塞.
                 task chain 是子 chain, 发言写到 task chain 不污染主群, 不需要群级串行保护.
                 group_lock 只保护主群 chain (防止发言混乱), task chain 并行执行.
                 修复"法官持锁等玩家1, 玩家1 等锁"的 600s 死等.
        """
        # v2 P3: 群级串行锁 — 在 agent 级 gate 之前 acquire, 确保 whole execute 互斥
        # v7 修复: task chain 不获取 group_lock, 避免级联阻塞.
        #   根因: 法官持 group_lock 在 result_collector.wait(600s) 等玩家1 的 NORMAL 包,
        #   玩家1 的 execute 卡在 group_lock.acquire() 拿不到锁, 双方死等 600s 超时.
        #   修复: task chain 是子 chain, 发言写到 task chain 不污染主群, 不需要群级串行保护.
        #   group_lock 只保护主群 chain (防止发言混乱), task chain 并行执行.
        #   注: group_lock 原初衷是防本地 ollama 并发导致 TTFT 累积, 云端 API (agnes-2.0-flash) 无此问题.
        #   判断: task is not None ⟺ chain.task_id 不为空 ⟺ 在 task chain 中执行.
        group_lock_acquired = False
        group_lock = None
        is_task_chain = task is not None
        if is_serial_group(group) and group is not None and not is_task_chain:
            group_lock = self._session_gate.get_group_lock(group.id)

        try:
            if group_lock is not None:
                t_glock = time.perf_counter()
                await group_lock.acquire()
                group_lock_acquired = True
                _perf(f"execute agent={agent.name} group_lock.acquire (group={group.name}, task_chain={is_task_chain})", t_glock)

            # session lifecycle gate: 等同 (agent, group) 已有 session 完成
            session_key = (agent.id, group.id if group else "")
            t0 = time.perf_counter()
            await self._session_gate.wait_for_active(session_key, timeout=600.0)
            _perf(f"execute agent={agent.name} session_gate.wait_for_active", t0)

            flow_agent, _workspace, chain_id = await self._prepare(
                agent, project_agent, group, task, chain
            )

            # 启用 stream_mode：StreamPushPlugin 捕获 token 并推送到 WebSocket
            # ResultCollector 仍然捕获最终 NORMAL 包用于结果返回
            flow_agent.set_stream_mode(True)

            MAX_LLM_RETRIES = 3
            for attempt in range(MAX_LLM_RETRIES):
                result_collector = ResultCollector()
                flow_agent.to(result_collector)
                # 把当前 collector task 注册为 active, 等它完成再放行
                # 用一个轻量级 task 包住 collector.wait
                current_task = asyncio.current_task()
                if current_task is not None:
                    await self._session_gate.register_active(session_key, current_task)

                user_packet = self._make_user_packet(chain_id, user_message)
                logger.debug("Sending user packet to agent: %s (attempt %d)", user_packet.id, attempt + 1)
                t0 = time.perf_counter()
                flow_agent.input(user_packet)
                logger.debug("User packet submitted to agent flow")

                # 不设总时间超时 (用户反馈: 多轮总时间超时本身不合理).
                # 三层独立兜底:
                #   1) 单次 LLM 请求挂起 → chat_stream 内 chunk-level timeout (60s)
                #   2) 工具循环不收敛    → ToolCallLimitPlugin max_threshold=50
                #   3) agent 自然结束    → ResultCollector._event.set()
                result = await result_collector.wait(timeout=None)
                _perf(f"execute agent={agent.name} flow_agent.input+wait (attempt={attempt+1})", t0)
                logger.debug("ResultCollector returned: %s", str(result.get('content', ''))[:100])

                content = result.get("content", "") or ""
                is_rate_limited = (
                    "429" in content
                    or "rate limit" in content.lower()
                    or "You've reached" in content
                )
                if not is_rate_limited:
                    # 从追踪器获取工具调用信息，合并到metadata
                    metadata = result.get("metadata", {})
                    if self._tool_calls_tracker:
                        metadata["tool_calls"] = self._tool_calls_tracker
                    return {
                        "content": result["content"],
                        "metadata": metadata,
                    }
                # 限流：递增等待后重试
                wait_seconds = 15 * (attempt + 1)  # 15s, 30s, 45s
                logger.warning(
                    "[execute] chain=%s 429 限流, 第 %d/%d 次重试, 等 %ds",
                    chain_id[:8], attempt + 1, MAX_LLM_RETRIES, wait_seconds,
                )
                if attempt < MAX_LLM_RETRIES - 1:
                    await asyncio.sleep(wait_seconds)
                    # 重连 collector：旧 collector 已 set 事件，重试需要新 collector
                    # 通过重建 result_collector 实现
                    continue
                logger.error(
                    "[execute] chain=%s 429 重试 %d 次仍失败, 返回错误",
                    chain_id[:8], MAX_LLM_RETRIES,
                )
                metadata = result.get("metadata", {})
                if self._tool_calls_tracker:
                    metadata["tool_calls"] = self._tool_calls_tracker
                return {
                    "content": result.get("content", f"[Agent error: 429 rate limit after {MAX_LLM_RETRIES} retries]"),
                    "metadata": metadata,
                }
        finally:
            if group_lock_acquired and group_lock is not None:
                group_lock.release()
                logger.info(
                    "[execute] agent=%s group_lock released (group=%s)",
                    agent.name, group.name if group else "?",
                )
            # 卡点 5 修复: task chain 完成 (无论正常/限流/异常), 如果 task 仍 in_progress,
            # 自动标记 done 触发 EventDispatcher 唤醒 lead + v9 修复激活下一个 todo
            await self._auto_complete_task_if_needed(task)

    async def execute_stream(
        self,
        agent: Agent,
        project_agent: Optional[ProjectAgent] = None,
        group: Optional[Group] = None,
        task: Optional[Task] = None,
        chain: Optional[Chain] = None,
        user_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        流式执行 Agent — 通过 StreamPushPlugin 将 token/tool_call/tool_result 实时推送到 WebSocket。

        与 execute() 共用底层逻辑（stream_mode=True）：
        - StreamPushPlugin（workspace 级别 plugin）捕获所有 packet 并推送到 WebSocket
        - ResultCollector 捕获最终 NORMAL 包用于结果返回
        - 调用方通过 await 获取最终结果，不再需要逐 chunk 迭代

        Returns:
            {"content": str, "metadata": dict}
        """
        return await self.execute(agent, project_agent, group, task, chain, user_message)
