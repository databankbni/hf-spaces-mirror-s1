from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, Union

from .id_generator import IDGenerator
from .manager import InfoManager
from .packet import InfoPacket, PacketType
from .plugin import Plugin
from .plugins.memory_plugin import MemoryPlugin
from .processor import Processor
from .specs import AgentSpec, LLMConfig

if TYPE_CHECKING:
    from .agent import Agent


class Workspace(Processor):
    """
    Workspace is a special processor that acts as:
    1. A registry for processors and agents.
    2. A router for targeted or cross-workspace messages.
    3. A shared resource container, especially for InfoManager-backed history.
    """

    def __init__(self, name: str, db_path: Optional[str] = None):
        super().__init__(name)
        self._processors: Dict[str, Processor] = {}
        self._agents: Dict[str, "Agent"] = {}
        self._agent_specs: Dict[str, AgentSpec] = {}
        self._info_manager = InfoManager(db_path or f"{name}.db")
        self._global_plugins: List[Union[Plugin, Callable[[], Plugin]]] = []
        self.tool_adapter: Optional[Any] = None  # ToolServiceAdapter 注入点

    def register(self, processor: Processor) -> "Workspace":
        if processor.name in self._processors:
            raise ValueError(f"Processor '{processor.name}' is already registered in workspace '{self.name}'")

        self._bind_workspace_resources(processor)
        self._apply_global_plugins(processor)

        self._processors[processor.name] = processor
        if hasattr(processor, "llm"):
            self._agents[processor.name] = processor
            if hasattr(processor, "to_spec"):
                try:
                    self._agent_specs[processor.name] = processor.to_spec()
                except Exception:
                    pass

        return self

    def unregister(self, name: str) -> "Workspace":
        self._processors.pop(name, None)
        self._agents.pop(name, None)
        self._agent_specs.pop(name, None)
        return self

    def get_processor(self, name: str) -> Optional[Processor]:
        return self._processors.get(name)

    def get_agent(self, name: str) -> Optional["Agent"]:
        return self._agents.get(name)

    def list_processors(self) -> List[str]:
        return list(self._processors.keys())

    def list_agents(self) -> List[str]:
        return list(self._agents.keys())

    def list_agent_specs(self) -> List[str]:
        return list(self._agent_specs.keys())

    def add_plugin_to_all(self, plugin: Union[Plugin, Callable[[], Plugin]]) -> "Workspace":
        self._global_plugins.append(plugin)
        for processor in self._processors.values():
            processor.add_plugin(self._create_plugin_instance(plugin))
        return self

    def _apply_global_plugins(self, processor: Processor) -> None:
        for plugin in self._global_plugins:
            processor.add_plugin(self._create_plugin_instance(plugin))

    def _create_plugin_instance(self, plugin: Union[Plugin, Callable[[], Plugin]]) -> Plugin:
        instance = plugin() if callable(plugin) and not isinstance(plugin, Plugin) else plugin.clone()
        if isinstance(instance, MemoryPlugin):
            instance.set_manager(self._info_manager)
        return instance

    def _bind_workspace_resources(self, processor: Processor) -> None:
        for plugin in processor.get_plugins(MemoryPlugin):
            plugin.set_manager(self._info_manager)

    def core_process(self, packet: InfoPacket) -> None:
        target_name = packet.get_metadata("target_processor")
        if target_name:
            target = self._processors.get(target_name)
            if target is not None:
                target.input(packet)
                return

            error_packet = self._create_packet(
                content={"error": f"Processor '{target_name}' not found"},
                packet_type=PacketType.ERROR,
                parent_id=packet.id,
                chain_id=packet.chain_id,
            )
            self._output(error_packet)
            return

        for processor in self._processors.values():
            processor.input(packet)

    def call_workspace(
        self,
        target_workspace: "Workspace",
        target_processor: str,
        content: Any,
        chain_id: Optional[str] = None,
    ) -> None:
        call_packet = InfoPacket(
            id=IDGenerator.generate_packet_id(self.sender_id, PacketType.CALL.value),
            sender_id=self.sender_id,
            parent_id=None,
            chain_id=chain_id or IDGenerator.generate_chain_id(),
            content=content,
            type=PacketType.CALL,
            timestamp=datetime.now(),
        )
        call_packet.add_metadata("target_processor", target_processor)
        call_packet.add_metadata("source_workspace", self.name)
        target_workspace.input(call_packet)

    def create_agent_from_spec(
        self,
        spec: Union[AgentSpec, Dict[str, Any]],
        default_llm_config: Optional[Union[LLMConfig, Dict[str, Any]]] = None,
        replace_existing: bool = False,
    ) -> "Agent":
        from .agent import Agent

        agent_spec = spec if isinstance(spec, AgentSpec) else AgentSpec.from_dict(spec)
        if agent_spec.name in self._processors:
            if not replace_existing:
                raise ValueError(f"Processor '{agent_spec.name}' is already registered in workspace '{self.name}'")
            self.unregister(agent_spec.name)

        agent = Agent.from_spec(
            agent_spec,
            workspace=self,
            default_llm_config=default_llm_config,
        )
        self.register(agent)
        self._agent_specs[agent.name] = agent.to_spec(
            builtin_tools=agent_spec.builtin_tools,
            tool_names=agent_spec.tool_names,
        )
        return agent

    def export_agent_spec(self, name: str) -> AgentSpec:
        if name in self._agent_specs:
            return self._agent_specs[name]

        agent = self.get_agent(name)
        if agent is None:
            raise ValueError(f"Agent '{name}' is not registered in workspace '{self.name}'")

        spec = agent.to_spec()
        self._agent_specs[name] = spec
        return spec

    @property
    def info_manager(self) -> InfoManager:
        return self._info_manager

    @property
    def global_plugins(self) -> List[str]:
        names = []
        for plugin in self._global_plugins:
            if isinstance(plugin, Plugin):
                names.append(plugin.name)
            else:
                names.append(getattr(plugin, "__name__", plugin.__class__.__name__))
        return names

    def close(self) -> None:
        self._info_manager.close()
