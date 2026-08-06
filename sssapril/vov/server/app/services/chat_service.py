"""
聊天服务模块

处理群聊中的消息发送和Agent响应生成。
通过 AgentExecutor 使用 agentflow 管线执行。
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.models.group import Group, GroupMember
from app.models.agent import Agent, ProjectAgent
from app.models.chain import Chain, Packet
from app.models.task import Task
from app.orchestrator.agent_executor import AgentExecutor
from app.services.chain_query_service import ChainQueryService
from app.services.stream_session import (
    registry as stream_registry,
    StreamSession,
)

from agentflow.content_protocol import strip_tool_call_markers


# 内容型工具：会产出一段实质文本（不只是元数据）
_CONTENT_TOOLS = {"write_file", "write_resource", "write_skill"}


def _summarize_content_tools(tool_calls: List[Dict[str, Any]]) -> str:
    """
    把内容型工具的产物摘要拼成一段文本

    当 LLM 调了 write_file / write_resource 写了大段内容，但自己在最终 NORMAL 包
    里没展开时，调用方在群聊里就看不到产物。本函数把工具产物的预览拼成可读文本。
    """
    blocks: List[str] = []
    for tc in tool_calls:
        name = tc.get("tool_name", "")
        if name not in _CONTENT_TOOLS:
            continue
        args = tc.get("arguments") or {}
        result = tc.get("result")

        # 1. 路径/标题
        if name == "write_file":
            path = args.get("path") or args.get("file_path") or "file"
            content = args.get("content", "")
            if not content and isinstance(result, dict):
                content = result.get("content") or result.get("file_content") or ""
            if not content:
                continue
            preview_chars = 1500  # 群聊里展示前 1500 字
            preview = content if len(content) <= preview_chars else content[:preview_chars] + "\n\n[... 内容过长，已截断 ...]"
            blocks.append(f"📄 **写入文件 `{path}`**（{len(content)} 字）：\n\n{preview}")
        elif name == "write_resource":
            title = args.get("title") or "资源"
            content = args.get("content", "")
            if not content and isinstance(result, dict):
                content = result.get("content") or ""
            if not content:
                # 用 title 至少给出存在信号
                blocks.append(f"📚 **资源 `{title}` 已写入项目资源库**")
                continue
            preview_chars = 1500
            preview = content if len(content) <= preview_chars else content[:preview_chars] + "\n\n[... 资源内容过长，已截断 ...]"
            blocks.append(f"📚 **写入资源 `{title}`**（{len(content)} 字）：\n\n{preview}")
        elif name == "write_skill":
            skill_name = args.get("name") or "skill"
            blocks.append(f"🛠 **技能 `{skill_name}` 已写入**")
    return "\n\n---\n\n".join(blocks)


def _extract_inject_from_tool_call(tc: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """从 page_inject 工具的 tool_call 记录中提取 inject_js / inject_description。

    优先读顶层字段（新版采集器/后端直填），否则从 result 字符串/字典里解析。
    """
    inject_js = tc.get("inject_js")
    inject_description = tc.get("inject_description")
    if inject_js:
        return inject_js, inject_description

    result_raw = tc.get("result")
    parsed: Optional[Dict[str, Any]] = None
    if isinstance(result_raw, dict):
        parsed = result_raw
    elif isinstance(result_raw, str) and result_raw.strip().startswith("{"):
        try:
            parsed = json.loads(result_raw)
        except (ValueError, TypeError):
            parsed = None

    if isinstance(parsed, dict):
        inject_js = parsed.get("inject_js") or inject_js
        if not inject_description:
            inject_description = parsed.get("description")

    return inject_js, inject_description


class ChatService:
    """聊天服务"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._agent_executor = AgentExecutor(session_factory)

    async def send_message_and_get_response(
        self,
        group_id: str,
        user_content: str,
        target_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        发送用户消息并获取Agent响应

        Args:
            group_id: 群聊ID
            user_content: 用户消息内容
            target_agent_id: 指定响应的Agent ID（@mention）

        Returns:
            Dict包含user_message和agent_message
        """
        async with self._session_factory() as db:
            # 1. 加载群聊及成员
            group = await self._load_group(db, group_id)
            if not group:
                raise ValueError(f"Group not found: {group_id}")

            # 2. 获取或创建Chain
            chain = await self._get_or_create_chain(db, group)

            # 3. 保存用户消息
            user_msg = await self._save_message(
                db, chain_id=chain.id,
                sender_type="user", sender_name="用户",
                content=user_content,
            )

            # 4. 获取目标Agent（支持@mention指定）
            if target_agent_id:
                lead_agent, project_agent = self._get_agent_by_id(group, target_agent_id)
            else:
                lead_agent, project_agent = self._get_lead_agent(group)
                if not lead_agent:
                    lead_agent, project_agent = self._get_first_member_agent(group)

            if not lead_agent:
                agent_msg = await self._save_message(
                    db, chain_id=chain.id,
                    sender_type="system", sender_name="系统",
                    content="群聊中暂无Agent，请先添加Agent成员。",
                )
                return {
                    "user_message": self._serialize_packet_for_chat(user_msg),
                    "agent_message": self._serialize_packet_for_chat(agent_msg),
                }

            # 5. 获取任务
            task = None
            if chain.task_id:
                task = await self._get_task(db, chain.task_id)

            # 5b. 构建群聊头消息（群 id + 群目标 + agent id）
            from app.services.context_header import build_group_context_header
            context_header = await build_group_context_header(db, group_id, agent_id=lead_agent.id)

            # 保存 db 引用供后续使用
            await db.commit()

        # 6. 通过 agentflow 管线执行 Agent（独立 session）
        llm_content = user_content  # 确保变量始终被定义
        try:
            # 清理@mention后传给LLM
            agent_names = [m.project_agent.agent.name for m in (group.members or []) if m.project_agent and m.project_agent.agent]
            if target_agent_id:
                llm_content = self._strip_mention(user_content, agent_names)

            # 头消息前置
            if context_header:
                llm_content = context_header + "\n\n" + llm_content

            result = await self._agent_executor.execute(
                agent=lead_agent,
                project_agent=project_agent,
                group=group,
                task=task,
                chain=chain,
                user_message=llm_content,
            )
            # 优先用 StreamPushPlugin 累积的流式内容 (含 <think> 标签),
            # 保证刷新后 think 块仍可见。回退到 ResultCollector content。
            push_plugin = self._agent_executor.get_push_plugin(chain.id)
            stream_content = push_plugin.latest_content if push_plugin else ""
            result_content = result.get("content", "") or ""
            agent_response = stream_content or result_content
            if stream_content:
                logger.info(
                    "[chat_service] send_message_and_get_response using stream_content len=%d (result_content len=%d)",
                    len(stream_content), len(result_content),
                )
            # 优先用 StreamPushPlugin._tool_calls (通过 pre_process 正确跟踪 RESPONSE 的 result),
            # 而非 result.metadata.tool_calls (来自 _tool_calls_tracker, 其 RESPONSE 处理是死代码,
            # 因为 RESPONSE 包只走 pre_process, 永远不会进入 post_process 的 track_call).
            # 不修复会导致 _seed_history_from_db 重建历史时缺失 RESPONSE 包,
            # OpenAI API 收到 assistant.tool_calls 但无对应 tool 消息, LLM 行为异常.
            if push_plugin and push_plugin.tool_calls:
                tool_calls = push_plugin.tool_calls
            else:
                tool_calls = result.get("metadata", {}).get("tool_calls", []) or []
        except Exception as e:
            logger.exception(f"[chat_service] Agent execution failed for group {group_id}")
            agent_response = f"[Agent响应异常: {str(e)}]"
            tool_calls = []

        # 7. 保存Agent消息（工具调用信息存入metadata，清理工具调用文本标记）
        cleaned_response = strip_tool_call_markers(agent_response)
        # 如果 agent 用了内容型工具（write_file / write_resource）但自己没在文本里展开，
        # 把工具产物的预览拼到回复尾部，让群聊用户看到实际产出。
        if tool_calls and len(cleaned_response) < 200:
            tool_summaries = _summarize_content_tools(tool_calls)
            if tool_summaries:
                cleaned_response = cleaned_response + "\n\n" + tool_summaries
        async with self._session_factory() as db:
            metadata = {}
            if tool_calls:
                metadata["tool_calls"] = tool_calls
                # page_inject: 提到 metadata 顶层，方便刷新页面后渲染 InjectJsBlock
                for tc in tool_calls:
                    inject_js, inject_description = _extract_inject_from_tool_call(tc)
                    if inject_js:
                        metadata["inject_js"] = inject_js
                        if inject_description:
                            metadata["inject_description"] = inject_description
                        break
            agent_msg = await self._save_message(
                db, chain_id=chain.id,
                sender_type="agent", sender_id=lead_agent.id,
                sender_name=lead_agent.name,
                content=cleaned_response,
                metadata=metadata,
            )

            # 8. 检查是否需要链交接
            rollover_info = await self._check_and_rollover(db, chain, lead_agent)

        result = {
            "user_message": self._serialize_packet_for_chat(user_msg),
            "agent_message": self._serialize_packet_for_chat(agent_msg),
        }
        if rollover_info:
            result["rollover"] = rollover_info
        return result

    async def _prepare_send_message_stream(
        self,
        group_id: str,
        user_content: str,
        target_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        流式发送前的准备阶段。

        加载 group / chain / agent, 保存 user 消息, 占位插入 agent_text packet
        (流将持续 partial save 到这个 packet)。返回一个 dict, 包含后续
        LLM 调用所需的全部上下文。

        Returns:
            {"error": "..."} 出错时
            否则: {
                "group", "chain", "agent", "project_agent", "task",
                "user_msg", "agent_packet_id", "llm_content",
            }
        """
        async with self._session_factory() as db:
            group = await self._load_group(db, group_id)
            if not group:
                return {"error": f"Group not found: {group_id}"}

            active_task_id = None
            for t in (group.tasks or []):
                if t.status == "in_progress":
                    active_task_id = t.id
                    break
            chain = await self._get_or_create_chain(db, group, task_id=active_task_id)

            # 1) 用户消息
            user_msg = await self._save_message(
                db, chain_id=chain.id,
                sender_type="user", sender_name="用户",
                content=user_content,
            )

            # 2) 目标 agent
            if target_agent_id:
                agent, project_agent = self._get_agent_by_id(group, target_agent_id)
                if not agent:
                    # B1: 传了 target_agent_id 但找不到，明确报错而非静默回退"暂无Agent"
                    return {
                        "error": (
                            f"指定的目标 Agent (id={target_agent_id[:8]}...) 不在该群成员中。"
                            "请确认 target_agent_id 是群成员的 global agent id（不是 project_agent_id）。"
                        ),
                    }
            else:
                agent, project_agent = self._get_lead_agent(group)
                if not agent:
                    agent, project_agent = self._get_first_member_agent(group)

            if not agent:
                # 没 agent 时, 也占位一个 system 包, 让前端能渲染"暂无 Agent"
                sys_msg = await self._save_message(
                    db, chain_id=chain.id,
                    sender_type="system", sender_name="系统",
                    content="群聊中暂无Agent，请先添加Agent成员。",
                )
                return {
                    "error": False,
                    "no_agent": True,
                    "group": group, "chain": chain, "user_msg": user_msg,
                    "agent_msg": sys_msg,
                }

            # 3) task + 头消息
            task = None
            if chain.task_id:
                task = await self._get_task(db, chain.task_id)
            from app.services.context_header import build_group_context_header
            context_header = await build_group_context_header(
                db, group_id, agent_id=agent.id
            )

            # 4) 占位 agent_text packet (流将 partial save 进去)
            placeholder = await self._save_packet(
                db, chain_id=chain.id,
                sender_type="agent", sender_id=agent.id,
                sender_name=agent.name,
                content="",
                packet_type="agent_text",
                metadata={"streaming": True},
            )
            await db.commit()
            await db.refresh(placeholder)
            agent_packet_id = placeholder.id

            # 5) 准备 LLM 入参
            agent_names = [
                m.project_agent.agent.name
                for m in (group.members or [])
                if m.project_agent and m.project_agent.agent
            ]
            llm_content = user_content
            if target_agent_id:
                llm_content = self._strip_mention(user_content, agent_names)
            if context_header:
                llm_content = context_header + "\n\n" + llm_content

            return {
                "error": False,
                "no_agent": False,
                "group": group,
                "chain": chain,
                "agent": agent,
                "project_agent": project_agent,
                "task": task,
                "user_msg": user_msg,
                "agent_packet_id": agent_packet_id,
                "llm_content": llm_content,
            }

    async def _ws_broadcast(self, group_id: str, message: Dict[str, Any]) -> None:
        """通过 WebSocket 广播消息到群聊房间。"""
        try:
            from app.orchestrator.websocket_manager import ws_manager
            await ws_manager.broadcast(group_id, message)
        except Exception:
            logger.debug("[chat_service] ws broadcast failed", exc_info=True)

    async def _sync_stream_content_to_session(
        self,
        session: StreamSession,
        chain_id: str,
        stop_event: asyncio.Event,
    ) -> None:
        """
        定期把 StreamPushPlugin 的 latest_content 同步到 session.latest_content。

        StreamPushPlugin 在流式过程中累积完整 token 内容（含 think 标签），
        但 session.latest_content 原只在流结束时更新。刷新页面后前端 attach
        拿到的是空快照，导致已生成的内容丢失。本同步任务每 50ms 从 push_plugin
        拉取最新内容写入 session，保证 attach 始终返回当前最新生成内容。
        """
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=0.05)
                except asyncio.TimeoutError:
                    pass
                try:
                    push_plugin = self._agent_executor.get_push_plugin(chain_id)
                    if push_plugin is not None:
                        session.latest_content = push_plugin.latest_content
                except Exception:
                    logger.exception("[chat_service] _sync_stream_content_to_session failed")
        except asyncio.CancelledError:
            pass

    async def _run_stream_decoupled(
        self,
        session: StreamSession,
        prepare: Dict[str, Any],
    ) -> None:
        """
        实际跑 LLM 流, 与客户端解耦。

        关键设计 (v2: StreamPushPlugin 替代 StreamCollector):
            - LLM 调用在自己的 task 中跑, 客户端断开不影响它
            - StreamPushPlugin 实时将 token/tool_call/tool_result 推送到 WebSocket
            - 本方法仅 await 最终结果, 不再逐 chunk 迭代
            - 异常 / cancel / 正常结束 -> 一次性写入最终 packet + 推送 chain_end/done

        finalize 兜底设计 (v6 streaming bug 修复):
            原代码 mark_done 在方法末尾, 中间步骤(rollover/ws broadcast)抛异常时
            mark_done 不执行 -> stream_registry 状态泄漏, packet 永远 streaming=true.
            现在用 try/finally 把 finalize + mark_done 放进 finally, 保证任何路径
            (正常/cancel/exception/中间异常) 都清理状态.
        """
        chain = prepare["chain"]
        agent = prepare["agent"]
        project_agent = prepare["project_agent"]
        task = prepare["task"]
        llm_content = prepare["llm_content"]
        group_id = session.group_id

        full_content = ""
        tool_calls: List[Dict[str, Any]] = []
        # 记录是否在异常路径下已经广播过 error, 避免重复
        error_broadcast = False

        # 启动内容同步任务：把 StreamPushPlugin 累积内容实时写入 session.latest_content
        stop_sync_event = asyncio.Event()
        sync_task = asyncio.create_task(
            self._sync_stream_content_to_session(session, chain.id, stop_sync_event)
        )

        try:
            try:
                result = await self._agent_executor.execute_stream(
                    agent=agent,
                    project_agent=project_agent,
                    group=prepare["group"],
                    task=task,
                    chain=chain,
                    user_message=llm_content,
                )
                # 优先用 StreamPushPlugin 累积的全部流式 token 作为最终内容
                # 修复: stream_content 可能只包含 <tool_call_pos /> 标记 (agent 只调工具不产文本时),
                # strip 后变空, 此时应回退到 result_content (含错误信息或正常总结)
                push_plugin = self._agent_executor.get_push_plugin(chain.id)
                raw_stream_content = push_plugin.latest_content if push_plugin else ""
                stream_content = strip_tool_call_markers(raw_stream_content)
                result_content = result.get("content", "") or ""
                full_content = stream_content or result_content
                logger.info(
                    "[chat_service] finalize content: push_plugin=%s raw_stream_len=%d stream_len=%d result_len=%d use_stream=%s",
                    "yes" if push_plugin else "None",
                    len(raw_stream_content),
                    len(stream_content),
                    len(result_content),
                    bool(stream_content),
                )
                if stream_content and not result_content:
                    logger.info(
                        "[chat_service] ResultCollector content empty, using StreamPushPlugin.latest_content len=%d",
                        len(stream_content),
                    )
                result_meta = result.get("metadata") or {}
                # 优先用 StreamPushPlugin._tool_calls (含 result, 通过 pre_process 正确跟踪)
                # 详见 send_message_and_get_response 同名修复说明.
                if push_plugin and push_plugin.tool_calls:
                    tool_calls = push_plugin.tool_calls
                else:
                    tool_calls = result_meta.get("tool_calls") or []
                # 合并 render_spec 等元数据到 session (供 snapshot 用)
                for k, v in result_meta.items():
                    if k != "tool_calls":
                        session.latest_metadata[k] = v
            except asyncio.CancelledError:
                # 用户主动 cancel: 用 StreamPushPlugin 累计的部分内容做 finalize
                logger.info("[chat_service] stream cancelled by user, packet=%s", session.packet_id[:8])
                push_plugin = self._agent_executor.get_push_plugin(chain.id)
                full_content = push_plugin.latest_content if push_plugin else ""
                # cancel 不重新 raise: 让 finally 走 finalize + mark_done 清理状态
                # (前端已通过 cancel API 知道流被取消, 不需要再广播 error)
            except Exception as e:
                logger.exception(
                    "[chat_service] stream task failed for group %s", session.group_id
                )
                session.error = f"{type(e).__name__}: {e}"
                full_content = "[Agent执行异常]"
                await self._ws_broadcast(group_id, {
                    "type": "error",
                    "payload": {"message": "Agent 执行异常，请重试"},
                })
                error_broadcast = True

            # 流结束: 一次性写最终 packet
            cleaned_content = strip_tool_call_markers(full_content)
            final_metadata: Dict[str, Any] = {}
            if tool_calls:
                final_metadata["tool_calls"] = tool_calls
                for tc in tool_calls:
                    inject_js, inject_description = _extract_inject_from_tool_call(tc)
                    if inject_js:
                        final_metadata["inject_js"] = inject_js
                        if inject_description:
                            final_metadata["inject_description"] = inject_description
                        break
            for k, v in session.latest_metadata.items():
                if k not in final_metadata:
                    final_metadata[k] = v

            # finalize packet (DB 写入) - 异常被吞, 但 mark_done 仍在 finally 执行
            try:
                await self._finalize_stream_packet(
                    session.packet_id, cleaned_content, final_metadata
                )
            except Exception:
                logger.exception("[chat_service] finalize packet failed")

            # rollover 检查 (失败不阻塞后续)
            try:
                async with self._session_factory() as db:
                    rollover_info = await self._check_and_rollover(db, chain, agent)
            except Exception:
                logger.exception("[chat_service] rollover check failed")
                rollover_info = None

            session.latest_content = cleaned_content
            session.latest_metadata = final_metadata
            chain_status = "completed" if rollover_info else "active"

            # 推送 chain_end + done 到 WebSocket
            # 修复: 无论是否 error_broadcast, 都必须发 done 事件!
            # 之前只在非异常路径发 done, 导致 fatal error 时前端 isStreaming 永远 true
            # (前端 done handler 里才调 clearStreamingState 重置 isStreaming)
            await self._ws_broadcast(group_id, {
                "type": "chain_end",
                "payload": {"chain_id": chain.id, "status": chain_status},
            })
            done_data = {
                "chain_id": chain.id,
                "packet_id": session.packet_id,
                "content": cleaned_content,
                "metadata": final_metadata,
            }
            if rollover_info:
                done_data["rollover"] = rollover_info
            if error_broadcast:
                # 标记 error 已广播, 让前端知道这是 error 后的 done (清理状态用)
                done_data["error"] = True
            await self._ws_broadcast(group_id, {"type": "done", "payload": done_data})
        finally:
            # 停止内容同步任务
            stop_sync_event.set()
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass
            # 最后再同步一次：push_plugin 累积的完整内容含 think 标签，
            # 作为 attach 快照返回给前端最完整。
            try:
                push_plugin = self._agent_executor.get_push_plugin(chain.id)
                if push_plugin is not None:
                    session.latest_content = push_plugin.latest_content
            except Exception:
                pass

            # 无论正常/异常/cancel/中间步骤抛异常, 都清理 stream_registry 状态
            # 防止 packet 永远卡在 streaming=true
            stream_registry.mark_done(session.packet_id)
            # v9 修复: DB 兜底 — 即使 _finalize_stream_packet 失败 (SQLite 锁冲突等),
            # 也要确保 DB 中 streaming 标记被 pop, 否则前端刷新后永远显示"流式进行中".
            try:
                await self._ensure_streaming_popped(session.packet_id)
            except Exception:
                logger.exception("[chat_service] _ensure_streaming_popped failed (packet=%s)", session.packet_id[:8])

    async def _finalize_stream_packet(
        self,
        packet_id: str,
        cleaned_content: str,
        final_metadata: Dict[str, Any],
    ) -> None:
        """流式结束: 写入最终 content + 清掉 streaming 标记 (含重试, 处理 SQLite 锁冲突)."""
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                async with self._session_factory() as db:
                    pkt = await db.get(Packet, packet_id)
                    if pkt is None:
                        logger.warning("[chat_service] _finalize_stream_packet: packet %s not found", packet_id[:8])
                        return
                    pkt.content = cleaned_content
                    pkt.metadata_json = {**(pkt.metadata_json or {}), **final_metadata}
                    pkt.metadata_json.pop("streaming", None)
                    await db.commit()
                return
            except Exception as e:
                last_err = e
                logger.warning(
                    "[chat_service] _finalize_stream_packet attempt=%d failed (packet=%s): %s",
                    attempt + 1, packet_id[:8], str(e)[:200],
                )
                await asyncio.sleep(0.1 * (attempt + 1))
        if last_err is not None:
            raise last_err

    async def _ensure_streaming_popped(self, packet_id: str) -> None:
        """v9 兜底: 即使 _finalize_stream_packet 失败, 也要 pop DB 中的 streaming 标记.

        场景: 法官调 create_task 触发 handover (改主群 chain status), 同时 _finalize_stream_packet
        试图 commit packet, SQLite 写锁冲突 → finalize 异常被吞 → DB 中 streaming=true 永不修复.
        本方法独立 session + 仅 pop streaming (不动 content), 作为最后兜底.
        """
        try:
            async with self._session_factory() as db:
                pkt = await db.get(Packet, packet_id)
                if pkt is None:
                    return
                meta = pkt.metadata_json or {}
                if "streaming" in meta:
                    meta.pop("streaming", None)
                    pkt.metadata_json = meta
                    await db.commit()
                    logger.debug("[chat_service] _ensure_streaming_popped popped streaming for packet=%s", packet_id[:8])
        except Exception as e:
            logger.exception("[chat_service] _ensure_streaming_popped failed for packet=%s: %s", packet_id[:8], e)
            raise

    async def send_message_stream(
        self,
        group_id: str,
        user_content: str,
        target_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        发送用户消息并启动 Agent 响应 (v2: WebSocket 推送, 不再使用 SSE)。

        流程:
            1. 准备阶段 (load + save user_msg + 占位 packet)
            2. 通过 WebSocket 推送 user_message + chain_start 事件
            3. 创建 StreamSession, 启动后台 task 跑 LLM
            4. 立即返回 {chain_id, packet_id, ...} 给前端
            5. 后台 task 完成后通过 WebSocket 推送 chain_end + done

        前端通过 WebSocket 实时接收:
            - token (StreamPushPlugin 直接推送)
            - tool_call / tool_result (StreamPushPlugin 直接推送)
            - chain_end / done (本方法后台 task 完成后推送)
        """
        prepare = await self._prepare_send_message_stream(
            group_id, user_content, target_agent_id
        )

        if prepare.get("error") and prepare.get("no_agent"):
            # 群中没有 agent: 推送 user_message + done 到 WebSocket
            user_msg_data = self._serialize_packet_for_chat(prepare["user_msg"])
            agent_msg_data = self._serialize_packet_for_chat(prepare["agent_msg"])
            await self._ws_broadcast(group_id, {"type": "user_message", "payload": user_msg_data})
            await self._ws_broadcast(group_id, {"type": "done", "payload": agent_msg_data})
            return {
                "no_agent": True,
                "user_message": user_msg_data,
                "agent_message": agent_msg_data,
            }
        if prepare.get("error"):
            return {"error": prepare["error"]}

        chain = prepare["chain"]
        agent = prepare["agent"]
        user_msg = prepare["user_msg"]
        agent_packet_id = prepare["agent_packet_id"]

        # 1) 推送 user_message 到 WebSocket
        user_msg_data = self._serialize_packet_for_chat(user_msg)
        await self._ws_broadcast(group_id, {"type": "user_message", "payload": user_msg_data})

        # 2) 推送 chain_start 到 WebSocket
        chain_start_data = {
            "chain_id": chain.id,
            "chain_type": chain.chain_type,
            "parent_chain_id": chain.parent_chain_id,
            "agent_id": agent.id,
            "agent_name": agent.name,
        }
        await self._ws_broadcast(group_id, {"type": "chain_start", "payload": chain_start_data})

        # 3) 创建 session
        session = stream_registry.create(
            chain_id=chain.id,
            packet_id=agent_packet_id,
            group_id=group_id,
        )

        # 4) 启动后台 task 跑 LLM (存入 session.task, 供 cancel 中断)
        task = asyncio.create_task(self._run_stream_decoupled(session, prepare))
        session.task = task

        # 5) 立即返回 (前端通过 WebSocket 接收后续事件)
        return {
            "chain_id": chain.id,
            "packet_id": agent_packet_id,
            "chain_type": chain.chain_type,
            "parent_chain_id": chain.parent_chain_id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "user_message": user_msg_data,
        }

    async def resume_stream(
        self,
        group_id: str,
        packet_id: Optional[str] = None,
        chain_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        查询正在进行的流的状态 (v2: 返回 snapshot dict, 不再使用 SSE 订阅)。

        前端通过 WebSocket 接收后续事件, 本方法仅返回当前快照:
            - 有活跃流: 返回 {active, chain_id, packet_id, content, metadata, chain_start}
            - 无活跃流: 返回 {active: false}
        """
        session: Optional[StreamSession] = None
        if packet_id:
            session = stream_registry.get(packet_id)
        if session is None and chain_id:
            session = stream_registry.get_active_for_chain(chain_id)
        if session is None:
            session = stream_registry.get_any_active_for_group(group_id)

        if session is None:
            return {
                "active": False,
                "group_id": group_id,
                "chain_id": chain_id,
                "packet_id": packet_id,
            }

        # 查 chain / agent 信息, 用于构造 chain_start (前端需要重建 activeReplyChain)
        chain_start_data: Optional[Dict[str, Any]] = None
        try:
            async with self._session_factory() as db:
                chain = await db.get(Chain, session.chain_id)
                if chain is not None:
                    chain_start_data = {
                        "chain_id": chain.id,
                        "chain_type": chain.chain_type,
                        "parent_chain_id": chain.parent_chain_id,
                        "agent_id": chain.agent_id,
                        "agent_name": None,
                    }
                    if chain.agent_id:
                        agent = await db.get(Agent, chain.agent_id)
                        if agent is not None:
                            chain_start_data["agent_name"] = agent.name
        except Exception:
            logger.exception("[chat_service] resume_stream: load chain failed")

        return {
            "active": True,
            "chain_id": session.chain_id,
            "packet_id": session.packet_id,
            "content": session.latest_content,
            "metadata": session.latest_metadata,
            "is_streaming": session.is_streaming,
            "is_cancelled": session.is_cancelled,
            "chain_start": chain_start_data,
        }

    async def cancel_stream(
        self,
        packet_id: Optional[str] = None,
        chain_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> bool:
        """
        主动停止一个正在进行的流 (用户按 Stop)。

        Returns:
            是否真的停止了一个 session
        """
        session: Optional[StreamSession] = None
        if packet_id:
            session = stream_registry.get(packet_id)
        if session is None and chain_id:
            session = stream_registry.get_active_for_chain(chain_id)
        if session is None and group_id:
            session = stream_registry.get_any_active_for_group(group_id)
        if session is None:
            return False
        return stream_registry.cancel(session.packet_id)

    async def resolve_mentioned_agent(
        self,
        group_id: str,
        content: str,
    ) -> Optional[str]:
        """
        从消息内容中解析@mention的Agent名称，返回匹配的Agent ID

        支持格式: @AgentName 或 @Agent Name（空格后为非空字符）
        """
        match = re.search(r"@(\S+(?:\s(?=\S)[^\s@]+)*)", content)
        if not match:
            return None

        mentioned_name = match.group(1).strip()

        async with self._session_factory() as db:
            group = await self._load_group(db, group_id)
            if not group:
                return None

            for member in (group.members or []):
                if member.project_agent and member.project_agent.agent:
                    if member.project_agent.agent.name == mentioned_name:
                        return member.project_agent.agent.id

        return None

    def _strip_mention(self, content: str, agent_names: list[str] | None = None) -> str:
        """移除消息开头的@mention，保留实际内容"""
        if agent_names:
            for name in sorted(agent_names, key=len, reverse=True):
                pattern = r"^@" + re.escape(name) + r"(?:\s+|$)"
                m = re.match(pattern, content)
                if m:
                    return content[m.end():]
        return content

    async def _load_group(self, db: AsyncSession, group_id: str) -> Optional[Group]:
        """加载群聊及关联数据"""
        query = (
            select(Group)
            .where(and_(Group.id == group_id, Group.deleted_at.is_(None)))
            .options(
                selectinload(Group.lead_agent).selectinload(ProjectAgent.agent),
                selectinload(Group.members).selectinload(GroupMember.project_agent).selectinload(ProjectAgent.agent),
                selectinload(Group.tasks),
            )
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def _get_or_create_chain(self, db: AsyncSession, group: Group, task_id: Optional[str] = None) -> Chain:
        """
        获取或创建群聊的活跃链（v2 P2: 支持任务接管主链）。

        逻辑:
          - 如果指定 task_id: 找该任务的 active task chain; 没有则 create_task_chain
          - 否则: 找 group 下任意 status="active" 的 chain（group 或 task 都行）
            - 找到: 直接用（如果 task chain 接管了, 消息进 task chain）
            - 没找到: 找/建 group chain (main chain)
              - group chain 是 paused: resume → active
              - group chain 不存在: 创建新的 active group chain
        """
        # 如果指定了 task_id, 复用该任务已有的 task chain (不限 status, archived 除外)
        # v2 P2+ 修复: 此前只查 status=="active", 当 task chain 处于 pending
        #   (如 handover 未触发或刚创建未接管) 时查不到, 会再建一条 pending task chain,
        #   产生孤儿链、消息散落。改为复用最新一条非 archived 的 task chain。
        if task_id:
            query = (
                select(Chain)
                .where(and_(
                    Chain.group_id == group.id,
                    Chain.task_id == task_id,
                    Chain.chain_type == "task",
                    Chain.status != "archived",
                    Chain.deleted_at.is_(None),
                ))
                .order_by(Chain.created_at.desc())
                .limit(1)
            )
            result = await db.execute(query)
            chain = result.scalar_one_or_none()
            if chain:
                return chain
            # 任务链不存在, 创建一个 (status="pending")
            return await self.create_task_chain(db, group, task_id, request_content="任务开始")

        # v2 P2: 找 group 下任意 active chain (可能 task chain 已接管)
        from app.services.chain_handover_service import ChainHandoverService
        handover = ChainHandoverService(db)
        active = await handover.get_active_chain_for_group(group.id)
        if active:
            return active

        # 没有 active chain, 找 group chain
        main_chain = await handover.get_or_create_main_chain(group.id)
        # 如果是 paused, 恢复 active
        if main_chain.status == "paused":
            main_chain.status = "active"
            main_chain.completed_at = None
            logger.info(
                "_get_or_create_chain: group=%s main chain %s resumed paused → active",
                group.id[:8], main_chain.id[:8],
            )
            await db.flush()
        return main_chain

    async def _get_task(self, db: AsyncSession, task_id: str) -> Optional[Task]:
        """获取任务"""
        query = select(Task).where(Task.id == task_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    def _get_lead_agent(group: Group):
        """获取群聊的主导Agent"""
        if not group.lead_agent_id:
            return None, None
        pa = group.lead_agent
        if pa and pa.agent:
            return pa.agent, pa
        return None, None

    @staticmethod
    def _get_first_member_agent(group: Group):
        """获取第一个成员的Agent"""
        for member in (group.members or []):
            if member.project_agent and member.project_agent.agent:
                return member.project_agent.agent, member.project_agent
        return None, None

    @staticmethod
    def _get_agent_by_id(group: Group, agent_id: str):
        """按Agent ID从群聊成员中查找"""
        for member in (group.members or []):
            if member.project_agent and member.project_agent.agent:
                if member.project_agent.agent.id == agent_id:
                    return member.project_agent.agent, member.project_agent
        return None, None

    async def create_task_chain(
        self,
        db: AsyncSession,
        group: Group,
        task_id: str,
        request_content: str = "",
    ) -> Chain:
        """
        为任务创建子链（v2 P2: 任务接管主链机制）。

        行为:
          - 创建 task chain, status="pending"（待接管, 不接管主链）
          - 在主链插入 system packet 标记"任务创建"
          - 任务 in_progress 时（调 update_task_status）由 ChainHandoverService
            把 status 从 pending 改成 active + 把主链 paused

        Args:
            task_id: 任务ID
            request_content: 请求内容（显示在主链中的请求节点）

        Returns:
            新创建的 task chain (status="pending")
        """
        # 获取主链
        main_chain = await self._get_or_create_chain(db, group)

        # v2 P2: 创建 task chain 时 status="pending"（待接管, 不立即 active）
        # 这样能保证 "整个 group 同一时刻只有 0/1 个 active chain" 的不变量
        task_chain = Chain(
            chain_type="task",
            parent_chain_id=main_chain.id,
            task_id=task_id,
            group_id=group.id,
            status="pending",  # ← v2 P2: 不再立即 active, 等 in_progress 才接管
        )
        db.add(task_chain)
        await db.flush()

        # 在主链中插入请求节点（sub_chain_id 指向任务链）
        request_content = request_content or f"任务创建"
        await self._save_packet(
            db, chain_id=main_chain.id,
            content=request_content,
            sender_type="system",
            sender_id="system",
            sender_name="系统",
            packet_type="system",
            sub_chain_id=task_chain.id,
        )

        # 更新主链的子链计数
        main_chain.sub_chain_count = (main_chain.sub_chain_count or 0) + 1

        await db.flush()
        return task_chain

    async def complete_task_chain(
        self,
        db: AsyncSession,
        task_chain: Chain,
        result_content: str = "",
    ) -> None:
        """
        完成任务链，并在群聊级链中插入结果节点。

        Args:
            task_chain: 任务链
            result_content: 结果内容（显示在群聊级链中的结果节点）
        """
        # 标记任务链为完成
        task_chain.status = "completed"
        task_chain.completed_at = datetime.now(timezone.utc)

        # 在群聊级链中插入结果节点
        if task_chain.parent_chain_id:
            result_content = result_content or "任务完成"
            await self._save_packet(
                db, chain_id=task_chain.parent_chain_id,
                content=result_content,
                sender_type="system",
                sender_id="system",
                sender_name="系统",
                packet_type="system",
                sub_chain_id=task_chain.id,
            )

        await db.flush()

    async def get_history_messages(
        self,
        group_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """
        获取群聊历史消息（从 Packet 表读取）

        v2 P2 修复：
        - 群下会有 1 个根 chain（group 级 active）+ N 个 task 子链（active）
        - 历史消息只从"根 chain + 它的子链"读，不要直接抓所有 active chain
          否则 scalar_one_or_none() 会 MultipleResultsFound

        v2 P2 链交接修复：
        - 当发生链交接时，旧根链变为 completed，新根链为 active
        - 需要沿 rollover_from_chain_id 回溯，包含所有历史链的包

        Args:
            group_id: 群聊ID
            limit: 返回消息数量上限

        Returns:
            消息列表（按时间正序）
        """
        async with self._session_factory() as db:
            # 1. 查找根 chain（优先 active，兜底取最新创建）
            # v2 P2 修复：优先查找 active 状态的链，如果没有 active 链，则取最新创建的链
            root_query = (
                select(Chain)
                .where(and_(
                    Chain.group_id == group_id,
                    Chain.parent_chain_id.is_(None),
                    Chain.chain_type == "group",
                    Chain.deleted_at.is_(None),
                ))
                .order_by(
                    # 优先选择 active 状态的链
                    Chain.status == "active",
                    Chain.created_at.desc()
                )
                .limit(1)
            )
            result = await db.execute(root_query)
            chain = result.scalar_one_or_none()

            if not chain:
                return []

            # 2. 收集所有相关链 ID：根链 + 交接前链（沿 rollover_from_chain_id 回溯）
            chain_service = ChainQueryService(db)
            chain_ids = await chain_service.collect_chain_ids_with_rollover(chain.id)

            # 2b. 子链（任务链、回复链、工具链）
            # v2 P2+ 隐私修复:
            #   主群 API 只应返回**主链** packet. task chain 是为单个 agent (assignee)
            #   派生的私有上下文链, 其内容 (e.g. 玩家的身份思考、任务描述里的真实身份)
            #   不能被主群前端看到, 否则会泄露隐私.
            #   task chain 的内容只对 lead/法官通过专用 task API (e.g. /tasks/{id}/chain)
            #   可见, 那是诊断/审计场景, 不是群聊历史.
            sub_chain_result = await db.execute(
                select(Chain.id).where(and_(
                    Chain.parent_chain_id.in_(chain_ids),
                    Chain.deleted_at.is_(None),
                ))
            )
            # 注意: 这里收集 sub_chain_ids 是为了在 rollup/统计等场景可能用到,
            # 但**不**用于主群消息查询. 主群消息查询只看主链.
            _sub_chain_ids = [row[0] for row in sub_chain_result.all()]

            pkt_query = (
                select(Packet)
                .where(and_(
                    Packet.chain_id.in_(chain_ids),
                    Packet.deleted_at.is_(None),
                ))
                .order_by(Packet.created_at.desc())
                .limit(limit)
            )
            result = await db.execute(pkt_query)
            packets = list(result.scalars().all())
            packets.reverse()

        return [self._serialize_packet(pkt) for pkt in packets]

    @staticmethod
    def _serialize_packet(pkt: Packet) -> dict:
        """序列化 Packet（兼容前端 Message 格式）"""
        created_at = pkt.created_at
        if created_at:
            iso = created_at.isoformat()
            if iso.endswith("+00:00"):
                iso = iso[:-6] + "Z"
            else:
                iso = iso + "Z"
        else:
            iso = None

        metadata = pkt.metadata_json or {}
        # 兜底：老数据里 inject_js 在 tool_calls[*].result 字符串中，
        # 这里提到顶层，让前端的 InjectJsBlock 能渲染。
        if isinstance(metadata, dict) and not metadata.get("inject_js"):
            tcs = metadata.get("tool_calls")
            if isinstance(tcs, list):
                for tc in tcs:
                    if not isinstance(tc, dict):
                        continue
                    js, desc = _extract_inject_from_tool_call(tc)
                    if js:
                        metadata["inject_js"] = js
                        if desc:
                            metadata["inject_description"] = desc
                        break

        return {
            "id": pkt.id,
            "chain_id": pkt.chain_id,
            "sender_id": pkt.sender_id,
            "sender_type": pkt.sender_type,
            "sender_name": pkt.sender_name,
            "content": pkt.content,
            "content_type": pkt.content_type,
            "metadata": metadata,
            "created_at": iso,
            # 额外提供 chain 结构信息
            "packet_type": pkt.packet_type,
            "sub_chain_id": pkt.sub_chain_id,
        }

    async def _check_and_rollover(
        self,
        db: AsyncSession,
        chain: Chain,
        agent: Agent,
    ) -> Optional[Dict[str, Any]]:
        """检查是否需要链交接"""
        from app.services.chain_rollover_service import ChainRolloverService

        rollover_svc = ChainRolloverService(db)
        llm_config = agent.llm_config or {}

        if not await rollover_svc.should_rollover(chain.id, llm_config):
            return None

        result = await rollover_svc.execute_rollover(
            chain=chain,
            agent_name=agent.name,
            agent_llm_config=llm_config,
        )

        return {
            "old_chain_id": result["old_chain_id"],
            "new_chain_id": result["new_chain_id"],
            "summary": result["summary"],
        }

    @staticmethod
    async def _save_message(
        db: AsyncSession,
        chain_id: str,
        content: str,
        sender_type: str,
        sender_id: Optional[str] = None,
        sender_name: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Packet:
        """保存消息到数据库（写入 Packet）"""
        packet = await ChatService._save_packet(
            db, chain_id=chain_id,
            content=content,
            sender_type=sender_type,
            sender_id=sender_id or sender_type,
            sender_name=sender_name,
            metadata=metadata,
        )
        await db.commit()
        await db.refresh(packet)
        return packet

    @staticmethod
    async def _save_packet(
        db: AsyncSession,
        chain_id: str,
        content: str,
        sender_type: str,
        sender_id: str,
        sender_name: str,
        metadata: Optional[Dict[str, Any]] = None,
        packet_type: Optional[str] = None,
        sub_chain_id: Optional[str] = None,
    ) -> Packet:
        """
        保存 Packet 到数据库，同步更新 Chain 的 head/tail/count。

        packet_type 不指定时根据 sender_type 自动推断：
          user → user_input, agent → agent_text, system → system, tool → tool_result
        """
        # 推断 packet_type
        if not packet_type:
            type_map = {
                "user": "user_input",
                "agent": "agent_text",
                "system": "system",
                "tool": "tool_result",
            }
            packet_type = type_map.get(sender_type, "agent_text")

        # 找当前 chain 的最后一个 packet（用于链表 prev_packet_id）
        last_pkt_result = await db.execute(
            select(Packet)
            .where(and_(Packet.chain_id == chain_id, Packet.deleted_at.is_(None)))
            .order_by(Packet.created_at.desc())
            .limit(1)
        )
        last_pkt = last_pkt_result.scalar_one_or_none()
        prev_packet_id = last_pkt.id if last_pkt else None

        # 创建 Packet
        packet = Packet(
            chain_id=chain_id,
            prev_packet_id=prev_packet_id,
            packet_type=packet_type,
            sender_type=sender_type,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content or "",
            content_type="text",
            sub_chain_id=sub_chain_id,
            metadata_json=metadata or {},
        )
        db.add(packet)
        await db.flush()  # 拿到 packet.id

        # 更新 Chain 的 head/tail/count
        chain_result = await db.execute(
            select(Chain).where(Chain.id == chain_id)
        )
        chain = chain_result.scalar_one_or_none()
        if chain:
            if not chain.head_packet_id:
                chain.head_packet_id = packet.id
            chain.tail_packet_id = packet.id
            chain.packet_count = (chain.packet_count or 0) + 1

        return packet

    @staticmethod
    def _serialize_packet_for_chat(pkt: Packet) -> dict:
        """序列化 Packet（兼容前端 Message 格式）"""
        created_at = pkt.created_at
        if created_at:
            iso = created_at.isoformat()
            if iso.endswith("+00:00"):
                iso = iso[:-6] + "Z"
            else:
                iso = iso + "Z"
        else:
            iso = None

        metadata = pkt.metadata_json or {}
        # 兜底：老数据里 inject_js 在 tool_calls[*].result 字符串中，
        # 这里提到顶层，让前端的 InjectJsBlock 能渲染。
        if isinstance(metadata, dict) and not metadata.get("inject_js"):
            tcs = metadata.get("tool_calls")
            if isinstance(tcs, list):
                for tc in tcs:
                    if not isinstance(tc, dict):
                        continue
                    js, desc = _extract_inject_from_tool_call(tc)
                    if js:
                        metadata["inject_js"] = js
                        if desc:
                            metadata["inject_description"] = desc
                        break

        return {
            "id": pkt.id,
            "chain_id": pkt.chain_id,
            "sender_id": pkt.sender_id,
            "sender_type": pkt.sender_type,
            "sender_name": pkt.sender_name,
            "content": pkt.content,
            "content_type": pkt.content_type,
            "metadata": metadata,
            "created_at": iso,
        }

    async def cleanup_old_packets(
        self,
        retention_days: int = 30,
        keep_latest_per_chain: int = 20,
    ) -> Dict[str, int]:
        """清理过期历史包（软删除）。"""
        from sqlalchemy import distinct

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        async with self._session_factory() as db:
            chain_ids_result = await db.execute(
                select(distinct(Packet.chain_id))
            )
            chain_ids = [row[0] for row in chain_ids_result.all()]

            total_deleted = 0
            for chain_id in chain_ids:
                old_packets_result = await db.execute(
                    select(Packet)
                    .where(and_(
                        Packet.chain_id == chain_id,
                        Packet.deleted_at.is_(None),
                        Packet.created_at < cutoff,
                    ))
                    .order_by(Packet.created_at.desc())
                    .offset(keep_latest_per_chain)
                )
                old_packets = list(old_packets_result.scalars().all())

                for pkt in old_packets:
                    pkt.soft_delete()
                    total_deleted += 1

            if total_deleted > 0:
                await db.commit()
        return {"chains_scanned": len(chain_ids), "packets_deleted": total_deleted}
