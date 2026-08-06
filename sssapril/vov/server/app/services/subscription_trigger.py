"""
订阅触发器

完整流程:
1. 事件发布 → on_event(event_type, payload)
2. 查项目下所有匹配 event_type 的订阅
3. 对每个订阅 filter 递归比较
4. 匹配的订阅渲染消息模板
5. 按 action 类型分派:
   - trigger_as_message → 注入到 subscriber（群/agent）
   - trigger_as_notification → 仅 WS 广播（不启动 agent）
   - trigger_as_task → 创建任务（暂未实现，留接口）
6. 标记订阅已触发（计数 + 一次性禁用）

设计原则:
- 不阻塞事件发布方（fire-and-forget）
- 失败不重试（避免循环）
- 每个订阅触发独立 try/except（一个失败不影响其他）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.subscription import Subscription
from app.repositories.subscription_repo import SubscriptionRepository
from app.services.subscription_engine import (
    match_filter,
    render_template,
    TRIGGER_AS_MESSAGE,
    TRIGGER_AS_NOTIFICATION,
    TRIGGER_AS_TASK,
)
from app.services.subscriber_dispatcher import SubscriberDispatcher

logger = logging.getLogger(__name__)


class SubscriptionTrigger:
    """订阅触发器：监听事件 → 匹配订阅 → 触发动作"""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        dispatcher: SubscriberDispatcher,
        ws_broadcast=None,
    ):
        """
        Args:
            session_factory: AsyncSession 工厂（用于 DB 操作）
            dispatcher: SubscriberDispatcher 实例
            ws_broadcast: 可选，WS 广播函数（用于 trigger_as_notification）
        """
        self.session_factory = session_factory
        self.dispatcher = dispatcher
        self.ws_broadcast = ws_broadcast

    async def on_event(self, event_type: str, payload: Dict[str, Any]) -> int:
        """事件发生时调用：匹配订阅 + 触发动作。

        Args:
            event_type: 事件类型
            payload: 事件 payload（必须含 project_id）

        Returns:
            int: 成功触发的订阅数
        """
        project_id = payload.get("project_id")
        if not project_id:
            logger.warning(
                "[subscription_trigger] event %s has no project_id, skip",
                event_type,
            )
            return 0

        # 1. 查所有匹配 event_type 的订阅
        async with self.session_factory() as session:
            repo = SubscriptionRepository(session)
            subs = await repo.list_by_event(
                project_id=project_id,
                event_type=event_type,
                enabled_only=True,
            )

        if not subs:
            return 0

        # 2. 逐个匹配 filter, 收集匹配项
        matched_subs: List[Subscription] = []
        triggered = 0
        for sub in subs:
            if not match_filter(sub.filter, payload):
                continue
            matched_subs.append(sub)
            # 3. 触发动作（fire-and-forget, 不阻塞）
            try:
                await self._trigger_one(sub, payload)
                triggered += 1
            except Exception as e:
                logger.warning(
                    "[subscription_trigger] failed to trigger %s: %s",
                    sub.id[:8], e,
                )

        # 4. 标记触发（更新计数 + 一次性禁用）
        if matched_subs:
            await self._mark_triggered_batch(matched_subs)

        return triggered

    async def _trigger_one(
        self,
        sub: Subscription,
        payload: Dict[str, Any],
    ) -> None:
        """触发单个订阅的动作"""
        message = render_template(sub.message_template, payload)

        if sub.action == TRIGGER_AS_MESSAGE:
            await self._trigger_as_message(sub, message)
        elif sub.action == TRIGGER_AS_NOTIFICATION:
            await self._trigger_as_notification(sub, message, payload)
        elif sub.action == TRIGGER_AS_TASK:
            # 暂未实现，预留接口
            logger.info(
                "[subscription_trigger] trigger_as_task not implemented yet, "
                "skip subscription %s",
                sub.id[:8],
            )
        else:
            logger.warning(
                "[subscription_trigger] unknown action %s, skip %s",
                sub.action, sub.id[:8],
            )

    async def _trigger_as_message(
        self,
        sub: Subscription,
        message: str,
    ) -> None:
        """触发消息注入到 subscriber"""
        async with self.session_factory() as session:
            success = await self.dispatcher.dispatch(
                subscriber_type=sub.subscriber_type,
                subscriber_id=sub.subscriber_id,
                message=message,
                session=session,
            )
        if success:
            logger.info(
                "[subscription_trigger] triggered %s -> %s=%s msg=%s...",
                sub.id[:8], sub.subscriber_type,
                sub.subscriber_id[:8], message[:50],
            )

    async def _trigger_as_notification(
        self,
        sub: Subscription,
        message: str,
        payload: Dict[str, Any],
    ) -> None:
        """仅发 WS 通知（不启动 agent）"""
        if not self.ws_broadcast:
            logger.warning(
                "[subscription_trigger] ws_broadcast not configured, "
                "skip notification %s",
                sub.id[:8],
            )
            return

        # 给订阅者所在群发系统通知
        # 如果 subscriber 是 group，直接广播到该群
        # 如果 subscriber 是 agent，查 agent 所在群后广播
        target_group_id = None
        if sub.subscriber_type == "group":
            target_group_id = sub.subscriber_id
        else:
            async with self.session_factory() as session:
                from app.models.group import GroupMember
                from sqlalchemy import select
                result = await session.execute(
                    select(GroupMember.group_id)
                    .where(GroupMember.project_agent_id == sub.subscriber_id)
                    .limit(1)
                )
                target_group_id = result.scalar_one_or_none()

        if target_group_id:
            await self.ws_broadcast(
                target_group_id,
                {
                    "type": "subscription_notification",
                    "payload": {
                        "subscription_id": sub.id,
                        "event_type": payload.get("event_type"),
                        "message": message,
                    },
                },
            )
            logger.info(
                "[subscription_trigger] notified %s=%s msg=%s...",
                sub.subscriber_type,
                sub.subscriber_id[:8], message[:50],
            )

    async def _mark_triggered_batch(
        self,
        subs: List[Subscription],
    ) -> None:
        """批量标记已触发：增加计数 + 一次性订阅自动禁用"""
        if not subs:
            return
        async with self.session_factory() as session:
            repo = SubscriptionRepository(session)
            for sub in subs:
                await repo.mark_triggered(sub.id, one_shot=sub.one_shot)
            await session.commit()
