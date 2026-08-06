"""
v2 P2+: 跨 dispatcher/executor 共享的 session lifecycle gate.

解决"重复 dispatch"问题:
  - 同一 (agent_id, group_id) 同时只允许一个 active session.
  - 新 session 启动时, 如果已有 active session, 排队等待完成.
  - 不管 session 是 chat API 启动还是 EventDispatcher 启动, 都通过此 gate 串行化.

为什么需要共享?
  - EventDispatcher 启动的 session 会被 registry 跟踪.
  - 但 chat API 直接调 executor.execute() 启动的 session 不在 registry 里,
    dispatcher 看不到, 仍会启动新的 session 并行. 这就导致:
    用户 chat 触发法官 session 1 (在跑) → 玩家 done → 派法官 session 2 (并行) → LLM 限流超时.
  - 修复: chat API 启动的 session 也通过 gate 注册.

设计:
  - gate 是 stateful 的, 维护 _active_sessions / _pending_triggers.
  - dispatcher 和 executor 共享同一个 gate 实例 (main.py 注入).
  - acquire_and_register / release_unregister 是核心 API.

v2 P3: 群级串行锁 (serial_execution)
  - 某些场景 (如狼人杀) 要求"群内串行": 同一群同时只允许一个 agent session 跑.
  - 通过 group.workflow_config.serial_execution = true 开启.
  - 实现: 每个 serial group 一个 asyncio.Lock, execute() 入口 acquire, finally release.
  - 与 agent 级 gate 互补: agent 级防同一 agent 重入, group 级防不同 agent 并发.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# 单个 (agent, group) 的待处理 trigger 队列上限.
# 超过则丢弃最早的 (FIFO), 避免 backlog 把 LLM 拖到无限循环.
_MAX_PENDING_TRIGGERS_PER_AGENT = 5


# 模块级单例: 所有 AgentExecutor / EventDispatcher 默认共享同一个 gate.
# 设计理由: gate 的核心职责就是"跨 executor/dispatcher 协调 session 生命周期",
# 如果每个 executor 各自创建 gate, 群级串行锁 / agent 级串行化都会失效.
# main.py 启动时通过 set_session_gate() 注册共享实例;
# AgentExecutor(session_gate=None) 时通过 get_session_gate() 取单例.
_global_gate: "Optional[SessionLifecycleGate]" = None


def get_session_gate() -> "SessionLifecycleGate":
    """获取全局共享的 SessionLifecycleGate 单例.

    若 main.py 未显式 set, 则懒创建一个 (保证总有 gate 可用).
    """
    global _global_gate
    if _global_gate is None:
        _global_gate = SessionLifecycleGate()
    return _global_gate


def set_session_gate(gate: "SessionLifecycleGate") -> None:
    """注册全局共享 gate. main.py 启动时调用."""
    global _global_gate
    _global_gate = gate


def reset_session_gate() -> None:
    """清除全局 gate. 仅供测试隔离使用."""
    global _global_gate
    _global_gate = None


def is_serial_group(group: Any) -> bool:
    """
    判断一个 group 是否要求"群内串行"执行.

    通过 group.workflow_config.serial_execution = true 开启.
    兼容 group 为 None 或 workflow_config 缺失的情况.
    """
    if group is None:
        return False
    wf = getattr(group, "workflow_config", None) or {}
    return bool(wf.get("serial_execution", False))


class SessionLifecycleGate:
    """
    同 (agent_id, group_id) 同时只允许一个 active session.

    v2 P3: 额外支持群级串行锁 (serial_execution), 让同一群内不同 agent 也串行.
    """

    def __init__(self):
        # key = (agent_id, group_id)
        self._active_sessions: Dict[Tuple[str, str], asyncio.Task] = {}
        # key = (agent_id, group_id) -> FIFO 队列, 存放等待中的 trigger dict
        self._pending_triggers: Dict[Tuple[str, str], Deque[Dict[str, Any]]] = {}
        # 串行化 check-then-act, 避免 race
        self._lock = asyncio.Lock()
        # v2 P3: 群级串行锁. key = group_id -> asyncio.Lock
        # 只对 workflow_config.serial_execution=true 的 group 生效.
        self._group_locks: Dict[str, asyncio.Lock] = {}

    def get_group_lock(self, group_id: str) -> asyncio.Lock:
        """
        获取 (或创建) 群级串行锁.

        幂等: 同一 group_id 多次调用返回同一个 Lock 实例.
        Lock 不会被自动清理 (group 数量有限, 无泄漏风险).
        """
        lock = self._group_locks.get(group_id)
        if lock is None:
            lock = asyncio.Lock()
            self._group_locks[group_id] = lock
        return lock

    def is_active(self, session_key: Tuple[str, str]) -> bool:
        """查询同 key 是否有 active session 在跑"""
        existing = self._active_sessions.get(session_key)
        return existing is not None and not existing.done()

    async def wait_for_active(self, session_key: Tuple[str, str], timeout: Optional[float] = None) -> None:
        """
        await 已有 active session 完成.
        用于 chat API / executor.execute() 入口, 让 chat 发起的 session 串行化.

        死锁防护: 如果 active 就是当前 task, 立即 return (否则会等自己完成).
        """
        existing = self._active_sessions.get(session_key)
        if existing is None or existing.done():
            return
        # 死锁防护: 自己是 active 时不要等自己
        try:
            current = asyncio.current_task()
            if current is existing:
                return
        except RuntimeError:
            pass
        logger.info(
            "[SessionGate] %s wait_for_active existing=%s, awaiting...",
            session_key[0][:8], id(existing),
        )
        try:
            if timeout is None:
                await existing
            else:
                await asyncio.wait_for(asyncio.shield(existing), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "[SessionGate] %s wait_for_active timeout", session_key[0][:8],
            )
        except Exception:
            pass

    async def start_or_enqueue(
        self,
        session_key: Tuple[str, str],
        runner_factory: Callable[[], Awaitable[Any]],
        on_finish: Optional[Callable[[], None]] = None,
    ) -> Tuple[bool, Optional[asyncio.Task]]:
        """
        启动新 session 任务. 若同 key 已有 active, 则入队等下次启动.

        Args:
            session_key: (agent_id, group_id) 标识
            runner_factory: 无参 async callable, 实际跑 session 的协程
            on_finish: 完成后回调 (清理 + 派下一个 pending)

        Returns:
            (started, task): started=True 表示本次启动, False 表示入队.
            task 是 asyncio.Task 句柄, 调用方可以 await / add_done_callback.
        """
        async with self._lock:
            existing = self._active_sessions.get(session_key)
            if existing and not existing.done():
                return False, None

            task = asyncio.create_task(runner_factory())
            self._active_sessions[session_key] = task

            def _cleanup(t: asyncio.Task) -> None:
                # 只在还是自己时清理, 防止覆盖
                if self._active_sessions.get(session_key) is t:
                    del self._active_sessions[session_key]
                if on_finish:
                    try:
                        on_finish()
                    except Exception:
                        logger.exception("[SessionGate] on_finish callback failed")

            task.add_done_callback(_cleanup)
            return True, task

    async def enqueue_trigger(
        self,
        session_key: Tuple[str, str],
        trigger: Dict[str, Any],
    ) -> None:
        """
        把 trigger 入队, 等 active session 完成后自动启动.
        trigger dict 应包含 session_runner_factory 需要的全部参数.
        """
        async with self._lock:
            queue = self._pending_triggers.setdefault(session_key, deque())
            if len(queue) >= _MAX_PENDING_TRIGGERS_PER_AGENT:
                dropped = queue.popleft()
                logger.warning(
                    "[SessionGate] %s pending queue full, drop oldest trigger: %s",
                    session_key[0][:8],
                    str(dropped.get("trigger_msg", ""))[:80],
                )
            queue.append(trigger)
            logger.info(
                "[SessionGate] %s enqueue trigger (queue=%d): %s",
                session_key[0][:8], len(queue),
                str(trigger.get("trigger_msg", ""))[:80],
            )

    async def register_active(self, session_key: Tuple[str, str], task: asyncio.Task) -> None:
        """
        把已有 task 注册为 active (用于 chat API 直接启动的 session).

        注意: 如果 existing 就是当前 task (executor.execute() 入口被 dispatcher 启动的
        _runner task 调用), 不视为冲突, 直接更新引用 (idempotent).
        """
        async with self._lock:
            existing = self._active_sessions.get(session_key)
            if existing and not existing.done():
                # existing 是当前 task (自己调自己) → idempotent, no-op
                if existing is task:
                    return
                logger.warning(
                    "[SessionGate] %s already has active session (id=%s), refused to register another (id=%s)",
                    session_key[0][:8], id(existing), id(task),
                )
                return
            self._active_sessions[session_key] = task
            logger.debug(
                "[SessionGate] %s active session registered (external, id=%s)",
                session_key[0][:8], id(task),
            )

    def consume_next_pending(self, session_key: Tuple[str, str]) -> Optional[Dict[str, Any]]:
        """
        弹出一个 pending trigger (FIFO). 没有则返回 None.
        调用方负责启动新 session.
        """
        queue = self._pending_triggers.get(session_key)
        if not queue:
            return None
        item = queue.popleft()
        if not queue:
            del self._pending_triggers[session_key]
        return item

    def get_active_task(self, session_key: Tuple[str, str]) -> Optional[asyncio.Task]:
        return self._active_sessions.get(session_key)

    def get_pending_count(self, session_key: Tuple[str, str]) -> int:
        return len(self._pending_triggers.get(session_key, ()))
