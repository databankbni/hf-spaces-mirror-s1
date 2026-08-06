"""
订阅 Service + Repository 集成测试

覆盖:
- CRUD 流程
- 一次性订阅触发后禁用
- 持续订阅触发后仍 enabled
- 多订阅匹配同一事件
- list_by_event 查询
- mark_triggered 行为
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription
from app.repositories.subscription_repo import SubscriptionRepository
from app.services.subscription_service import SubscriptionService
from app.services.subscription_engine import TRIGGER_AS_MESSAGE

from tests.conftest import TestSessionLocal


@pytest_asyncio.fixture
async def db_session():
    """提供 DB session"""
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def project_id():
    """固定测试项目 ID"""
    return "test-project-0001"


class TestSubscriptionRepository:
    """Repository 集成测试"""

    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session, project_id):
        """创建 + 查询"""
        repo = SubscriptionRepository(db_session)
        sub = await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
            "filter": {"group_id": "G2", "new_status": "completed"},
            "action": TRIGGER_AS_MESSAGE,
            "message_template": "G2 已完成",
            "enabled": True,
            "one_shot": False,
        })
        await db_session.flush()

        # 查询
        got = await repo.get_by_id(sub.id)
        assert got is not None
        assert got.subscriber_id == "G1"
        assert got.event_type == "group_status_changed"
        assert got.filter == {"group_id": "G2", "new_status": "completed"}

    @pytest.mark.asyncio
    async def test_list_by_project(self, db_session, project_id):
        """按项目列出"""
        repo = SubscriptionRepository(db_session)
        for i in range(3):
            await repo.create({
                "project_id": project_id,
                "subscriber_type": "group",
                "subscriber_id": f"G{i+1}",
                "event_type": "group_status_changed",
                "action": TRIGGER_AS_MESSAGE,
            })
        await db_session.flush()

        subs = await repo.list_by_project(project_id)
        assert len(subs) == 3

        # enabled_only 过滤
        subs_enabled = await repo.list_by_project(project_id, enabled_only=True)
        assert len(subs_enabled) == 3  # 默认都启用

    @pytest.mark.asyncio
    async def test_list_by_event(self, db_session, project_id):
        """按事件列出"""
        repo = SubscriptionRepository(db_session)
        await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
        })
        await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G2",
            "event_type": "resource_created",
        })
        await db_session.flush()

        # 只查 group_status_changed
        subs = await repo.list_by_event(project_id, "group_status_changed")
        assert len(subs) == 1
        assert subs[0].subscriber_id == "G1"

    @pytest.mark.asyncio
    async def test_list_by_subscriber(self, db_session, project_id):
        """按订阅者列出"""
        repo = SubscriptionRepository(db_session)
        await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
        })
        await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "resource_created",
        })
        await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G2",
            "event_type": "group_status_changed",
        })
        await db_session.flush()

        # G1 有 2 个订阅
        subs = await repo.list_by_subscriber("group", "G1")
        assert len(subs) == 2

        # G2 有 1 个订阅
        subs = await repo.list_by_subscriber("group", "G2")
        assert len(subs) == 1

    @pytest.mark.asyncio
    async def test_mark_triggered_persistent(self, db_session, project_id):
        """触发持续订阅: enabled 保持 True, count 增加"""
        repo = SubscriptionRepository(db_session)
        sub = await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
            "one_shot": False,
        })
        await db_session.flush()
        assert sub.triggered_count == 0

        # 触发
        await repo.mark_triggered(sub.id, one_shot=False)
        await db_session.flush()
        await db_session.refresh(sub)

        assert sub.enabled is True  # 仍然启用
        assert sub.triggered_count == 1
        assert sub.last_triggered_at is not None

    @pytest.mark.asyncio
    async def test_mark_triggered_one_shot(self, db_session, project_id):
        """触发一次性订阅: enabled 自动变 False"""
        repo = SubscriptionRepository(db_session)
        sub = await repo.create({
            "project_id": project_id,
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
            "one_shot": True,
        })
        await db_session.flush()

        # 触发
        await repo.mark_triggered(sub.id, one_shot=True)
        await db_session.flush()
        await db_session.refresh(sub)

        assert sub.enabled is False  # 自动禁用
        assert sub.triggered_count == 1


class TestSubscriptionService:
    """Service 集成测试"""

    @pytest.mark.asyncio
    async def test_create_subscription_valid(self, db_session, project_id):
        """有效配置创建成功"""
        service = SubscriptionService(db_session)
        result = await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "group",
                "subscriber_id": "G1",
                "event_type": "group_status_changed",
                "filter": {"group_id": "G2", "new_status": "completed"},
                "message_template": "G2 已完成，请开始工作",
            },
        )
        assert result["success"] is True
        assert result["data"]["subscriber_id"] == "G1"
        assert result["data"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_create_subscription_invalid(self, db_session, project_id):
        """无效配置创建失败"""
        service = SubscriptionService(db_session)
        result = await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "unknown_type",  # 无效
                "subscriber_id": "G1",
                "event_type": "group_status_changed",
            },
        )
        assert result["success"] is False
        assert "subscriber_type" in result["error"]

    @pytest.mark.asyncio
    async def test_list_subscriptions(self, db_session, project_id):
        """列出订阅"""
        service = SubscriptionService(db_session)
        # 创建 3 个订阅
        for i in range(3):
            await service.create_subscription(
                project_id=project_id,
                config={
                    "subscriber_type": "group",
                    "subscriber_id": f"G{i+1}",
                    "event_type": "group_status_changed",
                },
            )

        result = await service.list_subscriptions(project_id)
        assert result["success"] is True
        assert len(result["data"]) == 3

    @pytest.mark.asyncio
    async def test_update_subscription(self, db_session, project_id):
        """更新订阅"""
        service = SubscriptionService(db_session)
        create_result = await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "group",
                "subscriber_id": "G1",
                "event_type": "group_status_changed",
                "message_template": "原模板",
            },
        )
        sub_id = create_result["data"]["id"]

        # 更新
        result = await service.update_subscription(
            sub_id, {"message_template": "新模板", "enabled": False}
        )
        assert result["success"] is True
        assert result["data"]["message_template"] == "新模板"
        assert result["data"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_delete_subscription(self, db_session, project_id):
        """删除订阅"""
        service = SubscriptionService(db_session)
        create_result = await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "group",
                "subscriber_id": "G1",
                "event_type": "group_status_changed",
            },
        )
        sub_id = create_result["data"]["id"]

        # 删除
        result = await service.delete_subscription(sub_id)
        assert result["success"] is True

        # 查询确认已删除
        get_result = await service.get_subscription(sub_id)
        assert get_result["success"] is False

    @pytest.mark.asyncio
    async def test_enable_disable(self, db_session, project_id):
        """启用/禁用"""
        service = SubscriptionService(db_session)
        create_result = await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "group",
                "subscriber_id": "G1",
                "event_type": "group_status_changed",
            },
        )
        sub_id = create_result["data"]["id"]
        assert create_result["data"]["enabled"] is True

        # 禁用
        result = await service.enable_subscription(sub_id, False)
        assert result["success"] is True
        assert result["data"]["enabled"] is False

        # 启用
        result = await service.enable_subscription(sub_id, True)
        assert result["success"] is True
        assert result["data"]["enabled"] is True


class TestSubscriptionTriggerIntegration:
    """触发器集成测试（不真正调 chat_service）"""

    @pytest.mark.asyncio
    async def test_on_event_no_match_returns_zero(self, db_session, project_id):
        """无订阅时返回 0"""
        from app.services.subscription_trigger import SubscriptionTrigger
        from app.services.subscriber_dispatcher import SubscriberDispatcher

        # mock dispatcher
        class MockDispatcher:
            async def dispatch(self, **kwargs):
                return True

        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=MockDispatcher(),
        )

        # 无订阅
        count = await trigger.on_event(
            "group_status_changed",
            {"project_id": project_id, "group_id": "G1", "new_status": "completed"},
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_on_event_with_matching_sub(self, db_session, project_id):
        """有匹配订阅时触发"""
        from app.services.subscription_trigger import SubscriptionTrigger
        from app.services.subscription_service import SubscriptionService

        # 创建订阅
        service = SubscriptionService(db_session)
        await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "group",
                "subscriber_id": "G5",
                "event_type": "group_status_changed",
                "filter": {"group_id": "G4", "new_status": "completed"},
                "message_template": "G4 已完成，请开始",
            },
        )
        await db_session.commit()

        # mock dispatcher 记录调用
        dispatched = []

        class MockDispatcher:
            async def dispatch(self, **kwargs):
                dispatched.append(kwargs)
                return True

        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=MockDispatcher(),
        )

        # 触发事件
        count = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": project_id,
                "group_id": "G4",
                "new_status": "completed",
                "old_status": "active",
            },
        )
        assert count == 1
        assert len(dispatched) == 1
        assert dispatched[0]["subscriber_type"] == "group"
        assert dispatched[0]["subscriber_id"] == "G5"
        assert "G4 已完成" in dispatched[0]["message"]

    @pytest.mark.asyncio
    async def test_on_event_filter_no_match(self, db_session, project_id):
        """filter 不匹配时不触发"""
        from app.services.subscription_trigger import SubscriptionTrigger
        from app.services.subscription_service import SubscriptionService

        service = SubscriptionService(db_session)
        await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "group",
                "subscriber_id": "G5",
                "event_type": "group_status_changed",
                "filter": {"group_id": "G4", "new_status": "completed"},
            },
        )
        await db_session.commit()

        dispatched = []

        class MockDispatcher:
            async def dispatch(self, **kwargs):
                dispatched.append(kwargs)
                return True

        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=MockDispatcher(),
        )

        # 触发不匹配的事件 (group_id=G3，不是 G4)
        count = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": project_id,
                "group_id": "G3",  # 不匹配
                "new_status": "completed",
            },
        )
        assert count == 0
        assert len(dispatched) == 0

    @pytest.mark.asyncio
    async def test_one_shot_disables_after_trigger(self, db_session, project_id):
        """一次性订阅触发后自动禁用"""
        from app.services.subscription_trigger import SubscriptionTrigger
        from app.services.subscription_service import SubscriptionService

        service = SubscriptionService(db_session)
        result = await service.create_subscription(
            project_id=project_id,
            config={
                "subscriber_type": "group",
                "subscriber_id": "G5",
                "event_type": "group_status_changed",
                "filter": {"group_id": "G4", "new_status": "completed"},
                "one_shot": True,
            },
        )
        sub_id = result["data"]["id"]
        await db_session.commit()

        class MockDispatcher:
            async def dispatch(self, **kwargs):
                return True

        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=MockDispatcher(),
        )

        # 第一次触发
        count1 = await trigger.on_event(
            "group_status_changed",
            {"project_id": project_id, "group_id": "G4", "new_status": "completed"},
        )
        assert count1 == 1

        # 查询确认已禁用
        async with TestSessionLocal() as session:
            repo = SubscriptionRepository(session)
            sub = await repo.get_by_id(sub_id)
            assert sub.enabled is False
            assert sub.triggered_count == 1

        # 第二次触发：因为 disabled 不会被查到
        count2 = await trigger.on_event(
            "group_status_changed",
            {"project_id": project_id, "group_id": "G4", "new_status": "completed"},
        )
        assert count2 == 0
