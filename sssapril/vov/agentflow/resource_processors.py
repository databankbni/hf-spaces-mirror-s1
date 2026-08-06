"""
Resource Tool Processors

替代文件系统处理器，通过 ToolServiceAdapter 操作 DB 中的 Resource。
"""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from .builtin_processors import BuiltinProcessor, _function_schema, _extract_builtin_content
from .async_bridge import safe_run_async
from .packet import InfoPacket

if TYPE_CHECKING:
    from .tool_adapter import ToolServiceAdapter


class ResourceReadProcessor(BuiltinProcessor):
    kind = "read_resource"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "read_resource"):
        super().__init__(name=name, description="Read a resource by ID from the project database.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "resource_id": {"type": "string", "description": "Resource ID."},
        }, required=["resource_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.read_resource(args["resource_id"]),
            context="read_resource",
        )


class ResourceWriteProcessor(BuiltinProcessor):
    kind = "write_resource"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "write_resource"):
        super().__init__(name=name, description="Create or update a resource in the project database.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
            "title": {"type": "string", "description": "Resource title."},
            "content": {"type": "string", "description": "Resource content."},
            "resource_type": {"type": "string", "description": "Resource type. Valid values: note, reference, guideline, rule, custom, map. Default: note."},
            "content_type": {"type": "string", "description": "Content format type. Valid values: markdown, json, table, list, tree, document, card, stat, timeline, map. Default: auto-detected from resource_type (map->map, others->markdown)."},
            "group_id": {"type": "string", "description": "Optional group ID for group-scoped resources."},
            "is_required": {"type": "boolean", "description": "Whether this resource is required reading."},
        }, required=["project_id", "title", "content"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.write_resource(
                project_id=args["project_id"],
                title=args["title"],
                content=args["content"],
                resource_type=args.get("resource_type", "note"),
                content_type=args.get("content_type"),
                group_id=args.get("group_id"),
                is_required=args.get("is_required", False),
            ),
            context="write_resource",
        )


class ResourceSearchProcessor(BuiltinProcessor):
    kind = "search_resources"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "search_resources"):
        super().__init__(name=name, description="Search resources in a project by keyword.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
            "query": {"type": "string", "description": "Search keyword."},
        }, required=["project_id", "query"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.search_resources(
                project_id=args["project_id"],
                query=args["query"],
            ),
            context="search_resources",
        )
