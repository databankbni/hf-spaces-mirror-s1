"""
自主级别控制器模块

负责根据群聊的自主级别控制Agent的行为和人机交互。
"""

from typing import Optional, Dict, Any, Callable, Awaitable
from enum import Enum

from app.models.group import Group


class AutonomyLevel(str, Enum):
    """
    自主级别枚举

    控制Agent在讨论中的自主程度：
    - FULL_AUTO: 完全自主，无需人工干预
    - SEMI_AUTO: 半自主，关键节点需人工确认
    - MANUAL: 手动模式，每步都需人工确认
    """
    FULL_AUTO = "full_auto"
    SEMI_AUTO = "semi_auto"
    MANUAL = "manual"


class AutonomyController:
    """
    自主级别控制器

    根据群聊的自主级别控制：
    1. Agent是否可以自主发言
    2. 是否需要人工确认
    3. 何时暂停等待人工输入

    Example:
        controller = AutonomyController(group)

        # 检查是否可以自主发言
        if controller.can_auto_speak():
            await dispatcher.dispatch(...)

        # 检查是否需要人工确认
        if controller.needs_confirmation(action):
            await request_human_approval(...)
    """

    def __init__(self, group: Group):
        """
        初始化自主级别控制器

        Args:
            group: 群聊对象，包含autonomy_level和auto_advance配置
        """
        self.group = group
        self.level = AutonomyLevel(group.autonomy_level)
        self.auto_advance = group.auto_advance

    def can_auto_speak(self) -> bool:
        """
        检查Agent是否可以自主发言

        Returns:
            bool: 是否可以自主发言
        """
        return self.level in (AutonomyLevel.FULL_AUTO, AutonomyLevel.SEMI_AUTO)

    def needs_confirmation(self, action: str) -> bool:
        """
        检查操作是否需要人工确认

        Args:
            action: 操作类型，如 "speak", "complete_task", "advance_group"

        Returns:
            bool: 是否需要人工确认
        """
        if self.level == AutonomyLevel.FULL_AUTO:
            return False

        if self.level == AutonomyLevel.MANUAL:
            return True

        # SEMI_AUTO模式下，只有关键操作需要确认
        critical_actions = {"complete_task", "advance_group", "create_deliverable"}
        return action in critical_actions

    def should_pause_for_input(self) -> bool:
        """
        检查是否应该暂停等待人工输入

        Returns:
            bool: 是否应该暂停
        """
        return self.level == AutonomyLevel.MANUAL

    def should_auto_advance(self) -> bool:
        """
        检查任务完成后是否应该自动推进到下一个群聊

        Returns:
            bool: 是否应该自动推进
        """
        return self.auto_advance

    def get_waiting_reason(self, action: str) -> Optional[str]:
        """
        获取等待人工输入的原因描述

        Args:
            action: 当前操作

        Returns:
            Optional[str]: 原因描述，如果不需要等待则返回None
        """
        if not self.needs_confirmation(action):
            return None

        reasons = {
            "speak": "等待人工确认Agent发言",
            "complete_task": "等待人工确认任务完成",
            "advance_group": "等待人工确认推进到下一阶段",
            "create_deliverable": "等待人工确认创建交付物",
        }
        return reasons.get(action, f"等待人工确认: {action}")

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典

        Returns:
            Dict: 控制器状态
        """
        return {
            "level": self.level.value,
            "auto_advance": self.auto_advance,
            "can_auto_speak": self.can_auto_speak(),
        }
