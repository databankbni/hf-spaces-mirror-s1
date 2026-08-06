from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from .agent import Agent
from .manager import InfoManager
from .id_generator import IDGenerator
from .packet import InfoPacket, PacketType, thaw_value
from .processor import Processor
from .specs import AgentSpec, BuiltinProcessorConfig, LLMConfig
from .llm.base import LLMResponse
from .skills import (
    default_skill_roots,
    list_skill_files,
    load_skills_from_roots,
    normalize_skill_roots,
    resolve_skill_resource,
)

if TYPE_CHECKING:
    from .workspace import Workspace
    from .tool_adapter import ToolServiceAdapter


def _function_schema(
    name: str,
    description: str,
    properties: Dict[str, Dict[str, Any]],
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _stringify_content(content: Any) -> str:
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return str(content)


def _extract_builtin_content(packet: InfoPacket) -> Dict[str, Any]:
    content = packet.content if isinstance(packet.content, dict) else {}
    arguments = content.get("arguments")
    if isinstance(arguments, dict):
        # Handle double-nested pattern: {"arguments": "<json_string>"} -> parse inner string
        if "arguments" in arguments and isinstance(arguments["arguments"], str):
            try:
                parsed = json.loads(arguments["arguments"])
                if isinstance(parsed, dict):
                    return thaw_value(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        return thaw_value(arguments)
    return thaw_value(content)


class BuiltinProcessor(Processor):
    kind: str = "builtin"

    def __init__(
        self,
        name: str,
        description: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name)
        self.description = description
        self.config = config or {}

    def to_config(self) -> BuiltinProcessorConfig:
        return BuiltinProcessorConfig(
            kind=self.kind,
            name=self.name,
            description=self.description,
            config=dict(self.config),
        )

    # ── v2 P2: 工具入参校验统一化 ──────────────────────────
    def _check_required_args(self, packet: InfoPacket) -> Optional[InfoPacket]:
        """
        统一入参校验：从 get_schema() 中读 function.parameters.required，
        逐个检查 args（兼容双层嵌套）是否存在/非空。
        缺失时返回一个 error packet（不是抛异常）, 让 LLM 收到明确错误并重试。

        用法（子类 core_process 入口）:
            def core_process(self, packet):
                if err := self._check_required_args(packet):
                    return err
                args = _extract_builtin_content(packet)
                ...

        行为:
          - schema 无 required → 直接返回 None（不做检查）
          - 必填字段缺失/空 → 返回 error packet，content 包含缺失字段名 + 提示
          - 不抛异常（避免 Processor._process 把异常转成模糊的 ERROR packet）
        """
        try:
            schema = self.get_schema()
        except Exception:
            schema = None
        if not schema:
            return None

        try:
            params = schema.get("function", {}).get("parameters", {}) or {}
            required = params.get("required") or []
        except Exception:
            return None
        if not required:
            return None

        args = _extract_builtin_content(packet) or {}
        missing = [k for k in required if not args.get(k)]
        if not missing:
            return None

        missing_list = ", ".join(missing)
        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "error": (
                    f"{self.name} 工具调用错误: 缺少必填参数: {missing_list}。"
                    f"请参考工具 schema 描述后重试。"
                ),
                "missing_args": missing,
            },
            packet_type=PacketType.RESPONSE,
        )


class FileReadProcessor(BuiltinProcessor):
    kind = "read_file"

    def __init__(
        self,
        name: str = "read_file",
        base_path: Optional[Union[str, Path]] = None,
        encoding: str = "utf-8",
        max_chars: int = 20000,
    ):
        super().__init__(
            name=name,
            description="Read a text file from the project and optionally return only a line range.",
            config={
                "base_path": str(Path(base_path).resolve()) if base_path else None,
                "encoding": encoding,
                "max_chars": max_chars,
            },
        )
        self.base_path = Path(base_path).resolve() if base_path else None
        self.encoding = encoding
        self.max_chars = max_chars

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "path": {"type": "string", "description": "The target file path, relative to the base path when configured."},
                "start_line": {"type": "integer", "description": "Optional 1-based start line."},
                "end_line": {"type": "integer", "description": "Optional 1-based end line."},
            },
            required=["path"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        target_path = self._resolve_path(content["path"])
        raw_text = target_path.read_text(encoding=self.encoding)

        start_line = content.get("start_line")
        end_line = content.get("end_line")
        lines = raw_text.splitlines()

        if start_line or end_line:
            start_index = max((start_line or 1) - 1, 0)
            end_index = end_line or len(lines)
            selected_text = "\n".join(lines[start_index:end_index])
        else:
            selected_text = raw_text

        truncated = len(selected_text) > self.max_chars
        if truncated:
            selected_text = selected_text[: self.max_chars]

        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "path": str(target_path),
                "content": selected_text,
                "truncated": truncated,
                "line_count": len(lines),
            },
            packet_type=PacketType.RESPONSE,
        )

    def _resolve_path(self, raw_path: str) -> Path:
        target = Path(raw_path)
        if not target.is_absolute() and self.base_path is not None:
            target = self.base_path / target
        target = target.resolve()
        if self.base_path is not None and self.base_path not in target.parents and target != self.base_path:
            raise ValueError(f"Path '{target}' is outside the configured base path.")
        if not target.exists():
            raise FileNotFoundError(f"File '{target}' does not exist.")
        if not target.is_file():
            raise ValueError(f"Path '{target}' is not a file.")
        return target


class FileWriteProcessor(BuiltinProcessor):
    kind = "write_file"

    def __init__(
        self,
        name: str = "write_file",
        base_path: Optional[Union[str, Path]] = None,
        encoding: str = "utf-8",
        allow_overwrite: bool = True,
        create_dirs: bool = True,
    ):
        super().__init__(
            name=name,
            description="Write or append text to a file in the project.",
            config={
                "base_path": str(Path(base_path).resolve()) if base_path else None,
                "encoding": encoding,
                "allow_overwrite": allow_overwrite,
                "create_dirs": create_dirs,
            },
        )
        self.base_path = Path(base_path).resolve() if base_path else None
        self.encoding = encoding
        self.allow_overwrite = allow_overwrite
        self.create_dirs = create_dirs

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "path": {"type": "string", "description": "The target file path, relative to the base path when configured."},
                "content": {"type": "string", "description": "The text content to write."},
                "append": {"type": "boolean", "description": "When true, append instead of overwriting."},
            },
            required=["path", "content"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        target_path = self._resolve_path(content["path"])
        append = bool(content.get("append", False))

        if target_path.exists() and not append and not self.allow_overwrite:
            raise FileExistsError(f"File '{target_path}' already exists and overwriting is disabled.")

        if self.create_dirs:
            target_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        text = str(content["content"])
        with target_path.open(mode, encoding=self.encoding) as handle:
            handle.write(text)

        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "path": str(target_path),
                "bytes_written": len(text.encode(self.encoding)),
                "append": append,
            },
            packet_type=PacketType.RESPONSE,
        )

    def _resolve_path(self, raw_path: str) -> Path:
        target = Path(raw_path)
        if not target.is_absolute() and self.base_path is not None:
            target = self.base_path / target
        target = target.resolve()
        if self.base_path is not None and self.base_path not in target.parents and target != self.base_path:
            raise ValueError(f"Path '{target}' is outside the configured base path.")
        return target


class FileSearchProcessor(BuiltinProcessor):
    kind = "search_files"

    def __init__(
        self,
        name: str = "search_files",
        base_path: Optional[Union[str, Path]] = None,
        max_results: int = 20,
    ):
        super().__init__(
            name=name,
            description="Search for text across project files.",
            config={
                "base_path": str(Path(base_path).resolve()) if base_path else None,
                "max_results": max_results,
            },
        )
        self.base_path = Path(base_path or ".").resolve()
        self.max_results = max_results

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "query": {"type": "string", "description": "The text query to search for."},
                "path": {"type": "string", "description": "Optional subdirectory to search in."},
                "pattern": {"type": "string", "description": "Optional filename glob pattern."},
                "case_sensitive": {"type": "boolean", "description": "Whether the search is case-sensitive."},
            },
            required=["query"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        query = str(content["query"])
        pattern = str(content.get("pattern", "*"))
        case_sensitive = bool(content.get("case_sensitive", False))
        search_root = self._resolve_root(content.get("path"))

        matches = []
        needle = query if case_sensitive else query.lower()
        for candidate in search_root.rglob(pattern):
            if not candidate.is_file():
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(
                        {
                            "path": str(candidate),
                            "line": line_no,
                            "content": line.strip(),
                        }
                    )
                    if len(matches) >= self.max_results:
                        return packet.create_child(
                            sender_id=self.sender_id,
                            content={"query": query, "matches": matches, "truncated": True},
                            packet_type=PacketType.RESPONSE,
                        )

        return packet.create_child(
            sender_id=self.sender_id,
            content={"query": query, "matches": matches, "truncated": False},
            packet_type=PacketType.RESPONSE,
        )

    def _resolve_root(self, raw_path: Optional[str]) -> Path:
        if raw_path:
            target = Path(raw_path)
            if not target.is_absolute():
                target = self.base_path / target
            target = target.resolve()
        else:
            target = self.base_path

        if self.base_path not in target.parents and target != self.base_path:
            raise ValueError(f"Search root '{target}' is outside the configured base path.")
        return target


class BashProcessor(BuiltinProcessor):
    kind = "run_bash"

    def __init__(
        self,
        name: str = "run_bash",
        workdir: Optional[Union[str, Path]] = None,
        timeout_secs: int = 30,
    ):
        super().__init__(
            name=name,
            description="Execute a shell command inside the configured working directory.",
            config={
                "workdir": str(Path(workdir).resolve()) if workdir else str(Path.cwd()),
                "timeout_secs": timeout_secs,
            },
        )
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.timeout_secs = timeout_secs

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "command": {"type": "string", "description": "The shell command to execute."},
                "timeout_secs": {"type": "integer", "description": "Optional timeout override in seconds."},
            },
            required=["command"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        command = str(content["command"])
        timeout_secs = int(content.get("timeout_secs", self.timeout_secs))

        if os.name == "nt":
            cmd = ["powershell", "-NoProfile", "-Command", command]
        else:
            cmd = ["/bin/bash", "-lc", command]

        completed = subprocess.run(
            cmd,
            cwd=self.workdir,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
        )

        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "command": command,
                "workdir": str(self.workdir),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
            packet_type=PacketType.RESPONSE,
        )


class PythonExecProcessor(BuiltinProcessor):
    kind = "run_python"

    def __init__(
        self,
        name: str = "run_python",
        workdir: Optional[Union[str, Path]] = None,
        timeout_secs: int = 30,
    ):
        super().__init__(
            name=name,
            description="Execute inline Python code with the current Python interpreter.",
            config={
                "workdir": str(Path(workdir).resolve()) if workdir else str(Path.cwd()),
                "timeout_secs": timeout_secs,
            },
        )
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.timeout_secs = timeout_secs

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "code": {"type": "string", "description": "The inline Python code to execute."},
                "timeout_secs": {"type": "integer", "description": "Optional timeout override in seconds."},
            },
            required=["code"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        code = str(content["code"])
        timeout_secs = int(content.get("timeout_secs", self.timeout_secs))

        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.workdir,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
        )

        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
            packet_type=PacketType.RESPONSE,
        )


class HistoryQueryProcessor(BuiltinProcessor):
    kind = "query_history"

    def __init__(
        self,
        manager: InfoManager,
        workspace: Optional["Workspace"] = None,
        name: str = "query_history",
        max_results: int = 20,
    ):
        super().__init__(
            name=name,
            description="Query stored packet history by chain, sender, packet type, or text.",
            config={"max_results": max_results},
        )
        self.manager = manager
        self.workspace = workspace
        self.max_results = max_results

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "chain_id": {"type": "string", "description": "Optional chain id. Defaults to the current packet chain."},
                "query": {"type": "string", "description": "Optional text to search in packet content."},
                "sender_id": {"type": "string", "description": "Optional sender id filter."},
                "packet_type": {"type": "string", "description": "Optional packet type filter."},
                "mode": {"type": "string", "description": "Internal use only. Leave default 'search' unless directed by rollover metadata."},
                "requester_chain_id": {"type": "string", "description": "Optional requester chain when querying a previous chain."},
                "agent_name": {"type": "string", "description": "Optional agent name to answer from the previous chain context."},
                "read_only": {"type": "boolean", "description": "Whether the previous-chain query should avoid mutating history."},
                "limit": {"type": "integer", "description": "Optional maximum number of results."},
            },
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        mode = str(content.get("mode", "search"))
        if mode == "chain-switch":
            return self._query_with_chain_switch(packet, content)

        chain_id = content.get("chain_id") or packet.chain_id
        query = content.get("query")
        sender_id = content.get("sender_id")
        packet_type = content.get("packet_type")
        limit = int(content.get("limit", self.max_results))

        packets = self.manager.get_by_chain_id(chain_id)
        results = []
        for current in packets:
            if sender_id and current.sender_id != sender_id:
                continue
            if packet_type and current.type.value != packet_type:
                continue
            if query and query.lower() not in _stringify_content(current.content).lower():
                continue
            results.append(current.to_dict())
            if len(results) >= limit:
                break

        return packet.create_child(
            sender_id=self.sender_id,
            content={"chain_id": chain_id, "results": results},
            packet_type=PacketType.RESPONSE,
        )

    def _query_with_chain_switch(self, packet: InfoPacket, content: Dict[str, Any]) -> InfoPacket:
        requester_chain_id = content.get("requester_chain_id") or packet.chain_id
        source_chain_id = content.get("chain_id") or self._resolve_previous_chain_id(requester_chain_id)
        if not source_chain_id:
            # 容错：当 LLM 主动调用但当前 chain 没有 rollover metadata 时，
            # 不要污染整轮对话 — 退化为在当前 chain 上做普通 search，
            # 并把意图（想查旧 chain）以 warning 形式回传给 LLM。
            warning = (
                "[history notice] chain-switch 模式在当前 chain 上未找到前序 chain。"
                "已自动在当前 chain 上做 search。如需查早前对话，请提供准确的 chain_id。"
            )
            packets = self.manager.get_by_chain_id(requester_chain_id)
            results = []
            query = str(content.get("query", "")).strip()
            limit = int(content.get("limit", self.max_results))
            for current in packets:
                if current.type == PacketType.STREAM or current.get_metadata("rollover_handoff"):
                    continue
                if query and query.lower() not in _stringify_content(current.content).lower():
                    continue
                results.append(current.to_dict())
                if len(results) >= limit:
                    break
            return packet.create_child(
                sender_id=self.sender_id,
                content={
                    "chain_id": requester_chain_id,
                    "source_chain_id": requester_chain_id,
                    "results": results,
                    "fallback": "chain-switch fell back to current chain",
                    "warning": warning,
                },
                packet_type=PacketType.RESPONSE,
            )

        query = str(content.get("query", "")).strip()
        limit = int(content.get("limit", self.max_results))
        read_only = bool(content.get("read_only", True))
        agent_name = content.get("agent_name")

        packets = self.manager.get_by_chain_id(source_chain_id)
        results = []
        for current in packets:
            if current.type == PacketType.STREAM or current.get_metadata("rollover_handoff"):
                continue
            if query and query.lower() not in _stringify_content(current.content).lower():
                continue
            results.append(current.to_dict())
            if len(results) >= limit:
                break

        answer = None
        if agent_name and self.workspace is not None:
            answer = self._answer_from_chain_context(
                agent_name=agent_name,
                source_chain_id=source_chain_id,
                query=query or "请总结这个链里与当前问题最相关的信息。",
            )

        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "chain_id": source_chain_id,
                "source_chain_id": source_chain_id,
                "requester_chain_id": requester_chain_id,
                "mode": "chain-switch",
                "read_only": read_only,
                "results": results,
                "answer": answer,
            },
            packet_type=PacketType.RESPONSE,
        )

    def _resolve_previous_chain_id(self, requester_chain_id: str) -> Optional[str]:
        packets = self.manager.get_by_chain_id(requester_chain_id)
        for current in packets:
            previous = current.get_metadata("rollover_from_chain")
            if previous:
                return previous
        return None

    def _answer_from_chain_context(self, agent_name: str, source_chain_id: str, query: str) -> Optional[str]:
        agent = self.workspace.get_agent(agent_name) if self.workspace is not None else None
        if agent is None or getattr(agent, "llm", None) is None:
            return None

        synthetic_packet = InfoPacket(
            id=IDGenerator.generate_packet_id(agent.sender_id, PacketType.NORMAL.value),
            sender_id="history_query",
            parent_id=None,
            chain_id=source_chain_id,
            content=query,
            type=PacketType.NORMAL,
            timestamp=datetime.now(),
        )

        messages = agent._build_messages(synthetic_packet)
        response = asyncio.run(agent.llm.chat(messages, tools=None))
        return response.content if isinstance(response, LLMResponse) else None


class SkillCatalogProcessor(BuiltinProcessor):
    kind = "list_skills"

    def __init__(
        self,
        name: str = "list_skills",
        skill_roots: Optional[List[Union[str, Path]]] = None,
        max_results: int = 200,
    ):
        normalized_roots = [str(root) for root in normalize_skill_roots(skill_roots)]
        super().__init__(
            name=name,
            description="List installed local skills and their descriptions.",
            config={"skill_roots": normalized_roots, "max_results": max_results},
        )
        self.skill_roots = normalized_roots
        self.max_results = max_results

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "query": {"type": "string", "description": "Optional substring to filter skill names and descriptions."},
            },
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        query = str(content.get("query", "")).lower().strip()

        skills = load_skills_from_roots(self.skill_roots)
        if query:
            skills = [
                skill
                for skill in skills
                if query in skill.name.lower()
                or query in skill.description.lower()
                or query in Path(skill.path).parent.name.lower()
            ]
        items = []
        for skill in skills[: self.max_results]:
            payload = skill.to_summary_dict()
            payload["files"] = list_skill_files(skill)
            items.append(payload)

        return packet.create_child(
            sender_id=self.sender_id,
            content={"skills": items},
            packet_type=PacketType.RESPONSE,
        )


class SkillReadProcessor(BuiltinProcessor):
    kind = "read_skill"

    def __init__(
        self,
        name: str = "read_skill",
        skill_roots: Optional[List[Union[str, Path]]] = None,
        max_chars: int = 12000,
    ):
        normalized_roots = [str(root) for root in normalize_skill_roots(skill_roots)]
        super().__init__(
            name=name,
            description="Read the SKILL.md content for a named local skill.",
            config={"skill_roots": normalized_roots, "max_chars": max_chars},
        )
        self.skill_roots = normalized_roots
        self.max_chars = max_chars

    def get_schema(self) -> Dict[str, Any]:
        description = self._build_description()
        return _function_schema(
            self.name,
            description,
            {
                "name": {
                    "type": "string",
                    "description": (
                        "Use 'skill_name' to read SKILL.md, or 'skill_name/filename' to read a top-level file in that skill."
                    ),
                },
            },
            required=["name"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        requested = str(content["name"])
        resource = resolve_skill_resource(requested, self.skill_roots)
        resource_path = Path(resource.path)
        text = resource_path.read_text(encoding="utf-8")
        truncated = len(text) > self.max_chars
        if truncated:
            text = text[: self.max_chars]

        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "name": resource.skill.name,
                "path": str(resource_path),
                "relative_path": resource.relative_path,
                "description": resource.skill.description,
                "content": text,
                "truncated": truncated,
                "skill": resource.skill.to_summary_dict(),
                "available_files": list(resource.available_files),
            },
            packet_type=PacketType.RESPONSE,
        )

    def _build_description(self) -> str:
        base = (
            "Read a skill file from the configured skill library. "
            "Use 'skill_name' for SKILL.md, or 'skill_name/filename' for a top-level attached file."
        )
        skills = load_skills_from_roots(self.skill_roots)
        if not skills:
            return base

        summary_parts: List[str] = []
        total_chars = 0
        for skill in skills:
            summary = f"{skill.name}: {skill.description or 'No description'}"
            if total_chars + len(summary) > 1000 and summary_parts:
                break
            summary_parts.append(summary)
            total_chars += len(summary)

        if not summary_parts:
            return base
        return f"{base} Available skills: {'; '.join(summary_parts)}."


class AgentCatalogProcessor(BuiltinProcessor):
    kind = "list_agents"

    def __init__(self, workspace: "Workspace", name: str = "list_agents"):
        super().__init__(
            name=name,
            description="List registered agents and processors in the current workspace.",
            config={},
        )
        self.workspace = workspace

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(self.name, self.description, {})

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "agents": self.workspace.list_agents(),
                "processors": self.workspace.list_processors(),
            },
            packet_type=PacketType.RESPONSE,
        )


class AgentExportProcessor(BuiltinProcessor):
    kind = "export_agent"

    def __init__(self, workspace: "Workspace", name: str = "export_agent"):
        super().__init__(
            name=name,
            description="Export a registered agent into a serializable agent spec.",
            config={},
        )
        self.workspace = workspace

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {"name": {"type": "string", "description": "The registered agent name."}},
            required=["name"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        exported = self.workspace.export_agent_spec(content["name"])
        return packet.create_child(
            sender_id=self.sender_id,
            content=exported.to_dict(),
            packet_type=PacketType.RESPONSE,
        )


class AgentCreateProcessor(BuiltinProcessor):
    kind = "create_agent"

    def __init__(
        self,
        workspace: "Workspace",
        default_llm_config: Optional[Union[LLMConfig, Dict[str, Any]]] = None,
        name: str = "create_agent",
    ):
        normalized_llm = None
        if default_llm_config is not None:
            normalized_llm = default_llm_config if isinstance(default_llm_config, LLMConfig) else LLMConfig.from_dict(default_llm_config)

        super().__init__(
            name=name,
            description="Create and register a new agent from a serializable agent spec.",
            config={"default_llm_config": normalized_llm.to_dict() if normalized_llm else None},
        )
        self.workspace = workspace
        self.default_llm_config = normalized_llm

    def get_schema(self) -> Dict[str, Any]:
        return _function_schema(
            self.name,
            self.description,
            {
                "spec": {"type": "object", "description": "The agent spec dictionary."},
                "replace_existing": {"type": "boolean", "description": "Whether to replace an existing agent with the same name."},
            },
            required=["spec"],
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        content = _extract_builtin_content(packet)
        spec = AgentSpec.from_dict(content["spec"])
        if spec.llm_config is None and self.default_llm_config is not None:
            spec.llm_config = self.default_llm_config
        created_agent = self.workspace.create_agent_from_spec(
            spec,
            replace_existing=bool(content.get("replace_existing", False)),
        )
        return packet.create_child(
            sender_id=self.sender_id,
            content={
                "name": created_agent.name,
                "tools": [target.name for target in created_agent._call_targets],
            },
            packet_type=PacketType.RESPONSE,
        )


def create_builtin_processor(
    config: Union[BuiltinProcessorConfig, Dict[str, Any]],
    workspace: Optional["Workspace"] = None,
    default_llm_config: Optional[Union[LLMConfig, Dict[str, Any]]] = None,
) -> Processor:
    builtin_config = config if isinstance(config, BuiltinProcessorConfig) else BuiltinProcessorConfig.from_dict(config)
    kind = builtin_config.kind
    options = dict(builtin_config.config)
    name = builtin_config.name

    if kind == "read_file":
        return FileReadProcessor(name=name or "read_file", **options)
    if kind == "write_file":
        return FileWriteProcessor(name=name or "write_file", **options)
    if kind == "search_files":
        return FileSearchProcessor(name=name or "search_files", **options)
    if kind == "run_bash":
        return BashProcessor(name=name or "run_bash", **options)
    if kind == "run_python":
        return PythonExecProcessor(name=name or "run_python", **options)
    if kind == "query_history":
        manager = workspace.info_manager if workspace is not None else options.pop("manager", None)
        if manager is None:
            raise ValueError("query_history requires a workspace or manager.")
        return HistoryQueryProcessor(manager=manager, workspace=workspace, name=name or "query_history", **options)
    # ── File-system Skill processors (CLI-only, blocked in server mode) ──
    # 服务端模式下 Agent 不应感知本地文件系统，只能通过 db_list_skills/db_read_skill 访问数据库
    _fs_skill_kinds = {"list_skills", "read_skill"}
    if kind in _fs_skill_kinds:
        if workspace is not None and workspace.tool_adapter is not None:
            raise ValueError(
                f"'{kind}' is not available in server mode. "
                f"Use 'db_{kind}' instead (db_list_skills / db_read_skill)."
            )
        if kind == "list_skills":
            return SkillCatalogProcessor(name=name or "list_skills", **options)
        return SkillReadProcessor(name=name or "read_skill", **options)
    if kind == "list_agents":
        if workspace is None:
            raise ValueError("list_agents requires a workspace.")
        return AgentCatalogProcessor(workspace=workspace, name=name or "list_agents")
    if kind == "export_agent":
        if workspace is None:
            raise ValueError("export_agent requires a workspace.")
        return AgentExportProcessor(workspace=workspace, name=name or "export_agent")
    if kind == "create_agent":
        if workspace is None:
            raise ValueError("create_agent requires a workspace.")
        return AgentCreateProcessor(
            workspace=workspace,
            default_llm_config=default_llm_config or options.pop("default_llm_config", None),
            name=name or "create_agent",
        )

    # ── Render View processor ──
    if kind == "render_view":
        from .render_processors import RenderViewProcessor
        return RenderViewProcessor(name=name or "render_view")

    # ── CRUD processors (require workspace.tool_adapter) ──
    _crud_kinds = {
        "create_project", "list_projects", "get_project",
        "query_projects", "list_templates", "pick_template",
        "create_group", "list_groups", "get_group", "update_group", "delete_group",
        "invite_agent", "list_project_agents",
        "add_group_member", "list_group_members",
        "create_task", "list_tasks", "update_task_status",
        "create_deliverable", "list_deliverables",
        "send_message",
        "set_memory", "create_memory", "get_memory", "list_memories",
        "web_search", "fetch_url", "page_inject",
        "list_agents_db", "get_agent_db", "create_agent_db", "update_agent_db",
        # v2 P1: 原子能力
        "query_activity", "ping", "subscribe_event", "unsubscribe_event", "list_subscriptions",
        # 订阅机制 v1 (DB 持久化)
        "create_subscription", "delete_subscription", "query_subscriptions",
    }
    if kind in _crud_kinds:
        if workspace is None or workspace.tool_adapter is None:
            raise ValueError(f"'{kind}' requires workspace with tool_adapter.")
        from .crud_processors import (
            CreateProjectProcessor, ListProjectsProcessor, GetProjectProcessor,
            QueryProjectsProcessor, ListTemplatesProcessor, PickTemplateProcessor,
            CreateGroupProcessor, ListGroupsProcessor, GetGroupProcessor, UpdateGroupProcessor, DeleteGroupProcessor,
            InviteAgentProcessor, ListProjectAgentsProcessor,
            AddGroupMemberProcessor, ListGroupMembersProcessor,
            CreateTaskProcessor, ListTasksProcessor, UpdateTaskStatusProcessor,
            CreateDeliverableProcessor, ListDeliverablesProcessor,
            SendMessageProcessor,
            SetMemoryProcessor, CreateMemoryProcessor, GetMemoryProcessor, ListMemoriesProcessor,
            ListAgentsProcessor, GetAgentProcessor, CreateAgentDBProcessor, UpdateAgentDBProcessor,
            WebSearchProcessor, FetchUrlProcessor,
            PageInjectProcessor,
            # v2 P1 / P2
            QueryActivityProcessor, PingProcessor, SubscribeEventProcessor, UnsubscribeEventProcessor, ListSubscriptionsProcessor,
            # 订阅机制 v1 (DB 持久化)
            CreateSubscriptionProcessor, DeleteSubscriptionProcessor, QuerySubscriptionsProcessor,
        )
        _crud_map = {
            "create_project": CreateProjectProcessor,
            "list_projects": ListProjectsProcessor,
            "get_project": GetProjectProcessor,
            "query_projects": QueryProjectsProcessor,
            "list_templates": ListTemplatesProcessor,
            "pick_template": PickTemplateProcessor,
            "create_group": CreateGroupProcessor,
            "list_groups": ListGroupsProcessor,
            "get_group": GetGroupProcessor,
            "update_group": UpdateGroupProcessor,
            "delete_group": DeleteGroupProcessor,
            "invite_agent": InviteAgentProcessor,
            "list_project_agents": ListProjectAgentsProcessor,
            "add_group_member": AddGroupMemberProcessor,
            "list_group_members": ListGroupMembersProcessor,
            "create_task": CreateTaskProcessor,
            "list_tasks": ListTasksProcessor,
            "update_task_status": UpdateTaskStatusProcessor,
            "create_deliverable": CreateDeliverableProcessor,
            "list_deliverables": ListDeliverablesProcessor,
            "send_message": SendMessageProcessor,
            "set_memory": SetMemoryProcessor,
            "create_memory": CreateMemoryProcessor,
            "get_memory": GetMemoryProcessor,
            "list_memories": ListMemoriesProcessor,
            "list_agents_db": ListAgentsProcessor,
            "get_agent_db": GetAgentProcessor,
            "create_agent_db": CreateAgentDBProcessor,
            "update_agent_db": UpdateAgentDBProcessor,
            "web_search": WebSearchProcessor,
            "fetch_url": FetchUrlProcessor,
            "page_inject": PageInjectProcessor,
            # v2 P1 / P2
            "query_activity": QueryActivityProcessor,
            "ping": PingProcessor,
            "subscribe_event": SubscribeEventProcessor,
            "unsubscribe_event": UnsubscribeEventProcessor,
            "list_subscriptions": ListSubscriptionsProcessor,
            # 订阅机制 v1 (DB 持久化, group/agent 通用)
            "create_subscription": CreateSubscriptionProcessor,
            "delete_subscription": DeleteSubscriptionProcessor,
            "query_subscriptions": QuerySubscriptionsProcessor,
        }
        cls = _crud_map[kind]
        return cls(adapter=workspace.tool_adapter, name=name or kind)

    # ── Resource processors (require workspace.tool_adapter) ──
    _resource_kinds = {"read_resource", "write_resource", "search_resources"}
    if kind in _resource_kinds:
        if workspace is None or workspace.tool_adapter is None:
            raise ValueError(f"'{kind}' requires workspace with tool_adapter.")
        from .resource_processors import (
            ResourceReadProcessor, ResourceWriteProcessor, ResourceSearchProcessor,
        )
        _resource_map = {
            "read_resource": ResourceReadProcessor,
            "write_resource": ResourceWriteProcessor,
            "search_resources": ResourceSearchProcessor,
        }
        cls = _resource_map[kind]
        return cls(adapter=workspace.tool_adapter, name=name or kind)

    # ── DB Skill processors (require workspace.tool_adapter) ──
    _skill_kinds = {"db_list_skills", "db_read_skill", "db_list_skill_files"}
    if kind in _skill_kinds:
        if workspace is None or workspace.tool_adapter is None:
            raise ValueError(f"'{kind}' requires workspace with tool_adapter.")
        from .db_skill_processors import DBSkillCatalogProcessor, DBSkillReadProcessor, DBSkillListFilesProcessor
        _skill_map = {
            "db_list_skills": DBSkillCatalogProcessor,
            "db_read_skill": DBSkillReadProcessor,
            "db_list_skill_files": DBSkillListFilesProcessor,
        }
        cls = _skill_map[kind]
        return cls(adapter=workspace.tool_adapter, name=name or kind)

    raise ValueError(f"Unsupported builtin processor kind '{kind}'.")


def create_project_toolset(
    base_path: Union[str, Path],
    workspace: "Workspace",
    default_llm_config: Optional[Union[LLMConfig, Dict[str, Any]]] = None,
    skill_roots: Optional[List[Union[str, Path]]] = None,
) -> List[Processor]:
    resolved_base = Path(base_path).resolve()
    configs = [
        BuiltinProcessorConfig(kind="read_file", config={"base_path": str(resolved_base)}),
        BuiltinProcessorConfig(kind="write_file", config={"base_path": str(resolved_base)}),
        BuiltinProcessorConfig(kind="search_files", config={"base_path": str(resolved_base)}),
        BuiltinProcessorConfig(kind="run_bash", config={"workdir": str(resolved_base)}),
        BuiltinProcessorConfig(kind="run_python", config={"workdir": str(resolved_base)}),
        BuiltinProcessorConfig(kind="query_history"),
        BuiltinProcessorConfig(kind="list_agents"),
        BuiltinProcessorConfig(kind="export_agent"),
        BuiltinProcessorConfig(kind="create_agent"),
        BuiltinProcessorConfig(kind="render_view"),
    ]

    # 当 workspace 有 tool_adapter 时，追加 CRUD/Resource/DB Skill 工具
    # （Agent 通过数据库获取 Skill，不感知本地文件系统）
    if workspace.tool_adapter is not None:
        configs.extend([
            BuiltinProcessorConfig(kind="create_project"),
            BuiltinProcessorConfig(kind="list_projects"),
            BuiltinProcessorConfig(kind="get_project"),
            BuiltinProcessorConfig(kind="create_group"),
            BuiltinProcessorConfig(kind="list_groups"),
            BuiltinProcessorConfig(kind="get_group"),
            BuiltinProcessorConfig(kind="update_group"),
            BuiltinProcessorConfig(kind="delete_group"),
            BuiltinProcessorConfig(kind="invite_agent"),
            BuiltinProcessorConfig(kind="list_project_agents"),
            BuiltinProcessorConfig(kind="add_group_member"),
            BuiltinProcessorConfig(kind="list_group_members"),
            BuiltinProcessorConfig(kind="create_task"),
            BuiltinProcessorConfig(kind="list_tasks"),
            BuiltinProcessorConfig(kind="update_task_status"),
            BuiltinProcessorConfig(kind="create_deliverable"),
            BuiltinProcessorConfig(kind="list_deliverables"),
            BuiltinProcessorConfig(kind="send_message"),
            BuiltinProcessorConfig(kind="set_memory"),
            BuiltinProcessorConfig(kind="create_memory"),  # 向后兼容
            BuiltinProcessorConfig(kind="get_memory"),
            BuiltinProcessorConfig(kind="list_agents_db"),
            BuiltinProcessorConfig(kind="get_agent_db"),
            BuiltinProcessorConfig(kind="create_agent_db"),
            BuiltinProcessorConfig(kind="update_agent_db"),
            BuiltinProcessorConfig(kind="read_resource"),
            BuiltinProcessorConfig(kind="write_resource"),
            BuiltinProcessorConfig(kind="search_resources"),
            BuiltinProcessorConfig(kind="db_list_skills"),
            BuiltinProcessorConfig(kind="db_read_skill"),
            BuiltinProcessorConfig(kind="db_list_skill_files"),
        ])

    return [
        create_builtin_processor(config, workspace=workspace, default_llm_config=default_llm_config)
        for config in configs
    ]
