"""
项目模板服务

提供项目模板的列表、预览、应用功能。
模板以 JSON 文件形式存放在 `default_presets/project_templates/<id>/` 目录,
每个模板包含 template.json(元信息)、skills.json、agents.json、groups.json、resources.json。

应用模板时会:
1. 创建项目
2. 创建/复用全局 Skills
3. 创建/复用全局 Agents(带 tools 和 skill 绑定)
4. 创建 ProjectAgent 关联
5. 创建 Groups(带 GroupMember)
6. 创建 Tasks(带 TaskAssignee)
7. 创建项目级 Resources
8. 单事务提交

# Agent 实例展开 (instances)
模板里可以这样声明同质 agent:
    {"name": "玩家{N}", "instances": 5, "system_prompt": "...", ...}

框架会自动展开成 5 个独立 agent:
    [{"name": "玩家1", ...}, {"name": "玩家2", ...}, ..., {"name": "玩家5", ...}]

- {N} 占位符在所有字符串字段(name / description / system_prompt 等)中替换为序号
- 不声明 instances 的 agent 保持原样(向后兼容)
- instances 必须是 ≥1 的整数
- 展开后 instances 字段被移除(避免误用)
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent, AgentSkill, AgentTool, ProjectAgent, Skill
from app.models.group import Group, GroupMember
from app.models.task import Task, TaskAssignee
from app.models.project import Project
from app.models.resource import Resource


# 模板目录：default_presets/project_templates/
TEMPLATES_DIR = Path(__file__).parent.parent / "default_presets" / "project_templates"


# ── 结果数据类 ──


@dataclass
class TemplateSummary:
    """模板列表项"""

    template_id: str
    name: str
    description: str
    version: str
    cover_color: Optional[str] = None
    emoji: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    preview: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "cover_color": self.cover_color,
            "emoji": self.emoji,
            "tags": self.tags,
            "preview": self.preview,
        }


@dataclass
class TemplateDetail(TemplateSummary):
    """模板详情（包含 skills/agents/groups/resources 完整内容）"""

    skills: List[Dict[str, Any]] = field(default_factory=list)
    agents: List[Dict[str, Any]] = field(default_factory=list)
    groups: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)  # target_spec 等元数据

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "skills": self.skills,
            "agents": self.agents,
            "groups": self.groups,
            "resources": self.resources,
            "metadata": self.metadata,
        })
        return d


@dataclass
class ApplyResult:
    """应用模板的结果"""

    project_id: str
    project_name: str
    created_skills: List[str] = field(default_factory=list)
    reused_skills: List[str] = field(default_factory=list)
    created_agents: List[str] = field(default_factory=list)
    reused_agents: List[str] = field(default_factory=list)
    project_agent_count: int = 0
    group_count: int = 0
    task_count: int = 0
    resource_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "created_skills": self.created_skills,
            "reused_skills": self.reused_skills,
            "created_agents": self.created_agents,
            "reused_agents": self.reused_agents,
            "project_agent_count": self.project_agent_count,
            "group_count": self.group_count,
            "task_count": self.task_count,
            "resource_count": self.resource_count,
            "summary": (
                f"项目 '{self.project_name}' 创建成功："
                f"{len(self.created_skills) + len(self.reused_skills)} 个技能，"
                f"{len(self.created_agents) + len(self.reused_agents)} 个 Agent，"
                f"{self.project_agent_count} 个项目 Agent 关联，"
                f"{self.group_count} 个群聊，"
                f"{self.task_count} 个任务，"
                f"{self.resource_count} 个资源"
            ),
        }


# ── 模板加载 ──


_EXTEND_MARKER = "+extends"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """合并两个 agent 配置.

    规则:
    - 标量字段: override 有 → 用 override; 否则用 base
    - 数组字段 (tools, skill_refs, capabilities):
        如果 override 的数组里包含 "+extends" 标记 → 去掉标记, 把 base 的数组去重追加到前面
        否则 → 完全用 override 的数组
    - 不认识的字段: override 覆盖
    """
    result = dict(base)
    for key, val in override.items():
        if key == "extends":
            continue
        base_val = result.get(key)
        if isinstance(val, list) and isinstance(base_val, list):
            if _EXTEND_MARKER in val:
                merged = list(base_val)
                for item in val:
                    if item == _EXTEND_MARKER:
                        continue
                    if item not in merged:
                        merged.append(item)
                result[key] = merged
            else:
                result[key] = val
        else:
            result[key] = val
    return result


def resolve_extends(agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """解析 agent 的 `extends` 继承链.

    模板里声明:
        {"id": "player", "name": "玩家", "system_prompt": "...", "tools": [...]}
        {"id": "player1", "name": "玩家1", "extends": "player"}
        {"id": "judge", "name": "法官", "extends": "player",
         "system_prompt": "...", "tools": ["create_task", "+extends"]}

    规则:
    - `extends` 指向同模板内另一个 agent 的 `id`
    - 标量字段: 子有 → 覆盖; 子无 → 继承
    - 数组字段: 含 "+extends" → 追加; 否则 → 覆盖
    - 支持链式继承 (A extends B, B extends C)
    - 循环继承检测 (抛 ValueError)
    - 没有 `extends` 的 agent 原样返回
    - 解析后 `extends` 字段被移除, `id` 保留
    """
    # 建立 id → agent 原文的映射
    pool: Dict[str, Dict[str, Any]] = {}
    for agent in agents:
        aid = agent.get("id")
        if aid:
            if aid in pool:
                raise ValueError(f"agent id {aid!r} 重复")
            pool[aid] = agent

    resolved: List[Dict[str, Any]] = []

    def _resolve(agent: Dict[str, Any], visited: set) -> Dict[str, Any]:
        base_id = agent.get("extends")
        if not base_id:
            return dict(agent)
        if base_id in visited:
            raise ValueError(f"agent 继承链循环: {visited} → {base_id}")
        if base_id not in pool:
            raise ValueError(
                f"agent {agent.get('id')!r} extends {base_id!r}, 但模板中没有 id={base_id!r} 的 agent"
            )
        visited.add(base_id)
        base_resolved = _resolve(pool[base_id], visited)
        return _deep_merge(base_resolved, agent)

    for agent in agents:
        merged = _resolve(agent, set())
        merged.pop("extends", None)
        resolved.append(merged)

    return resolved


class TemplateService:
    """项目模板服务"""

    def __init__(self, db: AsyncSession, templates_dir: Optional[Path] = None):
        self.db = db
        self.templates_dir = templates_dir or TEMPLATES_DIR

    # ── 列表 / 详情 ──

    async def list_templates(self) -> List[TemplateSummary]:
        """列出所有可用模板"""
        result: List[TemplateSummary] = []
        if not self.templates_dir.exists():
            return result

        for entry in sorted(self.templates_dir.iterdir()):
            if not entry.is_dir():
                continue
            summary = self._load_summary(entry)
            if summary:
                result.append(summary)
        return result

    async def get_template(self, template_id: str) -> Optional[TemplateDetail]:
        """加载模板详情"""
        template_dir = self.templates_dir / template_id
        if not template_dir.exists():
            return None

        summary = self._load_summary(template_dir)
        if not summary:
            return None

        return TemplateDetail(
            template_id=summary.template_id,
            name=summary.name,
            description=summary.description,
            version=summary.version,
            cover_color=summary.cover_color,
            emoji=summary.emoji,
            tags=summary.tags,
            preview=summary.preview,
            skills=self._load_json(template_dir / "skills.json").get("skills", []),
            agents=resolve_extends(
                self._load_json(template_dir / "agents.json").get("agents", [])
            ),
            groups=self._load_json(template_dir / "groups.json").get("groups", []),
            resources=self._load_json(template_dir / "resources.json").get("resources", []),
            metadata=self._load_json(template_dir / "template.json"),
        )

    # ── 应用模板 ──

    async def apply_template(
        self,
        template_id: str,
        project_name: str,
        project_description: Optional[str] = None,
        cover_color: Optional[str] = None,
        project_tags: Optional[List[str]] = None,
        project_targets: Optional[Dict[str, Any]] = None,
    ) -> ApplyResult:
        """应用模板创建项目

        Args:
            project_targets: 项目级目标（覆盖模板 default），如
                {"word_count": 500000, "chapter_count": 200, ...}。
                会存入 workflow_config.targets，供 agent 上下文自动读取。
        """
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"模板 '{template_id}' 不存在")

        result = ApplyResult(project_id="", project_name=project_name)

        # 1. 创建项目
        # 合并 target_spec：项目级 > 模板 default
        spec_defaults = (template.metadata or {}).get("target_spec") or {}
        merged_targets: Dict[str, Any] = dict(spec_defaults)
        if project_targets:
            merged_targets.update(project_targets)

        project = Project(
            name=project_name,
            description=project_description or template.description,
            cover_color=cover_color or template.cover_color,
            tags=list(project_tags) if project_tags is not None else list(template.tags),
            status="active",
            workflow_config={
                "template_id": template.template_id,
                "template_version": template.version,
                "template_name": template.name,
                "targets": merged_targets,
            },
        )
        self.db.add(project)
        await self.db.flush()
        result.project_id = project.id

        # 2. 复用/创建全局 Skills（同时记录 created/reused）
        skill_id_map: Dict[str, str] = {}  # name -> skill_id
        for skill_data in template.skills:
            skill, is_created = await self._upsert_skill(skill_data)
            skill_id_map[skill_data["name"]] = skill.id
            if is_created:
                result.created_skills.append(skill_data["name"])
            else:
                result.reused_skills.append(skill_data["name"])

        # 3. 复用/创建全局 Agents（含 tools + skill_bindings）
        # v2 P2: 从 template.groups 提取 lead agent names, 传给 _upsert_agents
        # 让其知道哪些 agent 需要强制注入 create_task 工具
        lead_agent_names = {
            g["lead_agent"] for g in template.groups if g.get("lead_agent")
        }
        agent_id_map: Dict[str, str] = {}  # name -> agent_id
        agent_created_reused = await self._upsert_agents(
            template.agents, skill_id_map, lead_agent_names=lead_agent_names
        )
        for name, (agent_id, is_created) in agent_created_reused.items():
            agent_id_map[name] = agent_id
            if is_created:
                result.created_agents.append(name)
            else:
                result.reused_agents.append(name)

        # 4. 创建 ProjectAgent 关联
        project_agent_id_map: Dict[str, str] = {}  # agent_name -> project_agent_id
        for agent_name, agent_id in agent_id_map.items():
            pa = ProjectAgent(
                project_id=project.id,
                agent_id=agent_id,
                override_config={},
            )
            self.db.add(pa)
            await self.db.flush()
            project_agent_id_map[agent_name] = pa.id
        result.project_agent_count = len(project_agent_id_map)

        # 5. 创建 Groups（含 GroupMember + Tasks）
        # 记录每个 (group_name, task_title) 对应的实际 task_id，供 resources 回填
        task_ref_map: Dict[Tuple[str, str], str] = {}
        for group_data in template.groups:
            await self._create_group(
                project_id=project.id,
                group_data=group_data,
                project_agent_id_map=project_agent_id_map,
                result=result,
                task_ref_map=task_ref_map,
            )
        result.group_count = len(template.groups)

        # 6. 创建 Resources（支持追溯到具体任务）
        for res_data in template.resources:
            task_id: Optional[str] = None
            source_group = res_data.get("source_group_name")
            source_task = res_data.get("source_task_title")
            if source_group and source_task:
                task_id = task_ref_map.get((source_group, source_task))
            res = Resource(
                project_id=project.id,
                group_id=None,
                title=res_data["title"],
                content=res_data.get("content", ""),
                content_type=res_data.get("content_type", "markdown"),
                type=res_data.get("resource_type", "note"),
                tags=res_data.get("tags", []),
                is_required=res_data.get("is_required", False),
                created_by=res_data.get("created_by", "template"),
                task_id=task_id,
            )
            self.db.add(res)
            result.resource_count += 1

        # 6.5 v2 P2: 给所有 lead agent 注入运行时拆解能力
        # - 把 lead 工作流章节追加到 system_prompt（一次性, 不重复加）
        # - 强制给 lead 加 create_task 工具（不依赖 agents.json 是否声明）
        await self._inject_lead_runtime_decomposition(
            template_groups=template.groups,
            project_agent_id_map=project_agent_id_map,
        )

        # 6.6 v2 P2: 模板项目也走 project-level coordinator bootstrap。
        # 不在模板里硬塞一份 coordinator prompt（每模板重复维护）, 统一从
        # default_presets/agent_templates/coordinator.json 拉取, 与空白项目保持一致。
        # 兜底: bootstrap 失败不应阻断模板应用
        try:
            from app.services.project_service import ProjectService
            coordinator_service = ProjectService(self.db)
            await coordinator_service._ensure_project_coordinator(project)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[apply_template] _ensure_project_coordinator failed for project=%s: %s",
                project.id, e,
            )

        # 7. 提交
        await self.db.commit()

        return result

    # ── 内部方法 ──

    def _load_summary(self, template_dir: Path) -> Optional[TemplateSummary]:
        """从 template.json 加载摘要"""
        meta = self._load_json(template_dir / "template.json")
        if not meta:
            return None
        return TemplateSummary(
            template_id=meta.get("template_id", template_dir.name),
            name=meta.get("name", template_dir.name),
            description=meta.get("description", ""),
            version=meta.get("version", "1.0.0"),
            cover_color=meta.get("cover_color"),
            emoji=meta.get("emoji"),
            tags=meta.get("tags", []),
            preview=meta.get("preview", {}),
        )

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    async def _upsert_skill(self, skill_data: Dict[str, Any]) -> Tuple[Skill, bool]:
        """按名称复用或创建 Skill。返回 (Skill, is_created)"""
        name = skill_data["name"]
        res = await self.db.execute(select(Skill).where(Skill.name == name))
        existing = res.scalar_one_or_none()

        if existing:
            existing.description = skill_data.get("description", existing.description)
            existing.skill_type = skill_data.get("skill_type", existing.skill_type)
            existing.content = skill_data.get("content", existing.content)
            existing.config = skill_data.get("config", existing.config or {})
            existing.files = skill_data.get("files", existing.files or {})
            return existing, False

        skill = Skill(
            name=name,
            description=skill_data.get("description"),
            skill_type=skill_data.get("skill_type", "prompt"),
            content=skill_data.get("content", ""),
            config=skill_data.get("config", {}),
            files=skill_data.get("files", {}),
        )
        self.db.add(skill)
        await self.db.flush()
        return skill, True

    async def _collect_skill_diff(
        self,
        skills_data: List[Dict[str, Any]],
        skill_id_map: Dict[str, str],
    ) -> Tuple[List[str], List[str]]:
        """兼容旧调用：占位保留"""
        return [], []

    async def _upsert_agents(
        self,
        agents_data: List[Dict[str, Any]],
        skill_id_map: Dict[str, str],
        lead_agent_names: Optional[set] = None,
    ) -> Dict[str, Tuple[str, bool]]:
        """按名称复用或创建 Agent，返回 name -> (id, is_created)

        v2 P2: lead_agent_names 由 apply_template 从 template.groups 提取并传入,
        用于在创建/更新 agent 时强制给 lead 加 create_task 工具。
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[_upsert_agents] called with %d agents", len(agents_data))
        out: Dict[str, Tuple[str, bool]] = {}

        lead_agent_names = lead_agent_names or set()

        for agent_data in agents_data:
            name = agent_data["name"]
            # v2 P2: 跳过标记 skip=true 的占位 entry（如 novel-writing 留下的
            # __placeholder_for_legacy_coordinator__, 真正的 coordinator 由
            # project_service.bootstrap 统一提供, 不在模板层重复）
            if agent_data.get("skip"):
                logger.info("[_upsert_agents] skip placeholder agent: %r", name)
                continue
            logger.info("[_upsert_agents] processing agent: %r", name)
            is_lead = name in lead_agent_names

            res = await self.db.execute(
                select(Agent)
                .options(selectinload(Agent.tools), selectinload(Agent.skills))
                .where(Agent.name == name)
            )
            existing = res.scalar_one_or_none()
            logger.info("[_upsert_agents] %r existing=%s", name, existing is not None)

            # 工具列表：agents.json 里的 + (v2 P2 lead 强制) create_task
            tool_list = list(agent_data.get("tools", []))
            if is_lead and not any(t.get("name") == "create_task" for t in tool_list):
                tool_list.append({
                    "name": "create_task",
                    "kind": "create_task",
                    "tool_type": "builtin",
                    "description": "运行时创建任务（v2 P2, lead 用）",
                    "config": {},
                })

            if existing:
                # 覆盖更新主要字段
                # v2 P3: 删除 role 字段
                existing.avatar = agent_data.get("avatar", existing.avatar)
                existing.description = agent_data.get("description", existing.description)
                existing.system_prompt = agent_data.get("system_prompt", existing.system_prompt)
                existing.llm_config = agent_data.get("llm_config", existing.llm_config or {})
                existing.capabilities = agent_data.get("capabilities", existing.capabilities or [])
                existing.force_tool_choice = bool(
                    agent_data.get("force_tool_choice", existing.force_tool_choice)
                )

                # 重建工具绑定
                for old_tool in list(existing.tools or []):
                    await self.db.delete(old_tool)
                await self.db.flush()
                for tool_data in tool_list:
                    self.db.add(AgentTool(
                        agent_id=existing.id,
                        name=tool_data["name"],
                        kind=tool_data.get("kind", tool_data["name"]),
                        tool_type=tool_data.get("tool_type", "builtin"),
                        description=tool_data.get("description"),
                        config=tool_data.get("config", {}),
                    ))

                # 重建 skill 绑定
                await self._bind_agent_skills(existing.id, agent_data.get("skill_refs", []), skill_id_map)

                out[name] = (existing.id, False)
            else:
                agent = Agent(
                    name=name,
                    # v2 P3: 删除 role 字段
                    avatar=agent_data.get("avatar"),
                    description=agent_data.get("description"),
                    system_prompt=agent_data.get("system_prompt", ""),
                    llm_config=agent_data.get("llm_config", {}),
                    capabilities=agent_data.get("capabilities", []),
                    force_tool_choice=bool(agent_data.get("force_tool_choice", False)),
                )
                self.db.add(agent)
                await self.db.flush()

                for tool_data in tool_list:
                    self.db.add(AgentTool(
                        agent_id=agent.id,
                        name=tool_data["name"],
                        kind=tool_data.get("kind", tool_data["name"]),
                        tool_type=tool_data.get("tool_type", "builtin"),
                        description=tool_data.get("description"),
                        config=tool_data.get("config", {}),
                    ))

                await self._bind_agent_skills(agent.id, agent_data.get("skill_refs", []), skill_id_map)

                out[name] = (agent.id, True)

        return out

    async def _bind_agent_skills(
        self,
        agent_id: str,
        skill_refs: List[str],
        skill_id_map: Dict[str, str],
    ) -> None:
        """按名称绑定 agent 的 skills"""
        # 删除旧关联
        old = await self.db.execute(
            select(AgentSkill).where(AgentSkill.agent_id == agent_id)
        )
        for assoc in old.scalars().all():
            await self.db.delete(assoc)
        await self.db.flush()

        for skill_name in skill_refs or []:
            skill_id = skill_id_map.get(skill_name)
            if not skill_id:
                # 兜底：到数据库里再查一次
                res = await self.db.execute(select(Skill).where(Skill.name == skill_name))
                skill = res.scalar_one_or_none()
                if skill:
                    skill_id = skill.id
            if skill_id:
                self.db.add(AgentSkill(agent_id=agent_id, skill_id=skill_id))

    async def _create_group(
        self,
        project_id: str,
        group_data: Dict[str, Any],
        project_agent_id_map: Dict[str, str],
        result: ApplyResult,
        task_ref_map: Dict[Tuple[str, str], str],
    ) -> None:
        """创建单个群聊及其成员与任务

        v2 P2 改动:
        - 不再创建硬编码 tasks (group_data["tasks"] = [])
        - 把 decomposition_rules / deliverable / input_dependencies
          合并进 group.description, 让 lead 调 get_group 时能读到
        - lead 按 description 里的"拆解规则" 调 create_task 拆 task
        """
        lead_agent_name = group_data.get("lead_agent")
        lead_pa_id = project_agent_id_map.get(lead_agent_name) if lead_agent_name else None
        if not lead_pa_id:
            # 容错：群聊的 lead_agent 名字在 agent_id_map 中找不到（可能模板 agents.json 缺漏）。
            # 退而求其次，取 members 列表中第一个 participant 的 project_agent_id，
            # 让群聊至少有 lead 可调，避免"群聊中暂无Agent"硬性阻断。
            for m in group_data.get("members", []):
                candidate_pa = project_agent_id_map.get(m.get("agent_name", ""))
                if candidate_pa:
                    lead_pa_id = candidate_pa
                    break

        # v2 P2: 合并 description + decomposition_rules + deliverable + input_dependencies
        # 让 lead 调 get_group 一次就能拿到全部流程上下文
        base_description = group_data.get("description", "")
        decomposition_rules = group_data.get("decomposition_rules", "")
        deliverable = group_data.get("deliverable", {})
        input_dependencies = group_data.get("input_dependencies", [])

        full_description_parts = [base_description] if base_description else []
        if deliverable:
            deliverable_str = (
                f"## 交付物（deliverable）\n"
                f"- 类型: {deliverable.get('type', 'resource')}\n"
                f"- 标题: {deliverable.get('title', '')}\n"
                f"- 必出: {'是' if deliverable.get('is_required', True) else '否'}\n"
                f"- 最小长度: {deliverable.get('min_content_length', 0)} 字"
            )
            full_description_parts.append(deliverable_str)
        if input_dependencies:
            deps_str = "## 上游依赖（input_dependencies）\n" + "\n".join(
                f"- 来自群「{d.get('from_group', '')}」的交付物: {d.get('deliverable', '')}"
                for d in input_dependencies
            )
            full_description_parts.append(deps_str)
        if decomposition_rules:
            rules_str = "## 拆解规则（decomposition_rules, v2 P2）\n\n" + decomposition_rules
            full_description_parts.append(rules_str)
        full_description = "\n\n---\n\n".join(full_description_parts)

        group = Group(
            project_id=project_id,
            name=group_data["name"],
            description=full_description,
            status=group_data.get("status", "pending"),
            order_index=group_data.get("order_index", 0),
            autonomy_level=group_data.get("autonomy_level", "semi_auto"),
            auto_advance=group_data.get("auto_advance", False),
            lead_agent_id=lead_pa_id,
            workflow_config=group_data.get("workflow_config", {}),
        )
        self.db.add(group)
        await self.db.flush()

        # 创建 GroupMember
        for member in group_data.get("members", []):
            agent_name = member.get("agent_name")
            pa_id = project_agent_id_map.get(agent_name)
            if not pa_id:
                continue
            self.db.add(GroupMember(
                group_id=group.id,
                project_agent_id=pa_id,
                role=member.get("role", "participant"),
            ))

        # v2 P2: 不再创建硬编码 tasks（group_data["tasks"] = []）
        # 任务由 lead 在运行时调 create_task 创建, 按 description 里的"拆解规则"
        # 这样模板才通用（不需要为每部小说写一份 task 清单）

        # v2 P1: 预建 group 文件夹（资源自动归入的容器）
        # 按 v2 §0.5 原则: 文件夹是工具层保护（不是硬编码流程）。
        # 预建确保资源一写入就能正确归入, 不依赖 lazy-create 的首次写入时机。
        await self._ensure_group_folder(
            project_id=project_id,
            group_id=group.id,
            group_name=group.name,
        )

        # v2 P1: 预建 group 级 chain（让 send_message / ping 等"发消息"原子能力
        # 可直接使用, 不依赖 chat_service 的 _get_or_create_chain lazy 路径）。
        # - chat 的 _get_or_create_chain 是 lazy, 适用于"用户先发消息"场景
        # - 但 ping / system 发起的通知（v2 §0.5 原则 6）也写消息, 需要 chain 已存在
        # - chain 是工具层结构, 预建不算"硬编码流程"
        await self._ensure_group_chain(
            project_id=project_id,
            group_id=group.id,
        )

    async def _inject_lead_runtime_decomposition(
        self,
        template_groups: List[Dict[str, Any]],
        project_agent_id_map: Dict[str, str],
    ) -> None:
        """
        v2 P2: 给所有 lead agent 注入运行时拆解能力。

        目的（v2 §0.5 原则 6）:
        - 模板 = 角色 + 流程（不变量）
        - 实际 task 数量 / 章节数 / 字数 = 变量（lead 运行时拆解）
        - lead 的 system_prompt 必须明确告诉它怎么拆

        行为:
        1. 收集所有 group.lead_agent 去重
        2. 给每个 lead 的 system_prompt 追加"运行时拆解"章节（一次性, 已加过则跳过）
        3. 强制给 lead 加 create_task 工具（即使 agents.json 没声明）

        设计理由:
        - 不直接修改 agents.json（避免和 v1 内容混）
        - 注入到全局 Agent（因为 lead 角色在任何项目都需要这套能力）
        - 任何模板都自动获得此能力（不只 novel-writing）

        注意:
        - 用 session.new 检查待添加的 AgentTool, 避免和 _upsert_agents 阶段刚加的重复
        - 防御性: _upsert_agents 已经把新 tools add 到 session, 但未 flush, 这里 query 看不到
        """
        # 1. 收集去重的 lead agent name
        lead_agent_names = set()
        for g in template_groups:
            lead = g.get("lead_agent")
            if lead:
                lead_agent_names.add(lead)

        if not lead_agent_names:
            return

        # 2. 要追加的章节（标记 v2 P2, 幂等检查）
        RUNTIME_DECOMPOSITION_SECTION = """

## ⚠️ 运行时拆解（v2 P2, 必读）

**你是本群 lead（群主）**。模板的 groups.json 不再预置具体 task 清单——
任务由你按"群 description 里的拆解规则"在运行时调 `create_task` 创建。

**进入本群时**：
1. 调 `get_group(group_id)` 读本群 description
2. description 里有"## 拆解规则" 章节
3. 按拆解规则调 `create_task(title, description)` 拆 N 个 task
4. 调 `update_task_status(task_id, 'in_progress'/'done')` 推进
5. 全部 done → `update_group(group_id, 'completed')` + 写 deliverable 资源

**关键原则**：
- 拆多少个 task、每个 task 叫什么、什么时间拆 = 你根据上游交付物和当前进度决定
- 不需要等用户告诉你"开几个 task"——拆解规则已经写在 description 里
- 如果上游 deliverable 还没就绪 → `query_activity` 查上游 group 状态, 等
- 进度卡住 → 调 `ping(目标 agent, reason=...)` 推动, 不要等系统层硬编码（v2 没有 auto_continue）

**反面教材**：
❌ 模板里写了 27 个 task 就只开 27 个 → 50万字 200 章写不下
✅ 按描述+上游资源自己决定拆 N 个 → N 由题材/字数/大纲决定
"""

        from app.models.agent import Agent, AgentTool
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        # 先 flush, 确保 _upsert_agents 阶段的 delete/add 都已落库
        # 否则后面的 SELECT autoflush 会被之前的待 flush 操作阻塞/冲突
        await self.db.flush()

        for lead_name in lead_agent_names:
            # 取 lead agent（带 tools）
            res = await self.db.execute(
                select(Agent)
                .options(selectinload(Agent.tools))
                .where(Agent.name == lead_name)
            )
            agent = res.scalar_one_or_none()
            if not agent:
                continue

            # 2a. 追加 system_prompt 章节（幂等: 已加过则跳过）
            current_sp = agent.system_prompt or ""
            if "v2 P2, 必读" not in current_sp and "运行时拆解（v2 P2" not in current_sp:
                agent.system_prompt = current_sp + RUNTIME_DECOMPOSITION_SECTION

            # 2b. 强制加 create_task 工具（即使 agents.json 没声明）
            # 防御: 收集"已存在的 create_task" — 包括
            #  - DB 里的（agent.tools, 已 flush）
            #  - session.new 里的待添加的（_upsert_agents 刚加的, 未 flush）
            existing_tool_names = {t.name for t in (agent.tools or [])}
            pending_tool_names = {
                obj.name
                for obj in self.db.new
                if isinstance(obj, AgentTool) and obj.agent_id == agent.id
            }
            if "create_task" in existing_tool_names or "create_task" in pending_tool_names:
                continue  # 已经有, 跳过（避免 UNIQUE 约束）
            self.db.add(AgentTool(
                agent_id=agent.id,
                name="create_task",
                kind="create_task",
                tool_type="builtin",
                description="运行时创建任务（v2 P2, lead 用）",
                config={},
            ))

    async def _ensure_group_folder(
        self,
        project_id: str,
        group_id: str,
        group_name: str,
    ) -> Optional[str]:
        """
        v2 P1: 预建/复用 group 文件夹。

        行为:
        - 若 project + group 下已存在同名 (title) 的 folder, 复用
        - 否则创建新 folder (is_folder=True, type='custom')
        - 失败（重名约束等）不抛异常, 返回 None
        """
        from app.models.resource import Resource
        from sqlalchemy import select, and_

        folder_title = f"📁 {group_name}"
        try:
            existing = (await self.db.execute(
                select(Resource).where(and_(
                    Resource.project_id == project_id,
                    Resource.group_id == group_id,
                    Resource.is_folder == True,  # noqa: E712
                    Resource.title == folder_title,
                    Resource.deleted_at.is_(None),
                ))
            )).scalar_one_or_none()
            if existing:
                return existing.id

            folder = Resource(
                project_id=project_id,
                group_id=group_id,
                is_folder=True,
                title=folder_title,
                content=f"# {folder_title}\n\n本文件夹自动归入群聊「{group_name}」产出的资源。",
                type="custom",  # 避开 type check 约束, folder 用 is_folder=True 标识
                content_type="markdown",
                tags=["folder", "auto-generated"],
                is_required=False,
                created_by="system",
            )
            self.db.add(folder)
            await self.db.flush()
            return folder.id
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[_ensure_group_folder] %s: %s", folder_title, e
            )
            return None

    async def _ensure_group_chain(
        self,
        project_id: str,
        group_id: str,
    ) -> Optional[str]:
        """
        v2 P1: 预建/复用 group 级 active chain。

        行为:
        - 找 group 下 chain_type='group', status='active' 的 chain
        - 没有就创建一个 (chain_type='group', status='active', task_id=None)
        - 失败不抛异常, 返回 None

        目的:
        - send_message / ping 等发消息原子能力要求"群下有 active chain"
        - 之前依赖 chat_service 的 lazy create, 但 ping 是 system/agent 主动发起的,
          不会走 chat 入口, 所以必须在 group 创建时就预建
        """
        from app.models.chain import Chain
        from sqlalchemy import select, and_

        try:
            existing = (await self.db.execute(
                select(Chain).where(and_(
                    Chain.group_id == group_id,
                    Chain.chain_type == "group",
                    Chain.status == "active",
                    Chain.deleted_at.is_(None),
                ))
            )).scalar_one_or_none()
            if existing:
                return existing.id

            chain = Chain(
                chain_type="group",
                task_id=None,
                group_id=group_id,
                status="active",
                description=f"群聊 {group_id[:8]} 根链（v2 P1 预建）",
            )
            self.db.add(chain)
            await self.db.flush()
            return chain.id
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "[_ensure_group_chain] group=%s: %s", group_id[:8], e
            )
            return None

    async def _create_task(
        self,
        group_id: str,
        task_data: Dict[str, Any],
        project_agent_id_map: Dict[str, str],
        result: ApplyResult,
    ) -> Optional[str]:
        """创建单个任务及其指派，返回 task_id"""
        lead_agent_name = task_data.get("lead_agent")
        lead_pa_id = project_agent_id_map.get(lead_agent_name) if lead_agent_name else None

        task = Task(
            group_id=group_id,
            title=task_data["title"],
            description=task_data.get("description", ""),
            status="todo",
            order_index=task_data.get("order_index", 0),
            acceptance_criteria=task_data.get("acceptance_criteria"),
            lead_agent_id=lead_pa_id,
        )
        self.db.add(task)
        await self.db.flush()

        # 任务指派
        for assignee_name in task_data.get("assignees", []):
            pa_id = project_agent_id_map.get(assignee_name)
            if not pa_id:
                continue
            self.db.add(TaskAssignee(
                task_id=task.id,
                project_agent_id=pa_id,
            ))

        result.task_count += 1
        return task.id
