from __future__ import annotations

from abc import ABC
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING, Tuple, Union, get_type_hints
import asyncio
import copy
import inspect

from ._execution import ProcessorExecutors
from ._schema_utils import (
    coerce_call_argument,
    create_arg_extractor,
    extract_call_arguments,
    generate_schema_from_docstring,
)
from .id_generator import IDGenerator
from .packet import InfoPacket, PacketType
from .plugin import Plugin, PluginManager

if TYPE_CHECKING:
    PostProcessFunc = Callable[[InfoPacket, List["Processor"]], Tuple[InfoPacket, List["Processor"]]]
else:
    PostProcessFunc = Callable


class Processor(ABC):
    def __init__(
        self,
        name: str,
        core_process_func: Optional[Callable[[InfoPacket], Any]] = None,
        pre_processes: Optional[List[Callable[[InfoPacket], InfoPacket]]] = None,
        post_processes: Optional[List[PostProcessFunc]] = None,
        plugins: Optional[List[Plugin]] = None,
        to: Optional[Union["Processor", List["Processor"]]] = None,
        timeout: Optional[float] = None,
        max_retries: int = 0,
    ):
        self.name = name
        self.sender_id = IDGenerator.generate_sender_id(name)
        self._pre_processes = list(pre_processes) if pre_processes else []
        self._post_processes = list(post_processes) if post_processes else []
        self._to_list: List["Processor"] = []
        self._stream_to_list: List["Processor"] = []
        self._call_stack: Set[int] = set()
        self._timeout = timeout
        self._max_retries = max_retries
        self._plugin_manager = PluginManager()
        self._core_process_func = core_process_func
        self._on_stream_hooks: List[Callable[[InfoPacket], None]] = []

        if plugins:
            for plugin in plugins:
                self.add_plugin(plugin)
        if to:
            self.to(to)

    def add_pre_process(self, func: Callable[[InfoPacket], InfoPacket]) -> "Processor":
        self._pre_processes.append(func)
        return self

    def add_post_process(self, func: PostProcessFunc) -> "Processor":
        self._post_processes.append(func)
        return self

    def add_plugin(self, plugin: Plugin) -> "Processor":
        self._plugin_manager.add_plugin(plugin)
        plugin.attach(self)
        self.add_pre_process(plugin.pre_process)
        self.add_post_process(plugin.post_process)
        self._on_stream_hooks.append(plugin.on_stream)
        return self

    def get_plugins(self, plugin_type: Optional[type] = None) -> List[Plugin]:
        plugins = self._plugin_manager.plugins
        if plugin_type is None:
            return plugins
        return [plugin for plugin in plugins if isinstance(plugin, plugin_type)]

    def to(self, processors: Union["Processor", List["Processor"]], stream: bool = False, allow_loop: bool = False) -> "Processor":
        if isinstance(processors, Processor):
            processors = [processors]
        target_list = self._stream_to_list if stream else self._to_list
        for processor in processors:
            if not allow_loop:
                self._check_circular_call(processor)
            target_list.append(processor)
        return self

    def _check_circular_call(self, target: "Processor") -> None:
        current_id = id(self)
        if id(target) in self._call_stack:
            raise ValueError(f"Circular call detected: {self.name} -> {target.name}")
        to_check = [target]
        visited = set()
        while to_check:
            current = to_check.pop()
            current_id_to_check = id(current)
            if current_id_to_check in visited:
                continue
            visited.add(current_id_to_check)
            if current_id_to_check == current_id:
                raise ValueError("Circular call detected in chain")
            to_check.extend(current._to_list)

    def input(self, packet: InfoPacket) -> None:
        ProcessorExecutors.submit_process(self._process, packet)

    def _invoke_core_process(self, packet: InfoPacket) -> Any:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(self.core_process):  # type: ignore[name-defined]
                    return ProcessorExecutors.run_async(self.core_process(packet), timeout=self._timeout)
                return ProcessorExecutors.run_sync(lambda: self.core_process(packet), timeout=self._timeout)
            except Exception as exc:  # pragma: no cover - centralized execution path
                last_error = exc
                if attempt >= self._max_retries:
                    raise
        raise last_error or RuntimeError("Processor core_process failed.")

    def _process(self, packet: InfoPacket) -> None:
        try:
            for func in self._pre_processes:
                packet = func(packet)
                if packet.type == PacketType.INTERRUPT:
                    return

            result = self._invoke_core_process(packet)
            packets: List[InfoPacket]
            if result is None:
                packets = [packet]
            elif isinstance(result, InfoPacket):
                packets = [result]
            elif isinstance(result, list) and all(isinstance(item, InfoPacket) for item in result):
                packets = result
            else:
                packets = [packet]

            processed_outputs: List[Tuple[InfoPacket, List["Processor"]]] = []
            for current_packet in packets:
                if current_packet.type == PacketType.INTERRUPT:
                    return
                output_list = copy.copy(self._to_list)
                for func in self._post_processes:
                    current_packet, output_list = func(current_packet, output_list)
                    if current_packet.type == PacketType.INTERRUPT:
                        return
                processed_outputs.append((current_packet, output_list))

            for current_packet, output_list in processed_outputs:
                self._output_to_list(current_packet, output_list)
        except Exception as exc:  # pragma: no cover - error fanout path
            error_packet = self._create_error_packet(packet, str(exc))
            try:
                output_list = copy.copy(self._to_list)
                for func in self._post_processes:
                    error_packet, output_list = func(error_packet, output_list)
                    if error_packet.type == PacketType.INTERRUPT:
                        return
                self._output_to_list(error_packet, output_list)
            except Exception:
                self._output(error_packet)

    def core_process(self, packet: InfoPacket) -> Any:
        if self._core_process_func is None:
            raise NotImplementedError("Subclasses must implement core_process or provide core_process_func")
        return self._core_process_func(packet)

    def _output(self, packet: InfoPacket, stream: bool = False) -> None:
        if stream:
            for hook in self._on_stream_hooks:
                hook(packet)
        self._output_to_list(packet, self._stream_to_list if stream else self._to_list)

    def _output_to_list(self, packet: InfoPacket, target_list: List["Processor"]) -> None:
        for processor in target_list:
            processor.input(packet)

    def _create_packet(
        self,
        content: Union[str, dict, bytes],
        packet_type: PacketType = PacketType.NORMAL,
        parent_id: Optional[str] = None,
        chain_id: Optional[str] = None,
    ) -> InfoPacket:
        return InfoPacket(
            id=IDGenerator.generate_packet_id(self.sender_id, packet_type.value),
            sender_id=self.sender_id,
            parent_id=parent_id,
            chain_id=chain_id or IDGenerator.generate_chain_id(),
            content=content,
            type=packet_type,
            timestamp=datetime.now(),
        )

    def _create_child_packet(self, parent: InfoPacket, content: Union[str, dict, bytes], packet_type: PacketType = PacketType.NORMAL) -> InfoPacket:
        return parent.create_child(sender_id=self.sender_id, content=content, packet_type=packet_type)

    def _create_error_packet(self, original: InfoPacket, error_msg: str) -> InfoPacket:
        return original.create_child(
            sender_id=self.sender_id,
            content={"error": error_msg, "original_id": original.id},
            packet_type=PacketType.ERROR,
        )

    def set_timeout(self, seconds: float) -> "Processor":
        self._timeout = seconds
        return self

    def set_max_retries(self, count: int) -> "Processor":
        self._max_retries = count
        return self

    def get_schema(self) -> Optional[Dict[str, Any]]:
        return None


def processor(
    name: str,
    description: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    pre_processes: Optional[List[Callable[[InfoPacket], InfoPacket]]] = None,
    post_processes: Optional[List[PostProcessFunc]] = None,
    plugins: Optional[List[Plugin]] = None,
    to: Optional[Union[Processor, List[Processor]]] = None,
    timeout: Optional[float] = None,
    max_retries: int = 0,
) -> Callable[[Callable], Processor]:
    def decorator(func: Callable) -> Processor:
        extractor = create_arg_extractor(func)
        signature = inspect.signature(func)
        parameter_names = list(signature.parameters.keys())

        def wrapped_core_process(packet: InfoPacket):
            call_arguments = extract_call_arguments(packet)
            fallback_args = extractor(packet)
            fallback_map = dict(zip(parameter_names, fallback_args))
            args = []
            kwargs = {}
            for param_name, param in signature.parameters.items():
                provided = False
                value = None
                if param.annotation is InfoPacket:
                    value = packet
                    provided = True
                elif param_name in call_arguments:
                    value = coerce_call_argument(call_arguments[param_name], param.annotation)
                    provided = True
                elif param_name in fallback_map and fallback_map[param_name] is not packet:
                    value = fallback_map[param_name]
                    provided = True
                if not provided:
                    continue
                if param.kind == inspect.Parameter.POSITIONAL_ONLY:
                    args.append(value)
                else:
                    kwargs[param_name] = value
            result = func(*args, **kwargs)
            if result is None:
                return None
            if isinstance(result, InfoPacket):
                return result
            return packet.create_child(content=result, packet_type=PacketType.RESPONSE)

        proc = Processor(
            name=name,
            core_process_func=wrapped_core_process,
            pre_processes=pre_processes,
            post_processes=post_processes,
            plugins=plugins,
            to=to,
            timeout=timeout,
            max_retries=max_retries,
        )

        if schema is not None:
            proc._schema = schema
        elif description is not None:
            try:
                hints = get_type_hints(func)
            except Exception:
                hints = {}
            properties: dict[str, dict[str, Any]] = {}
            required: list[str] = []
            for param_name, param_type in hints.items():
                if param_name == "return" or param_type is InfoPacket:
                    continue
                type_map = {
                    str: "string",
                    int: "integer",
                    float: "number",
                    bool: "boolean",
                    dict: "object",
                    list: "array",
                    bytes: "string",
                }
                properties[param_name] = {
                    "type": type_map.get(param_type, "string"),
                    "description": f"The {param_name} parameter",
                }
                if signature.parameters[param_name].default == inspect.Parameter.empty:
                    required.append(param_name)
            parameters: dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                parameters["required"] = required
            proc._schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        else:
            proc._schema = generate_schema_from_docstring(func, name)

        proc.get_schema = lambda: getattr(proc, "_schema", None)
        return proc

    return decorator
