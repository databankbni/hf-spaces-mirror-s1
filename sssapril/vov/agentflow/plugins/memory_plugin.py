from typing import Optional, List, TYPE_CHECKING
from ..plugin import Plugin
from ..packet import InfoPacket, PacketType
from ..manager import InfoManager

if TYPE_CHECKING:
    from ..processor import Processor


class MemoryPlugin(Plugin):
    """
    记忆插件：记录 agent 的处理历史，让 agent 有记忆功能
    
    工作流程：
    1. 信息包从 input 进入时，通过 chain_id 查询链上所有记录
    2. 整合为拥有历史记录的信息包往后发送
    3. 记录信息包到数据库
    """
    
    def __init__(
        self,
        name: Optional[str] = None,
        manager: Optional[InfoManager] = None,
        max_history: int = 10
    ):
        super().__init__(name)
        self.manager = manager or InfoManager()
        self.max_history = max_history
        # 临时缓存: pre_process 查询的全量 chain history, 供同轮 _build_messages 复用,
        # 避免每轮 agentic loop 重复全表扫描 + JSON 反序列化.
        # 生命周期: pre_process 设置 → core_process(_build_messages) 读取 → post_process 清除
        self._cached_chain_id: Optional[str] = None
        self._cached_chain_history: Optional[List[InfoPacket]] = None

    def clone(self) -> 'MemoryPlugin':
        return MemoryPlugin(
            name=self.name,
            manager=self.manager,
            max_history=self.max_history
        )

    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        if packet.type != PacketType.STREAM:
            if self.manager.get_by_id(packet.id) is None:
                self.manager.save(packet)

            full_history = self.manager.get_by_chain_id(packet.chain_id)
            # 缓存全量 history (未过滤 STREAM/packet.id), 供 _build_messages 复用
            self._cached_chain_id = packet.chain_id
            self._cached_chain_history = list(full_history)

            history = [p for p in full_history if p.id != packet.id and p.type != PacketType.STREAM]

            history_truncated = len(history) > self.max_history
            history = history[-self.max_history:] if history_truncated else history

            if not packet.has_metadata('memory_loaded'):
                packet.add_metadata('memory_loaded', True)

            if history and not packet.has_metadata('history_packet_ids'):
                packet.add_metadata('history_packet_ids', [p.id for p in history])

            if history_truncated and not packet.has_metadata('history_truncated'):
                packet.add_metadata('history_truncated', True)

        return packet

    def post_process(self, packet: InfoPacket, output_list: list) -> tuple:
        if packet.type != PacketType.STREAM:
            if self.manager.get_by_id(packet.id) is None:
                self.manager.save(packet)
        # 清除缓存: post_process 后 history 已变 (output 已 save), 缓存失效
        self._cached_chain_id = None
        self._cached_chain_history = None
        return packet, output_list

    def set_manager(self, manager: InfoManager) -> 'MemoryPlugin':
        self.manager = manager
        return self

    def set_max_history(self, max_history: int) -> 'MemoryPlugin':
        self.max_history = max_history
        return self

    def get_chain_history(self, chain_id: str) -> List[InfoPacket]:
        """获取 chain 历史, 优先读 pre_process 缓存避免重复 DB 查询.

        注: pre_process 缓存的是全量未过滤 history, 与 manager.get_by_chain_id 语义一致.
        post_process 后缓存会被清除, 不会读到脏数据.
        """
        if self._cached_chain_id == chain_id and self._cached_chain_history is not None:
            return list(self._cached_chain_history)
        return self.manager.get_by_chain_id(chain_id)
    
    def clear_history(self, chain_id: str) -> None:
        self.manager.delete_by_chain_id(chain_id)
