"""
订阅引擎

核心职责:
1. filter 递归比较 — 判断事件是否匹配订阅的过滤条件
2. 消息模板渲染 — 把 event payload 渲染成消息内容
3. 触发执行 — 按 action 类型分派（trigger_as_message/task/notification）

不直接处理 DB CRUD（由 SubscriptionRepository 负责），不直接发布事件（由 event_bus 负责）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── 1. filter 递归比较 ──────────────────────────────────────────


def match_filter(filter_spec: Optional[Dict[str, Any]], event_payload: Dict[str, Any]) -> bool:
    """判断事件 payload 是否匹配订阅的 filter。

    匹配规则:
    - filter 为 None 或空 dict → 匹配所有事件
    - filter 字段值 == event_payload 对应字段值 → 该字段匹配
    - 嵌套 dict → 递归比较
    - list → 长度和顺序都相同（严格匹配）；event 中对应值若为 list 则元素集合相等
    - filter 中存在但 event 中缺失的字段 → 不匹配
    - filter 中不存在但 event 中存在的字段 → 忽略（不影响匹配）

    Args:
        filter_spec: 订阅配置的 filter 字段（JSON object）
        event_payload: 事件 payload（dict）

    Returns:
        bool: 是否匹配
    """
    if not filter_spec:
        return True

    if not isinstance(filter_spec, dict):
        # filter 不是 dict 视为匹配（容错）
        logger.warning(
            "[match_filter] filter is not a dict, treating as match-all: %s",
            type(filter_spec).__name__,
        )
        return True

    return _match_dict(filter_spec, event_payload)


def _match_dict(filter_dict: Dict[str, Any], event_dict: Dict[str, Any]) -> bool:
    """递归比较两个 dict。filter_dict 的所有键值对都必须在 event_dict 中找到匹配。"""
    for key, filter_value in filter_dict.items():
        if key not in event_dict:
            return False
        event_value = event_dict[key]
        if not _match_value(filter_value, event_value):
            return False
    return True


def _match_value(filter_value: Any, event_value: Any) -> bool:
    """递归比较单个值。"""
    # 类型不同直接不匹配（除了 dict/list 自己处理）
    if isinstance(filter_value, dict):
        if not isinstance(event_value, dict):
            return False
        return _match_dict(filter_value, event_value)
    if isinstance(filter_value, list):
        if not isinstance(event_value, list):
            return False
        return _match_list(filter_value, event_value)
    # 标量比较
    return filter_value == event_value


def _match_list(filter_list: list, event_list: list) -> bool:
    """list 匹配: 长度相同 + 每个元素递归匹配（按位置）。"""
    if len(filter_list) != len(event_list):
        return False
    for f, e in zip(filter_list, event_list):
        if not _match_value(f, e):
            return False
    return True


# ── 2. 消息模板渲染 ──────────────────────────────────────────


# 匹配 {field} 或 {a.b.c} 形式的占位符
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def render_template(template: Optional[str], event_payload: Dict[str, Any]) -> str:
    """渲染消息模板。

    支持:
    - {field} → event_payload[field]
    - {a.b.c} → event_payload[a][b][c]（嵌套字段访问）
    - 缺失字段 → 保留原占位符（不抛错，便于调试）
    - template 为 None 或空 → 返回默认消息

    Args:
        template: 消息模板字符串
        event_payload: 事件 payload

    Returns:
        str: 渲染后的消息
    """
    if not template:
        return _default_message(event_payload)

    def _replace(match: re.Match) -> str:
        path = match.group(1)
        value = _get_nested(event_payload, path)
        if value is None:
            # 缺失字段保留原占位符
            return match.group(0)
        return str(value)

    return _PLACEHOLDER_RE.sub(_replace, template)


def _get_nested(data: Dict[str, Any], path: str) -> Any:
    """按 a.b.c 路径取嵌套字段。"""
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _default_message(event_payload: Dict[str, Any]) -> str:
    """没有模板时的默认消息。"""
    event_type = event_payload.get("event_type", "event")
    project_id = event_payload.get("project_id", "")
    group_id = event_payload.get("group_id", "")
    parts = [f"[事件触发] {event_type}"]
    if project_id:
        parts.append(f"project={project_id[:8]}")
    if group_id:
        parts.append(f"group={group_id[:8]}")
    return " ".join(parts)


# ── 3. 触发动作类型 ─────────────────────────────────────────


TRIGGER_AS_MESSAGE = "trigger_as_message"
TRIGGER_AS_TASK = "trigger_as_task"
TRIGGER_AS_NOTIFICATION = "trigger_as_notification"

VALID_ACTIONS = {
    TRIGGER_AS_MESSAGE,
    TRIGGER_AS_TASK,
    TRIGGER_AS_NOTIFICATION,
}

VALID_SUBSCRIBER_TYPES = {"group", "agent"}

VALID_EVENT_TYPES = {
    "task_status_changed",
    "resource_created",
    "resource_updated",
    "group_status_changed",
}


def validate_subscription_config(config: Dict[str, Any]) -> Optional[str]:
    """校验订阅配置，返回错误消息（None 表示通过）。

    用于:
    - 创建订阅时校验
    - 工具调用时校验
    """
    subscriber_type = config.get("subscriber_type")
    if subscriber_type not in VALID_SUBSCRIBER_TYPES:
        return f"subscriber_type must be one of {VALID_SUBSCRIBER_TYPES}, got: {subscriber_type}"

    subscriber_id = config.get("subscriber_id")
    if not subscriber_id:
        return "subscriber_id is required"

    event_type = config.get("event_type")
    if event_type not in VALID_EVENT_TYPES:
        return (
            f"event_type must be one of {VALID_EVENT_TYPES}, got: {event_type}"
        )

    action = config.get("action", TRIGGER_AS_MESSAGE)
    if action not in VALID_ACTIONS:
        return f"action must be one of {VALID_ACTIONS}, got: {action}"

    filter_spec = config.get("filter")
    if filter_spec is not None and not isinstance(filter_spec, dict):
        return "filter must be a JSON object or null"

    message_template = config.get("message_template")
    if message_template is not None and not isinstance(message_template, str):
        return "message_template must be a string or null"

    if message_template and len(message_template) > 2000:
        return "message_template must be <= 2000 chars"

    return None
