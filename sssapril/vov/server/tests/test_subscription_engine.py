"""
订阅引擎单元测试

覆盖:
- filter 递归比较（match_filter）
- 消息模板渲染（render_template）
- 配置校验（validate_subscription_config）
"""
import pytest

from app.services.subscription_engine import (
    match_filter,
    render_template,
    validate_subscription_config,
    TRIGGER_AS_MESSAGE,
)


# ── match_filter ─────────────────────────────────────────


class TestMatchFilter:
    """filter 递归比较测试"""

    def test_empty_filter_matches_all(self):
        """空 filter 匹配所有事件"""
        assert match_filter(None, {"a": 1}) is True
        assert match_filter({}, {"a": 1}) is True

    def test_filter_not_dict_treated_as_match_all(self):
        """filter 不是 dict 时容错为匹配所有"""
        assert match_filter("not a dict", {"a": 1}) is True
        assert match_filter([1, 2], {"a": 1}) is True

    def test_single_field_match(self):
        """单字段匹配"""
        assert match_filter({"group_id": "G1"}, {"group_id": "G1"}) is True

    def test_single_field_no_match(self):
        """单字段不匹配"""
        assert match_filter({"group_id": "G1"}, {"group_id": "G2"}) is False

    def test_multiple_fields_all_match(self):
        """多字段全部匹配"""
        flt = {"group_id": "G1", "new_status": "completed"}
        event = {"group_id": "G1", "new_status": "completed", "extra": "ignored"}
        assert match_filter(flt, event) is True

    def test_multiple_fields_partial_match(self):
        """多字段部分匹配 → 不匹配"""
        flt = {"group_id": "G1", "new_status": "completed"}
        event = {"group_id": "G1", "new_status": "active"}
        assert match_filter(flt, event) is False

    def test_field_in_filter_but_missing_in_event(self):
        """filter 字段在 event 中不存在 → 不匹配"""
        assert match_filter({"missing_field": "x"}, {"group_id": "G1"}) is False

    def test_field_in_event_but_missing_in_filter(self):
        """filter 字段不存在但 event 有该字段 → 忽略，匹配"""
        assert match_filter({"group_id": "G1"}, {"group_id": "G1", "extra": "ignored"}) is True

    def test_nested_dict_match(self):
        """嵌套 dict 匹配"""
        flt = {"payload": {"title": "大纲"}}
        event = {"payload": {"title": "大纲", "id": "xxx"}}
        assert match_filter(flt, event) is True

    def test_nested_dict_partial_match(self):
        """嵌套 dict 部分字段不匹配"""
        flt = {"payload": {"title": "大纲"}}
        event = {"payload": {"title": "细纲", "id": "xxx"}}
        assert match_filter(flt, event) is False

    def test_nested_dict_missing_in_event(self):
        """嵌套字段在 event 中缺失 → 不匹配"""
        flt = {"payload": {"title": "x"}}
        event = {"group_id": "G1"}  # 没 payload
        assert match_filter(flt, event) is False

    def test_deeply_nested_match(self):
        """多层嵌套匹配"""
        flt = {"data": {"user": {"name": "Alice"}}}
        event = {"data": {"user": {"name": "Alice", "age": 30}, "other": 1}}
        assert match_filter(flt, event) is True

    def test_list_match_same_length(self):
        """list 长度相同且元素匹配"""
        flt = {"tags": ["a", "b"]}
        event = {"tags": ["a", "b"]}
        assert match_filter(flt, event) is True

    def test_list_match_different_length(self):
        """list 长度不同 → 不匹配"""
        flt = {"tags": ["a", "b"]}
        event = {"tags": ["a"]}
        assert match_filter(flt, event) is False

    def test_list_match_different_order(self):
        """list 元素相同但顺序不同 → 不匹配（严格匹配）"""
        flt = {"tags": ["a", "b"]}
        event = {"tags": ["b", "a"]}
        assert match_filter(flt, event) is False

    def test_type_mismatch_dict_vs_scalar(self):
        """filter 是 dict, event 是 scalar → 不匹配"""
        flt = {"payload": {"title": "x"}}
        event = {"payload": "scalar"}
        assert match_filter(flt, event) is False

    def test_type_mismatch_list_vs_scalar(self):
        """filter 是 list, event 是 scalar → 不匹配"""
        flt = {"tags": ["a"]}
        event = {"tags": "a"}
        assert match_filter(flt, event) is False

    def test_real_group_status_changed_scenario(self):
        """实际场景: 群状态变化订阅"""
        flt = {"group_id": "G4", "new_status": "completed"}
        event = {
            "project_id": "P1",
            "group_id": "G4",
            "new_status": "completed",
            "old_status": "active",
        }
        assert match_filter(flt, event) is True

    def test_real_resource_created_scenario(self):
        """实际场景: 资源创建订阅"""
        flt = {"resource_type": "outline"}
        event = {
            "project_id": "P1",
            "resource_id": "R1",
            "resource_type": "outline",
            "title": "主线大纲",
        }
        assert match_filter(flt, event) is True


# ── render_template ─────────────────────────────────────────


class TestRenderTemplate:
    """消息模板渲染测试"""

    def test_no_template_returns_default(self):
        """无模板返回默认消息"""
        event = {"event_type": "group_status_changed", "project_id": "P1"}
        msg = render_template(None, event)
        assert "group_status_changed" in msg
        assert "P1" in msg  # 截断到 8 字符

    def test_empty_template_returns_default(self):
        """空模板返回默认消息"""
        event = {"event_type": "group_status_changed"}
        msg = render_template("", event)
        assert "group_status_changed" in msg

    def test_single_field(self):
        """单字段占位符"""
        event = {"group_id": "G4", "new_status": "completed"}
        msg = render_template("G{group_id} 已 {new_status}", event)
        assert msg == "GG4 已 completed"

    def test_multiple_fields(self):
        """多字段占位符"""
        event = {"group_id": "G4", "new_status": "completed"}
        msg = render_template(
            "群 {group_id} 状态变为 {new_status}", event
        )
        assert msg == "群 G4 状态变为 completed"

    def test_nested_field(self):
        """嵌套字段占位符"""
        event = {"payload": {"title": "大纲"}}
        msg = render_template("资源: {payload.title}", event)
        assert msg == "资源: 大纲"

    def test_deeply_nested_field(self):
        """多层嵌套字段"""
        event = {"data": {"user": {"name": "Alice"}}}
        msg = render_template("用户: {data.user.name}", event)
        assert msg == "用户: Alice"

    def test_missing_field_preserved(self):
        """缺失字段保留原占位符"""
        event = {"group_id": "G4"}
        msg = render_template("{group_id} {missing_field}", event)
        assert msg == "G4 {missing_field}"

    def test_missing_nested_field_preserved(self):
        """缺失嵌套字段保留原占位符"""
        event = {"payload": {}}
        msg = render_template("{payload.title}", event)
        assert msg == "{payload.title}"

    def test_no_placeholders(self):
        """无占位符的模板原样返回"""
        event = {"group_id": "G4"}
        msg = render_template("固定消息文本", event)
        assert msg == "固定消息文本"

    def test_chinese_template(self):
        """中文模板"""
        event = {
            "group_id": "G4",
            "new_status": "completed",
        }
        msg = render_template(
            "上一环节（{group_id}）已 {new_status}，请基于其产出开始你的工作",
            event,
        )
        assert "上一环节（G4）已 completed" in msg
        assert "请基于其产出开始你的工作" in msg


# ── validate_subscription_config ─────────────────────────────────


class TestValidateSubscriptionConfig:
    """配置校验测试"""

    def test_valid_config(self):
        """有效配置"""
        config = {
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
            "action": "trigger_as_message",
            "filter": {"group_id": "G2"},
            "message_template": "G2 已完成",
        }
        assert validate_subscription_config(config) is None

    def test_minimal_config(self):
        """最小配置（filter 和 message_template 可选）"""
        config = {
            "subscriber_type": "agent",
            "subscriber_id": "A1",
            "event_type": "resource_created",
        }
        assert validate_subscription_config(config) is None

    def test_invalid_subscriber_type(self):
        """无效 subscriber_type"""
        config = {
            "subscriber_type": "unknown",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
        }
        err = validate_subscription_config(config)
        assert err is not None
        assert "subscriber_type" in err

    def test_missing_subscriber_id(self):
        """缺少 subscriber_id"""
        config = {
            "subscriber_type": "group",
            "event_type": "group_status_changed",
        }
        err = validate_subscription_config(config)
        assert err is not None
        assert "subscriber_id" in err

    def test_invalid_event_type(self):
        """无效 event_type"""
        config = {
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "unknown_event",
        }
        err = validate_subscription_config(config)
        assert err is not None
        assert "event_type" in err

    def test_invalid_action(self):
        """无效 action"""
        config = {
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
            "action": "invalid_action",
        }
        err = validate_subscription_config(config)
        assert err is not None
        assert "action" in err

    def test_invalid_filter_type(self):
        """filter 不是 dict"""
        config = {
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
            "filter": "not a dict",
        }
        err = validate_subscription_config(config)
        assert err is not None
        assert "filter" in err

    def test_message_template_too_long(self):
        """message_template 超长"""
        config = {
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
            "message_template": "x" * 2001,
        }
        err = validate_subscription_config(config)
        assert err is not None
        assert "2000" in err

    def test_default_action_is_trigger_as_message(self):
        """不传 action 时默认 trigger_as_message"""
        config = {
            "subscriber_type": "group",
            "subscriber_id": "G1",
            "event_type": "group_status_changed",
        }
        # 默认 action 应该通过校验
        assert validate_subscription_config(config) is None
