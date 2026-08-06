"""
ToolEventPlugin — 工具事件监控插件

在 pre_process 阶段捕获 RESPONSE/ERROR 包，转发给下游（StreamCollector），
使前端能在工具执行过程中实时显示 tool_call / tool_result 事件。

该插件不修改包内容，不干预流程，仅做"打点"。
"""
from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from ..packet import InfoPacket, PacketType
from ..plugin import Plugin

if TYPE_CHECKING:
    from ..processor import Processor


class ToolEventPlugin(Plugin):
    """
    工具事件监控：在 pre_process 中将 RESPONSE/ERROR 转发给下游用于前端展示。

    流程：
      1. RESPONSE/ERROR 进入 Agent._process → pre_process 链
      2. 本插件捕获包 → 调用 _processor._output_to_list 转发给 _to_list
      3. 包继续走后续 pre_process → core_process → 正常 LLM 调用

    注意：仅在 Agent 上下文有效（需要 _processor._to_list 存在）。
    """

    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        if packet.type in (PacketType.RESPONSE, PacketType.ERROR):
            processor = self._processor
            if processor is not None and hasattr(processor, '_to_list'):
                # 转发给下游（StreamCollector 等），用于前端实时展示工具结果
                processor._output_to_list(packet, processor._to_list)
        return packet
