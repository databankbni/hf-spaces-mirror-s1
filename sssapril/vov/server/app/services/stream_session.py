"""
流式 Session 注册表

设计目的：
    把"LLM 流式执行"和"SSE 客户端推送"解耦。
    - LLM 调用的产出 (token / 事件) 持续推入 session 的内部 queue
    - 多个 SSE 客户端可以同时订阅同一个 session
    - 客户端断开 (页面刷新/网络断开) 不会终止 LLM 调用, 只取消订阅
    - 主动 stop / 超时 / 异常才真正终止

关键不变量:
    1. 一个 (chain_id, packet_id) 同时只对应一个活跃 session
    2. session.latest_content 始终是 LLM 已生成内容的最新快照
       (用于 attach 时立即返回给新客户端)
    3. session.done_event.set() 之后, 所有订阅者最终会收到结束事件
    4. session 在 done 后保留 N 秒供后到的客户端能拿到 done 状态
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# 标记订阅队列的"流已结束"哨兵
_DONE_SENTINEL: Dict[str, Any] = {"__done__": True}


@dataclass
class StreamSession:
    """
    一个流式 LLM 调用的状态。

    字段:
        chain_id:      所属 chain
        packet_id:     正在写入的 packet (流开始时占位插入的)
        group_id:      所属 group (方便 group 维度的清理)
        is_streaming:  LLM 是否还在跑
        is_cancelled:  是否被用户主动 stop
        latest_content: 当前已 partial save 的累计内容 (用于 snapshot)
        latest_metadata: 流过程中收集到的 metadata (tool_calls / render_spec 等)
        error:         LLM 异常信息
        cancel_event:  asyncio.Event, 主动 stop 时 set, LLM 协程会监听
        done_event:    asyncio.Event, LLM 协程结束时 set
        task:          后台 _run_stream_decoupled 任务 (用于 cancel 时中断 execute)
        subscribers:   所有活跃 SSE 客户端各自的 asyncio.Queue
        created_at:    创建时间 (用于清理过期 session)
    """

    chain_id: str
    packet_id: str
    group_id: str

    is_streaming: bool = True
    is_cancelled: bool = False
    latest_content: str = ""
    latest_metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None

    subscribers: List[asyncio.Queue] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def push_event(self, event: Dict[str, Any]) -> None:
        """把一个事件广播给所有订阅者。"""
        for sub in list(self.subscribers):
            try:
                sub.put_nowait(event)
            except asyncio.QueueFull:
                # 慢消费者: 丢弃这个事件, 反正 partial save 也在做, 客户端能拉
                logger.warning(
                    "[stream_session] subscriber queue full, dropping event packet=%s",
                    self.packet_id[:8],
                )

    def push_done_sentinel(self) -> None:
        """通知所有订阅者流已结束。"""
        for sub in list(self.subscribers):
            try:
                sub.put_nowait(_DONE_SENTINEL)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        """新客户端订阅: 返回一个独立的 queue, 直到取消订阅。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=1024)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass

    def is_alive(self) -> bool:
        """session 还在运行或刚结束不久 (供 attach 决策)。"""
        if self.is_streaming:
            return True
        # 结束后保留 5 分钟供新客户端拿到 done 状态
        return (time.time() - self.created_at) < 300 and not self.is_cancelled


class StreamSessionRegistry:
    """
    全局流式 session 注册表 (按 packet_id 索引)。

    Thread-safety: 所有调用在同一个 asyncio event loop 中, 不需要锁。
    """

    def __init__(self) -> None:
        # packet_id -> StreamSession
        self._by_packet: Dict[str, StreamSession] = {}
        # chain_id -> 当前活跃的 packet_id (便于按 group 查)
        self._active_by_chain: Dict[str, str] = {}

    def create(self, chain_id: str, packet_id: str, group_id: str) -> StreamSession:
        """创建并注册一个 session。如果已有同名 session, 先清理。"""
        existing = self._by_packet.get(packet_id)
        if existing is not None:
            logger.warning(
                "[stream_session] replacing existing session for packet=%s", packet_id[:8]
            )
            self._remove(packet_id)

        session = StreamSession(
            chain_id=chain_id,
            packet_id=packet_id,
            group_id=group_id,
        )
        self._by_packet[packet_id] = session
        self._active_by_chain[chain_id] = packet_id
        logger.info(
            "[stream_session] created session chain=%s packet=%s",
            chain_id[:8], packet_id[:8],
        )
        return session

    def get(self, packet_id: str) -> Optional[StreamSession]:
        return self._by_packet.get(packet_id)

    def get_active_for_chain(self, chain_id: str) -> Optional[StreamSession]:
        """查 chain 当前的活跃 session (用于 attach 时按 chain 找)。"""
        pid = self._active_by_chain.get(chain_id)
        if not pid:
            return None
        session = self._by_packet.get(pid)
        if session is None or not session.is_alive():
            return None
        return session

    def get_any_active_for_group(self, group_id: str) -> Optional[StreamSession]:
        """查 group 下任一活跃 session (fallback, group 维度的查询)。"""
        # _active_by_chain 是按 chain_id 索引的, 这里需要按 group 过滤
        # 没有按 group 索引, 暂时遍历 (session 数量通常很少, 可接受)
        for sid, session in list(self._by_packet.items()):
            if session.group_id == group_id and session.is_alive():
                return session
        return None

    def mark_done(self, packet_id: str) -> None:
        """标记 session 为 done, 清理活跃索引。"""
        session = self._by_packet.get(packet_id)
        if session is None:
            return
        session.is_streaming = False
        session.done_event.set()
        session.push_done_sentinel()
        if self._active_by_chain.get(session.chain_id) == packet_id:
            self._active_by_chain.pop(session.chain_id, None)

        # 延迟清理 (给后到的 attach 客户端机会)
        async def _cleanup_later() -> None:
            try:
                # 保留 5 分钟, 让最后到的客户端能拿到 done 状态
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                return
            self._remove(packet_id)
            logger.info(
                "[stream_session] cleaned up session packet=%s (5min grace expired)",
                packet_id[:8],
            )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_cleanup_later())
        except RuntimeError:
            # 没有 running loop (理论不该发生), 直接删
            self._remove(packet_id)

    def cancel(self, packet_id: str) -> bool:
        """主动停止一个 session。返回是否存在。"""
        session = self._by_packet.get(packet_id)
        if session is None:
            return False
        session.is_cancelled = True
        session.cancel_event.set()
        # 中断后台 _run_stream_decoupled 任务（execute() 内部的 await 会被 CancelledError 打断）
        if session.task is not None and not session.task.done():
            session.task.cancel()
        logger.info("[stream_session] cancel signal sent packet=%s", packet_id[:8])
        return True

    def _remove(self, packet_id: str) -> None:
        session = self._by_packet.pop(packet_id, None)
        if session is None:
            return
        # 通知所有订阅者结束
        session.push_done_sentinel()
        if self._active_by_chain.get(session.chain_id) == packet_id:
            self._active_by_chain.pop(session.chain_id, None)

    def stats(self) -> Dict[str, int]:
        """诊断用。"""
        return {
            "total": len(self._by_packet),
            "streaming": sum(1 for s in self._by_packet.values() if s.is_streaming),
        }


# 全局单例
registry = StreamSessionRegistry()
