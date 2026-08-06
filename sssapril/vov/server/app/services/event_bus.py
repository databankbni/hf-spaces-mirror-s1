"""
v2 P2 事件总线（内存版）

按 v2 §0.5 原则 6: 系统给原子能力, skill 决定怎么用。
event_bus 是 subscribe / publish 的轻量封装, 跨进程版本留给 P3 用 Redis。

设计要点:
  1. 双层接口
     - subscribe()  给 agent 订阅（agent 自己用工具调用注册）
     - on()         给系统内部组件订阅（如 EventDispatcher, 同步注册）
  2. publish() 同时:
     - 通知 agent-side 订阅者（enqueue）
     - 触发 system-side callbacks（fire-and-forget, 不阻塞 publish）
  3. find_matching_subscribers() 给 dispatcher 用: 谁该被通知

支持事件:
- task_status_changed
- resource_created
- resource_updated
- group_status_changed
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from collections import defaultdict

logger = logging.getLogger(__name__)

# 系统侧 callback 类型: async def cb(event_type: str, payload: dict) -> None
SystemCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


class EventBus:
    """
    进程内事件总线（P2 增强版）

    agent 侧用法:
        await event_bus.subscribe("task_status_changed", agent_id, project_id, group_id)
        # 之后调 event_bus.drain_events(agent_id) 拉所有 pending 事件

    系统侧用法（EventDispatcher 用）:
        event_bus.on("task_status_changed", my_dispatcher_callback)
        # 事件 publish 时, my_dispatcher_callback(event_type, payload) 会被 fire-and-forget 调用
    """

    def __init__(self):
        # event_type -> set of (subscriber_agent_id, project_id, group_id)
        # agent 侧订阅
        self._subs: Dict[str, Set[tuple]] = defaultdict(set)
        # subscriber_agent_id -> asyncio.Queue（pending events）
        self._queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        # event_type -> List[SystemCallback]
        # 系统侧 callback
        self._callbacks: Dict[str, List[SystemCallback]] = defaultdict(list)
        # 锁: agent 侧订阅/取消订阅需要
        self._lock = asyncio.Lock()

    # ── Agent 侧 API ───────────────────────────────────────────

    async def subscribe(
        self,
        event_type: str,
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str] = None,
    ) -> None:
        async with self._lock:
            self._subs[event_type].add((subscriber_agent_id, project_id, group_id))
        logger.info(
            "[event_bus] agent=%s subscribed to %s (project=%s group=%s)",
            subscriber_agent_id[:8], event_type, project_id[:8], (group_id or "-")[:8],
        )

    async def unsubscribe(
        self,
        event_type: str,
        subscriber_agent_id: str,
        project_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> int:
        """
        取消订阅。
        - 不传 project_id/group_id: 全部取消
        - 传 project_id: 取消该 project
        - 传 project_id+group_id: 取消该 group
        返回取消的数量
        """
        async with self._lock:
            current = self._subs.get(event_type, set())
            to_remove = set()
            for sub in current:
                sub_agent, sub_proj, sub_grp = sub
                if sub_agent != subscriber_agent_id:
                    continue
                if project_id is not None and sub_proj != project_id:
                    continue
                if group_id is not None and sub_grp != group_id:
                    continue
                to_remove.add(sub)
            current -= to_remove
        if to_remove:
            logger.info(
                "[event_bus] agent=%s unsubscribed %d of %s",
                subscriber_agent_id[:8], len(to_remove), event_type,
            )
        return len(to_remove)

    async def list_subscriptions(self, subscriber_agent_id: str) -> List[Dict[str, Any]]:
        result = []
        async with self._lock:
            for event_type, subs in self._subs.items():
                for sub in subs:
                    if sub[0] == subscriber_agent_id:
                        result.append({
                            "event_type": event_type,
                            "project_id": sub[1],
                            "group_id": sub[2],
                        })
        return result

    async def drain_events(
        self,
        subscriber_agent_id: str,
        max_count: int = 50,
    ) -> List[Dict[str, Any]]:
        """排空某 subscriber 的 pending 事件（agent 主动拉取用）"""
        events = []
        q = self._queues[subscriber_agent_id]
        while not q.empty() and len(events) < max_count:
            try:
                events.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    def find_matching_subscribers(
        self,
        event_type: str,
        project_id: Optional[str],
        group_id: Optional[str],
    ) -> List[Dict[str, str]]:
        """
        (sync) 找出所有匹配的 agent 订阅者。
        用于 EventDispatcher 给定一个事件, 找谁该被通知。
        """
        subs = self._subs.get(event_type, set())
        matches = []
        for sub_agent_id, sub_project_id, sub_group_id in subs:
            if sub_project_id and project_id and sub_project_id != project_id:
                continue
            if sub_group_id and group_id and sub_group_id != group_id:
                continue
            matches.append({
                "subscriber_agent_id": sub_agent_id,
                "project_id": sub_project_id,
                "group_id": sub_group_id,
            })
        return matches

    # ── 系统侧 API ─────────────────────────────────────────────

    def on(self, event_type: str, callback: SystemCallback) -> None:
        """
        系统侧注册 callback（同步, 不需要 await）。

        callback 签名: async def cb(event_type: str, payload: dict) -> None
        callback 失败不影响 publish, 内部 try/except + logger。
        """
        self._callbacks[event_type].append(callback)
        logger.info("[event_bus] system callback registered for %s: %s", event_type, callback.__qualname__)

    def off(self, event_type: str, callback: SystemCallback) -> bool:
        """系统侧取消 callback。返回是否成功移除"""
        cbs = self._callbacks.get(event_type, [])
        if callback in cbs:
            cbs.remove(callback)
            return True
        return False

    # ── publish ───────────────────────────────────────────────

    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> int:
        """
        发布事件。
        1. 通知 agent-side 订阅者（enqueue, 同步）
        2. 触发 system-side callbacks（fire-and-forget, 不阻塞 publish）
        返回 agent 订阅者被通知数
        """
        project_id = payload.get("project_id", "")
        group_id = payload.get("group_id")

        # 1. Agent-side 通知
        notified = 0
        subs = self.find_matching_subscribers(event_type, project_id, group_id)
        for match in subs:
            sub_agent_id = match["subscriber_agent_id"]
            try:
                self._queues[sub_agent_id].put_nowait({
                    "event_type": event_type,
                    "payload": payload,
                    "published_at": asyncio.get_event_loop().time(),
                })
                notified += 1
            except Exception as e:
                logger.warning("[event_bus] failed to enqueue for %s: %s", sub_agent_id[:8], e)

        if notified:
            logger.info(
                "[event_bus] published %s → %d agent subscribers (project=%s group=%s)",
                event_type, notified, (project_id or "-")[:8], (group_id or "-")[:8],
            )

        # 2. System-side callbacks（fire-and-forget）
        cbs = list(self._callbacks.get(event_type, []))  # 快照, 防 cb 内 on/off 改 dict
        for cb in cbs:
            try:
                asyncio.create_task(self._safe_invoke(cb, event_type, payload))
            except RuntimeError:
                # 无事件循环（极少见, 同步上下文）, 退化
                logger.warning("[event_bus] no event loop, drop callback %s", cb.__qualname__)
            except Exception as e:
                logger.warning("[event_bus] failed to schedule callback %s: %s", cb.__qualname__, e)

        return notified

    @staticmethod
    async def _safe_invoke(cb: SystemCallback, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            await cb(event_type, payload)
        except Exception:
            logger.exception("[event_bus] system callback %s raised for %s", cb.__qualname__, event_type)


# 全局单例
event_bus = EventBus()
