from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING
import copy

if TYPE_CHECKING:
    from .packet import InfoPacket
    from .processor import Processor


class Plugin(ABC):
    def __init__(self, name: Optional[str] = None):
        self.name = name or self.__class__.__name__
        self._processor: Optional['Processor'] = None
    
    def attach(self, processor: 'Processor') -> 'Plugin':
        self._processor = processor
        self._on_attach(processor)
        return self
    
    def _on_attach(self, processor: 'Processor') -> None:
        pass

    def clone(self) -> 'Plugin':
        cloned = copy.deepcopy(self)
        cloned._processor = None
        return cloned
    
    def pre_process(self, packet: 'InfoPacket') -> 'InfoPacket':
        return packet

    def build_system_message(self, packet: 'InfoPacket') -> str:
        return ""
    
    def post_process(self, packet: 'InfoPacket', output_list: list) -> tuple:
        return packet, output_list

    def on_stream(self, packet: 'InfoPacket') -> None:
        """STREAM 包（token）钩子，由 Processor._output(stream=True) 调用。

        替代 StreamCollector 对 STREAM 包的捕获，让 plugin 统一处理所有 packet 类型。
        默认实现为空，不影响现有行为。子类可重写以捕获流式 token。
        """
        pass


class PluginManager:
    def __init__(self):
        self._plugins: list[Plugin] = []
    
    def add_plugin(self, plugin: Plugin) -> 'PluginManager':
        self._plugins.append(plugin)
        return self
    
    def get_pre_processes(self) -> list:
        return [p.pre_process for p in self._plugins]
    
    def get_post_processes(self) -> list:
        return [p.post_process for p in self._plugins]
    
    def attach_all(self, processor: 'Processor') -> None:
        for plugin in self._plugins:
            plugin.attach(processor)

    @property
    def plugins(self) -> list[Plugin]:
        return list(self._plugins)
