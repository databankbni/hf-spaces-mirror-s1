"""
DB Skill Tool Processors

替代文件系统 skill 处理器，通过 ToolServiceAdapter 操作 DB 中的 AgentSkill。
"""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from .builtin_processors import BuiltinProcessor, _function_schema, _extract_builtin_content
from .async_bridge import safe_run_async
from .packet import InfoPacket

if TYPE_CHECKING:
    from .tool_adapter import ToolServiceAdapter


class DBSkillCatalogProcessor(BuiltinProcessor):
    kind = "db_list_skills"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "db_list_skills"):
        super().__init__(name=name, description="List skills available to the agent from the database.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID."},
        }, required=["agent_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_agent_skills(args["agent_id"]),
            context="db_list_skills",
        )


class DBSkillReadProcessor(BuiltinProcessor):
    kind = "db_read_skill"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "db_read_skill"):
        super().__init__(name=name, description="Read a specific skill's content from the database. Use file_path to read a specific file within the skill.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID."},
            "skill_name": {"type": "string", "description": "Skill name."},
            "file_path": {"type": "string", "description": "Optional. Path of a specific file within the skill (e.g. 'views/table.md'). If omitted, returns the main content."},
        }, required=["agent_id", "skill_name"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.read_agent_skill(
                agent_id=args["agent_id"],
                skill_name=args["skill_name"],
                file_path=args.get("file_path"),
            ),
            context="db_read_skill",
        )


class DBSkillListFilesProcessor(BuiltinProcessor):
    kind = "db_list_skill_files"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "db_list_skill_files"):
        super().__init__(name=name, description="List additional files within a skill. Use this before db_read_skill with file_path to discover available files.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID."},
            "skill_name": {"type": "string", "description": "Skill name."},
        }, required=["agent_id", "skill_name"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_skill_files(
                agent_id=args["agent_id"],
                skill_name=args["skill_name"],
            ),
            context="db_list_skill_files",
        )
