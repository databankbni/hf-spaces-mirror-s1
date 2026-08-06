"""
消息调度器模块

负责管理讨论链中的消息调度，协调Agent发言顺序。
"""

import logging
import time
from typing import Optional, Dict, Any, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.agent import Agent, ProjectAgent
from app.models.group import Group
from app.models.task import Task
from app.models.chain import Chain, Packet
from app.orchestrator.agent_executor import AgentExecutor

_logger = logging.getLogger(__name__)


def _perf(label: str, start: float) -> None:
    """统一耗时日志（[perf] 前缀，便于 grep 排查慢点）"""
    _logger.info("[perf] %s %.3fs", label, time.perf_counter() - start)


class MessageType:
    """
    消息类型常量

    定义WebSocket和内部消息的类型。
    """
    # 客户端 → 服务器
    SEND_MESSAGE = "send_message"
    STOP_AGENT = "stop_agent"
    RESUME = "resume"
    PING = "ping"

    # 服务器 → 客户端
    AGENT_MESSAGE = "agent_message"
    AGENT_TYPING = "agent_typing"
    SYSTEM_MESSAGE = "system_message"
    TASK_UPDATE = "task_update"
    ERROR = "error"
    PONG = "pong"


class MessageDispatcher:
    """
    Agent消息调度器

    职责：
    1. 接收用户/Agent消息
    2. 决定下一个发言者
    3. 调用Agent生成回复
    4. 广播消息

    调度逻辑：
    - 主导Agent自行决定谁发言（通过LLM判断）
    - 系统不硬编码发言顺序
    - 同一时刻只有一个发言者

    Example:
        dispatcher = MessageDispatcher(db)
        await dispatcher.dispatch(chain_id, user_message="请开始讨论")
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        """
        初始化消息调度器

        Args:
            session_factory: 数据库会话工厂
        """
        self._session_factory = session_factory
        self.agent_executor = AgentExecutor(session_factory)
        self._active_chains: Dict[str, bool] = {}  # chain_id -> is_active
        self._stop_flags: Dict[str, bool] = {}  # chain_id -> should_stop

    async def dispatch(
        self,
        chain_id: str,
        user_message: Optional[str] = None,
        on_message: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        on_typing: Optional[Callable[[str, str], Awaitable[None]]] = None,
        skip_user_message_save: bool = False,
    ) -> Dict[str, Any]:
        """
        调度消息

        接收用户消息，触发Agent响应流程。

        Args:
            chain_id: 讨论链ID
            user_message: 用户消息
            on_message: 消息回调函数
            on_typing: 输入中回调函数
            skip_user_message_save: 跳过 user 消息保存（send_message 内部已写）

        Returns:
            Dict: 目标 agent 的最终回复信息，供调用方（send_message 工具）作为工具结果返回
            {
                "status": "ok" | "error",
                "sender_id": ...,
                "sender_name": "<目标 agent 名称>",
                "content": "<目标 agent 回复内容>",
                "tool_calls_made": ["set_memory", "send_message"],
                "error": "..." (status=error)
            }
        """
        # 标记链为活跃
        self._active_chains[chain_id] = True
        self._stop_flags[chain_id] = False

        t_dispatch_start = time.perf_counter()
        chain_tag = chain_id[:8]

        result: Dict[str, Any] = {
            "status": "error",
            "sender_name": "",
            "content": "",
            "tool_calls_made": [],
        }

        try:
            # 获取链信息
            t0 = time.perf_counter()
            chain = await self._get_chain(chain_id)
            _perf(f"dispatch.chain={chain_tag} get_chain", t0)
            if not chain:
                result["error"] = f"Chain not found: {chain_id}"
                return result

            # 获取群聊信息
            t0 = time.perf_counter()
            group = await self._get_group(chain.group_id)
            _perf(f"dispatch.chain={chain_tag} get_group", t0)
            if not group:
                result["error"] = f"Group not found: {chain.group_id}"
                return result

            # 获取任务信息
            t0 = time.perf_counter()
            task = await self._get_task(chain.task_id) if chain.task_id else None
            _perf(f"dispatch.chain={chain_tag} get_task", t0)

            # 获取主导Agent
            t0 = time.perf_counter()
            lead_agent = await self._get_lead_agent(group)
            _perf(f"dispatch.chain={chain_tag} get_lead_agent", t0)
            if not lead_agent:
                result["error"] = "No lead agent found"
                return result

            # 存储用户消息
            if user_message and not skip_user_message_save:
                t0 = time.perf_counter()
                await self._save_message(
                    chain_id=chain_id,
                    sender_type="user",
                    content=user_message,
                )
                _perf(f"dispatch.chain={chain_tag} save_user_message", t0)

            # 检查是否需要停止
            if self._stop_flags.get(chain_id):
                result["status"] = "ok"
                result["content"] = "[stopped]"
                return result

            # 通知正在输入
            if on_typing:
                await on_typing(lead_agent.id, lead_agent.name)

            _logger.info(
                "[perf] dispatch.chain=%s >>> agent=%s group=%s 进入 execute (累计 %.3fs)",
                chain_tag, lead_agent.name, group.id[:8],
                time.perf_counter() - t_dispatch_start,
            )

            # 调用 Agent（带 429 限流重试）
            # 免费模型档（agnes-2.0-flash）60s 限流容易触发，
            # 重试时 MemoryPlugin 持久化历史会保留，重跑 LLM 上下文不会丢。
            MAX_LLM_RETRIES = 3
            response: Dict[str, Any] = {"content": "", "metadata": {}}
            for llm_attempt in range(MAX_LLM_RETRIES):
                t_exec_start = time.perf_counter()
                response = await self.agent_executor.execute(
                    agent=lead_agent,
                    group=group,
                    task=task,
                    chain=chain,
                    user_message=user_message,
                )
                _perf(f"dispatch.chain={chain_tag} agent_executor.execute (attempt={llm_attempt+1})", t_exec_start)
                content = response.get("content", "") or ""
                is_rate_limited = (
                    "429" in content
                    or "rate limit" in content.lower()
                    or "You've reached" in content
                )
                if not is_rate_limited:
                    break
                # 限流命中：等待递增秒数后重试
                wait_seconds = 15 * (llm_attempt + 1)  # 15s, 30s, 45s
                _logger.warning(
                    "[dispatch] chain=%s 429 限流, 第 %d/%d 次重试, 等 %ds",
                    chain_tag, llm_attempt + 1, MAX_LLM_RETRIES, wait_seconds,
                )
                if llm_attempt < MAX_LLM_RETRIES - 1:
                    import asyncio as _asyncio
                    await _asyncio.sleep(wait_seconds)
                else:
                    _logger.error(
                        "[dispatch] chain=%s 429 重试 %d 次仍失败, 返回错误",
                        chain_tag, MAX_LLM_RETRIES,
                    )

            # 存储Agent消息
            t0 = time.perf_counter()
            await self._save_message(
                chain_id=chain_id,
                sender_id=lead_agent.id,
                sender_type="agent",
                sender_name=lead_agent.name,
                content=response["content"],
                metadata=response.get("metadata", {}),
            )
            _perf(f"dispatch.chain={chain_tag} save_agent_message", t0)

            # 广播消息
            if on_message:
                await on_message({
                    "type": MessageType.AGENT_MESSAGE,
                    "payload": {
                        "chain_id": chain_id,
                        "sender_id": lead_agent.id,
                        "sender_name": lead_agent.name,
                        "content": response["content"],
                        "metadata": response.get("metadata", {}),
                    },
                })

            # *** 关键：把回复包成结构化结果返回 ***
            result.update({
                "status": "ok",
                "sender_id": lead_agent.id,
                "sender_name": lead_agent.name,
                "content": response["content"],
                "tool_calls_made": [
                    tc.get("tool_name", "")
                    for tc in (response.get("metadata", {}) or {}).get("tool_calls", [])
                ],
            })
            _logger.info(
                "[perf] dispatch.chain=%s <<< DONE 总耗时 %.3fs (LLM重试 %d 次)",
                chain_tag, time.perf_counter() - t_dispatch_start, llm_attempt + 1,
            )
            return result

        except Exception as e:
            _logger.exception("dispatch failed: %s", e)
            result["error"] = str(e)[:200]
            return result
        finally:
            # 清理状态
            self._active_chains.pop(chain_id, None)
            self._stop_flags.pop(chain_id, None)

    async def stop(self, chain_id: str) -> None:
        """
        停止Agent响应

        Args:
            chain_id: 讨论链ID
        """
        self._stop_flags[chain_id] = True

    def is_active(self, chain_id: str) -> bool:
        """
        检查链是否正在处理

        Args:
            chain_id: 讨论链ID

        Returns:
            bool: 是否正在处理
        """
        return self._active_chains.get(chain_id, False)

    async def _get_chain(self, chain_id: str) -> Optional[Chain]:
        """获取讨论链"""
        from sqlalchemy import select
        async with self._session_factory() as db:
            query = select(Chain).where(Chain.id == chain_id)
            result = await db.execute(query)
            return result.scalar_one_or_none()

    async def _get_group(self, group_id: str) -> Optional[Group]:
        """获取群聊"""
        from sqlalchemy import select
        async with self._session_factory() as db:
            query = select(Group).where(Group.id == group_id)
            result = await db.execute(query)
            return result.scalar_one_or_none()

    async def _get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        from sqlalchemy import select
        async with self._session_factory() as db:
            query = select(Task).where(Task.id == task_id)
            result = await db.execute(query)
            return result.scalar_one_or_none()

    async def _get_lead_agent(self, group: Group) -> Optional[Agent]:
        """
        获取群聊的主导Agent

        groups.lead_agent_id 存的是 ProjectAgent.id (不是 Agent.id)，
        需要先查 ProjectAgent 拿到 agent_id，再查 Agent。

        如果 lead_agent 未设置（私有群场景），取群中第一个成员 agent。

        Args:
            group: 群聊对象

        Returns:
            Optional[Agent]: 主导Agent
        """
        import logging
        logger = logging.getLogger(__name__)
        from sqlalchemy import select
        from app.models.agent import ProjectAgent
        from app.models.group import GroupMember
        logger.info("[_get_lead_agent] group=%s lead_agent_id(pa_id)=%s", group.id[:8], group.lead_agent_id or "NONE")
        async with self._session_factory() as db:
            if group.lead_agent_id:
                # groups.lead_agent_id 是 ProjectAgent.id, 需先查到 ProjectAgent 再取 agent_id
                pa_query = select(ProjectAgent).where(ProjectAgent.id == group.lead_agent_id)
                pa = (await db.execute(pa_query)).scalar_one_or_none()
                if pa:
                    query = select(Agent).where(Agent.id == pa.agent_id)
                    agent = (await db.execute(query)).scalar_one_or_none()
                    logger.info("[_get_lead_agent] lead by lead_agent_id: %s", agent.name if agent else "NONE")
                    if agent:
                        return agent

            # 没设 lead_agent: 取群成员中第一个 agent
            query = (
                select(Agent)
                .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
                .join(GroupMember, GroupMember.project_agent_id == ProjectAgent.id)
                .where(GroupMember.group_id == group.id)
                .order_by(GroupMember.created_at.asc())
                .limit(1)
            )
            result = await db.execute(query)
            agent = result.scalar_one_or_none()
            logger.info("[_get_lead_agent] fallback to first member: %s", agent.name if agent else "NONE")
            return agent

    async def _save_message(
        self,
        chain_id: str,
        content: str,
        sender_type: str,
        sender_id: Optional[str] = None,
        sender_name: Optional[str] = None,
        content_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Packet:
        """保存消息到数据库（委托给 ChatService._save_packet）"""
        from app.services.chat_service import ChatService

        async with self._session_factory() as db:
            packet = await ChatService._save_packet(
                db,
                chain_id=chain_id,
                content=content,
                sender_type=sender_type,
                sender_id=sender_id or sender_type,
                sender_name=sender_name or "unknown",
                metadata=metadata,
            )
            await db.commit()
            await db.refresh(packet)
            return packet

    
