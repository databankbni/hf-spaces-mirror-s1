"""
订阅 Service

封装订阅的 CRUD 业务逻辑。
供 API 端点和工具调用使用。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.repositories.subscription_repo import SubscriptionRepository
from app.services.subscription_engine import (
    validate_subscription_config,
    TRIGGER_AS_MESSAGE,
)

logger = logging.getLogger(__name__)


class SubscriptionService:
    """订阅业务逻辑层"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SubscriptionRepository(db)

    async def create_subscription(
        self,
        project_id: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """创建订阅

        Args:
            project_id: 所属项目 ID
            config: 订阅配置（subscriber_type, subscriber_id, event_type, filter, action, message_template, one_shot）

        Returns:
            dict: {"success": bool, "data"?: dict, "error"?: str}
        """
        # 补全配置
        full_config = {
            "project_id": project_id,
            "subscriber_type": config.get("subscriber_type"),
            "subscriber_id": config.get("subscriber_id"),
            "event_type": config.get("event_type"),
            "filter": config.get("filter"),
            "action": config.get("action", TRIGGER_AS_MESSAGE),
            "message_template": config.get("message_template"),
            "one_shot": bool(config.get("one_shot", False)),
            "enabled": True,
        }

        # 校验
        err = validate_subscription_config(full_config)
        if err:
            return {"success": False, "error": err}

        # 创建
        try:
            sub = await self.repo.create(full_config)
            await self.db.commit()
            logger.info(
                "[subscription_service] created %s: %s=%s event=%s",
                sub.id[:8], sub.subscriber_type,
                sub.subscriber_id[:8], sub.event_type,
            )
            return {"success": True, "data": sub.to_dict()}
        except Exception as e:
            await self.db.rollback()
            logger.exception("[subscription_service] create failed")
            return {"success": False, "error": str(e)}

    async def list_subscriptions(
        self,
        project_id: str,
        subscriber_type: Optional[str] = None,
        subscriber_id: Optional[str] = None,
        enabled_only: bool = False,
    ) -> Dict[str, Any]:
        """列出订阅"""
        try:
            if subscriber_type and subscriber_id:
                subs = await self.repo.list_by_subscriber(
                    subscriber_type, subscriber_id, enabled_only=enabled_only,
                )
            else:
                subs = await self.repo.list_by_project(
                    project_id, enabled_only=enabled_only,
                )
            return {
                "success": True,
                "data": [s.to_dict() for s in subs],
            }
        except Exception as e:
            logger.exception("[subscription_service] list failed")
            return {"success": False, "error": str(e)}

    async def get_subscription(self, sub_id: str) -> Dict[str, Any]:
        """获取单个订阅"""
        try:
            sub = await self.repo.get_by_id(sub_id)
            if not sub:
                return {"success": False, "error": "subscription not found"}
            return {"success": True, "data": sub.to_dict()}
        except Exception as e:
            logger.exception("[subscription_service] get failed")
            return {"success": False, "error": str(e)}

    async def update_subscription(
        self,
        sub_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """更新订阅

        Args:
            sub_id: 订阅 ID
            updates: 可更新字段（filter, action, message_template, enabled, one_shot）
        """
        # 限制可更新字段
        allowed = {
            "filter", "action", "message_template", "enabled", "one_shot",
        }
        clean_updates = {k: v for k, v in updates.items() if k in allowed}

        if not clean_updates:
            return {"success": False, "error": "no updatable fields"}

        try:
            sub = await self.repo.update(sub_id, clean_updates)
            if not sub:
                return {"success": False, "error": "subscription not found"}
            await self.db.commit()
            return {"success": True, "data": sub.to_dict()}
        except Exception as e:
            await self.db.rollback()
            logger.exception("[subscription_service] update failed")
            return {"success": False, "error": str(e)}

    async def delete_subscription(self, sub_id: str) -> Dict[str, Any]:
        """删除订阅（软删除）"""
        try:
            ok = await self.repo.delete(sub_id)
            if not ok:
                return {"success": False, "error": "subscription not found"}
            await self.db.commit()
            return {"success": True}
        except Exception as e:
            await self.db.rollback()
            logger.exception("[subscription_service] delete failed")
            return {"success": False, "error": str(e)}

    async def enable_subscription(self, sub_id: str, enabled: bool) -> Dict[str, Any]:
        """启用/禁用订阅"""
        return await self.update_subscription(sub_id, {"enabled": enabled})
