"""
订阅 Repository

提供 subscription 表的数据访问层。
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from .base import BaseRepository


class SubscriptionRepository(BaseRepository[Subscription]):
    """订阅数据访问层"""

    def __init__(self, db: AsyncSession):
        super().__init__(Subscription, db)

    async def list_by_project(
        self,
        project_id: str,
        enabled_only: bool = False,
    ) -> List[Subscription]:
        """列出项目下所有订阅"""
        query = select(Subscription).where(
            Subscription.project_id == project_id,
            Subscription.deleted_at.is_(None),
        )
        if enabled_only:
            query = query.where(Subscription.enabled.is_(True))
        query = query.order_by(Subscription.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_subscriber(
        self,
        subscriber_type: str,
        subscriber_id: str,
        enabled_only: bool = False,
    ) -> List[Subscription]:
        """列出某订阅者的所有订阅"""
        query = select(Subscription).where(
            Subscription.subscriber_type == subscriber_type,
            Subscription.subscriber_id == subscriber_id,
            Subscription.deleted_at.is_(None),
        )
        if enabled_only:
            query = query.where(Subscription.enabled.is_(True))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_event(
        self,
        project_id: str,
        event_type: str,
        enabled_only: bool = True,
    ) -> List[Subscription]:
        """列出项目下订阅某事件的所有订阅（用于事件触发时查找匹配项）"""
        query = select(Subscription).where(
            Subscription.project_id == project_id,
            Subscription.event_type == event_type,
            Subscription.deleted_at.is_(None),
        )
        if enabled_only:
            query = query.where(Subscription.enabled.is_(True))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def mark_triggered(self, subscription_id: str, one_shot: bool) -> None:
        """标记订阅已触发：增加计数、更新时间、一次性订阅自动禁用"""
        values = {
            "triggered_count": Subscription.triggered_count + 1,
            "last_triggered_at": Subscription.updated_at,  # 由 db.onupdate 自动填
        }
        if one_shot:
            values["enabled"] = False
        await self.db.execute(
            update(Subscription)
            .where(Subscription.id == subscription_id)
            .values(**values)
        )

    async def get_by_id(self, id: str) -> Optional[Subscription]:
        """根据 ID 获取订阅"""
        query = select(Subscription).where(
            Subscription.id == id,
            Subscription.deleted_at.is_(None),
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
