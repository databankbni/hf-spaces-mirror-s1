"""
CRUD Tool Processors

将 server 的 CRUD API 包装为 agentflow 工具处理器。
每个处理器通过 ToolServiceAdapter 调用 server 服务。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .builtin_processors import BuiltinProcessor, _function_schema, _extract_builtin_content
from .async_bridge import safe_run_async
from .packet import InfoPacket

if TYPE_CHECKING:
    from .tool_adapter import ToolServiceAdapter


_logger = logging.getLogger(__name__)


# ── Project ──


class CreateProjectProcessor(BuiltinProcessor):
    kind = "create_project"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "create_project"):
        super().__init__(name=name, description="Create a new project.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "name": {"type": "string", "description": "Project name."},
            "description": {"type": "string", "description": "Project description."},
        }, required=["name"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.create_project(
                name=args["name"],
                description=args.get("description", ""),
            ),
            context="create_project",
        )


class ListProjectsProcessor(BuiltinProcessor):
    kind = "list_projects"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_projects"):
        super().__init__(name=name, description="List all projects.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {})

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        return safe_run_async(
            packet,
            self._adapter.list_projects(),
            context="list_projects",
        )


class GetProjectProcessor(BuiltinProcessor):
    kind = "get_project"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "get_project"):
        super().__init__(name=name, description="Get project details.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
        }, required=["project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.get_project(args["project_id"]),
            context="get_project",
        )


# ── 系统级工具（引导 agent 跨 project 操作） ──


class QueryProjectsProcessor(BuiltinProcessor):
    """查询用户项目列表（排除 is_guide=True 的引导 project）。引导 agent 用。"""
    kind = "query_projects"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "query_projects"):
        super().__init__(name=name, description="List all user projects (excluding guide projects).")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {})

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        return safe_run_async(
            packet,
            self._adapter.list_user_projects(),
            context="query_projects",
        )


class ListTemplatesProcessor(BuiltinProcessor):
    """列出所有可用的项目模板。引导 agent 用。"""
    kind = "list_templates"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_templates"):
        super().__init__(name=name, description="List all available project templates.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {})

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        return safe_run_async(
            packet,
            self._adapter.list_templates(),
            context="list_templates",
        )


class PickTemplateProcessor(BuiltinProcessor):
    """应用模板创建项目（含 agents/groups/skills/resources）。引导 agent 用。"""
    kind = "pick_template"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "pick_template"):
        super().__init__(
            name=name,
            description="Apply a project template to create a new project with pre-configured agents/groups/skills.",
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "template_id": {"type": "string", "description": "Template ID, e.g. 'novel-writing'."},
            "project_name": {"type": "string", "description": "New project name."},
            "project_description": {"type": "string", "description": "Optional project description."},
            "project_targets": {"type": "object", "description": "Optional target overrides, e.g. {word_count, chapter_count}."},
        }, required=["template_id", "project_name"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.apply_template(
                template_id=args["template_id"],
                project_name=args["project_name"],
                project_description=args.get("project_description"),
                project_targets=args.get("project_targets"),
            ),
            context="pick_template",
            timeout=120.0,
        )


# ── Group ──


class CreateGroupProcessor(BuiltinProcessor):
    kind = "create_group"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "create_group"):
        super().__init__(name=name, description="Create a new group chat in a project.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
            "name": {"type": "string", "description": "Group name."},
            "description": {"type": "string", "description": "Group description."},
        }, required=["project_id", "name"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.create_group(
                project_id=args["project_id"],
                name=args["name"],
                description=args.get("description", ""),
            ),
            context="create_group",
        )


class ListGroupsProcessor(BuiltinProcessor):
    kind = "list_groups"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_groups"):
        super().__init__(name=name, description="List groups in a project.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
        }, required=["project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        project_id = args["project_id"]
        if not isinstance(project_id, str):
            project_id = str(project_id)
        return safe_run_async(
            packet,
            self._adapter.list_groups(project_id),
            context="list_groups",
        )


class GetGroupProcessor(BuiltinProcessor):
    kind = "get_group"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "get_group"):
        super().__init__(name=name, description="Get group chat details.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
        }, required=["group_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.get_group(args["group_id"]),
            context="get_group",
        )


class UpdateGroupProcessor(BuiltinProcessor):
    kind = "update_group"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "update_group"):
        super().__init__(name=name, description="Update a group chat's information.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
            "name": {"type": "string", "description": "New group name."},
            "description": {"type": "string", "description": "New group description."},
            "status": {"type": "string", "description": "New status (pending/active/completed)."},
            "autonomy_level": {"type": "string", "description": "New autonomy level (full_auto/semi_auto/manual)."},
            "auto_advance": {"type": "boolean", "description": "Whether to auto-advance after completion."},
        }, required=["group_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.update_group(
                group_id=args["group_id"],
                name=args.get("name"),
                description=args.get("description"),
                status=args.get("status"),
                autonomy_level=args.get("autonomy_level"),
                auto_advance=args.get("auto_advance"),
            ),
            context="update_group",
        )


class DeleteGroupProcessor(BuiltinProcessor):
    kind = "delete_group"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "delete_group"):
        super().__init__(name=name, description="Delete a group chat.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID to delete."},
        }, required=["group_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.delete_group(args["group_id"]),
            context="delete_group",
        )


# ── Agent 邀请 ──


class InviteAgentProcessor(BuiltinProcessor):
    kind = "invite_agent"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "invite_agent"):
        super().__init__(name=name, description="Invite an agent to a project.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
            "agent_id": {"type": "string", "description": "Agent ID to invite."},
        }, required=["project_id", "agent_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.invite_agent(
                project_id=args["project_id"],
                agent_id=args["agent_id"],
            ),
            context="invite_agent",
        )


class ListProjectAgentsProcessor(BuiltinProcessor):
    kind = "list_project_agents"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_project_agents"):
        super().__init__(name=name, description="List agents in a project.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
        }, required=["project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_project_agents(args["project_id"]),
            context="list_project_agents",
        )


# ── Group Member ──


class AddGroupMemberProcessor(BuiltinProcessor):
    kind = "add_group_member"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "add_group_member"):
        super().__init__(name=name, description="Add a member to a group chat.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
            "project_agent_id": {"type": "string", "description": "Project-Agent ID."},
            "role": {"type": "string", "description": "Role in the group (default: member)."},
        }, required=["group_id", "project_agent_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.add_group_member(
                group_id=args["group_id"],
                project_agent_id=args["project_agent_id"],
                role=args.get("role", "member"),
            ),
            context="add_group_member",
        )


class ListGroupMembersProcessor(BuiltinProcessor):
    kind = "list_group_members"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_group_members"):
        super().__init__(name=name, description="List members of a group chat.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
        }, required=["group_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_group_members(args["group_id"]),
            context="list_group_members",
        )


# ── Task ──


class CreateTaskProcessor(BuiltinProcessor):
    kind = "create_task"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "create_task"):
        super().__init__(
            name=name,
            description=(
                "Create a new task in a group. "
                "Pass assignee_agent_name to assign the task to a specific group member. "
                "When the task is later set to in_progress, the system will automatically wake the assignee agent."
            ),
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
            "title": {"type": "string", "description": "Task title."},
            "description": {"type": "string", "description": "Task description."},
            "assignee_agent_name": {
                "type": "string",
                "description": (
                    "REQUIRED. The agent's display name. "
                    "System will look up the corresponding project_agent_id in the group members. "
                    "When the task is set to in_progress, the system will automatically wake the assignee. "
                    "If omitted, the tool returns an error listing available agent names — pass one of them and retry."
                ),
            },
            "inherit_main_chain": {
                "type": "boolean",
                "description": (
                    "OPTIONAL. Default true. "
                    "true: task chain inherits main-chain history up to the branch point. "
                    "false: task chain is fully isolated, only sees its own history (use for high-sensitivity flows)."
                ),
            },
            "status": {
                "type": "string",
                "enum": ["todo", "in_progress", "done", "reopened"],
                "description": (
                    "OPTIONAL. Default 'todo'. "
                    "Set to 'in_progress' to immediately hand over the main chain to the task chain and wake the assignee agent. "
                    "Use this when the task should start right away."
                ),
            },
        }, required=["group_id", "title", "assignee_agent_name"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            _logger.info(
                "[CreateTaskProcessor] CHECK_ARGS_FAILED packet_id=%s metadata=%s",
                packet.id, {k: v for k, v in packet.metadata.items() if k != "requester"},
            )
            return err
        args = _extract_builtin_content(packet)
        _logger.info(
            "[CreateTaskProcessor] ENTER packet_id=%s group_id=%s title=%s assignee=%s status=%s",
            packet.id,
            args.get("group_id"),
            args.get("title"),
            args.get("assignee_agent_name"),
            args.get("status"),
        )
        return safe_run_async(
            packet,
            self._adapter.create_task(
                group_id=args["group_id"],
                title=args["title"],
                description=args.get("description", ""),
                assignee_agent_name=args.get("assignee_agent_name"),
                inherit_main_chain=args.get("inherit_main_chain", True),
                status=args.get("status"),
            ),
            context="create_task",
        )


class ListTasksProcessor(BuiltinProcessor):
    kind = "list_tasks"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_tasks"):
        super().__init__(name=name, description="List tasks in a group.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
        }, required=["group_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_tasks(args["group_id"]),
            context="list_tasks",
        )


class UpdateTaskStatusProcessor(BuiltinProcessor):
    kind = "update_task_status"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "update_task_status"):
        super().__init__(name=name, description="Update a task's status.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "task_id": {"type": "string", "description": "Task ID."},
            "status": {"type": "string", "description": "New status (e.g. pending, in_progress, completed, cancelled)."},
            "result": {"type": "string", "description": "Optional. Short result/description to mount on the main chain when status=done. If omitted, only the status-change event is mounted."},
        }, required=["task_id", "status"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.update_task_status(
                task_id=args["task_id"],
                status=args["status"],
                result=args.get("result", ""),
            ),
            context="update_task_status",
        )


# ── Deliverable ──


class CreateDeliverableProcessor(BuiltinProcessor):
    kind = "create_deliverable"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "create_deliverable"):
        super().__init__(name=name, description="Create a deliverable for a group.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
            "title": {"type": "string", "description": "Deliverable title."},
            "content": {"type": "string", "description": "Deliverable content."},
            "scope": {"type": "string", "description": "Visibility scope: 'project' (visible to all project agents, default) or 'group' (only visible in this group)."},
        }, required=["group_id", "title"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.create_deliverable(
                group_id=args["group_id"],
                title=args["title"],
                content=args.get("content", ""),
                scope=args.get("scope", "project"),
            ),
            context="create_deliverable",
        )


class ListDeliverablesProcessor(BuiltinProcessor):
    kind = "list_deliverables"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_deliverables"):
        super().__init__(name=name, description="List deliverables in a group.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
        }, required=["group_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_deliverables(args["group_id"]),
            context="list_deliverables",
        )


# ── Message ──


class SendMessageProcessor(BuiltinProcessor):
    kind = "send_message"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "send_message"):
        super().__init__(name=name, description="Send a message to a group chat.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "Group ID."},
            "content": {"type": "string", "description": "Message content."},
        }, required=["group_id", "content"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.send_message(
                group_id=args["group_id"],
                content=args["content"],
            ),
            context="send_message",
            timeout=240.0,
        )


# ── Memory ──


class SetMemoryProcessor(BuiltinProcessor):
    kind = "set_memory"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "set_memory"):
        super().__init__(name=name, description="Create or update agent notes/memory, classified by slug. Supports multiple update modes.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID."},
            "project_id": {"type": "string", "description": "Project ID."},
            "content": {"type": "string", "description": "Memory content (Markdown). For replace_globally mode this is the replacement text. For rewrite_section mode this is the new section body (without the heading)."},
            "slug": {
                "type": "string",
                "description": "Classification slug (e.g. decisions, watchouts, state_snapshot, group_focus).",
                "default": "default",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for retrieval.",
            },
            "mode": {
                "type": "string",
                "enum": ["replace", "append", "replace_globally", "rewrite_section"],
                "description": "Update mode: 'replace' = full content replacement (default), 'append' = add to end, 'replace_globally' = find & replace (needs find+replace_with), 'rewrite_section' = replace a ## section (needs section_heading).",
                "default": "replace",
            },
            "find": {
                "type": "string",
                "description": "String to find in existing content. Required when mode='replace_globally'.",
            },
            "replace_with": {
                "type": "string",
                "description": "Replacement string. Used when mode='replace_globally'. Defaults to empty string if omitted.",
            },
            "section_heading": {
                "type": "string",
                "description": "The ## heading to find and replace its section content. Required when mode='rewrite_section'. Do not include the ## prefix.",
            },
        }, required=["agent_id", "project_id", "content"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        
        # 安全校验：用 _current_agent_id 覆盖 LLM 传入的 agent_id
        # 防止 LLM 误写其他 agent 的记忆
        import logging
        logger = logging.getLogger(__name__)
        caller_agent_id = getattr(self._adapter, '_current_agent_id', None)
        provided_agent_id = args.get("agent_id")
        if caller_agent_id and provided_agent_id != caller_agent_id:
            logger.warning(
                "[set_memory] AGENT_ID OVERRIDE: caller=%s provided=%s, using caller",
                caller_agent_id[:8] if caller_agent_id else "NONE",
                provided_agent_id[:8] if provided_agent_id else "NONE",
            )
            args["agent_id"] = caller_agent_id
        elif not provided_agent_id and caller_agent_id:
            args["agent_id"] = caller_agent_id
        
        requester = packet.metadata.get("requester") if packet.metadata else None
        logger.info(
            "[set_memory] agent_id=%s project_id=%s slug=%s requester=%s content_preview=%s",
            args.get("agent_id", "NONE")[:8] if args.get("agent_id") else "NONE",
            args.get("project_id", "NONE")[:8] if args.get("project_id") else "NONE",
            args.get("slug", "default"),
            requester or "UNKNOWN",
            (args.get("content") or "")[:100],
        )

        # v2 P2+: 把 set_memory 结果包成 (return_value, error_packet) 元组, 让 ResultCollector
        # 能识别异常并把 tool_result 真实地反馈给 LLM (避免 LLM 看不到错误而陷入循环)
        from .async_bridge import safe_run_async
        result_or_error = safe_run_async(
            packet,
            self._adapter.set_memory(
                agent_id=args["agent_id"],
                project_id=args["project_id"],
                content=args["content"],
                slug=args.get("slug", "default"),
                tags=args.get("tags"),
                mode=args.get("mode", "replace"),
                find=args.get("find"),
                replace_with=args.get("replace_with"),
                section_heading=args.get("section_heading"),
            ),
            context="set_memory",
        )
        # set_memory 实际结果记录 (诊断: LLM 是否能看到 set_memory 成功/失败)
        if isinstance(result_or_error, tuple) and len(result_or_error) == 2:
            ret_val, err_pkt = result_or_error
            if err_pkt is not None:
                logger.info(
                    "[set_memory] EXCEPTION: err_packet=%s",
                    getattr(err_pkt, 'message', '?')[:200],
                )
            else:
                logger.info(
                    "[set_memory] DONE: result_preview=%s",
                    repr(ret_val)[:200] if ret_val is not None else "None",
                )
        return result_or_error


# 向后兼容别名
class CreateMemoryProcessor(SetMemoryProcessor):
    """向后兼容：create_memory kind → set_memory"""
    kind = "create_memory"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "create_memory"):
        super().__init__(adapter=adapter, name=name)


class GetMemoryProcessor(BuiltinProcessor):
    kind = "get_memory"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "get_memory"):
        super().__init__(name=name, description="Get agent notes/memory by slug.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID."},
            "project_id": {"type": "string", "description": "Project ID."},
            "slug": {
                "type": "string",
                "description": "Classification slug to retrieve.",
                "default": "default",
            },
        }, required=["agent_id", "project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.get_memory(
                agent_id=args["agent_id"],
                project_id=args["project_id"],
                slug=args.get("slug", "default"),
            ),
            context="get_memory",
        )


class ListMemoriesProcessor(BuiltinProcessor):
    kind = "list_memories"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_memories"):
        super().__init__(name=name, description="List all of an agent's memory entries in a project (one per slug).")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID."},
            "project_id": {"type": "string", "description": "Project ID."},
        }, required=["agent_id", "project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_memories(
                agent_id=args["agent_id"],
                project_id=args["project_id"],
            ),
            context="list_memories",
        )


# ── Agent 管理 ──


class ListAgentsProcessor(BuiltinProcessor):
    kind = "list_agents_db"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_agents_db"):
        super().__init__(name=name, description="List all global agents in the database.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "active_only": {"type": "boolean", "description": "Only return active agents."},
        })

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_agents(
                active_only=bool(args.get("active_only", False)),
            ),
            context="list_agents_db",
        )


class GetAgentProcessor(BuiltinProcessor):
    kind = "get_agent_db"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "get_agent_db"):
        super().__init__(name=name, description="Get agent details including tools and skills.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID."},
        }, required=["agent_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.get_agent(agent_id=args["agent_id"]),
            context="get_agent_db",
        )


class CreateAgentDBProcessor(BuiltinProcessor):
    kind = "create_agent_db"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "create_agent_db"):
        super().__init__(name=name, description="Create a new global agent in the database.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "name": {"type": "string", "description": "Agent name."},
            "system_prompt": {"type": "string", "description": "System prompt defining agent behavior."},
            "role": {"type": "string", "description": "Role type: writer/critic/researcher/planner/editor/coder/designer/custom."},
            "description": {"type": "string", "description": "Agent description."},
            "avatar": {"type": "string", "description": "Avatar emoji or URL."},
            "llm_config": {"type": "object", "description": "LLM config, e.g. {model, temperature, max_tokens}."},
            "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Capability tags."},
        }, required=["name", "system_prompt"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.create_agent(
                name=args["name"],
                system_prompt=args["system_prompt"],
                role=args.get("role", "custom"),
                description=args.get("description", ""),
                avatar=args.get("avatar", "🤖"),
                llm_config=args.get("llm_config"),
                capabilities=args.get("capabilities"),
            ),
            context="create_agent_db",
        )


class UpdateAgentDBProcessor(BuiltinProcessor):
    kind = "update_agent_db"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "update_agent_db"):
        super().__init__(name=name, description="Update an existing global agent.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "agent_id": {"type": "string", "description": "Agent ID to update."},
            "name": {"type": "string", "description": "New agent name."},
            "system_prompt": {"type": "string", "description": "New system prompt."},
            "role": {"type": "string", "description": "New role type."},
            "description": {"type": "string", "description": "New description."},
            "avatar": {"type": "string", "description": "New avatar."},
            "llm_config": {"type": "object", "description": "New LLM config."},
            "capabilities": {"type": "array", "items": {"type": "string"}, "description": "New capability tags."},
            "is_active": {"type": "boolean", "description": "Enable/disable agent."},
        }, required=["agent_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.update_agent(
                agent_id=args["agent_id"],
                name=args.get("name"),
                system_prompt=args.get("system_prompt"),
                role=args.get("role"),
                description=args.get("description"),
                avatar=args.get("avatar"),
                llm_config=args.get("llm_config"),
                capabilities=args.get("capabilities"),
                is_active=args.get("is_active"),
            ),
            context="update_agent_db",
        )


# ── Web ──


class WebSearchProcessor(BuiltinProcessor):
    kind = "web_search"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "web_search"):
        super().__init__(name=name, description="Search the web for information. Returns a list of search results with titles, URLs, and snippets.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "query": {"type": "string", "description": "Search query string."},
            "max_results": {"type": "integer", "description": "Maximum number of results to return (default 5)."},
        }, required=["query"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.web_search(
                query=args["query"],
                max_results=args.get("max_results", 5),
            ),
            context="web_search",
        )


class FetchUrlProcessor(BuiltinProcessor):
    kind = "fetch_url"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "fetch_url"):
        super().__init__(name=name, description="Fetch a webpage and extract its text content. Supports HTML pages and JSON APIs.")
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "url": {"type": "string", "description": "The URL to fetch."},
            "max_chars": {"type": "integer", "description": "Maximum characters to return (default 8000)."},
        }, required=["url"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.fetch_url(
                url=args["url"],
                max_chars=args.get("max_chars", 8000),
            ),
            context="fetch_url",
        )


class PageInjectProcessor(BuiltinProcessor):
    kind = "page_inject"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "page_inject"):
        super().__init__(name=name, description=(
            "Inject JavaScript into the current page. Runs entirely in the browser. "
            "Use this to add event listeners, modify DOM, create interactive behaviors. "
            "Event callbacks execute directly in JS - no round-trip to agent. "
            "Write self-contained code with addEventListener for user interactions."
        ))
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "js_code": {"type": "string", "description": "JavaScript code to inject and execute in the page."},
            "description": {"type": "string", "description": "Brief description of what this code does (shown to user)."},
        }, required=["js_code"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        result = safe_run_async(
            packet,
            self._adapter.page_inject(
                js_code=args["js_code"],
                description=args.get("description", ""),
            ),
            context="page_inject",
        )
        # 将 inject_js 写入 metadata，前端会读取并执行
        inject_js = args["js_code"]
        result.add_metadata("inject_js", inject_js)
        result.add_metadata("inject_description", args.get("description", ""))
        return result


# ── v2 P1: 原子能力 Processors ──


class QueryActivityProcessor(BuiltinProcessor):
    kind = "query_activity"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "query_activity"):
        super().__init__(
            name=name,
            description=(
                "v2 §0.5 原则 6 原子能力: 查询项目活动状态。"
                "返回 last_message_at / last_tool_call_at / active_agent_ids / idle_seconds 等。"
                "agent 按自己 skill 决定什么时候调、拿到结果后做什么。"
            ),
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "project_id": {"type": "string", "description": "Project ID."},
        }, required=["project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.query_activity(project_id=args["project_id"]),
            context="query_activity",
        )


class PingProcessor(BuiltinProcessor):
    kind = "ping"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "ping"):
        super().__init__(
            name=name,
            description=(
                "v2 §0.5 原则 6 原子能力: 系统/agent 给指定 agent 发'催促'。"
                "发的是普通群聊消息（含 reason + context + 候选 agent），"
                "agent 接到后按自己 skill 决定怎么响应。"
                "**不**自动改任何状态。"
            ),
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "group_id": {"type": "string", "description": "群聊 ID."},
            "to_agent_id": {"type": "string", "description": "目标 agent id（可选）."},
            "reason": {"type": "string", "description": "ping 原因（结构化 hint，如 'task_idle'/'blocked'）."},
            "context": {"type": "object", "description": "上下文（task_id 等）."},
            "message": {"type": "string", "description": "自定义消息（不传则用模板）."},
        }, required=["group_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.ping(
                group_id=args["group_id"],
                to_agent_id=args.get("to_agent_id"),
                reason=args.get("reason", "ping"),
                context=args.get("context"),
                message=args.get("message"),
            ),
            context="ping",
            timeout=240.0,
        )


class SubscribeEventProcessor(BuiltinProcessor):
    kind = "subscribe_event"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "subscribe_event"):
        super().__init__(
            name=name,
            description=(
                "订阅事件。\n"
                "入参: event_type, subscriber_agent_id, project_id, group_id?, target_agent_id?\n"
                "返回: {success, event_type, subscriber_agent_id, target_agent_id, project_id, group_id, note}\n"
                "note='内存订阅, 重启会丢'。\n"
                "事件发生时, 系统会给你发 [系统通知] 消息。\n"
                "事件类型: task_status_changed / resource_created / resource_updated / group_status_changed。"
            ),
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "event_type": {
                "type": "string",
                "description": "task_status_changed / resource_created / resource_updated / group_status_changed",
            },
            "subscriber_agent_id": {
                "type": "string",
                "description": "订阅者的 agent id（通常是你自己, 调 get_agent_db 获取）",
            },
            "project_id": {
                "type": "string",
                "description": "项目 ID",
            },
            "group_id": {
                "type": "string",
                "description": "群聊 ID（可选, 限定订阅范围）",
            },
            "target_agent_id": {
                "type": "string",
                "description": "被通知的 agent id（可选, 默认=subscriber_agent_id）",
            },
        }, required=["event_type", "project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        # 兼容 LLM 漏传 subscriber_agent_id 的情况：从执行上下文拿
        subscriber_agent_id = args.get("subscriber_agent_id")
        if not subscriber_agent_id:
            # 尝试从 packet 元数据 / 上下文推断
            subscriber_agent_id = (
                getattr(packet, "sender_id", None)
                or packet.get_metadata("agent_id")
                or packet.get_metadata("caller_agent_id")
            )
        if not subscriber_agent_id:
            return packet.create_child(
                sender_id=self.sender_id,
                content={
                    "error": (
                        "subscribe_event 工具调用错误: 缺少必填参数 'subscriber_agent_id'。"
                        "请传你自己的 agent id（可调 get_agent_db / db_read_skill 查）。"
                    )
                },
                packet_type=PacketType.RESPONSE,
            )
        return safe_run_async(
            packet,
            self._adapter.subscribe_event(
                event_type=args["event_type"],
                subscriber_agent_id=subscriber_agent_id,
                project_id=args["project_id"],
                group_id=args.get("group_id"),
                target_agent_id=args.get("target_agent_id"),
            ),
            context="subscribe_event",
        )


class UnsubscribeEventProcessor(BuiltinProcessor):
    kind = "unsubscribe_event"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "unsubscribe_event"):
        super().__init__(
            name=name,
            description="v2 P2 原子能力: 取消订阅。",
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "event_type": {"type": "string", "description": "事件类型."},
            "subscriber_agent_id": {
                "type": "string",
                "description": "你的 agent id. 漏传时本工具自动从上下文推断.",
            },
            "project_id": {"type": "string", "description": "项目 ID."},
            "group_id": {"type": "string", "description": "群聊 ID（可选, 进一步限定）."},
        }, required=["event_type", "project_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        subscriber_agent_id = args.get("subscriber_agent_id")
        if not subscriber_agent_id:
            subscriber_agent_id = (
                getattr(packet, "sender_id", None)
                or packet.get_metadata("agent_id")
                or packet.get_metadata("caller_agent_id")
            )
        if not subscriber_agent_id:
            return packet.create_child(
                sender_id=self.sender_id,
                content={
                    "error": (
                        "unsubscribe_event 工具调用错误: 缺少必填参数 'subscriber_agent_id'。"
                    )
                },
                packet_type=PacketType.RESPONSE,
            )
        return safe_run_async(
            packet,
            self._adapter.unsubscribe_event(
                event_type=args["event_type"],
                subscriber_agent_id=subscriber_agent_id,
                project_id=args["project_id"],
                group_id=args.get("group_id"),
            ),
            context="unsubscribe_event",
        )


class ListSubscriptionsProcessor(BuiltinProcessor):
    kind = "list_subscriptions"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "list_subscriptions"):
        super().__init__(
            name=name,
            description="v2 §0.5 原则 6 原子能力: 列出某 agent 的所有订阅（调试/查看用）.",
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "subscriber_agent_id": {"type": "string", "description": "订阅者 agent id."},
        }, required=["subscriber_agent_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.list_subscriptions(subscriber_agent_id=args["subscriber_agent_id"]),
            context="list_subscriptions",
        )


# ── DB 持久化订阅 (订阅机制 v1) ──────────────────────────
# 与上面的内存版 subscribe_event 不同, 这组 processor 操作 DB 表 subscriptions,
# 支持群/agent 通用订阅, 事件触发时执行预定义动作 (注入消息/通知/创建任务).
# 适合场景: G5 订阅 G4 完成事件 → 自动启动 G5 工作.


class CreateSubscriptionProcessor(BuiltinProcessor):
    """创建事件订阅 (DB 持久化).

    用途: 让群/agent 订阅某个事件, 事件触发时按预设动作执行 (默认: 注入消息到订阅者).
    典型场景: G5 群订阅 G4 完成事件 → G4 完成时自动唤醒 G5 接力工作.
    """
    kind = "create_subscription"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "create_subscription"):
        super().__init__(
            name=name,
            description=(
                "创建事件订阅 (DB 持久化, 重启不丢)。\n"
                "让群/agent 订阅某个事件, 事件触发时执行预设动作 (注入消息/通知/创建任务)。\n"
                "典型场景: 上游群完成后自动唤醒下游群接力工作。\n\n"
                "入参:\n"
                "  subscriber_type: 'group' 或 'agent'\n"
                "  subscriber_id: 订阅者 ID (群 ID 或 agent ID)\n"
                "  event_type: 事件类型\n"
                "  filter: 过滤条件 (可选, JSON object)\n"
                "  action: 触发动作 (默认 'trigger_as_message')\n"
                "  message_template: 消息模板, 支持 {field} 占位符 (可选)\n"
                "  one_shot: 是否一次性 (默认 false)\n\n"
                "事件类型 event_type 可选值:\n"
                "  - group_status_changed: 群状态变化 (如 G4 完成)\n"
                "  - task_status_changed: 任务状态变化\n"
                "  - resource_created: 资源创建\n"
                "  - resource_updated: 资源更新\n\n"
                "filter 常用字段:\n"
                "  - group_id: 限定事件来源群 ID\n"
                "  - new_status: 限定新状态 (如 'completed')\n"
                "  - resource_type: 限定资源类型\n\n"
                "action 可选值:\n"
                "  - trigger_as_message: 渲染模板并注入消息到订阅者 (默认)\n"
                "  - trigger_as_notification: 仅发 WS 通知\n"
                "  - trigger_as_task: 创建任务 (暂未实现)\n\n"
                "message_template 支持 {field} 占位符, 字段来自事件 payload.\n"
                "例: '上游群 {group_id} 已 {new_status}, 请基于其产出开始你的工作'"
            ),
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "subscriber_type": {
                "type": "string",
                "description": "订阅者类型: 'group' 或 'agent'",
                "enum": ["group", "agent"],
            },
            "subscriber_id": {
                "type": "string",
                "description": "订阅者 ID (群 ID 或 agent ID)",
            },
            "event_type": {
                "type": "string",
                "description": "事件类型 (group_status_changed / task_status_changed / resource_created / resource_updated)",
                "enum": [
                    "group_status_changed",
                    "task_status_changed",
                    "resource_created",
                    "resource_updated",
                ],
            },
            "filter": {
                "type": "object",
                "description": "事件过滤条件 (JSON object), 例 {\"group_id\":\"G4\",\"new_status\":\"completed\"}",
            },
            "action": {
                "type": "string",
                "description": "触发动作 (默认 trigger_as_message)",
                "enum": ["trigger_as_message", "trigger_as_notification", "trigger_as_task"],
            },
            "message_template": {
                "type": "string",
                "description": "消息模板, 支持 {field} 占位符 (字段来自事件 payload)",
            },
            "one_shot": {
                "type": "boolean",
                "description": "是否一次性 (true=触发后自动禁用, false=持续)",
            },
        }, required=["subscriber_type", "subscriber_id", "event_type"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.create_subscription(
                subscriber_type=args["subscriber_type"],
                subscriber_id=args["subscriber_id"],
                event_type=args["event_type"],
                filter=args.get("filter"),
                action=args.get("action", "trigger_as_message"),
                message_template=args.get("message_template"),
                one_shot=args.get("one_shot", False),
            ),
            context="create_subscription",
        )


class DeleteSubscriptionProcessor(BuiltinProcessor):
    """删除事件订阅 (DB)."""
    kind = "delete_subscription"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "delete_subscription"):
        super().__init__(
            name=name,
            description="删除事件订阅 (DB 持久化). 入参: subscription_id.",
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "subscription_id": {
                "type": "string",
                "description": "订阅 ID (从 create_subscription 返回或 query_subscriptions 查得)",
            },
        }, required=["subscription_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.delete_subscription(subscription_id=args["subscription_id"]),
            context="delete_subscription",
        )


class QuerySubscriptionsProcessor(BuiltinProcessor):
    """列出订阅 (DB)."""
    kind = "query_subscriptions"

    def __init__(self, adapter: "ToolServiceAdapter", name: str = "query_subscriptions"):
        super().__init__(
            name=name,
            description=(
                "列出订阅 (DB 持久化). 列出某订阅者的所有事件订阅.\n"
                "入参: subscriber_type ('group'/'agent'), subscriber_id."
            ),
        )
        self._adapter = adapter

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {
            "subscriber_type": {
                "type": "string",
                "description": "订阅者类型",
                "enum": ["group", "agent"],
            },
            "subscriber_id": {
                "type": "string",
                "description": "订阅者 ID",
            },
        }, required=["subscriber_type", "subscriber_id"])

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        if err := self._check_required_args(packet):
            return err
        args = _extract_builtin_content(packet)
        return safe_run_async(
            packet,
            self._adapter.query_subscriptions(
                subscriber_type=args["subscriber_type"],
                subscriber_id=args["subscriber_id"],
            ),
            context="query_subscriptions",
        )
