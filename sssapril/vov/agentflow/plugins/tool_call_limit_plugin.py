from __future__ import annotations

import logging
from typing import Dict

from ..packet import InfoPacket, PacketType
from ..plugin import Plugin

logger = logging.getLogger(__name__)


class ToolCallLimitPlugin(Plugin):
    """工具调用次数上限插件（上下文管理职责）

    针对 agentic loop 中 LLM 反复调用工具但不产出文本的场景，提供两个阈值：

    - ``warn_threshold`` (默认 20):
        连续 tool_calls 没有产出"最终 NORMAL 文本"(无 tool_calls)时触发。
        下一轮 LLM 调用前, 通过 ``build_system_message`` 注入一条提醒, 让 LLM
        自我反思是否合理继续调工具。同一 chain 只会提醒一次, 避免反复打扰。
        **注意**: 带 ``has_pending_tool_calls=True`` 的 NORMAL 包(text + tool_calls
        组合)不算"最终文本", 不重置计数器 (修复 agnes-2.0-flash 每轮都产
        text+tool_call 绕过 warn 的问题).

    - ``max_threshold`` (默认 50):
        累计 tool_calls 数量（不重置）达到此值时触发。在 ``stream_process``
        /``core_process`` 调用 LLM 前由 Agent 检查，超限后强制走 NORMAL
        分支终止循环，content 是固定提示文本。这会触发 ``ResultCollector.set``
        让 ``execute_stream`` 正常返回，避免 ResultCollector.wait 超时和
        streaming=true 永不 pop。

    计数器按 ``chain_id`` 隔离，避免不同 chain 互相影响。

    设计原则：
    - 软提醒 (warn) 让 LLM 自我纠正，不强制中断。
    - 硬中断 (max) 是兜底，确保系统能恢复（等用户决策或换模型）。
    - 模型能力问题是模型本身的事，框架只保证不卡死。
    """

    def __init__(
        self,
        warn_threshold: int = 20,
        max_threshold: int = 50,
    ):
        super().__init__(name="ToolCallLimitPlugin")
        self.warn_threshold = warn_threshold
        self.max_threshold = max_threshold

        # chain_id → 连续 tool_call 计数（自上次 NORMAL 输出以来重置）
        # 用于触发 warn_threshold：如果 LLM 一度产出过文本，则不视为"卡死循环"
        self._consecutive_counts: Dict[str, int] = {}

        # chain_id → 累计 tool_call 计数（chain 生命周期内不重置）
        # 用于触发 max_threshold：整个 chain 的工具调用总量
        self._total_counts: Dict[str, int] = {}

        # chain_id → 是否已经发过 warn
        # 防止连续多轮都达到 warn_threshold 时反复注入提醒
        self._warned: Dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Plugin 钩子
    # ------------------------------------------------------------------
    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        """RESPONSE 包进入 Agent.input 时计数。

        RESPONSE 包是工具执行完回流到 Agent 的包，每个 RESPONSE 对应一次
        工具调用完成。计数后由 ``build_system_message`` / ``should_force_terminate``
        在下一轮 LLM 调用前检查。
        """
        if packet.type != PacketType.RESPONSE:
            return packet

        chain_id = packet.chain_id or ""
        self._consecutive_counts[chain_id] = self._consecutive_counts.get(chain_id, 0) + 1
        self._total_counts[chain_id] = self._total_counts.get(chain_id, 0) + 1

        # 诊断日志: INFO 级别, 每次 RESPONSE 包都打印 (用于排查 plugin 是否生效)
        logger.info(
            "[ToolCallLimit] chain=%s consecutive=%d total=%d warn_th=%d max_th=%d",
            chain_id[:8] if chain_id else "?",
            self._consecutive_counts[chain_id],
            self._total_counts[chain_id],
            self.warn_threshold,
            self.max_threshold,
        )
        return packet

    def post_process(self, packet: InfoPacket, output_list: list) -> tuple:
        """Agent 输出包时回调：NORMAL 包重置连续计数。

        场景区分：
        - 普通 NORMAL 包 (无 has_pending_tool_calls):
            LLM 真正收敛, 产出了最终文本回复. 重置 _consecutive_counts
            和 _warned, 允许下次 warn 再次触发.
        - NORMAL 包带 has_pending_tool_calls=True (text + tool_calls 组合):
            LLM 还在 agentic loop 中, 没收敛. **不重置** consecutive_count,
            否则像 agnes-2.0-flash 这种"每轮都产 text+tool_call"的模型
            会绕过 warn_threshold, 让 plugin 永远不触发提醒, 用户只能等
            ResultCollector.wait 超时 (默认 600s = 10 分钟).
        - CALL 包 (agent 调工具):
            不重置, 保持计数.
        """
        if packet.type == PacketType.NORMAL:
            chain_id = packet.chain_id or ""
            # 关键: 仅当 NORMAL 是真正的"最终回复"时才重置.
            # 带 has_pending_tool_calls=True 的 NORMAL 是 agentic loop 中间态
            # (LLM 一边产文本一边调工具), 不算"收敛", 不重置.
            has_pending = bool(packet.get_metadata("has_pending_tool_calls"))
            if has_pending:
                logger.debug(
                    "[ToolCallLimit] chain=%s NORMAL with pending tool_calls, keep consecutive=%d",
                    chain_id[:8] if chain_id else "?",
                    self._consecutive_counts.get(chain_id, 0),
                )
            else:
                if self._consecutive_counts.get(chain_id, 0) > 0:
                    logger.debug(
                        "[ToolCallLimit] chain=%s final NORMAL output, reset consecutive (was %d)",
                        chain_id[:8] if chain_id else "?",
                        self._consecutive_counts.get(chain_id, 0),
                    )
                self._consecutive_counts[chain_id] = 0
                self._warned[chain_id] = False
        return packet, output_list

    def build_system_message(self, packet: InfoPacket) -> str:
        """达到 warn_threshold 时注入提醒 system message。

        被 ``Agent._build_messages`` 调用，加在 messages 列表前面。
        仅在达到阈值且本 chain 未发过 warn 时触发，触发后标记 _warned=True
        防止重复打扰。返回空字符串时不注入。
        """
        chain_id = packet.chain_id or ""
        consecutive = self._consecutive_counts.get(chain_id, 0)

        if consecutive < self.warn_threshold:
            return ""

        if self._warned.get(chain_id, False):
            return ""

        self._warned[chain_id] = True
        logger.info(
            "[ToolCallLimit] chain=%s reached warn_threshold=%d, injecting reminder",
            chain_id[:8] if chain_id else "?",
            consecutive,
        )
        return (
            f"[ToolCallLimit] 你已连续调用工具 {consecutive} 次未输出普通文本。"
            f"请评估当前调用序列是否合理：是否重复调用了相同工具？是否应该直接"
            f"给出文字总结而非继续调工具？如果确实需要继续调用，请忽略本提醒。"
        )

    # ------------------------------------------------------------------
    # Agent 主动查询 API（供 stream_process / core_process 调用）
    # ------------------------------------------------------------------
    def should_force_terminate(self, packet: InfoPacket) -> bool:
        """是否达到硬上限，需要强制终止循环。

        在 Agent.stream_process / core_process 开头检查，返回 True 时
        Agent 应跳过 LLM 调用，直接走 normal_packet 分支返回固定提示文本。
        """
        chain_id = packet.chain_id or ""
        total = self._total_counts.get(chain_id, 0)
        return total >= self.max_threshold

    def get_consecutive_count(self, chain_id: str) -> int:
        return self._consecutive_counts.get(chain_id or "", 0)

    def get_total_count(self, chain_id: str) -> int:
        return self._total_counts.get(chain_id or "", 0)

    def reset(self, chain_id: str) -> None:
        """chain 结束后清理计数器（可选，防止内存泄漏）。

        Agent 执行完一个 chain 后可调用，避免长期运行计数器字典无限增长。
        """
        chain_id = chain_id or ""
        self._consecutive_counts.pop(chain_id, None)
        self._total_counts.pop(chain_id, None)
        self._warned.pop(chain_id, None)
