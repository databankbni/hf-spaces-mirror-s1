"""
订阅机制 v1 - DB 持久化 processor 测试

测试范围:
1. 3 个新 processor (CreateSubscription / DeleteSubscription / QuerySubscriptions)
   通过 create_builtin_processor 工厂正确实例化
2. Schema 结构校验 (function name / parameters / required / enum)
3. 必填参数缺失时 _check_required_args 返回 error packet
4. 正常调用时 processor 正确桥接到 adapter 方法 (mock safe_run_async 捕获 coro)
5. 与旧的内存版 processor (SubscribeEvent / UnsubscribeEvent / ListSubscriptions) 不冲突

设计说明:
- safe_run_async 在子线程中调度协程到主循环, 在测试中直接调用会死锁.
  因此本测试通过 mock safe_run_async 捕获 coroutine, 不实际运行它.
  Coroutine 内部就是 `self._adapter.method(**kwargs)`, 我们用 inspect 验证.
- adapter 方法的实际行为由 server/tests/test_subscription_integration.py 覆盖.
"""
from __future__ import annotations

import asyncio
import inspect
import types
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from agentflow.builtin_processors import create_builtin_processor
from agentflow.crud_processors import (
    CreateSubscriptionProcessor,
    DeleteSubscriptionProcessor,
    QuerySubscriptionsProcessor,
    SubscribeEventProcessor,  # 旧版内存
    UnsubscribeEventProcessor,  # 旧版内存
    ListSubscriptionsProcessor,  # 旧版内存
)
from agentflow.packet import InfoPacket, PacketType
from agentflow.specs import BuiltinProcessorConfig


# ── Mock Adapter ──────────────────────────────────────────


class MockAdapter:
    """记录所有调用的 mock adapter (方法签名与 ServerToolAdapter 对齐).

    使用显式参数而非 **kwargs, 这样 coroutine.cr_frame.f_locals 里的参数名
    可被 _extract_coro_call 直接读取.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def create_subscription(
        self,
        subscriber_type: str,
        subscriber_id: str,
        event_type: str,
        filter: Optional[Dict[str, Any]] = None,
        action: str = "trigger_as_message",
        message_template: Optional[str] = None,
        one_shot: bool = False,
    ) -> Dict[str, Any]:
        kwargs = {
            "subscriber_type": subscriber_type,
            "subscriber_id": subscriber_id,
            "event_type": event_type,
            "filter": filter,
            "action": action,
            "message_template": message_template,
            "one_shot": one_shot,
        }
        self.calls.append({"method": "create_subscription", **kwargs})
        return {"id": "sub-1", **kwargs}

    async def delete_subscription(self, subscription_id: str) -> Dict[str, Any]:
        self.calls.append({"method": "delete_subscription", "subscription_id": subscription_id})
        return {"success": True}

    async def query_subscriptions(
        self,
        subscriber_type: Optional[str] = None,
        subscriber_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self.calls.append({
            "method": "query_subscriptions",
            "subscriber_type": subscriber_type,
            "subscriber_id": subscriber_id,
        })
        return [{"id": "sub-1", "event_type": "group_status_changed"}]

    # 旧版内存订阅 - 不应被新 processor 调用
    async def subscribe_event(
        self,
        event_type: str,
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str] = None,
        target_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.calls.append({
            "method": "subscribe_event",
            "event_type": event_type,
            "subscriber_agent_id": subscriber_agent_id,
            "project_id": project_id,
        })
        return {"success": True, "note": "legacy in-memory"}

    async def unsubscribe_event(
        self,
        event_type: str,
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.calls.append({
            "method": "unsubscribe_event",
            "event_type": event_type,
        })
        return {"success": True}

    async def list_subscriptions(self, subscriber_agent_id: str) -> List[Dict[str, Any]]:
        self.calls.append({
            "method": "list_subscriptions",
            "subscriber_agent_id": subscriber_agent_id,
        })
        return []


def _make_ws(adapter: MockAdapter) -> types.SimpleNamespace:
    fake_ws = types.SimpleNamespace()
    fake_ws.tool_adapter = adapter
    return fake_ws


def _make_packet(arguments: Dict[str, Any]) -> InfoPacket:
    """构造一个 builtin tool call packet, 模拟 LLM 发起的工具调用.

    builtin processor 通过 _extract_builtin_content(packet) 提取参数,
    该函数读取 packet.content["arguments"].
    """
    from datetime import datetime
    return InfoPacket(
        id="pkt-test-1",
        sender_id="agent-test",
        parent_id=None,
        chain_id="chain-test-1",
        content={"arguments": arguments},
        type=PacketType.CALL,
        timestamp=datetime.now(),
    )


# ── 1. 工厂注册 + 实例化 ──────────────────────────────────


class TestFactoryRegistration:
    """验证 create_builtin_processor 能正确实例化新 processor 且不破坏旧版"""

    @pytest.fixture
    def ws(self) -> types.SimpleNamespace:
        return _make_ws(MockAdapter())

    @pytest.mark.parametrize(
        "kind,expected_cls",
        [
            ("create_subscription", CreateSubscriptionProcessor),
            ("delete_subscription", DeleteSubscriptionProcessor),
            ("query_subscriptions", QuerySubscriptionsProcessor),
            # 旧版仍然可用 - 不被覆盖
            ("subscribe_event", SubscribeEventProcessor),
            ("unsubscribe_event", UnsubscribeEventProcessor),
            ("list_subscriptions", ListSubscriptionsProcessor),
        ],
    )
    def test_factory_can_instantiate(
        self,
        ws: types.SimpleNamespace,
        kind: str,
        expected_cls: type,
    ) -> None:
        cfg = BuiltinProcessorConfig(kind=kind, name=kind)
        p = create_builtin_processor(cfg, ws)
        assert isinstance(p, expected_cls), (
            f"kind={kind} should produce {expected_cls.__name__}, got {type(p).__name__}"
        )

    def test_unknown_kind_still_raises(self, ws: types.SimpleNamespace) -> None:
        cfg = BuiltinProcessorConfig(kind="not_a_real_kind", name="x")
        with pytest.raises(ValueError, match="Unsupported builtin processor kind"):
            create_builtin_processor(cfg, ws)


# ── 2. Schema 校验 ────────────────────────────────────────


class TestSchema:
    """验证 schema 结构 (function name / required / enum)"""

    @pytest.fixture
    def create_proc(self) -> CreateSubscriptionProcessor:
        return CreateSubscriptionProcessor(adapter=MockAdapter())

    @pytest.fixture
    def delete_proc(self) -> DeleteSubscriptionProcessor:
        return DeleteSubscriptionProcessor(adapter=MockAdapter())

    @pytest.fixture
    def query_proc(self) -> QuerySubscriptionsProcessor:
        return QuerySubscriptionsProcessor(adapter=MockAdapter())

    def test_create_schema_structure(self, create_proc: CreateSubscriptionProcessor) -> None:
        schema = create_proc.get_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "create_subscription"
        assert "description" in fn and fn["description"]

        params = fn["parameters"]
        assert params["type"] == "object"
        props = params["properties"]

        # 必填字段
        assert set(params["required"]) == {"subscriber_type", "subscriber_id", "event_type"}

        # 关键字段存在
        for field in (
            "subscriber_type",
            "subscriber_id",
            "event_type",
            "filter",
            "action",
            "message_template",
            "one_shot",
        ):
            assert field in props, f"create_subscription schema missing field: {field}"

        # enum 校验
        assert props["subscriber_type"].get("enum") == ["group", "agent"]
        assert props["action"].get("enum") == [
            "trigger_as_message",
            "trigger_as_notification",
            "trigger_as_task",
        ]
        assert set(props["event_type"].get("enum", [])) == {
            "group_status_changed",
            "task_status_changed",
            "resource_created",
            "resource_updated",
        }

    def test_delete_schema_structure(self, delete_proc: DeleteSubscriptionProcessor) -> None:
        schema = delete_proc.get_schema()
        fn = schema["function"]
        assert fn["name"] == "delete_subscription"
        assert set(fn["parameters"]["required"]) == {"subscription_id"}
        assert "subscription_id" in fn["parameters"]["properties"]

    def test_query_schema_structure(self, query_proc: QuerySubscriptionsProcessor) -> None:
        schema = query_proc.get_schema()
        fn = schema["function"]
        assert fn["name"] == "query_subscriptions"
        assert set(fn["parameters"]["required"]) == {"subscriber_type", "subscriber_id"}
        assert (
            fn["parameters"]["properties"]["subscriber_type"].get("enum")
            == ["group", "agent"]
        )

    def test_legacy_schemas_not_broken(self) -> None:
        """旧版内存订阅 processor 的 schema 不应被新版破坏."""
        sub = SubscribeEventProcessor(adapter=MockAdapter())
        unsub = UnsubscribeEventProcessor(adapter=MockAdapter())
        list_proc = ListSubscriptionsProcessor(adapter=MockAdapter())

        # 旧版 subscribe_event schema 仍要求 event_type+project_id
        s = sub.get_schema()
        assert s["function"]["name"] == "subscribe_event"
        assert set(s["function"]["parameters"]["required"]) == {"event_type", "project_id"}

        u = unsub.get_schema()
        assert u["function"]["name"] == "unsubscribe_event"
        assert set(u["function"]["parameters"]["required"]) == {"event_type", "project_id"}

        l = list_proc.get_schema()
        assert l["function"]["name"] == "list_subscriptions"
        assert set(l["function"]["parameters"]["required"]) == {"subscriber_agent_id"}


# ── 3. 必填参数校验 ──────────────────────────────────────


class TestRequiredArgsValidation:
    """验证 _check_required_args 在缺失必填参数时返回 error packet"""

    def test_create_missing_subscriber_id_returns_error(self) -> None:
        proc = CreateSubscriptionProcessor(adapter=MockAdapter())
        # 缺 subscriber_id 和 event_type
        packet = _make_packet({"subscriber_type": "group"})
        result = proc._check_required_args(packet)
        assert result is not None, "missing required args should return error packet"
        assert "error" in result.content
        assert "subscriber_id" in result.content["error"] or "event_type" in result.content["error"]

    def test_create_missing_event_type_returns_error(self) -> None:
        proc = CreateSubscriptionProcessor(adapter=MockAdapter())
        packet = _make_packet({
            "subscriber_type": "group",
            "subscriber_id": "g-1",
        })
        result = proc._check_required_args(packet)
        assert result is not None
        assert "event_type" in result.content["error"]

    def test_create_with_all_required_passes(self) -> None:
        proc = CreateSubscriptionProcessor(adapter=MockAdapter())
        packet = _make_packet({
            "subscriber_type": "group",
            "subscriber_id": "g-1",
            "event_type": "group_status_changed",
        })
        result = proc._check_required_args(packet)
        assert result is None, "all required args present should return None (no error)"

    def test_delete_missing_subscription_id_returns_error(self) -> None:
        proc = DeleteSubscriptionProcessor(adapter=MockAdapter())
        packet = _make_packet({})  # 缺 subscription_id
        result = proc._check_required_args(packet)
        assert result is not None
        assert "subscription_id" in result.content["error"]

    def test_query_missing_subscriber_id_returns_error(self) -> None:
        proc = QuerySubscriptionsProcessor(adapter=MockAdapter())
        packet = _make_packet({"subscriber_type": "group"})  # 缺 subscriber_id
        result = proc._check_required_args(packet)
        assert result is not None
        assert "subscriber_id" in result.content["error"]

    def test_query_missing_subscriber_type_returns_error(self) -> None:
        proc = QuerySubscriptionsProcessor(adapter=MockAdapter())
        packet = _make_packet({"subscriber_id": "g-1"})  # 缺 subscriber_type
        result = proc._check_required_args(packet)
        assert result is not None
        assert "subscriber_type" in result.content["error"]


# ── 4. 桥接到 adapter 方法 (mock safe_run_async) ─────────


class TestAdapterBridging:
    """验证 processor 把 LLM 工具调用正确翻译为 adapter 方法调用.

    策略: mock crud_processors.safe_run_async, 捕获其收到的 coro,
    从 coro 上读出 cr_frame.f_locals 提取 adapter 方法和参数.
    """

    @pytest.fixture(autouse=True)
    def _patch_safe_run_async(self, monkeypatch):
        """替换 crud_processors.safe_run_async, 捕获 coro 而不实际运行."""
        captured: List[Any] = []

        def fake_safe_run_async(packet, coro, timeout=None, context=""):
            captured.append({
                "packet": packet,
                "coro": coro,
                "timeout": timeout,
                "context": context,
            })
            # 返回一个简单 InfoPacket 模拟 success_packet
            return packet.create_child(
                sender_id="tool",
                content={"captured": True},
                packet_type=PacketType.RESPONSE,
            )

        # patch 在 crud_processors 模块作用域
        from agentflow import crud_processors as crud_mod
        monkeypatch.setattr(crud_mod, "safe_run_async", fake_safe_run_async)
        self._captured = captured

    @staticmethod
    def _extract_coro_call(coro) -> Dict[str, Any]:
        """从 coroutine 对象的 frame locals 提取 adapter 方法名和调用参数.

        coroutine.cr_frame.f_locals 包含:
          - self: processor 实例
          - 调用 adapter.method(**kwargs) 时的 self._adapter, kwargs 等
        """
        # coro 可能是 self._adapter.create_subscription(...) 协程
        # 它的 cr_frame 是 method 的 frame
        frame = coro.cr_frame
        local_vars = frame.f_locals.copy()
        # 提取方法名
        co_name = coro.cr_code.co_name
        # 提取除 self 外的参数
        kwargs = {k: v for k, v in local_vars.items() if k not in ("self", "__class__")}
        return {
            "method_name": co_name,
            "kwargs": kwargs,
        }

    def test_create_calls_adapter_create_subscription(self) -> None:
        adapter = MockAdapter()
        proc = CreateSubscriptionProcessor(adapter=adapter)
        packet = _make_packet({
            "subscriber_type": "group",
            "subscriber_id": "g-abc",
            "event_type": "group_status_changed",
            "filter": {"group_id": "g-upstream", "new_status": "completed"},
            "action": "trigger_as_message",
            "message_template": "上游完成, 开始你的工作",
            "one_shot": True,
        })
        proc.core_process(packet)

        # 应该捕获到 1 个 coro 调用
        assert len(self._captured) == 1
        cap = self._captured[0]
        assert cap["context"] == "create_subscription"

        call = self._extract_coro_call(cap["coro"])
        assert call["method_name"] == "create_subscription"
        assert call["kwargs"]["subscriber_type"] == "group"
        assert call["kwargs"]["subscriber_id"] == "g-abc"
        assert call["kwargs"]["event_type"] == "group_status_changed"
        assert call["kwargs"]["filter"] == {
            "group_id": "g-upstream",
            "new_status": "completed",
        }
        assert call["kwargs"]["action"] == "trigger_as_message"
        assert call["kwargs"]["message_template"] == "上游完成, 开始你的工作"
        assert call["kwargs"]["one_shot"] is True

    def test_create_with_defaults(self) -> None:
        """LLM 只传必填参数时, 可选参数应使用 schema 描述的默认值."""
        adapter = MockAdapter()
        proc = CreateSubscriptionProcessor(adapter=adapter)
        packet = _make_packet({
            "subscriber_type": "agent",
            "subscriber_id": "a-1",
            "event_type": "resource_created",
        })
        proc.core_process(packet)

        assert len(self._captured) == 1
        call = self._extract_coro_call(self._captured[0]["coro"])
        # 默认 action / one_shot (从 processor 的 core_process 看, 用 args.get(..., default))
        assert call["kwargs"]["action"] == "trigger_as_message"
        assert call["kwargs"]["one_shot"] is False
        assert call["kwargs"]["filter"] is None
        assert call["kwargs"]["message_template"] is None

    def test_delete_calls_adapter_delete_subscription(self) -> None:
        adapter = MockAdapter()
        proc = DeleteSubscriptionProcessor(adapter=adapter)
        packet = _make_packet({"subscription_id": "sub-xyz"})
        proc.core_process(packet)

        assert len(self._captured) == 1
        cap = self._captured[0]
        assert cap["context"] == "delete_subscription"
        call = self._extract_coro_call(cap["coro"])
        assert call["method_name"] == "delete_subscription"
        assert call["kwargs"]["subscription_id"] == "sub-xyz"

    def test_query_calls_adapter_query_subscriptions(self) -> None:
        adapter = MockAdapter()
        proc = QuerySubscriptionsProcessor(adapter=adapter)
        packet = _make_packet({
            "subscriber_type": "group",
            "subscriber_id": "g-1",
        })
        proc.core_process(packet)

        assert len(self._captured) == 1
        cap = self._captured[0]
        assert cap["context"] == "query_subscriptions"
        call = self._extract_coro_call(cap["coro"])
        assert call["method_name"] == "query_subscriptions"
        assert call["kwargs"]["subscriber_type"] == "group"
        assert call["kwargs"]["subscriber_id"] == "g-1"

    def test_new_processors_do_not_call_legacy_methods(self) -> None:
        """关键回归: 新版 processor 不应调用旧版内存 subscribe_event 方法."""
        adapter = MockAdapter()
        # 全部走一遍新 processor
        for proc_cls, args in [
            (CreateSubscriptionProcessor, {
                "subscriber_type": "group",
                "subscriber_id": "g-1",
                "event_type": "group_status_changed",
            }),
            (DeleteSubscriptionProcessor, {"subscription_id": "x"}),
            (QuerySubscriptionsProcessor, {
                "subscriber_type": "group",
                "subscriber_id": "g-1",
            }),
        ]:
            proc = proc_cls(adapter=adapter)
            packet = _make_packet(args)
            proc.core_process(packet)

        # 检查所有捕获的 coro, 它们调用的方法名都应该是 DB 版
        legacy_method_names = {"subscribe_event", "unsubscribe_event", "list_subscriptions"}
        db_method_names = {"create_subscription", "delete_subscription", "query_subscriptions"}

        actual_methods = set()
        for cap in self._captured:
            call = self._extract_coro_call(cap["coro"])
            actual_methods.add(call["method_name"])

        # 不应有任何旧版方法被调用
        legacy_called = actual_methods & legacy_method_names
        assert not legacy_called, (
            f"new DB processors should NOT call legacy in-memory methods, "
            f"but got: {legacy_called}"
        )
        # 应该只看到 DB 方法
        assert actual_methods.issubset(db_method_names), (
            f"unexpected methods called: {actual_methods - db_method_names}"
        )
        assert actual_methods == db_method_names, (
            f"expected all 3 DB methods to be called, got: {actual_methods}"
        )
