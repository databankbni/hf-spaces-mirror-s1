from dataclasses import dataclass, field
from typing import Optional, Union, Any
from datetime import datetime
from enum import Enum
import json


class PacketType(Enum):
    CALL = "call"
    RESPONSE = "response"
    ERROR = "error"
    NORMAL = "normal"
    STREAM = "stream"
    INTERRUPT = "interrupt"


class FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("FrozenDict is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


class FrozenList(list):
    def _immutable(self, *args, **kwargs):
        raise TypeError("FrozenList is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def freeze_value(value: Any) -> Any:
    if isinstance(value, FrozenDict) or isinstance(value, FrozenList):
        return value
    if isinstance(value, dict):
        return FrozenDict({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return FrozenList(freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_value(item) for item in value)
    return value


def thaw_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: thaw_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [thaw_value(item) for item in value]
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    return value


@dataclass
class InfoPacket:
    id: str
    sender_id: str
    parent_id: Optional[str]
    chain_id: str
    content: Union[str, dict, bytes]
    type: PacketType
    timestamp: datetime
    _metadata: dict = field(default_factory=dict, repr=False)
    _initialized: bool = field(default=False, repr=False)
    
    _IMMUTABLE_FIELDS = frozenset(['id', 'sender_id', 'parent_id', 'chain_id', 'content', 'type', 'timestamp'])
    
    def __post_init__(self):
        object.__setattr__(self, 'content', freeze_value(self.content))
        object.__setattr__(
            self,
            '_metadata',
            {key: freeze_value(value) for key, value in self._metadata.items()}
        )
        object.__setattr__(self, '_initialized', True)
    
    def __setattr__(self, name: str, value: Any) -> None:
        if name == '_initialized':
            object.__setattr__(self, name, value)
            return
        
        if hasattr(self, '_initialized') and self._initialized:
            if name in self._IMMUTABLE_FIELDS:
                raise AttributeError(
                    f"Cannot modify immutable field '{name}'. "
                    f"Core fields (id, sender_id, parent_id, chain_id, content, type, timestamp) cannot be changed after creation."
                )
        
        object.__setattr__(self, name, value)
    
    def add_metadata(self, key: str, value: Any) -> None:
        if key in self._metadata:
            raise KeyError(
                f"Metadata key '{key}' already exists. "
                f"Metadata is append-only and cannot be modified."
            )
        self._metadata[key] = freeze_value(value)

    def set_metadata(self, key: str, value: Any) -> None:
        """设置或覆盖 metadata。用于需要更新计数器等场景。"""
        self._metadata[key] = freeze_value(value)
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        if key not in self._metadata:
            return default
        return thaw_value(self._metadata[key])
    
    def has_metadata(self, key: str) -> bool:
        return key in self._metadata
    
    @property
    def metadata(self) -> dict:
        return thaw_value(self._metadata)
    
    def to_dict(self) -> dict:
        content = thaw_value(self.content)
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'parent_id': self.parent_id,
            'chain_id': self.chain_id,
            'content': content,
            'type': self.type.value,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'InfoPacket':
        content = data['content']
        if isinstance(content, str) and data.get('content_type') == 'bytes':
            content = content.encode('utf-8')
        
        return cls(
            id=data['id'],
            sender_id=data['sender_id'],
            parent_id=data.get('parent_id'),
            chain_id=data['chain_id'],
            content=content,
            type=PacketType(data['type']),
            timestamp=datetime.fromisoformat(data['timestamp']),
            _metadata=data.get('metadata', {}).copy()
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'InfoPacket':
        return cls.from_dict(json.loads(json_str))
    
    def create_child(
        self,
        sender_id: Optional[str] = None,
        content: Optional[Union[str, dict, bytes]] = None,
        packet_type: Optional[PacketType] = None,
        id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        inherit_metadata: bool = True
    ) -> 'InfoPacket':
        """
        快捷创建子信息包，自动继承父包的 chain_id 和 parent_id
        
        Args:
            sender_id: 发送者 ID，默认继承父包
            content: 信息内容，默认继承父包
            packet_type: 信息包类型，默认继承父包
            id: 包 ID，默认自动生成
            timestamp: 时间戳，默认当前时间
            inherit_metadata: 是否继承 metadata，默认 True
        
        Returns:
            InfoPacket: 新的子信息包
        
        Example:
            # 创建子包，只更新 content
            child = parent.create_child(content="new content")
            
            # 创建子包，更新 content 和 type
            child = parent.create_child(
                content="response",
                packet_type=PacketType.RESPONSE
            )
            
            # 创建子包，不继承 metadata
            child = parent.create_child(
                content="clean content",
                inherit_metadata=False
            )
        """
        from .id_generator import IDGenerator
        
        child = InfoPacket(
            id=id or IDGenerator.generate_packet_id(
                sender_id or self.sender_id,
                (packet_type or self.type).value
            ),
            sender_id=sender_id or self.sender_id,
            parent_id=self.id,
            chain_id=self.chain_id,
            content=content if content is not None else self.content,
            type=packet_type or self.type,
            timestamp=timestamp or datetime.now(),
            _metadata=self._metadata.copy() if inherit_metadata else {}
        )
        
        return child
    
    def __repr__(self) -> str:
        return (
            f"InfoPacket(id={self.id!r}, sender_id={self.sender_id!r}, "
            f"parent_id={self.parent_id!r}, chain_id={self.chain_id!r}, "
            f"type={self.type}, timestamp={self.timestamp})"
        )
