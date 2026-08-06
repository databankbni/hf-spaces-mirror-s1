from typing import Optional, TYPE_CHECKING, Dict, Any, List, Tuple
import threading
from ..plugin import Plugin
from ..packet import InfoPacket, PacketType
from ..id_generator import IDGenerator
from datetime import datetime

if TYPE_CHECKING:
    from ..processor import Processor


class CallbackPlugin(Plugin):
    """
    回流插件：将 processor 返回的结果回流到调用者 agent

    工作流程：
    1. 在 pre_process 中记录 chain 的头包（第一个包）
    2. 在 post_process 中将返回的包转为头包的子包
    3. 如果头包是 call 包，则子包设为 response 类型
    4. 通过修改 output_list 将包回流到 requester（从 packet metadata 获取）
    """

    def __init__(self, name: Optional[str] = None):
        super().__init__(name)
        self._chain_heads: Dict[str, Dict[str, Any]] = {}
        self._call_heads: Dict[str, Dict[str, Any]] = {}
        self._requesters: Dict[str, 'Processor'] = {}
        self._lock = threading.RLock()

    def clone(self) -> 'CallbackPlugin':
        cloned = CallbackPlugin(name=self.name)
        cloned._requesters = self._requesters.copy()
        return cloned

    def set_callback_target(self, target: 'Processor') -> 'CallbackPlugin':
        with self._lock:
            self._requesters[target.sender_id] = target
        return self

    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        with self._lock:
            if packet.type == PacketType.CALL:
                # 子链隔离：CALL 包到达工具处理器时，创建新的子链包
                # 保存原始 chain_id 用于后续 RESPONSE 回流到调用者链
                original_chain_id = packet.chain_id
                sub_chain_id = IDGenerator.generate_chain_id()

                # 创建新包（InfoPacket 核心字段不可变，需创建新实例）
                sub_packet = InfoPacket(
                    id=packet.id,
                    sender_id=packet.sender_id,
                    parent_id=packet.parent_id,
                    chain_id=sub_chain_id,
                    content=packet.content,
                    type=packet.type,
                    timestamp=packet.timestamp,
                    _metadata=dict(packet._metadata),
                )

                call_info = {
                    'head_packet': sub_packet,
                    'is_call': True,
                    'requester': packet.get_metadata('requester'),
                    'original_chain_id': original_chain_id,
                }
                self._call_heads[sub_packet.id] = call_info
                self._chain_heads[sub_chain_id] = call_info
                return sub_packet
            elif packet.parent_id and packet.parent_id in self._call_heads:
                self._call_heads[packet.id] = self._call_heads[packet.parent_id]
            elif packet.chain_id not in self._chain_heads:
                self._chain_heads[packet.chain_id] = {
                    'head_packet': packet,
                    'is_call': False,
                    'requester': packet.get_metadata('requester')
                }
        return packet
    
    def post_process(
        self, 
        packet: InfoPacket, 
        output_list: List['Processor']
    ) -> Tuple[InfoPacket, List['Processor']]:
        if packet.type == PacketType.CALL:
            return packet, output_list
        
        with self._lock:
            chain_info = None
            if packet.parent_id and packet.parent_id in self._call_heads:
                chain_info = self._call_heads[packet.parent_id]
            elif packet.chain_id in self._chain_heads:
                chain_info = self._chain_heads[packet.chain_id]

        if not chain_info:
            import logging
            logging.getLogger(__name__).warning(
                "[CallbackPlugin] NO chain_info for packet.parent_id=%s chain_id=%s type=%s — RESPONSE will be DROPPED",
                packet.parent_id, packet.chain_id, packet.type,
            )
            return packet, output_list
        
        head_packet = chain_info['head_packet']
        is_call_chain = chain_info['is_call']
        requester_id = chain_info.get('requester')
        
        if is_call_chain:
            original_chain_id = chain_info.get('original_chain_id')
            response_packet = self._create_callback_child(packet, head_packet, original_chain_id)
            # 保留工具执行后添加的元数据（如 render_spec），这些不在原始 CALL 包中
            for key, value in packet.metadata.items():
                if key not in response_packet.metadata and key != "display_content":
                    response_packet.add_metadata(key, value)
            with self._lock:
                if requester_id:
                    requester = self._requesters.get(requester_id)
                    callback_targets = [requester] if requester is not None else []
                else:
                    callback_targets = list(self._requesters.values())

            for callback_target in callback_targets:
                if callback_target not in output_list:
                    output_list = output_list + [callback_target]

            return response_packet, output_list
        else:
            # is_call_chain=False: 非工具调用链,CallbackPlugin 不应干预
            # 直接返回原 packet,避免用 head_packet.metadata 替换 packet.metadata
            # (否则会丢失 has_pending_tool_calls 等关键元数据,导致 execute() 提前返回)
            return packet, output_list
    
    def _create_callback_child(
        self,
        packet: InfoPacket,
        call_packet: InfoPacket,
        original_chain_id: Optional[str] = None,
    ) -> InfoPacket:
        response_metadata = self._propagate_child_metadata(call_packet.metadata)
        packet_type = PacketType.ERROR if packet.type == PacketType.ERROR else PacketType.RESPONSE
        return InfoPacket(
            id=IDGenerator.generate_packet_id(packet.sender_id, packet_type.value),
            sender_id=packet.sender_id,
            parent_id=call_packet.id,
            chain_id=original_chain_id or packet.chain_id,
            content=packet.content,
            type=packet_type,
            timestamp=datetime.now(),
            _metadata=response_metadata
        )

    def _propagate_child_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        # display_content only exists to preserve the original visible user text
        # for request packets whose raw content carries hidden room context.
        # Child assistant packets must render their own real content.
        return {
            key: value
            for key, value in metadata.items()
            if key != "display_content"
        }
    
    def clear_chain(self, chain_id: str) -> None:
        with self._lock:
            if chain_id in self._chain_heads:
                del self._chain_heads[chain_id]

            call_ids_to_remove = [
                call_id for call_id, info in self._call_heads.items()
                if info['head_packet'].chain_id == chain_id
            ]
            for call_id in call_ids_to_remove:
                del self._call_heads[call_id]
