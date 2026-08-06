"""
工具目录注册表

集中定义所有内置工具的展示元数据（分类、中文标签、详细说明、参数描述）。
后端 API 从此注册表生成工具目录，前端动态加载，保持单一数据源。

添加新工具时，只需在此文件中添加一条 TOOL_CATALOG_ENTRIES 记录即可。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ── 数据结构 ──

class ToolParamDef:
    """工具参数定义"""
    def __init__(
        self,
        key: str,
        label: str,
        type: str = "string",
        required: bool = False,
        placeholder: str = "",
        default: Optional[str] = None,
    ):
        self.key = key
        self.label = label
        self.type = type
        self.required = required
        self.placeholder = placeholder
        self.default = default

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
        }
        if self.required:
            d["required"] = True
        if self.placeholder:
            d["placeholder"] = self.placeholder
        if self.default is not None:
            d["default"] = self.default
        return d


class ToolCatalogEntry:
    """工具目录条目"""
    def __init__(
        self,
        kind: str,
        name: str,
        description: str,
        detail: str,
        category: str,
        params: Optional[List[ToolParamDef]] = None,
        recommended: bool = False,
    ):
        self.kind = kind
        self.name = name
        self.description = description
        self.detail = detail
        self.category = category
        self.params = params or []
        self.recommended = recommended

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "detail": self.detail,
            "category": self.category,
            "params": [p.to_dict() for p in self.params],
            "recommended": self.recommended,
        }


# ── 分类定义 ──

CATEGORY_LABELS: Dict[str, Dict[str, str]] = {
    "file": {"label": "文件操作", "icon": "📄"},
    "shell": {"label": "命令执行", "icon": "💻"},
    "memory": {"label": "记忆与历史", "icon": "🧠"},
    "skill": {"label": "技能管理", "icon": "⚡"},
    "agent": {"label": "Agent 管理", "icon": "🤖"},
    "project": {"label": "项目管理", "icon": "📁"},
    "group": {"label": "群聊管理", "icon": "💬"},
    "task": {"label": "任务管理", "icon": "✅"},
    "resource": {"label": "资源管理", "icon": "📦"},
    "render": {"label": "数据渲染", "icon": "🎨"},
    "web": {"label": "网络访问", "icon": "🌐"},
    "event": {"label": "事件订阅", "icon": "🔔"},
}


# ── 工具目录条目 ──

TOOL_CATALOG_ENTRIES: List[ToolCatalogEntry] = [
    # ── 文件操作 ──
    ToolCatalogEntry(
        kind="read_file",
        name="读取文件",
        description="读取项目中的文本文件，支持指定行范围",
        detail="从项目目录中读取文本文件内容。支持通过起止行号只读取文件的指定片段，超过最大字符数时自动截断。路径相对于项目根目录，不允许访问项目外的文件。",
        category="file",
        recommended=True,
        params=[
            ToolParamDef("path", "文件路径", required=True, placeholder="src/main.py"),
            ToolParamDef("start_line", "起始行号", type="number", placeholder="1（从第 1 行开始）"),
            ToolParamDef("end_line", "结束行号", type="number", placeholder="100"),
        ],
    ),
    ToolCatalogEntry(
        kind="write_file",
        name="写入文件",
        description="创建或覆写项目中的文件",
        detail="将文本内容写入项目中的文件。如果文件不存在会自动创建（包括父目录）。支持覆写模式和追加模式。当配置为不允许覆写时，已存在的文件会报错。",
        category="file",
        recommended=True,
        params=[
            ToolParamDef("path", "文件路径", required=True, placeholder="output/result.txt"),
            ToolParamDef("content", "写入内容", required=True, placeholder="要写入的文本内容"),
            ToolParamDef("append", "追加模式", type="boolean", placeholder="true = 追加，false = 覆写（默认）"),
        ],
    ),
    ToolCatalogEntry(
        kind="search_files",
        name="搜索文件",
        description="在项目文件中搜索文本内容",
        detail="在项目目录中递归搜索包含指定文本的文件。支持文件名 glob 过滤和大小写控制。返回匹配的文件路径、行号和内容。结果数量有上限，防止输出过大。",
        category="file",
        recommended=True,
        params=[
            ToolParamDef("query", "搜索关键词", required=True, placeholder="def main"),
            ToolParamDef("path", "搜索子目录", placeholder="src（限定搜索范围）"),
            ToolParamDef("pattern", "文件名匹配", placeholder="*.py（glob 模式）"),
            ToolParamDef("case_sensitive", "区分大小写", type="boolean", placeholder="默认 false"),
        ],
    ),

    # ── 命令执行 ──
    ToolCatalogEntry(
        kind="run_bash",
        name="执行 Shell",
        description="在项目目录中执行 Shell 命令",
        detail="在项目工作目录中执行 Shell 命令（Windows 使用 PowerShell，Linux/macOS 使用 bash）。返回退出码、标准输出和标准错误。有超时限制，防止命令挂起。",
        category="shell",
        params=[
            ToolParamDef("command", "Shell 命令", required=True, placeholder="npm install"),
            ToolParamDef("timeout_secs", "超时秒数", type="number", placeholder="默认 30 秒"),
        ],
    ),
    ToolCatalogEntry(
        kind="run_python",
        name="执行 Python",
        description="执行内联 Python 代码",
        detail="使用当前 Python 解释器执行内联代码。在项目工作目录下运行，返回退出码、标准输出和标准错误。适合数据处理、计算、文件操作等脚本任务。",
        category="shell",
        params=[
            ToolParamDef("code", "Python 代码", required=True, placeholder='print("Hello World")'),
            ToolParamDef("timeout_secs", "超时秒数", type="number", placeholder="默认 30 秒"),
        ],
    ),

    # ── 记忆与历史 ──
    ToolCatalogEntry(
        kind="query_history",
        name="查询历史",
        description="查询消息历史记录，支持文本搜索和链切换",
        detail="查询消息历史记录。支持按链 ID、发送者、消息类型、文本内容进行过滤搜索。还支持 chain-switch 模式，从之前的链上下文中获取信息，用于跨轮次的知识延续。",
        category="memory",
        recommended=True,
        params=[
            ToolParamDef("chain_id", "链 ID", placeholder="默认当前链"),
            ToolParamDef("query", "搜索文本", placeholder="关键词过滤"),
            ToolParamDef("sender_id", "发送者 ID", placeholder="按发送者过滤"),
            ToolParamDef("packet_type", "消息类型", placeholder="normal/response/stream"),
            ToolParamDef("mode", "查询模式", placeholder="留空默认 search"),
            ToolParamDef("limit", "结果上限", type="number", placeholder="默认 20"),
        ],
    ),
    ToolCatalogEntry(
        kind="set_memory",
        name="写入记忆",
        description="创建或更新 Agent 在项目中的笔记（按 slug 分类，支持多种更新模式）",
        detail="为指定 Agent 在指定项目中创建或更新记忆笔记，按 slug 分类。支持四种更新模式：replace（全量替换，默认）、append（追加到末尾）、replace_globally（全文查找替换）、rewrite_section（按 Markdown 标题替换整个 section）。跨会话、跨群聊保留。",
        category="memory",
        recommended=True,
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="Agent 唯一标识"),
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目唯一标识"),
            ToolParamDef("content", "记忆内容", required=True, placeholder="要记录的笔记内容（Markdown）"),
            ToolParamDef("slug", "分类 slug", required=False, default="default", placeholder="decisions / watchouts / state_snapshot / group_focus / ..."),
            ToolParamDef("tags", "标签", type="array", required=False, placeholder="便于检索的标签"),
            ToolParamDef("mode", "更新模式", required=False, default="replace", placeholder="replace / append / replace_globally / rewrite_section"),
            ToolParamDef("find", "查找字符串", required=False, placeholder="mode=replace_globally 时要查找的字符串"),
            ToolParamDef("replace_with", "替换为", required=False, placeholder="mode=replace_globally 时替换为的字符串"),
            ToolParamDef("section_heading", "Section 标题", required=False, placeholder="mode=rewrite_section 时要替换的 ## 标题（不含 ## 前缀）"),
        ],
    ),
    ToolCatalogEntry(
        kind="create_memory",
        name="写入记忆（旧版）",
        description="创建或更新 Agent 笔记（兼容旧版，推荐使用 set_memory）",
        detail="兼容旧版的 create_memory 工具，功能与 set_memory(mode='replace') 相同。推荐使用 set_memory 以获得 append/replace_globally/rewrite_section 等更新模式。",
        category="memory",
        recommended=False,
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="Agent 唯一标识"),
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目唯一标识"),
            ToolParamDef("content", "记忆内容", required=True, placeholder="要记录的笔记内容（Markdown）"),
            ToolParamDef("slug", "分类 slug", required=False, default="default", placeholder="decisions / watchouts / state_snapshot / group_focus / ..."),
            ToolParamDef("tags", "标签", type="array", required=False, placeholder="便于检索的标签"),
        ],
    ),
    ToolCatalogEntry(
        kind="get_memory",
        name="读取记忆",
        description="获取 Agent 在项目中的笔记（按 slug）",
        detail="读取指定 Agent 在指定项目下指定 slug 的记忆笔记。如果该 slug 不存在则返回空。",
        category="memory",
        recommended=True,
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="Agent 唯一标识"),
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目唯一标识"),
            ToolParamDef("slug", "分类 slug", required=False, default="default", placeholder="decisions / watchouts / state_snapshot / group_focus / ..."),
        ],
    ),
    ToolCatalogEntry(
        kind="list_memories",
        name="列出我的所有笔记",
        description="列出 Agent 在项目下的所有 slug 笔记",
        detail="返回 Agent 在项目下的所有记忆条目（按 slug 分类），含每条的 slug、content 前 200 字预览、tags 和 updated_at。适合做自我盘点。",
        category="memory",
        recommended=False,
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="Agent 唯一标识"),
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目唯一标识"),
        ],
    ),

    # ── 技能管理 ──
    ToolCatalogEntry(
        kind="db_list_skills",
        name="浏览技能",
        description="列出 Agent 可用的技能",
        detail="从数据库中获取指定 Agent 绑定的所有技能列表。返回技能名称、类型、描述和配置信息。用于查询 Agent 的技能配置。",
        category="skill",
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="Agent 唯一标识"),
        ],
    ),
    ToolCatalogEntry(
        kind="db_read_skill",
        name="读取技能",
        description="读取指定技能的完整内容",
        detail="从数据库中读取指定 Agent 的某个技能的完整内容，包括提示词模板、配置等。用于获取技能的详细信息以执行或分析。",
        category="skill",
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="Agent 唯一标识"),
            ToolParamDef("skill_name", "技能名称", required=True, placeholder="要读取的技能名"),
        ],
    ),

    # ── Agent 管理 ──
    ToolCatalogEntry(
        kind="list_agents",
        name="列出 Agent",
        description="列出当前工作区中注册的 Agent 和处理器",
        detail="列出当前 agentflow 运行时工作区中所有已注册的 Agent 和处理器。返回 Agent 名称列表和处理器列表。用于了解当前运行环境中有哪些可用的 Agent。",
        category="agent",
        params=[],
    ),
    ToolCatalogEntry(
        kind="export_agent",
        name="导出 Agent",
        description="将已注册的 Agent 导出为可序列化的 spec",
        detail="将工作区中已注册的 Agent 导出为 AgentSpec 序列化格式。导出内容包括 Agent 名称、系统提示词、LLM 配置、工具列表等。可用于备份或迁移 Agent 配置。",
        category="agent",
        params=[
            ToolParamDef("name", "Agent 名称", required=True, placeholder="已注册的 Agent 名称"),
        ],
    ),
    ToolCatalogEntry(
        kind="create_agent",
        name="创建运行时 Agent",
        description="从 spec 创建并注册一个新的运行时 Agent",
        detail="从 AgentSpec 字典创建并注册一个新的运行时 Agent。如果同名 Agent 已存在，可选择是否替换。创建后 Agent 立即可用。返回创建的 Agent 名称和工具列表。",
        category="agent",
        params=[
            ToolParamDef("spec", "Agent Spec", required=True, placeholder="JSON 格式的 Agent 配置对象"),
            ToolParamDef("replace_existing", "替换已有", type="boolean", placeholder="true = 替换同名 Agent"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_agents_db",
        name="列出 DB Agent",
        description="列出数据库中的所有全局 Agent",
        detail="从数据库中获取所有全局 Agent 列表。可选择只返回启用状态的 Agent。返回 Agent 基本信息（名称、角色、描述等）。",
        category="agent",
        params=[
            ToolParamDef("active_only", "仅启用", type="boolean", placeholder="true = 只返回启用的 Agent"),
        ],
    ),
    ToolCatalogEntry(
        kind="get_agent_db",
        name="查看 Agent 详情",
        description="获取数据库中 Agent 的详细信息（含工具和技能）",
        detail="从数据库中获取指定 Agent 的完整详情，包括绑定的工具列表、技能列表、LLM 配置、能力标签等。用于全面了解一个 Agent 的配置。",
        category="agent",
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="Agent 唯一标识"),
        ],
    ),
    ToolCatalogEntry(
        kind="create_agent_db",
        name="创建 DB Agent",
        description="在数据库中创建新的全局 Agent",
        detail="在数据库中创建一个新的全局 Agent。需要提供名称和系统提示词，可选配置角色、描述、头像、LLM 参数和能力标签。创建后的 Agent 可被项目引用和加入群聊。",
        category="agent",
        params=[
            ToolParamDef("name", "Agent 名称", required=True, placeholder="如：产品经理"),
            ToolParamDef("system_prompt", "系统提示词", required=True, placeholder="定义 Agent 行为的提示词"),
            ToolParamDef("role", "角色类型", placeholder="writer/critic/researcher/planner/editor/coder/designer/custom"),
            ToolParamDef("description", "描述", placeholder="Agent 的简要描述"),
            ToolParamDef("avatar", "头像", placeholder="emoji 或 URL"),
            ToolParamDef("llm_config", "LLM 配置", placeholder="JSON: {model, temperature, max_tokens}"),
            ToolParamDef("capabilities", "能力标签", placeholder='JSON 数组: ["写作","翻译"]'),
        ],
    ),
    ToolCatalogEntry(
        kind="update_agent_db",
        name="更新 DB Agent",
        description="更新数据库中的全局 Agent 信息",
        detail="更新数据库中已有 Agent 的信息。只需传入要修改的字段，未传入的字段保持不变。可更新名称、提示词、角色、描述、LLM 配置、启用状态等。",
        category="agent",
        params=[
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="要更新的 Agent ID"),
            ToolParamDef("name", "新名称", placeholder="留空则不修改"),
            ToolParamDef("system_prompt", "新提示词", placeholder="留空则不修改"),
            ToolParamDef("role", "新角色", placeholder="留空则不修改"),
            ToolParamDef("description", "新描述", placeholder="留空则不修改"),
            ToolParamDef("avatar", "新头像", placeholder="留空则不修改"),
            ToolParamDef("llm_config", "新 LLM 配置", placeholder="留空则不修改"),
            ToolParamDef("is_active", "启用/禁用", type="boolean", placeholder="true/false"),
        ],
    ),

    # ── 项目管理 ──
    ToolCatalogEntry(
        kind="create_project",
        name="创建项目",
        description="创建一个新项目",
        detail="在系统中创建一个新项目。需要提供项目名称，可选提供描述。项目是 Agent 协作的顶层容器，包含群聊、资源、任务等。",
        category="project",
        params=[
            ToolParamDef("name", "项目名称", required=True, placeholder="如：新产品研发"),
            ToolParamDef("description", "项目描述", placeholder="项目的简要说明"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_projects",
        name="列出项目",
        description="列出所有项目",
        detail="获取系统中所有项目的列表。返回项目名称、描述、状态、群聊数量、Agent 数量等概览信息。",
        category="project",
        params=[],
    ),
    ToolCatalogEntry(
        kind="get_project",
        name="查看项目",
        description="获取项目详情",
        detail="获取指定项目的详细信息，包括项目设置、关联的群聊列表、Agent 列表、任务统计等。",
        category="project",
        params=[
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目唯一标识"),
        ],
    ),

    # ── 系统级工具（引导 agent 跨 project 操作） ──
    ToolCatalogEntry(
        kind="query_projects",
        name="查询用户项目",
        description="列出用户的所有项目（排除引导 project）",
        detail="列出系统中所有用户项目，自动排除 is_guide=True 的引导 project。引导 agent 用此工具了解用户已有项目，决定是继续已有项目还是创建新的。",
        category="project",
        params=[],
    ),
    ToolCatalogEntry(
        kind="list_templates",
        name="列出项目模板",
        description="列出所有可用的项目模板",
        detail="列出系统中所有可用的项目模板。每个模板包含预配置的 agents/groups/skills/resources。引导 agent 用此工具给用户推荐合适的模板。",
        category="project",
        params=[],
    ),
    ToolCatalogEntry(
        kind="pick_template",
        name="应用模板建项目",
        description="应用项目模板创建新项目",
        detail="应用指定模板创建新项目，自动创建模板中定义的所有 agents/groups/skills/resources。引导 agent 确认用户需求后，用此工具一键建出完整项目结构。",
        category="project",
        params=[
            ToolParamDef("template_id", "模板 ID", required=True, placeholder="如 novel-writing"),
            ToolParamDef("project_name", "项目名称", required=True, placeholder="新项目名称"),
            ToolParamDef("project_description", "项目描述", placeholder="项目简要说明"),
            ToolParamDef("project_targets", "目标配置", placeholder="JSON: {word_count, chapter_count} 等目标覆盖"),
        ],
    ),

    # ── 群聊管理 ──
    ToolCatalogEntry(
        kind="create_group",
        name="创建群聊",
        description="在项目中创建新的群聊",
        detail="在指定项目中创建一个新的群聊。群聊是 Agent 之间协作对话的场所。需要项目 ID 和群聊名称，可选描述。",
        category="group",
        params=[
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="所属项目 ID"),
            ToolParamDef("name", "群聊名称", required=True, placeholder="如：产品讨论组"),
            ToolParamDef("description", "群聊描述", placeholder="群聊的用途说明"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_groups",
        name="列出群聊",
        description="列出项目中的所有群聊",
        detail="获取指定项目中所有群聊的列表。返回群聊名称、描述、成员数量、任务数量等信息。",
        category="group",
        params=[
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目 ID"),
        ],
    ),
    ToolCatalogEntry(
        kind="get_group",
        name="查看群聊详情",
        description="获取群聊的详细信息",
        detail="根据群聊 ID 获取群聊的完整详情，包括名称、描述、状态、成员列表、任务列表、资源列表等。用于全面了解一个群聊的当前状态。",
        category="group",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="群聊唯一标识"),
        ],
    ),
    ToolCatalogEntry(
        kind="update_group",
        name="更新群聊",
        description="更新群聊的信息",
        detail="更新指定群聊的信息。可修改名称、描述、状态、自主级别、是否自动推进等属性。只需传入要修改的字段，未传入的字段保持不变。",
        category="group",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="要更新的群聊 ID"),
            ToolParamDef("name", "新名称", placeholder="留空则不修改"),
            ToolParamDef("description", "新描述", placeholder="留空则不修改"),
            ToolParamDef("status", "新状态", placeholder="pending/active/completed"),
            ToolParamDef("autonomy_level", "自主级别", placeholder="full_auto/semi_auto/manual"),
            ToolParamDef("auto_advance", "自动推进", type="boolean", placeholder="完成后是否自动推进"),
        ],
    ),
    ToolCatalogEntry(
        kind="delete_group",
        name="删除群聊",
        description="删除指定的群聊",
        detail="软删除指定的群聊。删除后群聊将不再可见，但数据仍保留在数据库中。此操作不可逆，请谨慎使用。",
        category="group",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="要删除的群聊 ID"),
        ],
    ),
    ToolCatalogEntry(
        kind="invite_agent",
        name="邀请 Agent",
        description="邀请 Agent 加入项目",
        detail="将一个全局 Agent 邀请到指定项目中，创建 ProjectAgent 记录。邀请后 Agent 可被加入项目中的群聊。如果 Agent 已在项目中则返回已有记录。",
        category="group",
        params=[
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="目标项目 ID"),
            ToolParamDef("agent_id", "Agent ID", required=True, placeholder="要邀请的 Agent ID"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_project_agents",
        name="列出项目 Agent",
        description="列出项目中的所有 Agent",
        detail="获取指定项目中已邀请的所有 Agent 列表。返回项目 Agent ID、关联的全局 Agent 信息、覆盖配置等。",
        category="group",
        params=[
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目 ID"),
        ],
    ),
    ToolCatalogEntry(
        kind="add_group_member",
        name="添加群成员",
        description="将 Agent 添加到群聊中",
        detail="将项目中的 Agent（ProjectAgent）添加到指定群聊中。可指定成员角色（如 lead/participant）。添加后 Agent 可在群聊中收发消息。",
        category="group",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="目标群聊 ID"),
            ToolParamDef("project_agent_id", "项目 Agent ID", required=True, placeholder="ProjectAgent ID"),
            ToolParamDef("role", "角色", placeholder="默认 member，可设为 lead"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_group_members",
        name="列出群成员",
        description="列出群聊中的所有成员",
        detail="获取指定群聊中的所有成员列表。返回成员 ID、角色、关联的 Agent 信息等。",
        category="group",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="群聊 ID"),
        ],
    ),
    ToolCatalogEntry(
        kind="send_message",
        name="发送消息",
        description="向群聊中发送消息",
        detail="向指定群聊中发送一条文本消息。消息会记录在群聊历史中，所有群成员可以看到。可用于 Agent 之间的信息传递或人类用户向群聊发言。",
        category="group",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="目标群聊 ID"),
            ToolParamDef("content", "消息内容", required=True, placeholder="要发送的消息文本"),
        ],
    ),

    # ── 任务管理 ──
    ToolCatalogEntry(
        kind="create_task",
        name="创建任务",
        description="在群聊中创建新任务（状态为 todo）",
        detail="在指定群聊中创建一个新任务，创建后状态为 todo（待完成）。\n\n任务创建后，你需要显式调 update_task_status(task_id, 'in_progress') 才能让任务进入进行中状态——这会触发 chain 切换（task chain 接管主链）并唤醒 assignee。\n\n不要在 create_task 时直接传 in_progress，状态流转必须分步：\n  1. create_task → todo\n  2. update_task_status(task_id, 'in_progress') → 切 chain + 唤醒 assignee\n  3. assignee 完成后 update_task_status(task_id, 'done', result=...)\n\nv2 P2 任务级开关 inherit_main_chain:\n- true (默认): 任务链上下文继承主链截至分支点的历史\n- false (高敏感场景): task chain 完全隔离, 不读主链历史",
        category="task",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="所属群聊 ID"),
            ToolParamDef("title", "任务标题", required=True, placeholder="如：完成需求文档"),
            ToolParamDef("description", "任务描述", placeholder="任务的详细说明"),
            ToolParamDef("assignee_agent_name", "负责人 Agent 名称", required=True, placeholder="群成员 Agent 显示名称"),
            ToolParamDef("inherit_main_chain", "是否继承主链历史", required=False, placeholder="true(默认,继承)/false(完全隔离)"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_tasks",
        name="列出任务",
        description="列出群聊中的所有任务",
        detail="获取指定群聊中的所有任务列表。返回任务标题、描述、状态、负责人、创建时间等信息。",
        category="task",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="群聊 ID"),
        ],
    ),
    ToolCatalogEntry(
        kind="update_task_status",
        name="更新任务状态",
        description="更新任务的状态（进行中/已完成等）",
        detail="更新指定任务的状态。有效状态：todo（待办）、in_progress（进行中）、done（已完成）、reopened（已重开）。状态流转规则：todo→in_progress→done→reopened→in_progress。状态变更会记录在任务历史中。done 时可选传 result：本次任务的简短结果描述，会作为一条 system 消息挂载到主链（公共群可见），task chain 里的具体过程不会泄露。建议保持 result 简短（一两句话）。",
        category="task",
        params=[
            ToolParamDef("task_id", "任务 ID", required=True, placeholder="要更新的任务 ID"),
            ToolParamDef("status", "新状态", required=True, placeholder="todo/in_progress/done/reopened"),
            ToolParamDef("result", "结果描述", required=False, placeholder="仅 done 时使用：挂到主链的简短结果（一两句话），可选"),
        ],
    ),
    ToolCatalogEntry(
        kind="create_deliverable",
        name="创建交付物",
        description="为群聊创建交付物",
        detail="为指定群聊创建一个交付物。交付物是群聊协作的产出成果，如文档、设计稿、代码等。包含标题和内容，支持版本管理。",
        category="task",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="所属群聊 ID"),
            ToolParamDef("title", "交付物标题", required=True, placeholder="如：产品需求文档 v1"),
            ToolParamDef("content", "交付物内容", placeholder="交付物的正文内容"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_deliverables",
        name="列出交付物",
        description="列出群聊中的所有交付物",
        detail="获取指定群聊中的所有交付物列表。返回交付物标题、内容摘要、类型、版本、创建时间等信息。",
        category="task",
        params=[
            ToolParamDef("group_id", "群聊 ID", required=True, placeholder="群聊 ID"),
        ],
    ),

    # ── 资源管理 ──
    ToolCatalogEntry(
        kind="read_resource",
        name="读取资源",
        description="从项目数据库中读取资源内容",
        detail="根据资源 ID 从项目数据库中读取资源的完整内容。资源是项目中的文档、参考资料等，可被 Agent 引用和查阅。",
        category="resource",
        params=[
            ToolParamDef("resource_id", "资源 ID", required=True, placeholder="资源唯一标识"),
        ],
    ),
    ToolCatalogEntry(
        kind="write_resource",
        name="写入资源",
        description="在项目数据库中创建或更新资源",
        detail="在项目数据库中创建或更新资源。资源可以是文档、参考资料、背景知识等。支持指定资源类型、关联群聊、标记为必读、添加标签（便于按 tag 检索）等。",
        category="resource",
        params=[
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="所属项目 ID"),
            ToolParamDef("title", "资源标题", required=True, placeholder="如：竞品分析报告"),
            ToolParamDef("content", "资源内容", required=True, placeholder="资源正文"),
            ToolParamDef("resource_type", "资源类型", placeholder="note/reference/guideline/rule/custom/map（默认 note）"),
            ToolParamDef("group_id", "关联群聊 ID", placeholder="可选，限定到特定群聊"),
            ToolParamDef("is_required", "是否必读", type="boolean", placeholder="标记为必读资源"),
            ToolParamDef("tags", "标签列表", type="array", placeholder="可选，例：['细纲', '卷一', 'G5']，便于按 tag 检索"),
        ],
    ),
    ToolCatalogEntry(
        kind="search_resources",
        name="搜索资源",
        description="按关键词搜索项目中的资源",
        detail="在指定项目中按关键词搜索资源。搜索范围包括资源标题和内容。返回匹配的资源列表。",
        category="resource",
        params=[
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目 ID"),
            ToolParamDef("query", "搜索关键词", required=True, placeholder="搜索关键词"),
        ],
    ),

    # ── 事件订阅 ──
    ToolCatalogEntry(
        kind="subscribe_event",
        name="订阅事件",
        description="订阅事件。事件发生时, 系统会给你发 [系统通知] 消息。",
        detail="入参: event_type, subscriber_agent_id, project_id, group_id?, target_agent_id?\n返回: {success, event_type, subscriber_agent_id, target_agent_id, project_id, group_id, note}。note='内存订阅, 重启会丢'。\n事件类型: task_status_changed / resource_created / resource_updated / group_status_changed。",
        category="event",
        recommended=True,
        params=[
            ToolParamDef("event_type", "task_status_changed / resource_created / resource_updated / group_status_changed", required=True, placeholder="事件类型"),
            ToolParamDef("subscriber_agent_id", "订阅者的 agent id（通常是调用者自己, 调 get_agent_db 获取）", required=True, placeholder="agent id"),
            ToolParamDef("project_id", "项目 ID", required=True, placeholder="项目 ID"),
            ToolParamDef("group_id", "群聊 ID（可选, 限定订阅范围）", placeholder="不传则监听项目所有群"),
        ],
    ),
    ToolCatalogEntry(
        kind="unsubscribe_event",
        name="取消订阅",
        description="取消事件订阅",
        detail="取消一个或多个事件订阅。不传 project_id/group_id 则全部取消，传 project_id 则仅取消该项目的订阅，依此类推。返回取消数量。",
        category="event",
        params=[
            ToolParamDef("event_type", "事件类型", required=True, placeholder="group_status_changed / task_status_changed / ..."),
            ToolParamDef("subscriber_agent_id", "订阅者 agent id", required=True, placeholder="自己的 agent id"),
            ToolParamDef("project_id", "项目 ID", placeholder="不传则取消该 agent 所有项目订阅"),
            ToolParamDef("group_id", "群聊 ID", placeholder="不传则取消该项目的所有群订阅"),
        ],
    ),
    ToolCatalogEntry(
        kind="list_subscriptions",
        name="列出当前订阅",
        description="列出当前 agent 的所有事件订阅",
        detail="返回该 agent 当前的所有订阅: [{event_type, project_id, group_id}, ...]。用于诊断和清理过期订阅。",
        category="event",
        params=[
            ToolParamDef("subscriber_agent_id", "订阅者 agent id", required=True, placeholder="自己的 agent id"),
        ],
    ),

    # ── 数据渲染 ──
    ToolCatalogEntry(
        kind="render_view",
        name="数据渲染展示",
        description="将数据以表格、树形、列表、文档、卡片、统计、时间线、地图、图谱等视图形式呈现给用户",
        detail="使用此工具将结构化数据以可视化方式呈现给用户。Agent 决定展示什么和怎么展示，前端自动渲染。支持9种视图类型：table（表格）、list（列表）、tree（树形）、document（文档）、card（卡片）、stat（统计指标）、timeline（时间线）、map（地图）、graph（通用 DAG 图谱）。map 类型支持六边形/方格网格、领地渲染、连接线、子地图钻取等；graph 类型支持有向无环图（DAG），节点/边可自定义样式，可用于项目流水线、任务依赖、知识图谱、Agent 协作图等任何 DAG 场景。数据可通过 data 字段内联提供，也可通过 data_source 指定 API 端点让前端自动获取。需要配合 render-view Skill 使用以了解完整配置格式。",
        category="render",
        recommended=True,
        params=[
            ToolParamDef("view_type", "视图类型", required=True, placeholder="table/list/tree/document/card/stat/timeline/map/graph"),
            ToolParamDef("title", "视图标题", placeholder="展示给用户的标题"),
            ToolParamDef("description", "视图描述", placeholder="标题下方的简短说明"),
            ToolParamDef("data", "内联数据", placeholder="JSON 对象，Agent 已有数据时使用"),
            ToolParamDef("data_source", "API 数据源", placeholder="JSON: {api, data_path, params, transform}"),
            ToolParamDef("options", "视图选项", placeholder="JSON: 列定义、排序、分页、图标映射等。graph 类型: {layout, directed, node_render, edge_render}"),
            ToolParamDef("style", "样式配置", placeholder="JSON: {bordered, compact, height}"),
            ToolParamDef("actions", "交互动作", placeholder="JSON 数组: 点击跳转、打开详情等"),
            ToolParamDef("render_target", "渲染目标", placeholder="CSS选择器，如 #my-panel"),
            ToolParamDef("expandable", "可展开全屏", placeholder="true/false"),
        ],
    ),

    # ── 网络访问 ──
    ToolCatalogEntry(
        kind="web_search",
        name="网页搜索",
        description="搜索互联网获取信息",
        detail="使用 DuckDuckGo 搜索引擎查询互联网信息。返回搜索结果列表，每条结果包含标题、URL 和摘要。适用于：查询实时信息、查找参考资料、验证事实、了解最新动态等。",
        category="web",
        recommended=True,
        params=[
            ToolParamDef("query", "搜索关键词", required=True, placeholder="要搜索的内容"),
            ToolParamDef("max_results", "最大结果数", placeholder="默认 5"),
        ],
    ),
    ToolCatalogEntry(
        kind="fetch_url",
        name="获取网页",
        description="访问指定 URL 获取网页内容",
        detail="访问指定的 URL 并提取网页正文内容。支持 HTML 页面（自动去除 script/style 等标签，提取可读文本）和 JSON API。适用于：阅读文章、获取 API 数据、提取网页信息等。",
        category="web",
        recommended=True,
        params=[
            ToolParamDef("url", "网址", required=True, placeholder="https://example.com"),
            ToolParamDef("max_chars", "最大字符数", placeholder="默认 8000"),
        ],
    ),
    ToolCatalogEntry(
        kind="page_inject",
        name="注入脚本",
        description="向前端页面注入 JavaScript 代码，支持事件监听和交互",
        detail="向当前页面注入 JavaScript 并执行。代码完全在浏览器中运行，事件回调直接执行，不经过 Agent。适用于：添加事件监听（点击、输入、键盘）、DOM 操作（修改样式、创建元素）、数据交互（localStorage、计数器、定时器）等。",
        category="web",
        params=[
            ToolParamDef("js_code", "JavaScript 代码", required=True, placeholder="要注入执行的 JS 代码"),
            ToolParamDef("description", "功能说明", placeholder="这段代码做什么（展示给用户）"),
        ],
    ),
]


def get_tool_catalog() -> List[Dict[str, Any]]:
    """获取工具目录的序列化列表"""
    return [entry.to_dict() for entry in TOOL_CATALOG_ENTRIES]


def get_category_labels() -> Dict[str, Dict[str, str]]:
    """获取分类标签映射

    以 CATEGORY_LABELS 为权威展示元数据；TOOL_CATALOG_ENTRIES 中存在但未在
    CATEGORY_LABELS 显式声明的分类，会用默认 icon/label 自动补全，避免前后端
    因为两个字典漂移导致前端崩溃。
    """
    used_categories = {entry.category for entry in TOOL_CATALOG_ENTRIES}
    result: Dict[str, Dict[str, str]] = {k: dict(v) for k, v in CATEGORY_LABELS.items()}
    for cat in used_categories:
        if cat not in result:
            result[cat] = {"label": cat, "icon": "🧰"}
    return result


def find_tool_by_kind(kind: str) -> Optional[Dict[str, Any]]:
    """根据 kind 查找工具目录条目"""
    for entry in TOOL_CATALOG_ENTRIES:
        if entry.kind == kind:
            return entry.to_dict()
    return None
