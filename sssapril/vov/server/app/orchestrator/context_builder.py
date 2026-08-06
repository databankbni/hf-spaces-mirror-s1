"""
上下文组装器模块

负责从多个来源收集和组装Agent执行所需的上下文信息。

设计原则（软约束优先）：
1. Skills 只放元信息——Agent 知道有哪些 skill 可用，需要时通过 read_skill 加载全文
2. Resources 分两层：must_read（is_required=True）全文注入；其他资源只放目录
3. Memory 按 slug 选择性注入：decisions / state_snapshot / group_focus 默认注入，其他按需
4. Lead agent 的 group_focus 记忆可作为路由表，过滤本群成员的资源视图
"""

import logging
import re
import json
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.agent import Agent, ProjectAgent
from app.models.group import Group, GroupMember
from app.models.task import Task
from app.models.chain import Chain, Packet
from app.models.resource import Resource
from app.models.memory import Memory
from app.models.deliverable import Deliverable


logger = logging.getLogger(__name__)


# 默认注入的 memory slug（其他 slug 需要时由 agent 调 get_memory 拉）
# 设计原则: 记忆的可见性由 agent 自己管理——agent 调 set_memory 写入什么,
#   后续 agent 启动时通过 get_memory(slug=...) 主动拉取。
# 这不是系统代写, 也不是系统硬路由注入——而是给 agent 提供"按需加载"的工具。
DEFAULT_MEMORY_SLUGS = {"decisions", "state_snapshot", "group_focus"}


class ContextBuilder:
    """
    Agent上下文组装器

    职责：
    1. 从多个来源收集上下文信息
    2. 组装成Agent可理解的格式
    3. 通过 lead agent 的 group_focus 路由资源（软约束）

    上下文层级（注入策略）：
    - 第一优先（必读全文）：任务上下文、约束、is_required=True 的资源
    - 第二优先（按 slug 注入）：decisions / state_snapshot / group_focus 记忆
    - 第三优先（元信息目录）：其他资源、其他 slug 记忆、skills 元信息
    - 最后：自主模式指令
    """

    def __init__(self, db: AsyncSession):
        """
        初始化上下文组装器

        Args:
            db: 数据库会话
        """
        self.db = db

    async def build(
        self,
        agent: Agent,
        project_agent: Optional[ProjectAgent] = None,
        group: Optional[Group] = None,
        task: Optional[Task] = None,
        chain: Optional[Chain] = None,
        include_history: bool = True,
        history_limit: int = 20,
    ) -> Dict[str, Any]:
        """
        组装Agent上下文

        按照层级收集上下文信息，组装成完整的上下文字典。
        关键设计：skills/resources/memory 都按"全文 vs 元信息"分层。

        Args:
            agent: Agent对象
            project_agent: 项目Agent对象（包含覆盖配置）
            group: 群聊对象
            task: 任务对象
            chain: 讨论链对象
            include_history: 是否包含历史消息
            history_limit: 历史消息数量限制

        Returns:
            Dict: 组装好的上下文信息，包含：
                - system_prompt: 系统提示词
                - tools: 工具列表
                - skills: 技能元信息列表（不含全文，agent 按需 read_skill）
                - resources: 注入全文的资源（is_required=True 或 lead group_focus must_read）
                - resource_catalog: 资源目录（标题+类型+tags，agent 按需 read_resource）
                - memory: 注入全文的笔记（按 slug）
                - memory_catalog: 笔记目录（按 slug）
                - history: 历史消息
                - task_context: 任务上下文
                - constraints: 约束条件
        """
        context = {
            "system_prompt": "",
            "tools": [],
            "skills": [],
            "resources": [],
            "resource_catalog": [],
            "memory": [],
            "memory_catalog": [],
            "history": [],
            "task_context": {},
            "constraints": [],
            "agent_id": agent.id,
            "agent_name": agent.name,
            "project_id": group.project_id if group else None,
            "group_id": group.id if group else None,
            "autonomy_level": getattr(group, 'autonomy_level', 'semi_auto') or 'semi_auto' if group else 'semi_auto',
            # 保留 group.workflow_config 供 format_for_llm 读 execution_variant（项目级 A/B 测试 override）
            "workflow_config": (getattr(group, 'workflow_config', None) or {}) if group else {},
        }

        # 1. Agent自我设定（system_prompt + tools + skills元信息）
        await self._build_agent_context(context, agent, project_agent)

        # 2. 项目全局资源
        if group:
            await self._build_project_resources(context, group.project_id)

        # 3. 群聊共享资源
        if group:
            await self._build_group_resources(context, group.id)

        # 4. Lead agent 的路由表（软路由）—— 拆分 resources 与 resource_catalog
        if group:
            await self._route_resources_for_agent(
                context=context,
                project_id=group.project_id,
                group_id=group.id,
                current_agent_name=agent.name,
            )

        # 5. Agent个人笔记（按 slug 选择性注入）
        if group:
            await self._build_agent_memory(context, agent.id, group.project_id)

        # 6. 当前链历史
        if chain and include_history:
            # v2 P2: 如果是 task chain 且 task.inherit_main_chain=true,
            # 先加载主链截至分支点的历史, 再加载 task chain 自身历史
            if task and getattr(task, 'inherit_main_chain', 1) and chain.chain_type == "task":
                await self._build_inherited_main_chain_history(
                    context, chain, history_limit,
                )
            else:
                await self._build_chain_history(context, chain.id, history_limit)

        # 7. 任务约束
        if task:
            await self._build_task_context(context, task)

        # 8. 项目级元信息（targets / 模板配置）—— 让 agent 看到篇幅/类型等软约束
        if group:
            await self._build_project_metadata(context, group.project_id)

        # 9. 群聊成员花名册 —— 让 lead agent 知道有哪些可协作的同事（软约束）
        if group:
            await self._build_group_roster(context, group)

        return context

    async def _build_project_metadata(
        self,
        context: Dict[str, Any],
        project_id: str,
    ) -> None:
        """从 project.workflow_config.targets 读项目级目标"""
        from app.models.project import Project as ProjectModel
        proj = (await self.db.execute(
            select(ProjectModel).where(ProjectModel.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            return
        cfg = proj.workflow_config or {}
        targets = cfg.get("targets") or {}
        context["project_metadata"] = {
            "name": proj.name,
            "description": proj.description,
            "tags": proj.tags or [],
            "targets": targets,
        }

    async def _build_group_roster(
        self,
        context: Dict[str, Any],
        group: Group,
    ) -> None:
        """
        群聊花名册：暴露给 agent 让它知道可以把谁当工具调用（@协作软约束）

        不暴露 system_prompt 等隐私，仅给 name/role/description/id。
        """
        roster = []
        for m in (group.members or []):
            pa = m.project_agent
            if not pa or not pa.agent:
                continue
            a = pa.agent
            roster.append({
                "id": a.id,
                "name": a.name,
                # v2 P3: 删除 role 字段, agent 的"职业身份"由 system_prompt 表达
                "description": a.description,
                "is_lead": m.role == "lead",
                "member_role": m.role,
            })
        context["group_roster"] = roster

    async def _build_agent_context(
        self,
        context: Dict[str, Any],
        agent: Agent,
        project_agent: Optional[ProjectAgent] = None,
    ) -> None:
        """
        组装Agent自我设定

        包括系统提示词、工具、技能。
        如果有项目级覆盖配置，应用覆盖。

        Args:
            context: 上下文字典
            agent: Agent对象
            project_agent: 项目Agent对象
        """
        # 基础系统提示词
        system_prompt = agent.system_prompt

        # 应用项目级覆盖
        if project_agent and project_agent.override_config:
            override = project_agent.override_config
            if "system_prompt_suffix" in override:
                system_prompt += "\n\n" + override["system_prompt_suffix"]

        context["system_prompt"] = system_prompt

        # 工具列表（kind 优先取显式 kind 字段，fallback 到 config.kind，再 fallback 到 name）
        context["tools"] = [
            {
                "kind": tool.kind or (tool.config.get("kind") if isinstance(tool.config, dict) else None) or tool.name,
                "name": tool.name,
                "description": tool.description,
                "type": tool.tool_type,
                "config": tool.config,
            }
            for tool in agent.tools
        ]

        # 技能列表 —— 只放元信息（name + description + skill_type + config 摘要）
        # Agent 需要详情时调 read_skill 工具拉全文
        # 这样 LLM 不会被数千字的 skill content 占用上下文
        context["skills"] = [
            {
                "name": skill.name,
                "description": skill.description,
                "type": skill.skill_type,
                # 标记是否有 files（agent 可以读子文件）
                "has_files": bool(skill.files),
            }
            for skill in agent.skills
        ]

    async def _build_project_resources(
        self,
        context: Dict[str, Any],
        project_id: str,
    ) -> None:
        """
        组装项目全局资源

        全文注入到 context["resources"]，由后续 _route_resources_for_agent 做软路由拆分。

        Args:
            context: 上下文字典
            project_id: 项目ID
        """
        # 查询项目全局资源
        query = select(Resource).where(and_(
            Resource.project_id == project_id,
            Resource.group_id.is_(None),  # 全局资源
            Resource.deleted_at.is_(None),
        )).order_by(Resource.is_required.desc(), Resource.created_at)
        result = await self.db.execute(query)
        resources = list(result.scalars().all())

        # 构建资源列表（待路由拆分）
        for resource in resources:
            context["resources"].append({
                "id": resource.id,
                "title": resource.title,
                "content": resource.content,
                "type": resource.type,
                "is_required": resource.is_required,
                "scope": "project",
                "tags": resource.tags or [],
            })

    async def _build_group_resources(
        self,
        context: Dict[str, Any],
        group_id: str,
    ) -> None:
        """
        组装群聊共享资源

        Args:
            context: 上下文字典
            group_id: 群聊ID
        """
        # 查询群聊资源
        query = select(Resource).where(and_(
            Resource.group_id == group_id,
            Resource.deleted_at.is_(None),
        )).order_by(Resource.is_required.desc(), Resource.created_at)
        result = await self.db.execute(query)
        resources = list(result.scalars().all())

        # 构建资源列表
        for resource in resources:
            context["resources"].append({
                "id": resource.id,
                "title": resource.title,
                "content": resource.content,
                "type": resource.type,
                "is_required": resource.is_required,
                "scope": "group",
            })

    async def _route_resources_for_agent(
        self,
        context: Dict[str, Any],
        project_id: str,
        group_id: str,
        current_agent_name: str,
    ) -> None:
        """
        根据 lead agent 的 group_focus 路由资源

        设计：这是"软约束"。lead agent 在自己的 group_focus 记忆里维护
        - must_read: 本群所有成员必读（与当前 agent 匹配则注入全文）
        - skip: 本群根本不要的资源
        - watch: 临时关注（按需）

        Lead agent 自己在的群聊时，路由表对本 lead 也适用（一致性）。
        Lead 没维护路由表时，资源按 is_required 分层（必读全文，其他目录）。

        Args:
            context: 上下文字典
            project_id: 项目 ID
            group_id: 当前群聊 ID
            current_agent_name: 当前 agent 名称（用于 member_roster 匹配）
        """
        # 1. 找本群 lead agent
        from app.models.agent import ProjectAgent as ProjectAgentModel
        lead_pa_id = await self._get_group_lead_id(group_id)
        if not lead_pa_id:
            return await self._fallback_split_resources(context)

        lead_agent_id = await self._get_agent_id_by_project_agent(lead_pa_id)
        if not lead_agent_id:
            return await self._fallback_split_resources(context)

        # 2. 读 lead 的 group_focus memory
        group_focus = await self._get_memory_content(lead_agent_id, project_id, "group_focus")
        if not group_focus:
            return await self._fallback_split_resources(context)

        # 3. 解析路由表
        must_read_titles = self._parse_group_focus_must_read(group_focus, current_agent_name)
        skip_titles = self._parse_group_focus_skip(group_focus)

        # 4. 拆分 resources
        must_read_full: List[Dict[str, Any]] = []
        catalog: List[Dict[str, Any]] = []
        for res in context["resources"]:
            title = res.get("title", "")
            if title in skip_titles:
                # 本群根本不要：连目录都不放
                continue
            if res.get("is_required") or title in must_read_titles:
                must_read_full.append(res)
            else:
                catalog.append({
                    "id": res.get("id"),
                    "title": title,
                    "type": res.get("type"),
                    "tags": res.get("tags", []),
                    "scope": res.get("scope"),
                })

        context["resources"] = must_read_full
        context["resource_catalog"] = catalog
        context["routed_by_lead"] = True

    async def _fallback_split_resources(self, context: Dict[str, Any]) -> None:
        """无路由表时的默认拆分：is_required 全文，其他目录"""
        must_read_full: List[Dict[str, Any]] = []
        catalog: List[Dict[str, Any]] = []
        for res in context["resources"]:
            if res.get("is_required"):
                must_read_full.append(res)
            else:
                catalog.append({
                    "id": res.get("id"),
                    "title": res.get("title", ""),
                    "type": res.get("type"),
                    "tags": res.get("tags", []),
                    "scope": res.get("scope"),
                })
        context["resources"] = must_read_full
        context["resource_catalog"] = catalog
        context["routed_by_lead"] = False

    async def _get_group_lead_id(self, group_id: str) -> Optional[str]:
        """取群聊的 lead_agent_id（ProjectAgent.id）"""
        query = select(Group.lead_agent_id).where(Group.id == group_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _get_agent_id_by_project_agent(self, project_agent_id: str) -> Optional[str]:
        """ProjectAgent.id -> Agent.id"""
        query = select(ProjectAgent.agent_id).where(ProjectAgent.id == project_agent_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def _get_memory_content(
        self,
        agent_id: str,
        project_id: str,
        slug: str,
    ) -> Optional[str]:
        """读某个 slug 的 memory content"""
        query = select(Memory).where(and_(
            Memory.agent_id == agent_id,
            Memory.project_id == project_id,
            Memory.slug == slug,
            Memory.deleted_at.is_(None),
        ))
        result = await self.db.execute(query)
        mem = result.scalar_one_or_none()
        return mem.content if mem else None

    def _parse_group_focus_must_read(
        self,
        group_focus_md: str,
        current_agent_name: str,
    ) -> set:
        """
        解析 group_focus 中对当前 agent 有效的 must_read 标题集合

        支持两种格式：
        1. 顶层 `## must_read` —— 所有成员都读
        2. `## member_roster` 下的 `agent: 必读=[A, B]` —— 该 agent 专属
        """
        titles: set = set()
        if not group_focus_md:
            return titles

        # 顶层 must_read
        in_must = False
        for line in group_focus_md.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                in_must = stripped.lower() == "## must_read"
                continue
            if in_must and stripped.startswith("- "):
                t = self._extract_bracketed_title(stripped[2:])
                if t:
                    titles.add(t)

        # member_roster 下的 agent 专属
        in_roster = False
        for line in group_focus_md.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                in_roster = "member_roster" in stripped.lower()
                continue
            if in_roster and stripped.lower().startswith(current_agent_name.lower()):
                # 找 `必读=[...]`
                m = re.search(r"必读\s*=\s*\[([^\]]*)\]", stripped)
                if m:
                    for t in m.group(1).split(","):
                        t = t.strip()
                        if t:
                            titles.add(t)
        return titles

    def _parse_group_focus_skip(self, group_focus_md: str) -> set:
        """解析 group_focus 中 skip 段的所有标题"""
        titles: set = set()
        if not group_focus_md:
            return titles
        in_skip = False
        for line in group_focus_md.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                in_skip = stripped.lower() == "## skip"
                continue
            if in_skip and stripped.startswith("- "):
                t = self._extract_bracketed_title(stripped[2:])
                if t:
                    titles.add(t)
        return titles

    @staticmethod
    def _extract_bracketed_title(text: str) -> Optional[str]:
        """从 `- [标题] (备注)` 或 `- [标题]` 中提取标题"""
        m = re.match(r"\[([^\]]+)\]", text)
        return m.group(1).strip() if m else None

    async def _build_agent_memory(
        self,
        context: Dict[str, Any],
        agent_id: str,
        project_id: str,
    ) -> None:
        """
        组装 Agent 个人笔记（按 slug 选择性注入）

        - slug ∈ DEFAULT_MEMORY_SLUGS（decisions / state_snapshot / group_focus）的全文注入
        - 其他 slug 暂存为 memory_catalog，agent 需要时通过 get_memory(slug=...) 拉
        - 写入笔记用 set_memory（支持 replace/append/replace_globally/rewrite_section 四种模式）
        """
        # 查询 Agent 在项目下的所有 notes
        query = select(Memory).where(and_(
            Memory.agent_id == agent_id,
            Memory.project_id == project_id,
            Memory.deleted_at.is_(None),
        ))
        result = await self.db.execute(query)
        memories = list(result.scalars().all())

        injected: List[Dict[str, Any]] = []
        catalog: List[Dict[str, Any]] = []
        for mem in memories:
            entry = {
                "slug": mem.slug,
                "content": mem.content,
                "tags": mem.tags,
                "updated_at": mem.updated_at.isoformat() if mem.updated_at else None,
            }
            if mem.slug in DEFAULT_MEMORY_SLUGS:
                injected.append(entry)
            else:
                catalog.append({
                    "slug": mem.slug,
                    "preview": (mem.content or "")[:200],
                    "tags": mem.tags,
                    "updated_at": mem.updated_at.isoformat() if mem.updated_at else None,
                })

        context["memory"] = injected       # list[dict] —— 全文注入
        context["memory_catalog"] = catalog  # list[dict] —— 目录，按需加载

    async def _build_inherited_main_chain_history(
        self,
        context: Dict[str, Any],
        task_chain: Chain,
        limit: int = 20,
    ) -> None:
        """
        v2 P2: task chain 继承主链截至分支点的历史.

        加载顺序:
          1. 主链 (task_chain.parent_chain_id) 在 task_chain.created_at 之前的历史
          2. task chain 自身历史

        用例: 狼人杀玩家在 task chain 中, 也能看到法官之前在主链发的"天黑请闭眼"等公告.
              但不看到主链在 task 期间产生的新消息 (因为 task 期间主链 paused).
        """
        from app.models.chain import Chain, Packet
        from datetime import timezone

        if task_chain.parent_chain_id is None:
            # 没有 parent chain, fallback 到普通加载
            await self._build_chain_history(context, task_chain.id, limit)
            return

        # 1. 加载主链截至 task chain 创建之前的历史
        # 限制: 主链历史最多 limit/2 条, 留 limit/2 给 task chain 自身
        main_limit = max(limit // 2, 5)
        main_q = (
            select(Packet)
            .where(and_(
                Packet.chain_id == task_chain.parent_chain_id,
                Packet.deleted_at.is_(None),
                Packet.created_at < task_chain.created_at,
            ))
            .order_by(Packet.created_at.desc())
            .limit(main_limit)
        )
        main_packets = list((await self.db.execute(main_q)).scalars().all())
        main_packets.reverse()  # 时间正序

        # 2. 加载 task chain 自身历史
        task_q = (
            select(Packet)
            .where(and_(
                Packet.chain_id == task_chain.id,
                Packet.deleted_at.is_(None),
            ))
            .order_by(Packet.created_at.desc())
            .limit(limit)
        )
        task_packets = list((await self.db.execute(task_q)).scalars().all())
        task_packets.reverse()  # 时间正序

        # 3. 拼接 (主链在前面, task chain 在后面), 标记 packet 来源 chain
        def _to_dict(pkt: Packet, source: str) -> dict:
            return {
                "id": pkt.id,
                "sender_id": pkt.sender_id,
                "sender_type": pkt.sender_type,
                "sender_name": pkt.sender_name,
                "content": pkt.content,
                "content_type": pkt.content_type,
                "packet_type": pkt.packet_type,
                "metadata": pkt.metadata_json or {},
                "created_at": pkt.created_at.isoformat(),
                "from_chain": source,  # "main" or "task"
            }

        history = (
            [_to_dict(p, "main") for p in main_packets]
            + [_to_dict(p, "task") for p in task_packets]
        )
        context["history"] = history
        context["history_inherited_from_main"] = bool(main_packets)

    async def _build_chain_history(
        self,
        context: Dict[str, Any],
        chain_id: str,
        limit: int = 20,
    ) -> None:
        """
        组装讨论链历史（从 Packet 表读取）

        Args:
            context: 上下文字典
            chain_id: 讨论链ID
            limit: 包数量限制
        """
        from app.models.chain import Chain, Packet

        # 收集链及其子链的 ID
        chain_ids = [chain_id]
        sub_chain_result = await self.db.execute(
            select(Chain.id)
            .where(and_(Chain.parent_chain_id == chain_id, Chain.deleted_at.is_(None)))
        )
        chain_ids.extend([row[0] for row in sub_chain_result.all()])

        # 从 Packet 表查询历史
        query = (
            select(Packet)
            .where(and_(
                Packet.chain_id.in_(chain_ids),
                Packet.deleted_at.is_(None),
            ))
            .order_by(Packet.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        packets = list(result.scalars().all())

        # 反转为时间正序
        packets.reverse()

        # 构建历史列表（含 metadata，用于保留 tool_calls 等结构信息）
        context["history"] = [
            {
                "id": pkt.id,
                "sender_id": pkt.sender_id,
                "sender_type": pkt.sender_type,
                "sender_name": pkt.sender_name,
                "content": pkt.content,
                "content_type": pkt.content_type,
                "packet_type": pkt.packet_type,
                "metadata": pkt.metadata_json or {},
                "created_at": pkt.created_at.isoformat(),
            }
            for pkt in packets
        ]

    async def _build_task_context(
        self,
        context: Dict[str, Any],
        task: Task,
    ) -> None:
        """
        组装任务上下文

        包括任务标题、描述、验收标准等。

        Args:
            context: 上下文字典
            task: 任务对象
        """
        context["task_context"] = {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "acceptance_criteria": task.acceptance_criteria,
            "status": task.status,
        }

        # 添加任务约束
        if task.acceptance_criteria:
            context["constraints"].append({
                "type": "acceptance_criteria",
                "content": task.acceptance_criteria,
            })

    @staticmethod
    def _strip_think_blocks(content: str) -> str:
        """剥离<think>...</think>块，用于构建agent上下文时节省token。"""
        sanitized = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
        return sanitized.strip()

    def format_for_llm(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        将上下文格式化为LLM可用的格式

        分层策略：
        - 必读全文：system_prompt + 运行上下文 + 必读资源 + 关键 memory（按 slug）
        - 元信息目录：其他资源、其他 slug memory、skills 目录
        - 任务/约束/历史/自主模式
        - 软约束注入：项目目标（target word count）、群协作提示（call_target 名单）
        """
        # 构建系统消息
        system_parts = [context["system_prompt"]]

        # 添加运行上下文（Agent 身份和环境 ID，供工具调用使用）
        ctx_lines = []
        if context.get("agent_id"):
            ctx_lines.append(f"- agent_id: {context['agent_id']}")
        if context.get("agent_name"):
            ctx_lines.append(f"- agent_name: {context['agent_name']}")
        if context.get("project_id"):
            ctx_lines.append(f"- project_id: {context['project_id']}")
        if context.get("group_id"):
            ctx_lines.append(f"- group_id: {context['group_id']}")
        if ctx_lines:
            system_parts.append("\n\n## 运行上下文\n\n" + "\n".join(ctx_lines))

        # === 软约束 1：项目目标（target_word_count / chapter_count 等）===
        proj_meta = context.get("project_metadata") or {}
        targets = proj_meta.get("targets") or {}
        if targets:
            target_lines = []
            # 简洁展示关键目标
            for key in ("word_count", "chapter_count", "chapter_word_count", "genre"):
                v = targets.get(f"default_{key}") or targets.get(key)
                if v is not None:
                    target_lines.append(f"- {key}: {v}")
            guidance = targets.get("guidance")
            if target_lines:
                proj_name = proj_meta.get("name", "")
                title = f"## 项目目标（{proj_name}）" if proj_name else "## 项目目标"
                block = "\n".join(target_lines)
                if guidance:
                    block += f"\n\n> {guidance}"
                system_parts.append(f"\n\n{title}\n\n{block}")

        # === 软约束 2：群聊花名册 + 协作提示（@ 机制软约束）===
        roster = context.get("group_roster") or []
        if roster:
            # 当前 agent 自己不放进"可调"列表
            my_name = context.get("agent_name", "")
            callable_roster = [r for r in roster if r.get("name") != my_name]
            if callable_roster:
                lines = ["**本群成员（可作为工具调用，触发对方回应）**："]
                for r in callable_roster:
                    role_tag = "（lead）" if r.get("is_lead") else ""
                    desc = r.get("description") or ""
                    lines.append(f"- {r.get('name')}{role_tag}：{desc[:80]}")
                lines.append("")
                lines.append(
                    "**协作约定**：\n"
                    "1. 你的工具列表里，名字与上面成员一致的条目就是该 agent 的调用入口。\n"
                    "2. **一次只调用一个 agent**：每轮最多调用 1 个群成员 agent，避免并行限流。\n"
                    "3. **按职责分工（核心）**：群成员各自负责不同的专业领域，"
                    "任何匹配该 agent 职责范围的工作，**必须交给那个 agent 去完成**。"
                    "不要因为对方没回应就自己替代写——那是你越权，破坏了协作流程。\n"
                    "4. **职责边界**：你自己（lead）的职责是流程管理、任务分解、验收、汇总、向用户汇报。"
                    "**不负责**专业内容生产（故事架构/读者分析/写作润色等）。这些必须调对应 agent。\n"
                    "5. 需要对方参与时，**直接调用对应 agent 工具**（不是只在文本里写'@对方'）。\n"
                    "6. 调用对方后，对方的回复会作为工具结果回流到你的上下文，你再综合判断继续推进。\n"
                    "7. 如果对方意见与你的判断冲突，**你（lead）有最终决策权**。"
                )
                system_parts.append("\n\n## 群聊成员与协作约定\n\n" + "\n".join(lines))

        # === 软约束 3：执行原则（避免"只查不写" / "无限准备"）===
        # 通用能力：所有 agent 都看到，自己根据角色内化。
        # 资料查询类工具调用（search/read/db_read）连续超过 3 次还没输出实质文本时，
        # 应立即停止查询并基于已有信息开始输出。
        # 宁可先给 60-70% 完整度的草稿，也不要在完美条件前无限等待。
        system_parts.append(
            "\n\n## 执行原则（必读，违反会导致空转失败）\n\n"
            "**核心规则：先交付再完美。**\n\n"
            "1. **先开干再迭代**：资料查询（`search_resources` / `db_read_skill` / `query_history` 等）"
            "**累计 1-2 次后，无论资料是否齐全，都要开始输出实质内容**。\n"
            "   - 反例：连续 5 次 db_read_skill 后说'我准备好了，可以开始'——准备不是交付物。\n"
            "   - 注意：服务端模式下只能用 `db_read_skill`（数据库 skill），"
            "**不能调 `read_skill` / `read_skill_file`**——那是文件系统版, 服务端会拒绝并返回 Permission denied.\n"
            "2. **草稿优于等待**：如果某些信息缺失（如人物卡未完成、用户未确认细节），"
            "**先基于已有信息出 60-70% 完整度的草稿**，用 `[*待补：xxx]` 标记缺失部分，主体推进。\n"
            "3. **避免空转**：如果你发现自己连续 3 次工具调用都只是在'准备'（查资料/读 skill）而没有输出，"
            "**立即停止准备，开始输出**。\n"
            "4. **写完用工具落地**：完成交付物（立项书/世界观/人物卡/大纲/章节正文等）后，"
            "**必须用 `write_resource` 工具写入项目资源库**（不是只在群里发文本）。\n"
            "   - 这是后续 Agent 能读到这份产出的唯一方式。\n"
            "5. **自查信号（每轮输出前自问）**：\n"
            "   - [ ] 我这一轮是否在写实质内容（不是只说'我来看看资料'）？\n"
            "   - [ ] 我查资料累计几次了？（>2 次应停止查询，开始输出）\n"
            "   - [ ] 我产出的内容是否已经写到 `write_resource` 工具调用？\n"
            "   - [ ] 如果有缺失信息，是否已用 `[*待补]` 标记而非阻塞？\n"
            "\n"
            "6. **工具失败兜底（关键）**：\n"
            "   - 工具返回 `Error: ...` / `Permission denied` / `400` 等错误时，**不要**反复重试同一工具，"
            "也**不要**在群里发'工具坏了,我等一下'然后停住。\n"
            "   - 正确做法: 立刻降级——\n"
            "     a. 若目标是'读 skill/skill 全文': 改用 `read_resource` 找资源,"
            "或基于 system prompt 里已注入的 skills 目录直接推进。\n"
            "     b. 若目标是'通知另一个 agent': 改用 `update_task_status(in_progress)` 触发系统派发,"
            "不要用 `send_message` 自给自足。\n"
            "     c. 若目标是'跨 agent 调用 sub-agent': 不要强行再调,"
            "直接在群里发文本指令让对方接管,然后用 `list_tasks` 轮询状态。\n"
            "     d. **核心原则: 任何一个工具失败, 立刻出 60-70% 草稿到 `write_resource` 落地, "
            "不要让群组进入'等工具恢复'状态。**\n"
            "\n"
            "**反面教材**：\n"
            "❌ 收到任务 → 查 5 次资料 → 读 3 个 skill → 说'我准备好了' → 用户催 → 又查 2 次 → 仍然没输出\n"
            "✅ 收到任务 → 查 1-2 次资料 → 直接出 60-70% 草稿 → 写到资源库 → 群里简短汇报"
        )

        # 添加必读资源（must_read 全文）
        if context.get("resources"):
            resource_texts = []
            for res in context["resources"]:
                prefix = "[必读] " if res.get("is_required") else ""
                resource_texts.append(f"{prefix}{res['title']}:\n{res['content']}")
            resource_text = "\n\n".join(resource_texts)
            MAX_RESOURCE_CHARS = 8000
            if len(resource_text) > MAX_RESOURCE_CHARS:
                resource_text = resource_text[:MAX_RESOURCE_CHARS] + "\n\n[...资料内容过长，已截断。请使用 read_resource(id=...) 工具查询完整资料。]"
            system_parts.append("\n\n## 参考资源\n\n" + resource_text)

        # 添加资料目录（非 must_read 的资源元信息，agent 可按需 read_resource 拉）
        if context.get("resource_catalog"):
            catalog_lines = ["如需完整内容，调 `read_resource(id=...)` 或 `search_resources(query=...)` 工具获取。"]
            for r in context["resource_catalog"]:
                tags_str = f" [tags: {', '.join(r.get('tags', []))}]" if r.get("tags") else ""
                catalog_lines.append(f"- [{r.get('title', '?')}] (id={r.get('id')}, type={r.get('type')}, scope={r.get('scope')}){tags_str}")
            system_parts.append("\n\n## 资料目录\n\n" + "\n".join(catalog_lines))

        # 添加按 slug 注入的 memory（decisions / state_snapshot / group_focus）
        if context.get("memory"):
            mem_texts = []
            for mem in context["memory"]:
                mem_texts.append(f"### {mem['slug']}\n{mem['content']}")
            system_parts.append("\n\n## 个人笔记\n\n" + "\n\n".join(mem_texts))

        # 添加 memory 目录（其他 slug）
        if context.get("memory_catalog"):
            catalog_lines = ["如需完整内容，调 `get_memory(slug=...)` 工具获取。写入用 `set_memory(slug=..., content=..., mode=...)` 工具，支持 mode: replace（全量替换）/ append（追加）/ replace_globally（查找替换）/ rewrite_section（按标题替换 section）。"]
            for m in context["memory_catalog"]:
                tags_str = f" [tags: {', '.join(m.get('tags', []))}]" if m.get("tags") else ""
                catalog_lines.append(f"- slug=`{m['slug']}`{tags_str}: {m.get('preview', '')}")
            system_parts.append("\n\n## 笔记目录\n\n" + "\n".join(catalog_lines))

        # 添加任务上下文
        if context.get("task_context"):
            task = context["task_context"]
            task_text = f"## 当前任务\n\n标题: {task['title']}"
            if task.get("description"):
                task_text += f"\n描述: {task['description']}"
            if task.get("acceptance_criteria"):
                task_text += f"\n验收标准: {task['acceptance_criteria']}"
            system_parts.append(f"\n\n{task_text}")

        # 添加约束
        if context.get("constraints"):
            constraint_texts = [c["content"] for c in context["constraints"]]
            system_parts.append("\n\n## 约束条件\n\n" + "\n".join(f"- {c}" for c in constraint_texts))

        # 添加 Skills 元信息目录（按需 read_skill 加载全文）
        if context.get("skills"):
            skill_lines = ["如需某个 skill 的方法论全文，调 `db_read_skill(agent_id=..., skill_name=...)` 工具获取。"]
            for s in context["skills"]:
                files_hint = "（含附加文件）" if s.get("has_files") else ""
                skill_lines.append(f"- **{s['name']}** ({s.get('type', 'prompt')}){files_hint}: {s.get('description', '')}")
            system_parts.append("\n\n## Agent Skills（目录）\n\n" + "\n".join(skill_lines))

        # 添加路由表提示（如果本群 lead 维护了 group_focus）
        if context.get("routed_by_lead"):
            system_parts.append(
                "\n\n## 上下文路由\n"
                "本群聊 lead agent 维护了一份群焦点记忆（group_focus）。\n"
                "上述资源/笔记是按 lead 的路由表为你过滤后的——lead 觉得本群用不上的资源被放进了目录而非全文。\n"
                "需要时调 `read_resource(id=...)` 主动加载。"
            )

        # 添加自主级别行为指令（从 execution_modes.json 加载，支持 A/B 测试变体）
        autonomy = context.get("autonomy_level", "semi_auto")
        mode_info: Dict[str, Any] = {}
        if autonomy in ("full_auto", "semi_auto", "manual"):
            try:
                from app.config import ExecutionModeService
                service = ExecutionModeService.instance()
                # 项目级 override 优先（从 group.workflow_config.execution_variant 读）
                # workflow_config 已在 build() 里存入 context（format_for_llm 是同步方法，无法访问 group 对象）
                workflow_cfg = context.get("workflow_config") or {}
                project_override = workflow_cfg.get("execution_variant") if isinstance(workflow_cfg, dict) else None
                # agent 级 override 暂未实现，留作扩展

                suffix = service.get_system_suffix(
                    autonomy_level=autonomy,
                    project_override=project_override,
                )
                if suffix:
                    system_parts.append("\n\n" + suffix)
                mode_info = service.get_mode_info(autonomy_level=autonomy)
            except Exception as e:
                logger.warning("Failed to load execution mode suffix: %s", e)

        # 暴露到 context 供日志/调试使用
        context["execution_mode"] = mode_info

        system_message = "\n".join(system_parts)

        # 构建消息列表（agent消息剥离think块以节省token）
        # 同时保留 raw_history 供 _seed_history_from_db 创建正确类型的 InfoPacket
        messages = []
        for msg in context.get("history", []):
            pkt_type = msg.get("packet_type", "normal")
            metadata = msg.get("metadata") or {}
            sender_type = msg.get("sender_type", "agent")

            if pkt_type == "call":
                # Tool call packet → assistant message with tool_calls
                content = msg.get("content", {})
                if isinstance(content, dict):
                    tool_name = content.get("tool_name") or metadata.get("tool_name") or "unknown"
                    tool_call_id = content.get("tool_call_id") or metadata.get("tool_call_id") or f"call_{msg['id'][:8]}"
                    arguments = content.get("arguments", {})
                else:
                    tool_name = metadata.get("tool_name") or "unknown"
                    tool_call_id = metadata.get("tool_call_id") or f"call_{msg['id'][:8]}"
                    arguments = {}
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, dict) else str(arguments),
                        },
                    }],
                    "sender_name": msg.get("sender_name", ""),
                })
            elif pkt_type == "response":
                # Tool response → tool role message
                tool_call_id = metadata.get("tool_call_id")
                result = msg.get("content", "")
                if isinstance(result, (dict, list)):
                    result = json.dumps(result, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "content": str(result),
                    "tool_call_id": tool_call_id,
                })
            elif pkt_type == "error":
                # Tool error → tool role message with error info
                tool_call_id = metadata.get("tool_call_id")
                error = msg.get("content", "")
                messages.append({
                    "role": "tool",
                    "content": f"[ERROR] {error}",
                    "tool_call_id": tool_call_id,
                })
            elif sender_type == "user":
                messages.append({
                    "role": "user",
                    "content": msg["content"],
                    "sender_name": msg.get("sender_name", "用户"),
                })
            elif sender_type == "agent":
                clean = self._strip_think_blocks(msg["content"])
                if clean:
                    entry = {
                        "role": "assistant",
                        "content": clean,
                        "sender_name": msg.get("sender_name", ""),
                    }
                    # 保留 metadata 中的 tool_calls（agent 响应中可能包含工具调用信息）
                    agent_tool_calls = metadata.get("tool_calls")
                    if agent_tool_calls:
                        entry["tool_calls"] = agent_tool_calls
                    messages.append(entry)

        return {
            "system_message": system_message,
            "messages": messages,
            "raw_history": context.get("history", []),
            "tools": context.get("tools", []),
            "skills": context.get("skills", []),
            "resource_catalog": context.get("resource_catalog", []),
            "memory_catalog": context.get("memory_catalog", []),
            "execution_mode": mode_info,
        }
