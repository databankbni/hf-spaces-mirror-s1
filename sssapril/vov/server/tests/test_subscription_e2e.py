"""
订阅机制 v1 - 端到端测试

测试完整链路:
1. 创建真实 Project + Group (G1 上游, G2 下游)
2. 创建订阅: G2 订阅 G1 的 group_status_changed (filter: new_status=completed)
3. 通过 SubscriptionTrigger.on_event 发布事件
4. 验证 SubscriberDispatcher 调用 ChatService.send_message_stream 注入消息到 G2
5. 验证消息模板正确渲染 (含事件 payload 字段)
6. 验证 one_shot 订阅触发后自动禁用
7. 验证持续订阅可多次触发

测试边界:
- 真实 DB (TestSessionLocal)
- 真实 SubscriptionTrigger + SubscriberDispatcher
- Mock ChatService (避免启动真实 LLM agent session)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group
from app.models.project import Project
from app.services.subscriber_dispatcher import SubscriberDispatcher
from app.services.subscription_service import SubscriptionService
from app.services.subscription_trigger import SubscriptionTrigger

from tests.conftest import TestSessionLocal


# ── 辅助: 创建真实 Project + Group ────────────────────────


async def _create_project_and_groups(db_session: AsyncSession) -> Dict[str, str]:
    """创建 1 个 project + 2 个 group (G1 上游, G2 下游), 返回 ID 映射."""
    project = Project(
        name="E2E Test Project",
        description="订阅机制端到端测试",
        status="active",
    )
    db_session.add(project)
    await db_session.flush()

    g1 = Group(
        project_id=project.id,
        name="G1 立项",
        description="上游群",
        status="active",
        order_index=1,
    )
    g2 = Group(
        project_id=project.id,
        name="G5 细纲",
        description="下游群",
        status="pending",
        order_index=5,
    )
    db_session.add_all([g1, g2])
    await db_session.flush()

    return {
        "project_id": project.id,
        "g1_id": g1.id,
        "g2_id": g2.id,
    }


# ── Mock ChatService ──────────────────────────────────────


class MockChatService:
    """记录 send_message_stream 调用, 不启动真实 agent session."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def send_message_stream(
        self,
        group_id: str,
        user_content: str,
        target_agent_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append({
            "group_id": group_id,
            "user_content": user_content,
            "target_agent_id": target_agent_id,
        })
        return {
            "chain_id": "mock-chain-id",
            "message_id": "mock-message-id",
        }


# ── 端到端测试 ────────────────────────────────────────────


class TestSubscriptionE2E:
    """端到端: 事件 → 匹配 → 触发 → 注入消息"""

    @pytest_asyncio.fixture
    async def setup_data(self):
        """创建 project + groups + subscription, 返回 (ids, mock_chat, trigger)"""
        async with TestSessionLocal() as session:
            ids = await _create_project_and_groups(session)

            # 创建订阅: G2 订阅 G1 的 group_status_changed (filter: new_status=completed)
            service = SubscriptionService(session)
            await service.create_subscription(
                project_id=ids["project_id"],
                config={
                    "subscriber_type": "group",
                    "subscriber_id": ids["g2_id"],
                    "event_type": "group_status_changed",
                    "filter": {
                        "group_id": ids["g1_id"],
                        "new_status": "completed",
                    },
                    "message_template": (
                        "上游群 {group_id} 已 {new_status}, 请基于其产出开始你的工作"
                    ),
                    "one_shot": False,
                },
            )
            await session.commit()

        # mock chat service + dispatcher + trigger
        mock_chat = MockChatService()
        dispatcher = SubscriberDispatcher(chat_service=mock_chat)
        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=dispatcher,
        )
        return ids, mock_chat, trigger

    @pytest.mark.asyncio
    async def test_e2e_event_triggers_message_injection(self, setup_data):
        """完整链路: G1 完成事件 → G2 收到注入消息"""
        ids, mock_chat, trigger = setup_data

        # 发布事件: G1 状态变为 completed
        count = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g1_id"],
                "new_status": "completed",
                "old_status": "active",
                "name": "G1 立项",
            },
        )

        # 应该触发 1 个订阅
        assert count == 1, f"expected 1 trigger, got {count}"

        # mock chat_service 应该被调用, 注入消息到 G2
        assert len(mock_chat.calls) == 1, (
            f"expected 1 chat_service call, got {len(mock_chat.calls)}"
        )
        call = mock_chat.calls[0]
        assert call["group_id"] == ids["g2_id"], (
            f"message should be injected to G2, got group_id={call['group_id']}"
        )
        # 消息模板应该被渲染
        msg = call["user_content"]
        assert "completed" in msg, f"rendered message should contain new_status, got: {msg}"
        assert "请基于其产出开始你的工作" in msg
        # {group_id} 占位符应被替换为 G1 的实际 ID
        assert ids["g1_id"] in msg or "{group_id}" not in msg, (
            f"group_id placeholder should be rendered, got: {msg}"
        )

    @pytest.mark.asyncio
    async def test_e2e_filter_mismatch_no_trigger(self, setup_data):
        """filter 不匹配时不触发 (new_status 不是 completed)"""
        ids, mock_chat, trigger = setup_data

        count = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g1_id"],
                "new_status": "active",  # 不匹配 filter (要 completed)
            },
        )
        assert count == 0
        assert len(mock_chat.calls) == 0

    @pytest.mark.asyncio
    async def test_e2e_wrong_group_no_trigger(self, setup_data):
        """事件来源群不匹配时不触发 (不是 G1 的事件)"""
        ids, mock_chat, trigger = setup_data

        count = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": "some-other-group-id",  # 不是 G1
                "new_status": "completed",
            },
        )
        assert count == 0
        assert len(mock_chat.calls) == 0

    @pytest.mark.asyncio
    async def test_e2e_persistent_subscription_multiple_triggers(self, setup_data):
        """持续订阅可多次触发 (one_shot=False)"""
        ids, mock_chat, trigger = setup_data

        # 第一次触发
        count1 = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g1_id"],
                "new_status": "completed",
            },
        )
        assert count1 == 1

        # 第二次触发 (持续订阅应仍可触发)
        count2 = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g1_id"],
                "new_status": "completed",
            },
        )
        assert count2 == 1, "persistent subscription should trigger again"

        # mock chat 应被调用 2 次
        assert len(mock_chat.calls) == 2


class TestSubscriptionOneShotE2E:
    """一次性订阅端到端"""

    @pytest_asyncio.fixture
    async def setup_one_shot(self):
        """创建 one_shot 订阅"""
        async with TestSessionLocal() as session:
            ids = await _create_project_and_groups(session)

            service = SubscriptionService(session)
            await service.create_subscription(
                project_id=ids["project_id"],
                config={
                    "subscriber_type": "group",
                    "subscriber_id": ids["g2_id"],
                    "event_type": "group_status_changed",
                    "filter": {
                        "group_id": ids["g1_id"],
                        "new_status": "completed",
                    },
                    "message_template": "一次性触发: {group_id} -> {new_status}",
                    "one_shot": True,  # 一次性
                },
            )
            await session.commit()

        mock_chat = MockChatService()
        dispatcher = SubscriberDispatcher(chat_service=mock_chat)
        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=dispatcher,
        )
        return ids, mock_chat, trigger

    @pytest.mark.asyncio
    async def test_one_shot_triggers_once_then_disables(self, setup_one_shot):
        """一次性订阅: 第一次触发成功, 第二次因 disabled 不触发"""
        ids, mock_chat, trigger = setup_one_shot

        # 第一次: 应该触发
        count1 = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g1_id"],
                "new_status": "completed",
            },
        )
        assert count1 == 1
        assert len(mock_chat.calls) == 1
        assert "一次性触发" in mock_chat.calls[0]["user_content"]

        # 第二次: 应该不触发 (one_shot 已禁用)
        count2 = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g1_id"],
                "new_status": "completed",
            },
        )
        assert count2 == 0, "one_shot subscription should not trigger again"
        assert len(mock_chat.calls) == 1, "no new chat_service call expected"


class TestSubscriptionMultiSubscriberE2E:
    """多订阅者端到端: 一个事件触发多个订阅"""

    @pytest_asyncio.fixture
    async def setup_multi(self):
        """创建 3 个下游群, 都订阅 G1 完成事件"""
        async with TestSessionLocal() as session:
            project = Project(name="Multi Sub Project", status="active")
            session.add(project)
            await session.flush()

            g_up = Group(
                project_id=project.id,
                name="上游",
                status="active",
                order_index=1,
            )
            g_down_1 = Group(
                project_id=project.id,
                name="下游1",
                status="pending",
                order_index=2,
            )
            g_down_2 = Group(
                project_id=project.id,
                name="下游2",
                status="pending",
                order_index=3,
            )
            g_down_3 = Group(
                project_id=project.id,
                name="下游3",
                status="pending",
                order_index=4,
            )
            session.add_all([g_up, g_down_1, g_down_2, g_down_3])
            await session.flush()

            ids = {
                "project_id": project.id,
                "g_up": g_up.id,
                "g_down_1": g_down_1.id,
                "g_down_2": g_down_2.id,
                "g_down_3": g_down_3.id,
            }

            # 3 个下游群都订阅 g_up 完成事件
            service = SubscriptionService(session)
            for g_id in [g_down_1.id, g_down_2.id, g_down_3.id]:
                await service.create_subscription(
                    project_id=project.id,
                    config={
                        "subscriber_type": "group",
                        "subscriber_id": g_id,
                        "event_type": "group_status_changed",
                        "filter": {
                            "group_id": g_up.id,
                            "new_status": "completed",
                        },
                        "message_template": f"下游 {g_id[:8]} 收到通知",
                    },
                )
            await session.commit()

        mock_chat = MockChatService()
        dispatcher = SubscriberDispatcher(chat_service=mock_chat)
        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=dispatcher,
        )
        return ids, mock_chat, trigger

    @pytest.mark.asyncio
    async def test_multi_subscriber_all_triggered(self, setup_multi):
        """一个事件触发 3 个订阅, 各自注入到对应群"""
        ids, mock_chat, trigger = setup_multi

        count = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g_up"],
                "new_status": "completed",
            },
        )
        assert count == 3, f"expected 3 triggers, got {count}"
        assert len(mock_chat.calls) == 3

        # 验证 3 个下游群都收到了消息
        triggered_groups = {call["group_id"] for call in mock_chat.calls}
        assert triggered_groups == {ids["g_down_1"], ids["g_down_2"], ids["g_down_3"]}, (
            f"all 3 downstream groups should be triggered, got: {triggered_groups}"
        )


class TestSubscriptionAgentSubscriberE2E:
    """agent 订阅者端到端 (subscriber_type=agent)"""

    @pytest_asyncio.fixture
    async def setup_agent_sub(self):
        """创建 agent 订阅者 (需要 ProjectAgent + GroupMember)"""
        from app.models.agent import Agent, ProjectAgent
        from app.models.group import GroupMember

        async with TestSessionLocal() as session:
            project = Project(name="Agent Sub Project", status="active")
            session.add(project)
            await session.flush()

            g_up = Group(
                project_id=project.id,
                name="上游",
                status="active",
                order_index=1,
            )
            g_down = Group(
                project_id=project.id,
                name="下游",
                status="pending",
                order_index=2,
            )
            session.add_all([g_up, g_down])
            await session.flush()

            # 创建 agent + ProjectAgent + GroupMember
            agent = Agent(
                name="测试 Agent",
                system_prompt="you are a test agent",
            )
            session.add(agent)
            await session.flush()

            pa = ProjectAgent(
                project_id=project.id,
                agent_id=agent.id,
                override_config={},
            )
            session.add(pa)
            await session.flush()

            gm = GroupMember(
                group_id=g_down.id,
                project_agent_id=pa.id,
                role="member",
            )
            session.add(gm)
            await session.flush()

            ids = {
                "project_id": project.id,
                "g_up_id": g_up.id,
                "g_down_id": g_down.id,
                "agent_id": agent.id,
                "pa_id": pa.id,
            }

            # agent 订阅 g_up 完成事件
            service = SubscriptionService(session)
            await service.create_subscription(
                project_id=project.id,
                config={
                    "subscriber_type": "agent",
                    "subscriber_id": pa.id,  # ProjectAgent ID
                    "event_type": "group_status_changed",
                    "filter": {
                        "group_id": g_up.id,
                        "new_status": "completed",
                    },
                    "message_template": "agent 通知: 上游 {group_id} 完成",
                },
            )
            await session.commit()

        mock_chat = MockChatService()
        dispatcher = SubscriberDispatcher(chat_service=mock_chat)
        trigger = SubscriptionTrigger(
            session_factory=TestSessionLocal,
            dispatcher=dispatcher,
        )
        return ids, mock_chat, trigger

    @pytest.mark.asyncio
    async def test_agent_subscriber_triggered(self, setup_agent_sub):
        """agent 订阅者: 事件触发后注入到 agent 所在群, 带 target_agent_id"""
        ids, mock_chat, trigger = setup_agent_sub

        count = await trigger.on_event(
            "group_status_changed",
            {
                "project_id": ids["project_id"],
                "group_id": ids["g_up_id"],
                "new_status": "completed",
            },
        )
        assert count == 1
        assert len(mock_chat.calls) == 1

        call = mock_chat.calls[0]
        # 消息应该注入到 agent 所在的群 (g_down)
        assert call["group_id"] == ids["g_down_id"]
        # target_agent_id 应该是订阅的 agent
        assert call["target_agent_id"] == ids["pa_id"]
        # 消息模板应渲染
        assert "上游" in call["user_content"]
        assert "完成" in call["user_content"]
