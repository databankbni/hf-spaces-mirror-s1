"""
v2 P2 EventDispatcher

订阅 event_bus 上的事件, 把事件转换为"通知某个 agent"。
负责:
  1. 查 event_bus 找出所有匹配的 agent 订阅者
  2. 对每个订阅者:
     a. 冷却检查 (避免重复打扰)
     b. 写一条 system packet 到对应 group chain
     c. 启动一次新 chat session (调 AgentExecutor.execute)

设计原则:
  - 不绑死具体流程（不硬编码"任务 done → 唤 lead"）
  - 默认通知 = 谁订阅就通知谁 (subscribe 时未指定 target_agent_id)
  - 同一 (subscriber, event_type) 60s 内只发一次
  - LLM 不健康时, 不发 (避免空跑 LLM 调用)
  - 启动新 session 失败时, 记录并跳过 (不阻塞 publish)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


def _to_utc_ts(value: Any) -> Optional[float]:
    """统一把 created_at 解析为 UTC unix 时间戳.

    背景: BaseModel.created_at 是 DateTime(timezone=True) + default=utc_now(),
    SQLite 存为 ISO 字符串无 tz 后缀。早期代码用 datetime.fromisoformat(...).timestamp()
    把字符串当成本地时间算, 服务端在 UTC+8 时区会把 14:00 UTC 误算为 14:00 本地,
    偏差正好 8 小时 (= 用户看到的"480 分钟"假象)。

    正确做法: 字符串无 tz 后缀时强制当 UTC 处理 (与模型声明一致),
    有 tz 后缀或 datetime 对象时显式转 UTC。
    """
    if value is None:
        return None
    try:
        if isinstance(value, str):
            cleaned = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).timestamp()
    except Exception:
        return None
    return None


def _format_iso_utc(value: Any) -> str:
    """把 created_at 统一格式化为 UTC ISO 字符串 (秒级), 给 watchdog 提示用.

    避免在提示文本里把 raw DB 字符串 (如 "2026-07-09 14:00:53.447698") 原样显示
    (既没时区标识也没统一格式), 改成带 "Z" 后缀的 UTC ISO 字符串。
    """
    if value is None:
        return "未知"
    try:
        if isinstance(value, str):
            cleaned = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
        elif isinstance(value, datetime):
            dt = value
        else:
            return str(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # 保留秒级, 不带微秒, 前端用浏览器本地时区显示
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    except Exception:
        return str(value)


class EventDispatcher:
    """
    把事件总线事件转换为对 agent 的通知 + 新 session。

    用法（在 main startup 里）:
        from app.services.event_bus import event_bus
        from app.orchestrator.event_dispatcher import EventDispatcher

        dispatcher = EventDispatcher(agent_executor=executor, session_factory=sf)
        dispatcher.register()  # 在 event_bus 上挂 callbacks
    """

    # 冷却：同一 (subscriber_agent_id, event_type) 5s 内只发一次
    # 短冷却是为了让 lead 在自己标完 task done 后, 立即被事件触发开下一个 task,
    # 不需要用户再 push 一次。60s 太长, 用户体验差。
    DEFAULT_COOLDOWN_SECONDS = 5.0

    # system packet 标识，agent 收到时知道这是事件通知（不是普通消息）
    # 注意: packets 表的 packet_type CHECK 约束只允许 ('user_input', 'agent_text', 'think',
    # 'tool_call', 'tool_result', 'error', 'system'), 这里复用合法的 'system' + sender_type
    # 也用 'system', metadata 里加 event_type 标记是事件通知, 与普通系统消息区分.
    SYSTEM_PACKET_TYPE = "system"

    def __init__(
        self,
        session_factory,
        agent_executor=None,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        session_gate=None,
        subscription_trigger=None,
    ):
        """
        Args:
            session_factory: SQLAlchemy async_session_factory
            agent_executor: 可选, 注入的 AgentExecutor。None 时内部懒创建。
            session_gate: 可选, 共享的 SessionLifecycleGate 实例. None 时内部创建一个.
                          推荐由 main.py 创建并注入, 让 chat API 启动的 session 也参与串行化.
            subscription_trigger: 可选, DB 持久化订阅触发器 (订阅机制 v1).
                                  与 event_bus 内存订阅并存, 互不影响.
        """
        self._session_factory = session_factory
        self._cooldown_seconds = cooldown_seconds
        # (subscriber_agent_id, event_type) -> last_notified_monotonic_time
        self._cooldowns: Dict[Tuple[str, str], float] = {}
        # 失败计数 (subscriber_agent_id, event_type) -> count
        self._failure_counts: Dict[Tuple[str, str], int] = {}
        # 失败的回退时间: 失败后, (subscriber, event_type) 暂停 N 秒
        # 用于 _is_in_failure_backoff 中 backoff = self._failure_backoff * (2 ** ...)
        self._failure_backoff: float = 10.0  # 失败回退 10s (原来是 60s)
        # executor 懒创建
        self._agent_executor = agent_executor
        self._executor_lock = asyncio.Lock()

        # ── session lifecycle gate (v2 P2+) ──────────────────────
        # 同 (agent_id, group_id) 同时只允许一个 active session.
        # 共享给 AgentExecutor, 让 chat API 启动的 session 也走 gate.
        if session_gate is None:
            from app.orchestrator.session_lifecycle import SessionLifecycleGate
            session_gate = SessionLifecycleGate()
        self._session_gate = session_gate
        # 暴露 gate 给外部 (AgentExecutor)
        self.session_gate = session_gate

        # ── DB 持久化订阅触发器 (订阅机制 v1) ───────────────────
        # 与 event_bus 内存订阅并存：event_bus 内存订阅由本类 _on_* 处理器处理,
        # DB 订阅由 subscription_trigger.on_event 处理。
        # 两者独立, 各自 fire-and-forget, 互不影响。
        self._subscription_trigger = subscription_trigger

    def bind_executor(self, agent_executor) -> None:
        """在 startup 时绑定 executor。后续启动 session 会用它。"""
        self._agent_executor = agent_executor
        logger.info("[EventDispatcher] executor bound: %s", type(agent_executor).__name__)

    async def _get_executor(self):
        if self._agent_executor is None:
            async with self._executor_lock:
                if self._agent_executor is None:
                    from app.orchestrator.agent_executor import AgentExecutor
                    self._agent_executor = AgentExecutor(self._session_factory)
                    logger.info("[EventDispatcher] lazy-created AgentExecutor")
        return self._agent_executor

    def register(self) -> None:
        """
        在 event_bus 上挂 callback。重复 register 会重复挂, 注意幂等。
        """
        from app.services.event_bus import event_bus
        # 用 bound method, off 时需要传同一引用
        event_bus.on("task_status_changed", self._on_task_status_changed)
        event_bus.on("resource_created", self._on_resource_event)
        event_bus.on("resource_updated", self._on_resource_event)
        event_bus.on("group_status_changed", self._on_group_status_changed)
        logger.info("[EventDispatcher] registered on event_bus")

    def unregister(self) -> None:
        from app.services.event_bus import event_bus
        event_bus.off("task_status_changed", self._on_task_status_changed)
        event_bus.off("resource_created", self._on_resource_event)
        event_bus.off("resource_updated", self._on_resource_event)
        event_bus.off("group_status_changed", self._on_group_status_changed)
        logger.info("[EventDispatcher] unregistered from event_bus")

    # ── 核心事件处理 ─────────────────────────────────────────

    async def _on_task_status_changed(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        任务状态变更通知。

        关键决策（按用户要求：默认通知订阅者, 不硬编码具体流程）:
          - 给所有匹配的 agent 订阅者发通知
          - 每个订阅者由它自己的 skill 决定收到后做什么
            （lead 收到可能继续推进, assignee 收到可能自评, etc.）

        v2 P2+: 任务 in_progress 时, 系统级自动唤醒 assignee
          - 这是**系统责任**, 不依赖 subscribe_event
          - 设计理由: assignee 推动 task chain 进展是被设计好的"业务闭环",
            不应该让 agent 手动协调订阅来获得被通知的权利
          - 与 subscriber 通知的差别:
              subscriber 通知: 自愿订阅 (e.g., lead 想知道所有 task 进展)
              assignee 通知: 系统保证 (task 派给谁, 谁就会被唤醒)
          - 冷却去重: 同一 (agent_id, event_type) 5s 内只发一次,
            如果 assignee 也是 subscriber, 不会重复唤醒
        """
        task_id = payload.get("task_id")
        project_id = payload.get("project_id")
        group_id = payload.get("group_id")
        status = payload.get("status")

        if not (task_id and project_id and group_id and status):
            logger.debug("[EventDispatcher] skip task_status_changed, missing fields: %s", payload)
            return

        # 准备 trigger 消息（一次性查 task 详情, 给所有 dispatches 用）
        task_info = await self._load_task_summary(task_id)
        if task_info is None:
            return

        # 1) v2 P2+: 任务 in_progress → 系统级自动唤醒 assignee
        auto_dispatched: Set[str] = set()
        if status == "in_progress":
            auto_dispatched = await self._auto_dispatch_to_assignees(
                task_id=task_id,
                project_id=project_id,
                group_id=group_id,
                task_info=task_info,
            )
            if auto_dispatched:
                logger.info(
                    "[EventDispatcher] task=%s in_progress → auto-dispatched %d assignee(s): %s",
                    task_id[:8], len(auto_dispatched),
                    [a[:8] for a in auto_dispatched],
                )

        # 1.5) v2 P2+: 任务 done → 系统级自动唤醒 lead (架构改进: 业务闭环由系统保证)
        #   业务闭环 "任务完成 → lead 继续推进" 是设计内建的责任, 不依赖 subscribe_event.
        #   与 in_progress→assignee 的关系对称.
        #   - lead 不存在 (匿名任务) 时跳过
        #   - lead 与 assignee 重合时跳过 (避免重复唤醒, 已在 auto_dispatched 里)
        lead_dispatched: Set[str] = set()
        if status == "done":
            lead_dispatched = await self._auto_dispatch_to_lead(
                task_id=task_id,
                project_id=project_id,
                group_id=group_id,
                task_info=task_info,
                exclude_agent_ids=auto_dispatched,
            )
            if lead_dispatched:
                logger.info(
                    "[EventDispatcher] task=%s done → auto-dispatched lead %d: %s",
                    task_id[:8], len(lead_dispatched),
                    [a[:8] for a in lead_dispatched],
                )

        # 2) 给订阅者发通知（去掉已自动分派的 assignee, 避免重复唤醒）
        from app.services.event_bus import event_bus
        subscribers = event_bus.find_matching_subscribers("task_status_changed", project_id, group_id)
        for sub in subscribers:
            sub_id = sub["subscriber_agent_id"]
            if sub_id in auto_dispatched or sub_id in lead_dispatched:
                continue
            await self._dispatch_to_subscriber(
                subscriber_agent_id=sub_id,
                project_id=project_id,
                group_id=group_id,
                event_type=event_type,
                trigger_msg=self._compose_task_status_msg(task_info, status),
                task_id=task_id,
            )

        # 触发 DB 持久化订阅（订阅机制 v1）
        await self._trigger_db_subscriptions(event_type, payload)

    async def _on_resource_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """资源创建/更新通知"""
        resource_id = payload.get("resource_id")
        project_id = payload.get("project_id")
        group_id = payload.get("group_id")
        if not (resource_id and project_id):
            return

        from app.services.event_bus import event_bus
        subscribers = event_bus.find_matching_subscribers(event_type, project_id, group_id)
        if not subscribers:
            return

        trigger_msg = (
            f"[系统通知] 资源事件: {event_type}\n"
            f"资源 ID: {resource_id}\n"
            f"群 ID: {group_id or '(项目级)'}"
        )
        for sub in subscribers:
            await self._dispatch_to_subscriber(
                subscriber_agent_id=sub["subscriber_agent_id"],
                project_id=project_id,
                group_id=group_id,
                event_type=event_type,
                trigger_msg=trigger_msg,
            )

        # 触发 DB 持久化订阅（订阅机制 v1）
        await self._trigger_db_subscriptions(event_type, payload)

    async def _on_group_status_changed(self, event_type: str, payload: Dict[str, Any]) -> None:
        """群状态变更通知"""
        project_id = payload.get("project_id")
        group_id = payload.get("group_id")
        if not (project_id and group_id):
            return

        from app.services.event_bus import event_bus
        subscribers = event_bus.find_matching_subscribers(event_type, project_id, group_id)
        if not subscribers:
            return

        new_status = payload.get("new_status", "?")
        trigger_msg = (
            f"[系统通知] 群状态变更: {new_status}\n"
            f"群 ID: {group_id}"
        )
        for sub in subscribers:
            await self._dispatch_to_subscriber(
                subscriber_agent_id=sub["subscriber_agent_id"],
                project_id=project_id,
                group_id=group_id,
                event_type=event_type,
                trigger_msg=trigger_msg,
            )

        # 触发 DB 持久化订阅（订阅机制 v1）
        await self._trigger_db_subscriptions(event_type, payload)

    # ── 空闲 Watchdog (P0 修复) ─────────────────────────────────
    # 防止"lead 静默停摆"——比如 08:33:35 之后 3 小时无任何 packet
    # 但 group.status 还是 active 的情况。
    # 设计: 每 60s 扫一次所有 active group, 查 group chain 最后 packet 时间,
    #       超 IDLE_THRESHOLD_SECONDS 没动 → 向 lead 发"[系统通知] 已空闲 X 分钟"
    #       连续 N 次提醒仍不动 → mark group.idle (写 metadata), 不强行 completed.
    #
    # 设计原则:
    #   - 不强行 mark group.completed (可能还有 deliverable 没写)
    #   - 不打断 in_progress 任务 (任务串行机制已经管)
    #   - 只对 active 群生效, pending/completed 群不打扰
    #   - 同一个群在 WATCHDOG_COOLDOWN_SECONDS 内只提醒一次, 避免 spam

    IDLE_THRESHOLD_SECONDS = 600  # 10 分钟无活动视为空闲
    WATCHDOG_CHECK_INTERVAL = 60  # 每 60s 扫一次
    WATCHDOG_COOLDOWN_SECONDS = 1800  # 同一群 30 分钟内最多提醒 1 次

    def start_idle_watchdog(self) -> None:
        """启动空闲 watchdog 后台任务 (在 lifespan 启动时调用)"""
        if getattr(self, "_idle_watchdog_task", None) and not self._idle_watchdog_task.done():
            return
        self._idle_watchdog_task = asyncio.create_task(self._idle_watchdog_loop())
        logger.info("[EventDispatcher] idle watchdog started (threshold=%ds, interval=%ds)",
                    self.IDLE_THRESHOLD_SECONDS, self.WATCHDOG_CHECK_INTERVAL)

    def stop_idle_watchdog(self) -> None:
        """停止 watchdog (在 lifespan 关闭时调用)"""
        task = getattr(self, "_idle_watchdog_task", None)
        if task and not task.done():
            task.cancel()
            logger.info("[EventDispatcher] idle watchdog stopped")

    async def _idle_watchdog_loop(self) -> None:
        """watchdog 主循环 — 异常吞掉, 不能因为 watchdog 崩了影响主 dispatcher"""
        # 启动后等 1 个 check interval, 让 server 先稳定
        await asyncio.sleep(self.WATCHDOG_CHECK_INTERVAL)
        while True:
            try:
                await self._check_idle_groups_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("[Watchdog] check loop error (non-fatal): %s", e)
            await asyncio.sleep(self.WATCHDOG_CHECK_INTERVAL)

    async def _check_idle_groups_once(self) -> None:
        """扫描所有 active group, 对空闲 group 向 lead 发提醒"""
        from app.models.group import Group, GroupMember
        from app.models.agent import Agent, ProjectAgent
        from app.models.chain import Chain, Packet
        from sqlalchemy.orm import selectinload
        from sqlalchemy import func, desc

        now_ts = time.time()
        # 群级提醒冷却: group_id -> last_nudge_monotonic_time
        if not hasattr(self, "_watchdog_last_nudge"):
            self._watchdog_last_nudge: Dict[str, float] = {}

        async with self._session_factory() as db:
            # 1. 找所有 active group
            active_groups = (await db.execute(
                select(Group).where(Group.status == "active", Group.deleted_at.is_(None))
            )).scalars().all()
            if not active_groups:
                return

            for group in active_groups:
                # 0. 群级 watchdog 开关: 用户在 EditGroupModal 可关闭
                #    关闭后整个 watchdog loop 跳过此群, 防止"用户不关心的群被反复激活"
                if getattr(group, "watchdog_enabled", True) is False:
                    continue

                # 冷却: 同群 30 分钟内只提醒 1 次
                last_nudge = self._watchdog_last_nudge.get(group.id, 0)
                if now_ts - last_nudge < self.WATCHDOG_COOLDOWN_SECONDS:
                    continue

                # 2. 找 group chain 最后 packet 时间
                #    群主 chain (chain_type='group') 是"人能看到对话"的主链
                group_chain = (await db.execute(
                    select(Chain).where(
                        Chain.group_id == group.id,
                        Chain.chain_type == "group",
                    )
                )).scalar_one_or_none()
                if not group_chain:
                    continue

                last_pkt = (await db.execute(
                    select(Packet)
                    .where(Packet.chain_id == group_chain.id, Packet.deleted_at.is_(None))
                    .order_by(desc(Packet.created_at))
                    .limit(1)
                )).scalar_one_or_none()

                last_pkt_ts: Optional[float] = _to_utc_ts(last_pkt.created_at) if last_pkt else None

                if last_pkt_ts is None:
                    continue  # 没历史, 不算空闲

                idle_seconds = now_ts - last_pkt_ts
                if idle_seconds < self.IDLE_THRESHOLD_SECONDS:
                    continue  # 还在阈值内

                # 2.5 冷启动保护: 群主链必须有过至少一条 user 消息,
                #     否则 (e.g. 刚创建还没人说话 / 只有系统初始化包) 不提醒。
                #     避免一上线就弹"已空闲 N 分钟"给 lead, 让 lead 自作主张接管空群。
                has_user_packet = (await db.execute(
                    select(Packet.id).where(
                        Packet.chain_id == group_chain.id,
                        Packet.sender_type == "user",
                        Packet.deleted_at.is_(None),
                    ).limit(1)
                )).scalar_one_or_none()
                if not has_user_packet:
                    continue

                # 3. 找 lead agent
                if not group.lead_agent_id:
                    continue
                lead_pa = (await db.execute(
                    select(ProjectAgent).where(ProjectAgent.id == group.lead_agent_id)
                )).scalar_one_or_none()
                if not lead_pa:
                    continue
                lead_agent = (await db.execute(
                    select(Agent).where(Agent.id == lead_pa.agent_id)
                )).scalar_one_or_none()
                if not lead_agent:
                    continue

                # 4. 写一条 system packet 到 group chain (前端能看到)
                idle_min = int(idle_seconds // 60)
                # 重新格式化 last_pkt 时间给前端看 (本地时区 → ISO 字符串, 与 DB UTC 一致即可)
                last_pkt_iso = _format_iso_utc(last_pkt.created_at)
                trigger_msg = (
                    f"[系统提醒] 群「{group.name}」已空闲 {idle_min} 分钟 (上次活动: {last_pkt_iso}).\n"
                    f"你是本群 lead. 请决定下一步: 继续推进 / 写交付物 / 标记群完成.\n"
                    f"如果工具不可用, 按 system prompt 「工具失败兜底」降级处理, "
                    f"**不要停下来等**.\n"
                )

                from app.services.chat_service import ChatService
                await ChatService._save_packet(
                    db,
                    chain_id=group_chain.id,
                    content=trigger_msg,
                    sender_type="system",
                    sender_id="system",
                    sender_name="空闲提醒",
                    metadata={"event_type": "idle_watchdog", "idle_seconds": int(idle_seconds)},
                )
                await db.commit()
                self._watchdog_last_nudge[group.id] = now_ts

                logger.warning(
                    "[Watchdog] group %s (%s) idle for %dm, nudged lead %s",
                    group.id[:8], group.name, idle_min, lead_agent.name,
                )

                # 5. 主动启动 lead 的 session, 让 LLM 看到这条提醒
                try:
                    executor = await self._get_executor()
                    await executor.execute(
                        agent=lead_agent,
                        project_agent=lead_pa,
                        group=group,
                        task=None,
                        chain=group_chain,
                        user_message=trigger_msg,
                    )
                except Exception as e:
                    logger.exception("[Watchdog] failed to start lead session for %s: %s",
                                     group.id[:8], e)

    # ── 通用 dispatch ─────────────────────────────────────────

    async def _auto_dispatch_to_assignees(
        self,
        task_id: str,
        project_id: str,
        group_id: str,
        task_info: Dict[str, Any],
    ) -> Set[str]:
        """
        v2 P2+: 任务 in_progress 时, 系统级自动唤醒所有 assignee.

        返回已成功发起 dispatch 的 assignee agent_id 集合 (用于与订阅者通知去重).

        设计:
          - 复用 _dispatch_to_subscriber 的冷却/启动 session 逻辑
          - trigger_msg 比通用版多强调任务描述, 因为 assignee 是"接活干"
          - 任务无 assignee 时直接返回空集, 不做事
        """
        from app.models.task import Task
        from app.models.agent import ProjectAgent
        from sqlalchemy.orm import selectinload

        # 1. 一次性查 task 的 assignees → agent_ids
        #    ⚠️ 必须 selectinload(Task.assignees) —— 异步 ORM 不预加载会访问失败
        async with self._session_factory() as db:
            task = (await db.execute(
                select(Task)
                .options(selectinload(Task.assignees))
                .where(Task.id == task_id)
            )).scalar_one_or_none()
            if not task:
                logger.debug("[EventDispatcher] task %s not found in assignee dispatch", task_id[:8])
                return set()
            if not task.assignees:
                logger.debug(
                    "[EventDispatcher] task %s has no assignees, skip assignee dispatch",
                    task_id[:8],
                )
                return set()

            assignee_pa_ids = [a.project_agent_id for a in task.assignees if a.project_agent_id]
            if not assignee_pa_ids:
                return set()

            pa_rows = (await db.execute(
                select(ProjectAgent).where(ProjectAgent.id.in_(assignee_pa_ids))
            )).scalars().all()
            agent_ids = [pa.agent_id for pa in pa_rows if pa.agent_id]

        if not agent_ids:
            return set()

        # 2. 给每个 assignee 派 session
        trigger_msg = self._compose_task_assignment_msg(task_info)
        dispatched: Set[str] = set()
        for agent_id in agent_ids:
            try:
                await self._dispatch_to_subscriber(
                    subscriber_agent_id=agent_id,
                    project_id=project_id,
                    group_id=group_id,
                    event_type="task_status_changed",
                    trigger_msg=trigger_msg,
                    task_id=task_id,
                )
                dispatched.add(agent_id)
            except Exception as e:
                logger.exception(
                    "[EventDispatcher] auto-dispatch to assignee %s failed: %s",
                    agent_id[:8], e,
                )
        return dispatched

    async def _auto_dispatch_to_lead(
        self,
        task_id: str,
        project_id: str,
        group_id: str,
        task_info: Dict[str, Any],
        exclude_agent_ids: Optional[Set[str]] = None,
    ) -> Set[str]:
        """
        v2 P2+ 架构改进: 任务 done 时, 系统级自动唤醒 lead (继续推进者).

        与 _auto_dispatch_to_assignees 对称:
          - 复用 _dispatch_to_subscriber 的冷却/启动 session 逻辑
          - trigger_msg 强调"任务已完成", lead 据此决定下一步
          - lead 不存在时返回空集
          - lead agent_id 在 exclude_agent_ids 里 (即 lead 兼 assignee) 时跳过,
            避免重复唤醒同一个 agent
        """
        from app.models.task import Task
        from app.models.agent import ProjectAgent
        from sqlalchemy.orm import selectinload

        exclude_agent_ids = exclude_agent_ids or set()

        # 1. 查 task → lead_agent (ProjectAgent) → agent_id
        #    关键: 必须 selectinload(Task.lead_agent) —— 异步 ORM 不预加载访问会失败
        async with self._session_factory() as db:
            task = (await db.execute(
                select(Task)
                .options(selectinload(Task.lead_agent))
                .where(Task.id == task_id)
            )).scalar_one_or_none()
            if not task:
                logger.debug("[EventDispatcher] task %s not found in lead dispatch", task_id[:8])
                return set()
            if not task.lead_agent or not task.lead_agent.agent_id:
                logger.debug(
                    "[EventDispatcher] task %s has no lead_agent (匿名任务), skip lead dispatch",
                    task_id[:8],
                )
                return set()
            lead_agent_id = task.lead_agent.agent_id

        if lead_agent_id in exclude_agent_ids:
            logger.debug(
                "[EventDispatcher] task %s lead=%s is also assignee, skip (already dispatched)",
                task_id[:8], lead_agent_id[:8],
            )
            return set()

        # 2. 给 lead 派 session
        trigger_msg = self._compose_task_done_for_lead_msg(task_info)
        dispatched: Set[str] = set()
        try:
            await self._dispatch_to_subscriber(
                subscriber_agent_id=lead_agent_id,
                project_id=project_id,
                group_id=group_id,
                event_type="task_status_changed",
                trigger_msg=trigger_msg,
                task_id=task_id,
            )
            dispatched.add(lead_agent_id)
        except Exception as e:
            logger.exception(
                "[EventDispatcher] auto-dispatch to lead %s failed: %s",
                lead_agent_id[:8], e,
            )
        return dispatched

    async def _dispatch_to_subscriber(
        self,
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str],
        event_type: str,
        trigger_msg: str,
        task_id: Optional[str] = None,
    ) -> None:
        """
        给一个订阅者发通知:
          1. 冷却检查
          2. LLM 健康检查
          3. 写 system packet
          4. 启动新 session（fire-and-forget）
        """
        key = (subscriber_agent_id, event_type)

        # 1. 冷却
        if self._is_in_cooldown(key):
            logger.debug(
                "[EventDispatcher] %s for %s in cooldown, skip",
                event_type, subscriber_agent_id[:8],
            )
            return

        # 2. 失败回退
        if self._is_in_failure_backoff(key):
            logger.debug(
                "[EventDispatcher] %s for %s in failure backoff, skip",
                event_type, subscriber_agent_id[:8],
            )
            return

        # 3. LLM 健康检查
        if not await self._is_llm_healthy():
            logger.warning(
                "[EventDispatcher] LLM unhealthy, skip notifying %s for %s",
                subscriber_agent_id[:8], event_type,
            )
            return

        # 4. 写 system packet
        try:
            await self._write_system_packet(
                group_id=group_id, content=trigger_msg, event_type=event_type
            )
        except Exception as e:
            logger.exception("[EventDispatcher] write system packet failed: %s", e)
            return

        # 5. session lifecycle gate: 同 (agent, group) 同时只跑一个 session
        #    没有 active 时立刻启动, 否则入队等现有 session 完成后消费
        session_key = (subscriber_agent_id, group_id or "")
        try:
            await self._start_or_enqueue_session(
                session_key=session_key,
                subscriber_agent_id=subscriber_agent_id,
                project_id=project_id,
                group_id=group_id,
                trigger_msg=trigger_msg,
                key=key,
                task_id=task_id,
            )
        except RuntimeError:
            logger.warning(
                "[EventDispatcher] no event loop, cannot enqueue session for %s",
                subscriber_agent_id[:8],
            )
            return

        # 6. 标记冷却
        self._cooldowns[key] = time.monotonic()

    async def _start_or_enqueue_session(
        self,
        session_key: Tuple[str, str],
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str],
        trigger_msg: str,
        key: Tuple[str, str],
        task_id: Optional[str] = None,
    ) -> None:
        """
        v2 P2+: session lifecycle gate (refactored to use SessionLifecycleGate).

        - 同 (agent_id, group_id) 同时只允许一个 active session.
        - 没有 active 时: 启动新 session (fire-and-forget).
        - 有 active 时: 把 trigger 入队; active session 完成后, 自动消费下一个.

        为什么用 (agent_id, group_id) 而不是 (agent_id) 作为 key?
            同一 agent 可能加入多个群 (狼人杀 + 别的群), 不同群的事件应该
            各自独立处理, 不能互相阻塞.
        """
        # 先 await chat API 启动的同 key session 完成 (如果有)
        # 否则 dispatcher 启动的会和 chat 启动的并行
        await self._session_gate.wait_for_active(session_key)

        trigger_payload = {
            "subscriber_agent_id": subscriber_agent_id,
            "project_id": project_id,
            "group_id": group_id,
            "trigger_msg": trigger_msg,
            "key": key,
            "task_id": task_id,
        }

        def _on_finish() -> None:
            """active session 完成后: 消费下一个 pending trigger, 启动下一个 session"""
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning(
                    "[EventDispatcher] no running loop in on_finish, drop pending for %s",
                    session_key[0][:8],
                )
                return
            next_trigger = self._session_gate.consume_next_pending(session_key)
            if not next_trigger:
                return
            loop.create_task(
                self._start_or_enqueue_session(
                    session_key=session_key,
                    **next_trigger,
                )
            )

        async def _runner() -> None:
            try:
                await self._start_session_for_subscriber(
                    subscriber_agent_id=subscriber_agent_id,
                    project_id=project_id,
                    group_id=group_id,
                    trigger_msg=trigger_msg,
                    key=key,
                    task_id=task_id,
                )
            except Exception as e:
                logger.exception(
                    "[EventDispatcher] session_runner failed for %s: %s",
                    subscriber_agent_id[:8], e,
                )
                self._record_failure(key)

        started, task = await self._session_gate.start_or_enqueue(
            session_key=session_key,
            runner_factory=_runner,
            on_finish=_on_finish,
        )
        if started:
            logger.info(
                "[EventDispatcher] %s session started (group=%s, event=%s, task=%s)",
                subscriber_agent_id[:8], group_id[:8] if group_id else "?",
                key[1], task_id[:8] if task_id else "none",
            )
        else:
            # 已有 active, 入队
            await self._session_gate.enqueue_trigger(session_key, trigger_payload)

    async def _start_session_for_subscriber(
        self,
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str],
        trigger_msg: str,
        key: Tuple[str, str],
        task_id: Optional[str] = None,
    ) -> None:
        """实际启动新 chat session。失败时增加回退时间"""
        try:
            async with self._session_factory() as db:
                from app.models.agent import Agent, ProjectAgent
                from app.models.group import Group, GroupMember
                from app.models.chain import Chain
                from app.models.task import Task
                from sqlalchemy.orm import selectinload

                # 1. 加载 agent
                agent = (await db.execute(
                    select(Agent).where(Agent.id == subscriber_agent_id)
                )).scalar_one_or_none()
                if not agent:
                    logger.warning(
                        "[EventDispatcher] subscriber agent %s not found",
                        subscriber_agent_id[:8],
                    )
                    return

                # 2. 加载 project_agent
                pa = (await db.execute(
                    select(ProjectAgent).where(
                        ProjectAgent.agent_id == subscriber_agent_id,
                        ProjectAgent.project_id == project_id,
                    )
                )).scalar_one_or_none()
                if not pa:
                    logger.warning(
                        "[EventDispatcher] subscriber %s not in project %s",
                        subscriber_agent_id[:8], project_id[:8],
                    )
                    return

                # 3. 加载 group (如指定)，同时预加载 members，避免 detach 后访问失败
                group = None
                if group_id:
                    group = (await db.execute(
                        select(Group)
                        .options(
                            selectinload(Group.members)
                            .selectinload(GroupMember.project_agent)
                            .selectinload(ProjectAgent.agent)
                        )
                        .where(Group.id == group_id)
                    )).scalar_one_or_none()
                if group is None:
                    # fallback: agent 在项目里的第一个 active 群
                    grp_q = (
                        select(Group)
                        .options(
                            selectinload(Group.members)
                            .selectinload(GroupMember.project_agent)
                            .selectinload(ProjectAgent.agent)
                        )
                        .join(GroupMember, GroupMember.group_id == Group.id)
                        .where(
                            GroupMember.project_agent_id == pa.id,
                            Group.status == "active",
                            Group.deleted_at.is_(None),
                        )
                        .limit(1)
                    )
                    group = (await db.execute(grp_q)).scalar_one_or_none()

                if group is None:
                    logger.warning(
                        "[EventDispatcher] no group to dispatch for agent=%s project=%s",
                        subscriber_agent_id[:8], project_id[:8],
                    )
                    return

                # 4. 加载 chain: 有 task_id 时优先用 task chain（隔离上下文）
                #    否则用 group 下任意 active chain（v2 P2 任务接管主链机制）
                chain = None
                if task_id:
                    chain = (await db.execute(
                        select(Chain).where(
                            Chain.task_id == task_id,
                            Chain.chain_type == "task",
                            Chain.status == "active",
                        )
                    )).scalar_one_or_none()
                    if chain:
                        logger.info(
                            "[EventDispatcher] using task chain %s for agent=%s",
                            chain.id[:8], subscriber_agent_id[:8],
                        )

                if chain is None:
                    # 卡点 6 修复: task chain 已 archived (task done) 时,
                    # fallback 不能选群内其他 active task chain (会污染别人的上下文),
                    # 必须回到主群 group chain.
                    # 之前: handover.get_active_chain_for_group 会返回任意 active chain,
                    # 包括其他 task 的子链, 导致 lead 通知写错 chain.
                    # 修复: 优先找 group chain (chain_type="group"), 没有才 fallback.
                    group_chain = (await db.execute(
                        select(Chain).where(
                            Chain.group_id == group.id,
                            Chain.chain_type == "group",
                            Chain.status.in_(["active", "paused"]),
                        )
                    )).scalar_one_or_none()
                    if group_chain:
                        chain = group_chain
                        logger.info(
                            "[EventDispatcher] using group chain %s for lead/subscriber (task=%s chain archived)",
                            chain.id[:8], (task_id or "?")[:8],
                        )
                    else:
                        from app.services.chain_handover_service import ChainHandoverService
                        handover = ChainHandoverService(db)
                        chain = await handover.get_active_chain_for_group(group.id)

                # 5. 加载 task（如果 chain 是 task chain，需要把 task 传给 executor，
                #    这样上下文 builder 才会注入 task_context 并继承/隔离主链历史）
                task = None
                if chain and chain.task_id:
                    task = (await db.execute(
                        select(Task).where(Task.id == chain.task_id)
                    )).scalar_one_or_none()

            if chain is None:
                logger.warning(
                    "[EventDispatcher] no active chain for agent=%s group=%s, skip session",
                    subscriber_agent_id[:8], group.id[:8] if group else "?",
                )
                return

            # 6. 启动新 session (调 AgentExecutor.execute)
            executor = await self._get_executor()
            logger.info(
                "[EventDispatcher] starting session for %s (group=%s, chain=%s, event=%s)",
                agent.name, group.name[:16] if group else "?", chain.id[:8], key[1],
            )
            response = await executor.execute(
                agent=agent,
                project_agent=pa,
                group=group,
                task=task,
                chain=chain,
                user_message=trigger_msg,
            )

            # 7. 把 agent 的回复持久化到 chain，并广播给前端。
            #    之前 EventDispatcher 只写 system packet 但不存 agent 回复，
            #    导致 task chain 里只能看到系统事件、看不到 agent 对话。
            content = (response.get("content") or "").strip()
            resp_metadata = response.get("metadata") or {}
            has_tool_calls = bool(resp_metadata.get("tool_calls"))
            if content or has_tool_calls:
                await self._save_agent_response_and_broadcast(
                    chain_id=chain.id,
                    agent=agent,
                    content=content,
                    metadata=resp_metadata,
                    group_id=group.id,
                )

            # 成功 -> 清失败计数
            self._failure_counts.pop(key, None)

        except Exception as e:
            logger.exception(
                "[EventDispatcher] start session failed for %s: %s",
                subscriber_agent_id[:8], e,
            )
            self._record_failure(key)

    # ── 冷却 / 失败管理 ──────────────────────────────────────

    def _is_in_cooldown(self, key: Tuple[str, str]) -> bool:
        last = self._cooldowns.get(key)
        if last is None:
            return False
        return (time.monotonic() - last) < self._cooldown_seconds

    def _is_in_failure_backoff(self, key: Tuple[str, str]) -> bool:
        # 失败 3 次以上 → 5 分钟回退
        count = self._failure_counts.get(key, 0)
        if count < 3:
            return False
        last_fail = self._cooldowns.get(key)
        if last_fail is None:
            return False
        backoff = self._failure_backoff * (2 ** min(count - 3, 3))  # 5m, 10m, 20m, 40m
        return (time.monotonic() - last_fail) < backoff

    def _record_failure(self, key: Tuple[str, str]) -> None:
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
        self._cooldowns[key] = time.monotonic()

    # ── 辅助 ────────────────────────────────────────────────

    async def _trigger_db_subscriptions(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        """触发 DB 持久化订阅（订阅机制 v1）

        与 event_bus 内存订阅并存：
        - event_bus 内存订阅由本类 _on_* 处理器处理（向 agent 发系统消息）
        - DB 订阅由 SubscriptionTrigger.on_event 处理（按 action 类型分派）

        失败不抛错（fire-and-forget），仅记录日志。
        """
        if self._subscription_trigger is None:
            return
        try:
            await self._subscription_trigger.on_event(event_type, payload)
        except Exception as e:
            logger.warning(
                "[EventDispatcher] _trigger_db_subscriptions failed for %s: %s",
                event_type, e,
            )

    async def _is_llm_healthy(self) -> bool:
        """轻量 LLM 健康检查。P2 简化为 always True, 失败由 executor.execute 兜底。"""
        return True

    async def _write_system_packet(self, group_id: Optional[str], content: str, event_type: str) -> None:
        """写一条 system packet 到 group 下当前 active chain（v2 P2: 可能 task chain 接管中）"""
        from app.models.chain import Chain, Packet
        from app.models.group import Group

        if not group_id:
            return

        async with self._session_factory() as db:
            # v2 P2: 找 group 下任意 active chain (group chain 或 task chain 都行)
            from app.services.chain_handover_service import ChainHandoverService
            handover = ChainHandoverService(db)
            group_chain = await handover.get_active_chain_for_group(group_id)
            if group_chain is None:
                logger.debug(
                    "[EventDispatcher] no active chain for group %s, skip system packet",
                    group_id[:8],
                )
                return

            prev_packet = (await db.execute(
                select(Packet)
                .where(Packet.chain_id == group_chain.id, Packet.deleted_at.is_(None))
                .order_by(Packet.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()

            packet = Packet(
                chain_id=group_chain.id,
                prev_packet_id=prev_packet.id if prev_packet else None,
                packet_type=self.SYSTEM_PACKET_TYPE,
                sender_type="system",
                sender_id="event_dispatcher",
                sender_name="系统事件",
                content=content,
                content_type="text",
                metadata_json={"event_type": event_type, "auto": True},
            )
            db.add(packet)

            if not group_chain.head_packet_id:
                group_chain.head_packet_id = packet.id
            group_chain.tail_packet_id = packet.id
            group_chain.packet_count = (group_chain.packet_count or 0) + 1

            await db.commit()

    async def _save_agent_response_and_broadcast(
        self,
        chain_id: str,
        agent: Any,
        content: str,
        metadata: Dict[str, Any],
        group_id: str,
    ) -> None:
        """
        把 EventDispatcher 唤起 agent 产生的回复保存为 Packet，并广播到前端。

        这是 task chain 里能看到对话的关键：之前只写了 system packet，
        agent 的回复没有持久化，所以前端 task chain 看起来是空的。
        """
        from app.services.chat_service import ChatService

        async with self._session_factory() as db:
            packet = await ChatService._save_packet(
                db,
                chain_id=chain_id,
                content=content,
                sender_type="agent",
                sender_id=agent.id,
                sender_name=agent.name,
                metadata=metadata,
            )
            await db.commit()
            await db.refresh(packet)

        # 广播给前端，让当前在群聊页的用户实时看到 agent 回复
        try:
            from app.orchestrator.websocket_manager import ws_manager
            await ws_manager.broadcast(str(group_id), {
                "type": "agent_message",
                "payload": {
                    "chain_id": chain_id,
                    "sender_id": agent.id,
                    "sender_name": agent.name,
                    "content": content,
                    "metadata": metadata,
                },
            })
        except Exception:
            logger.debug("[EventDispatcher] broadcast agent response failed", exc_info=True)

    async def _load_task_summary(self, task_id: str) -> Optional[Dict[str, Any]]:
        """加载 task 摘要（title, description, accept_criteria）"""
        from app.models.task import Task
        async with self._session_factory() as db:
            task = (await db.execute(
                select(Task).where(Task.id == task_id)
            )).scalar_one_or_none()
            if not task:
                return None
            return {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "acceptance_criteria": getattr(task, "acceptance_criteria", None),
                "group_id": task.group_id,
            }

    def _compose_task_status_msg(self, task_info: Dict[str, Any], new_status: str) -> str:
        """拼装 task 状态变更消息 (v2 P2+ 隐私修复: 不在主群写 title)"""
        criteria = task_info.get("acceptance_criteria")
        criteria_section = f"\n\n验收标准:\n{criteria}" if criteria else ""

        return (
            f"[系统通知] 任务状态变更\n"
            f"任务 ID: {task_info['id']}\n"
            f"新状态: {new_status}"
            f"{criteria_section}"
        )

    def _compose_task_assignment_msg(self, task_info: Dict[str, Any]) -> str:
        """
        给 assignee 的任务派发消息 (in_progress 时自动唤醒).

        v2 P2+ 隐私修复:
          - **不**把 task.title 写到 trigger_msg 注入主群 (title 经常含身份, 见狼人杀)
          - 任务描述已包含在通知里, assignee 不需要额外调 get_task

        v2 P2+ 精简: 只保留任务事实信息 (ID/描述/验收标准), 不再重复"按描述执行 /
        set_memory / update_task_status" 等框架操作引导 —— 这些 agent 应在 system_prompt
        或 skill 中一次性学会, 每次任务重复既浪费 token, 也容易把场景特化措辞
        (如"身份/角色") 混进框架通用模板.

        卡点 8 修复: 删除"调 get_task(task_id)"提示, 因为部分 agent 没有 get_task 工具,
        LLM 试图调用会触发 Permission denied ERROR 导致流终止.
        """
        desc = task_info.get("description") or "(无)"
        criteria = task_info.get("acceptance_criteria")
        criteria_section = f"\n\n**验收标准**:\n{criteria}" if criteria else ""

        return (
            f"[系统通知] 你有新任务待办\n\n"
            f"**任务 ID**: {task_info['id']}\n\n"
            f"**任务描述**:\n{desc}"
            f"{criteria_section}"
        )

    def _compose_task_done_for_lead_msg(self, task_info: Dict[str, Any]) -> str:
        """
        v2 P2+ 架构改进: 给 lead 的"任务完成"消息 (done 时自动唤醒 lead 继续推进).

        设计要点:
          - 不强加具体动作 (调 list_tasks / 开新任务) — lead 自己决定
          - 列出与本任务相关的"邻近状态": 还有哪些 todo 任务待处理, 让 lead 一次看清
          - 明确"业务闭环"信号: 你的派活被完成了, 是否继续推进由你决定

        v2 P2+ 隐私修复: 不含 task.title (可能含身份)

        卡点 8 修复: 删除"调 get_task(task_id)"提示, 因为部分 agent 没有 get_task 工具.
        """
        task_id = task_info.get("id") or "?"

        return (
            f"[系统通知] 你派出的任务已完成\n\n"
            f"**任务 ID**: {task_id}\n"
            f"**新状态**: done\n\n"
            f"---\n\n"
            f"**接下来由你决定**:\n"
            f"- 调 `list_tasks(group_id=...)` 看本群还有哪些 todo 任务待激活\n"
            f"- 调 `list_memories` / `get_memory` 看执行者可能写入的状态\n"
            f"- 如果还有 todo, **一次只激活 1 个** (避免多人同时说话, 群内串行)\n"
            f"- 如果都 done 了, 进入下一阶段 / 回合"
        )
